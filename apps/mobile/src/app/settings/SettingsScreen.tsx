import { Ionicons } from "@expo/vector-icons";
import { useEffect, useMemo, useRef, useState } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";

import { useAppTheme } from "../theme/AppTheme";
import { AccessiblePressable } from "../../shared/accessibility/AccessiblePressable";
import { AccessibilityStatus } from "../../shared/accessibility/AccessibilityStatus";
import {
  announceAccessibility,
  type AccessibilityAnnouncer,
} from "../../shared/accessibility/announcements";
import {
  focusAccessibilityElement,
  useAccessibilityScreenFocus,
  type AccessibilityFocusRequester,
} from "../../shared/accessibility/focus";
import { BackButton } from "../../shared/components/BackButton";
import { TransientSuccessBanner } from "../../shared/components/TransientSuccessBanner";
import { APPEARANCE_OPTIONS, appearanceOptionSelected } from "./settingsModel";
import { UsdaCredentialSettings } from "./UsdaCredentialSettings";
import { LocalBackupSettings } from "./LocalBackupSettings";
import { deviceTimeZone } from "../../features/calendar/deviceTimeZone";
import {
  useCalendarState,
  useConfirmCalendarTimeZoneChange,
  useEstablishCalendarTimeZone,
  usePreviewCalendarTimeZoneChange,
} from "../../features/calendar/hooks/useCalendar";

type Props = {
  onBack: () => void;
  onOpenNutritionTargets: () => void;
  onOpenOcrDiagnostics?: () => void;
  accessibilityAnnouncer?: AccessibilityAnnouncer;
  requestAccessibilityFocus?: AccessibilityFocusRequester;
};

export function SettingsScreen({
  onBack,
  onOpenNutritionTargets,
  onOpenOcrDiagnostics,
  accessibilityAnnouncer = announceAccessibility,
  requestAccessibilityFocus = focusAccessibilityElement,
}: Props) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const calendar = useCalendarState();
  const establish = useEstablishCalendarTimeZone();
  const previewChange = usePreviewCalendarTimeZoneChange();
  const confirmChange = useConfirmCalendarTimeZoneChange();
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const settingsHeadingRef = useRef<Text>(null);
  const calendarStatusRef = useRef<Text>(null);
  const reviewHeadingRef = useRef<Text>(null);
  const reviewRequestedRef = useRef(false);
  const proposedTimeZone = deviceTimeZone();
  const isEstablished = calendar.data?.is_established === true;
  const timeZoneLabel = isEstablished ? "Authoritative time zone" : "Provisional device time zone";
  const timeZoneValue = isEstablished ? calendar.data?.authoritative_time_zone ?? proposedTimeZone : proposedTimeZone;
  const preview = previewChange.data;
  const reviewingChange = isEstablished && preview !== undefined && !confirmChange.isError;

  useAccessibilityScreenFocus({
    active: true,
    routeKey: "settings",
    targetRef: settingsHeadingRef,
    requestFocus: requestAccessibilityFocus,
  });

  useEffect(() => {
    if (!reviewingChange || !reviewRequestedRef.current) return;
    reviewRequestedRef.current = false;
    return requestAccessibilityFocus(reviewHeadingRef.current, { focusKeyboardTarget: false });
  }, [preview?.preview_token, requestAccessibilityFocus, reviewingChange]);

  useEffect(() => {
    if (!establish.isSuccess) return;

    setSuccessMessage(`Daily Log time zone confirmed as ${proposedTimeZone}.`);

    const cancelFocus = requestAccessibilityFocus(calendarStatusRef.current, {
      delayMs: 0,
      focusKeyboardTarget: false,
    });

    return cancelFocus;
  }, [establish.isSuccess, proposedTimeZone, requestAccessibilityFocus]);

  useEffect(() => {
    if (confirmChange.isSuccess) {
      const confirmedTimeZone = preview?.proposed_time_zone ?? proposedTimeZone;

      setSuccessMessage(
          `Daily Log time zone changed to ${confirmedTimeZone}. Entry dates and historical nutrition were not changed.`,
      );

      previewChange.reset();
      confirmChange.reset();

      return requestAccessibilityFocus(calendarStatusRef.current, {
        delayMs: 0,
        focusKeyboardTarget: false,
      });
    }
  }, [
    confirmChange.isSuccess,
    confirmChange.reset,
    preview?.proposed_time_zone,
    previewChange.reset,
    proposedTimeZone,
    requestAccessibilityFocus,
  ]);

  function reviewTimeZoneChange() {
    setSuccessMessage(null);
    reviewRequestedRef.current = true;
    previewChange.reset();
    confirmChange.reset();
    previewChange.mutate(proposedTimeZone);
  }

  function confirmTimeZoneChange() {
    setSuccessMessage(null);
    if (!preview) {
      return;
    }
    confirmChange.mutate({
      timeZone: preview.proposed_time_zone,
      calendarRevision: preview.calendar_revision,
      previewToken: preview.preview_token,
    });
  }
  return (
    <ScrollView contentContainerStyle={styles.screen} keyboardShouldPersistTaps="handled" style={styles.scroll}>
      <View style={styles.header}>
        <BackButton accessibilityLabel="Back from settings" onPress={onBack} />
        <Text ref={settingsHeadingRef} accessibilityRole="header" style={styles.title}>Settings</Text>
      </View>

      <TransientSuccessBanner
          message={successMessage}
          onExpired={() => setSuccessMessage(null)}
          announcer={accessibilityAnnouncer}
      />

      <Text accessibilityRole="header" style={styles.sectionTitle}>Appearance</Text>
      <View style={styles.options} accessibilityRole="radiogroup">
        {APPEARANCE_OPTIONS.map((option) => {
          const selected = appearanceOptionSelected(theme.preference, option.value);
          return (
            <AccessiblePressable
              key={option.value}
              accessibilityLabel={`${option.label} appearance`}
              accessibilityRole="radio"
              accessibilityState={{ checked: selected }}
              onPress={() => theme.setPreference(option.value)}
              style={({ pressed }) => [styles.option, selected && styles.selectedOption, pressed && styles.pressed]}
            >
              <Text style={styles.optionText}>{option.label}</Text>
              <Ionicons name={selected ? "checkmark-circle" : "ellipse-outline"} size={23} color={selected ? theme.colors.accent : theme.colors.secondaryText} />
            </AccessiblePressable>
          );
        })}
      </View>
      <Text accessibilityRole="header" style={styles.sectionTitle}>Daily Log calendar</Text>
      <View style={styles.calendarCard}>
        <Text ref={calendarStatusRef} accessibilityRole="header" style={styles.calendarText}>{timeZoneLabel}</Text>
        <Text accessibilityLabel={`${timeZoneLabel}: ${timeZoneValue}`} style={styles.calendarValue}>{timeZoneValue}</Text>
        {!isEstablished ? (
          <>
            <AccessiblePressable
              accessibilityLabel={`Confirm ${proposedTimeZone} as the Daily Log time zone`}
              busy={establish.isPending}
              disabled={establish.isPending}
              onPress={() => establish.mutate(proposedTimeZone)}
              style={({ pressed }) => [styles.confirmButton, pressed && styles.pressed, establish.isPending && styles.disabled]}
            >
              <Text style={styles.confirmButtonText}>{establish.isPending ? "Confirming…" : `Confirm ${proposedTimeZone}`}</Text>
            </AccessiblePressable>
            {establish.isError ? (
              <AccessibilityStatus
                kind="retryable-failure"
                message="The Daily Log time zone could not be confirmed. Try again."
                onRetry={() => establish.mutate(proposedTimeZone)}
                retryContext="Daily Log time-zone confirmation"
              />
            ) : null}
          </>
        ) : null}
        {isEstablished ? (
          <>
            <Text style={styles.calendarHint}>
              Device zone proposal: {proposedTimeZone}. Changing this shared calendar never moves, edits, or deletes entries.
            </Text>
            {!reviewingChange ? (
              <AccessiblePressable
                accessibilityLabel="Review time-zone change"
                accessibilityHint="Shows whether today changes and which saved entries would become future-dated"
                busy={previewChange.isPending}
                disabled={previewChange.isPending}
                onPress={reviewTimeZoneChange}
                style={({ pressed }) => [styles.confirmButton, pressed && styles.pressed, previewChange.isPending && styles.disabled]}
              >
                <Text style={styles.confirmButtonText}>{previewChange.isPending ? "Reviewing…" : "Review time-zone change"}</Text>
              </AccessiblePressable>
            ) : preview ? (
              <View style={styles.reviewCard}>
                <Text ref={reviewHeadingRef} accessibilityRole="header" style={styles.reviewTitle}>Review calendar consequences</Text>
                <Text style={styles.reviewText}>Current zone: {preview.current_time_zone}</Text>
                <Text style={styles.reviewText}>Proposed zone: {preview.proposed_time_zone}</Text>
                <Text style={styles.reviewText}>
                  Today {preview.today_changes ? "changes" : "does not change"} ({preview.current_today} → {preview.proposed_today}).
                </Text>
                <Text style={styles.reviewText}>
                  {preview.affected_entry_count} persisted {preview.affected_entry_count === 1 ? "entry becomes" : "entries become"} future-dated.
                </Text>
                <Text style={styles.calendarHint}>
                  Affected entries are reclassified under the new calendar. Their dates and historical nutrition remain unchanged.
                </Text>
                {preview.affected_entries.length > 0 ? (
                  <View>
                    <Text accessibilityRole="header" style={styles.affectedEntriesTitle}>Affected entries</Text>
                    {preview.affected_entries.map((entry) => (
                      <Text
                        key={entry.id}
                        accessibilityLabel={`${entry.food_name_snapshot ?? "Food"}, ${entry.meal_type ?? "no meal"}, logged ${entry.logged_date}`}
                        style={styles.affectedEntry}
                      >
                        {entry.logged_date} · {entry.food_name_snapshot ?? "Food"}{entry.meal_type ? ` · ${entry.meal_type}` : ""}
                      </Text>
                    ))}
                  </View>
                ) : null}
                <AccessiblePressable
                  accessibilityLabel="Confirm time-zone change"
                  accessibilityHint="Applies the reviewed shared calendar change without moving, editing, or deleting entries"
                  busy={confirmChange.isPending}
                  disabled={confirmChange.isPending}
                  onPress={confirmTimeZoneChange}
                  style={({ pressed }) => [styles.confirmButton, pressed && styles.pressed, confirmChange.isPending && styles.disabled]}
                >
                  <Text style={styles.confirmButtonText}>{confirmChange.isPending ? "Applying…" : "Confirm time-zone change"}</Text>
                </AccessiblePressable>
              </View>
            ) : null}
            {confirmChange.isError ? (
              <AccessibilityStatus
                kind="retryable-failure"
                message="The time-zone change could not be applied. Review the current calendar and try again."
                onRetry={preview ? confirmTimeZoneChange : reviewTimeZoneChange}
                retryContext="time-zone change"
              />
            ) : null}
            {previewChange.isError ? (
              <AccessibilityStatus
                kind="retryable-failure"
                message="The time-zone change could not be reviewed. Try again."
                onRetry={reviewTimeZoneChange}
                retryContext="time-zone change review"
              />
            ) : null}
          </>
        ) : null}
        {calendar.isError ? (
          <AccessibilityStatus
            kind="initial-failure"
            message="Unable to load calendar settings."
            onRetry={calendar.refetch}
            retryContext="calendar settings"
          />
        ) : null}
      </View>
      <UsdaCredentialSettings />
      <LocalBackupSettings />
      <Text accessibilityRole="header" style={styles.sectionTitle}>Nutrition</Text>
      <AccessiblePressable accessibilityLabel="Open nutrition targets" onPress={onOpenNutritionTargets} style={({ pressed }) => [styles.option, pressed && styles.pressed]}>
        <Text style={styles.optionText}>Nutrition targets</Text>
        <Ionicons name="chevron-forward" size={22} color={theme.colors.secondaryText} />
      </AccessiblePressable>
      {onOpenOcrDiagnostics && (
        <>
          <Text accessibilityRole="header" style={styles.sectionTitle}>Development</Text>
          <AccessiblePressable
            accessibilityLabel="Open Apple Vision OCR diagnostics"
            onPress={onOpenOcrDiagnostics}
            style={({ pressed }) => [styles.option, pressed && styles.pressed]}
          >
            <Text style={styles.optionText}>Apple Vision OCR diagnostics</Text>
            <Ionicons name="chevron-forward" size={22} color={theme.colors.secondaryText} />
          </AccessiblePressable>
        </>
      )}
    </ScrollView>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    header: { gap: 8 },
    option: { alignItems: "center", backgroundColor: theme.colors.surface, borderBottomColor: theme.colors.border, borderBottomWidth: 1, flexDirection: "row", gap: 8, justifyContent: "space-between", minHeight: 52, paddingHorizontal: 14, paddingVertical: 8 },
    optionText: { color: theme.colors.text, flex: 1, fontSize: 17 },
    options: { borderColor: theme.colors.border, borderRadius: 10, borderWidth: 1, overflow: "hidden" },
    calendarCard: { backgroundColor: theme.colors.surface, borderColor: theme.colors.border, borderRadius: 10, borderWidth: 1, gap: 10, padding: 14 },
    calendarText: { color: theme.colors.text, fontSize: 16, fontWeight: "700" },
    calendarValue: { color: theme.colors.text, fontSize: 18, fontWeight: "700" },
    calendarHint: { color: theme.colors.secondaryText, fontSize: 14, lineHeight: 20 },
    reviewCard: { backgroundColor: theme.colors.activeBackground, borderColor: theme.colors.border, borderRadius: 8, borderWidth: 1, gap: 8, padding: 12 },
    reviewTitle: { color: theme.colors.text, fontSize: 16, fontWeight: "700" },
    reviewText: { color: theme.colors.text, fontSize: 14, lineHeight: 20 },
    affectedEntriesTitle: { color: theme.colors.text, fontSize: 14, fontWeight: "700", marginBottom: 4 },
    affectedEntry: { color: theme.colors.secondaryText, fontSize: 13, lineHeight: 19 },
    confirmButton: { alignSelf: "stretch", backgroundColor: theme.colors.accent, borderRadius: 6, paddingHorizontal: 12, paddingVertical: 10 },
    confirmButtonText: { color: theme.colors.accentForeground, flexShrink: 1, fontWeight: "700", textAlign: "center" },
    disabled: { opacity: 0.6 },
    pressed: { backgroundColor: theme.colors.pressedBackground },
    screen: { backgroundColor: theme.colors.background, flexGrow: 1, gap: 14, padding: 16, paddingBottom: 40 },
    scroll: { backgroundColor: theme.colors.background, flex: 1 },
    sectionTitle: { color: theme.colors.secondaryText, fontSize: 14, fontWeight: "700", marginTop: 8, textTransform: "uppercase" },
    selectedOption: { backgroundColor: theme.colors.activeBackground },
    title: { color: theme.colors.text, fontSize: 32, fontWeight: "800", lineHeight: 38 },
  });
}
