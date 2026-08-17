import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { StyleSheet, Text, TextInput, View } from "react-native";

import { useAppTheme } from "../../../app/theme/AppTheme";
import { createClientRequestId } from "../../logging/utils/clientRequestId";
import { KeyboardSafeScrollView, type KeyboardSafeScrollViewHandle } from "../../../shared/forms/KeyboardSafeScrollView";
import { LabeledField } from "../../../shared/forms/LabeledField";
import { AccessiblePressable } from "../../../shared/accessibility/AccessiblePressable";
import { AccessibleModal } from "../../../shared/accessibility/AccessibleModal";
import { useAccessibilityAnnouncement } from "../../../shared/accessibility/announcements";
import { focusAccessibilityElement, useAccessibilityScreenFocus, type CancelAccessibilityFocus } from "../../../shared/accessibility/focus";
import { useNutrients } from "../../foods/hooks/useFoods";
import type { ConfirmationField, NutritionConfirmationDraft } from "../api/types";
import { OcrServingEditor } from "../components/OcrServingEditor";
import { addManualNutrient, confirmationPayload, confirmationValidationIssues, hydrateCanonicalNutrientUnits, omitReview, updateReview } from "../confirmation/confirmationModel";
import { bindConfirmationIntent, type ConfirmationIntent } from "../confirmation/confirmationIntent";
import { confirmationErrorCode, confirmationErrorMessage } from "../confirmation/confirmationErrors";
import { useNutritionRuntime } from "../../../runtime/NutritionRuntimeContext";
import { NutrientAmountRow } from "../../../shared/nutrition/NutrientAmountRow";
import {
  CLEAN_DRAFT_STATUS,
  draftObjectsEqual,
  useDraftStatusReporter,
  type DraftStatusReporter,
} from "../../../shared/navigation/draftGuard";

const FINGERPRINT_PLACEHOLDER_REQUEST_ID = "00000000-0000-4000-8000-000000000000";

function showsUseValueAction(field: ConfirmationField, allowEnteredValue = false): boolean {
  const hasSuggestedValue = Boolean(field.suggestedValue);
  const hasEnteredValueWithoutSuggestion = allowEnteredValue
    && field.suggestedValue === null
    && Boolean(field.confirmedValue);
  return (hasSuggestedValue || hasEnteredValueWithoutSuggestion)
    && (field.decision === "unresolved" || field.decision === "edited" || field.decision === "omitted");
}

type DirectedReviewItem =
  | { kind: "field"; field: ConfirmationField }
  | { kind: "unknown"; index: number; label: string };

function requiredReviewItems(draft: NutritionConfirmationDraft): DirectedReviewItem[] {
  const fields = [draft.calories, ...draft.nutrients]
    .filter((field) => field.decision === "unresolved")
    .map((field): DirectedReviewItem => ({ kind: "field", field }));
  const unknownNutrients = draft.unknownNutrients.flatMap((item, index) => item.dismissed
    ? []
    : [{ kind: "unknown" as const, index, label: item.originalName }]);
  return [...fields, ...unknownNutrients];
}

function directedReviewItemKey(item: DirectedReviewItem | null): string | null {
  if (!item) return null;
  return item.kind === "field" ? item.field.fieldKey : `unknown.${item.index}`;
}

function directedReviewActionCopy(count: number): string {
  return `Review ${count} item${count === 1 ? "" : "s"}`;
}

function nutrientCatalogSubmissionError({
  isError,
  isLoading,
  canonicalUnitsAvailable,
}: {
  isError: boolean;
  isLoading: boolean;
  canonicalUnitsAvailable: boolean;
}): string | null {
  if (isError) {
    return "The nutrient catalog could not be loaded. Try again.";
  }
  if (isLoading) {
    return "The nutrient catalog is still loading. Try again when canonical units are available.";
  }
  if (!canonicalUnitsAvailable) {
    return "The canonical nutrient catalog is incomplete. This food cannot be confirmed safely.";
  }
  return null;
}

export function NutritionConfirmationScreen({
  initialDraft,
  onCancel,
  onCreated,
  onRetake,
  draftStateKey,
  onDraftStateChange,
}: {
  initialDraft: NutritionConfirmationDraft;
  onCancel: () => boolean | void;
  onCreated: (foodId: string) => void;
  onRetake: () => boolean | void;
  draftStateKey?: string;
  onDraftStateChange?: DraftStatusReporter;
}) {
  const runtime = useNutritionRuntime();
  const nutrientQuery = useNutrients();
  const theme = useAppTheme(); const styles = useMemo(() => createStyles(theme), [theme]);
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(initialDraft);
  const [validationAttempted, setValidationAttempted] = useState(false);
  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const [showMissingNutrients, setShowMissingNutrients] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [directedReviewVisible, setDirectedReviewVisible] = useState(() => requiredReviewItems(initialDraft).length > 0);
  const submittingRef = useRef(false);
  const mountedRef = useRef(true);
  const navigationClaimedRef = useRef(false);
  const successClaimedRef = useRef(false);
  const intentRef = useRef<ConfirmationIntent | null>(null);
  const scrollRef = useRef<KeyboardSafeScrollViewHandle>(null);
  const headingRef = useRef<Text>(null);
  const errorRef = useRef<Text>(null);
  const reviewTriggerRef = useRef<View>(null);
  const reviewFieldRef = useRef<TextInput>(null);
  const reviewHeadingRef = useRef<Text>(null);
  const reviewModalPresentedRef = useRef(false);
  const reviewFocusedItemKeyRef = useRef<string | null>(null);
  const reviewTransitionFocusCancelRef = useRef<CancelAccessibilityFocus | null>(null);
  const initialReviewRequiresModalFocusRef = useRef(requiredReviewItems(initialDraft).length > 0);
  const validationFocusKeyRef = useRef<string | null>(null);
  const announce = useAccessibilityAnnouncement();
  const hydratedDraft = useMemo(
    () => hydrateCanonicalNutrientUnits(draft, nutrientQuery.data ?? []),
    [draft, nutrientQuery.data],
  );
  const fields = [hydratedDraft.calories, ...hydratedDraft.nutrients];
  const reviewItems = useMemo(() => requiredReviewItems(hydratedDraft), [hydratedDraft]);
  const currentReviewItem = reviewItems[0] ?? null;
  const reviewPresented = directedReviewVisible && reviewItems.length > 0;
  const validationIssues = validationAttempted ? confirmationValidationIssues(hydratedDraft) : [];
  const issuesByField = new Map(validationIssues
    .filter((issue): issue is typeof issue & { fieldKey: string } => issue.fieldKey !== null)
    .map((issue) => [issue.fieldKey, issue]));
  const validationSummary = validationIssues.length === 0
    ? null
    : validationIssues.length === 1
      ? validationIssues[0]!.message
      : `Review ${validationIssues.length} items before creating the Food. ${validationIssues.map(({ message }) => message).join(" ")}`;
  const displayedError = submissionError ?? validationSummary;
  const presentNutrientIds = new Set(fields.map(({ nutrientId }) => nutrientId).filter(Boolean));
  const availableNutrients = (nutrientQuery.data ?? []).filter(({ id }) => !presentNutrientIds.has(id));
  const availableDefinitionIds = new Set((nutrientQuery.data ?? []).map(({ id }) => id));
  const canonicalUnitsAvailable = fields.every(({ nutrientId }) => nutrientId === null || availableDefinitionIds.has(nutrientId));
  const isDirty = !draftObjectsEqual(draft, initialDraft);

  useDraftStatusReporter({
    draftKey: draftStateKey,
    dirty: isDirty,
    busy: submitting,
    reporter: onDraftStateChange,
  });

  useAccessibilityScreenFocus({
    active: !initialReviewRequiresModalFocusRef.current,
    routeKey: "nutrition-confirmation",
    targetRef: headingRef,
  });

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    if (reviewItems.length === 0 && directedReviewVisible) setDirectedReviewVisible(false);
  }, [directedReviewVisible, reviewItems.length]);

  useEffect(() => {
    if (!reviewPresented) {
      reviewModalPresentedRef.current = false;
      reviewFocusedItemKeyRef.current = null;
      reviewTransitionFocusCancelRef.current?.();
      reviewTransitionFocusCancelRef.current = null;
      return;
    }
    if (!reviewModalPresentedRef.current) return;
    const nextItemKey = directedReviewItemKey(currentReviewItem);
    if (nextItemKey === reviewFocusedItemKeyRef.current) return;
    reviewTransitionFocusCancelRef.current?.();
    reviewTransitionFocusCancelRef.current = null;
    reviewFocusedItemKeyRef.current = nextItemKey;
    const target = currentReviewItem?.kind === "field" ? reviewFieldRef.current : reviewHeadingRef.current;
    reviewTransitionFocusCancelRef.current = focusAccessibilityElement(target, {
      delayMs: 60,
      focusKeyboardTarget: false,
    });
  }, [currentReviewItem, reviewPresented]);

  useEffect(() => () => {
    reviewTransitionFocusCancelRef.current?.();
    reviewTransitionFocusCancelRef.current = null;
  }, []);

  useEffect(() => {
    if (!displayedError) return;
    const cancelAnnouncement = announce(displayedError, { key: "nutrition-confirmation-error", kind: "error", priority: "assertive" });
    const focusKey = validationFocusKeyRef.current;
    validationFocusKeyRef.current = null;
    const focusedField = focusKey ? scrollRef.current?.focusTarget(focusKey) : false;
    const cancelFocus = focusedField || (!focusKey && !submissionError)
      ? null
      : focusAccessibilityElement(errorRef.current, { focusKeyboardTarget: false });
    return () => { cancelAnnouncement(); cancelFocus?.(); };
  }, [announce, displayedError, submissionError]);

  const replaceField = (next: ConfirmationField) => setDraft((current) => next.nutrientId === "calories"
    ? { ...current, calories: next }
    : { ...current, nutrients: current.nutrients.map((field) => field.fieldKey === next.fieldKey ? next : field) });

  const updateDirectedReviewValue = (field: ConfirmationField, value: string) => replaceField({
    ...field,
    confirmedValue: value,
    decision: "unresolved",
  });

  const dismissUnknown = (index: number) => setDraft((current) => ({
    ...current,
    unknownNutrients: current.unknownNutrients.map((entry, itemIndex) => itemIndex === index ? { ...entry, dismissed: true } : entry),
  }));

  const renderFieldActions = (field: ConfirmationField, allowEnteredValue = false) => <>
    {showsUseValueAction(field, allowEnteredValue) ? <AccessiblePressable accessibilityLabel={`Use ${field.label} value`} disabled={submitting} onPress={() => { const value = field.decision === "omitted" ? field.suggestedValue ?? "" : field.confirmedValue; replaceField(updateReview(field, value, value === (field.suggestedValue ?? "") ? "accepted" : "edited")); }}><Text style={styles.link}>Use value</Text></AccessiblePressable> : null}
    <AccessiblePressable accessibilityLabel={`Omit ${field.label}`} disabled={submitting || field.decision === "omitted"} onPress={() => replaceField(omitReview(field))}><Text style={styles.link}>Omit</Text></AccessiblePressable>
  </>;

  const cancel = () => {
    if (submittingRef.current || navigationClaimedRef.current || successClaimedRef.current) return;
    const accepted = onCancel();
    if (accepted !== false) {
      navigationClaimedRef.current = true;
    }
  };

  const retake = () => {
    if (submittingRef.current || navigationClaimedRef.current || successClaimedRef.current) return;
    const accepted = onRetake();
    if (accepted !== false) {
      navigationClaimedRef.current = true;
    }
  };

  const submit = async () => {
    if (submittingRef.current || navigationClaimedRef.current || successClaimedRef.current) return;
    if (reviewItems.length > 0) {
      setDirectedReviewVisible(true);
      return;
    }
    const catalogError = nutrientCatalogSubmissionError({
      isError: nutrientQuery.isError,
      isLoading: nutrientQuery.isLoading,
      canonicalUnitsAvailable,
    });
    if (catalogError) {
      setValidationAttempted(false);
      setSubmissionError(catalogError);
      return;
    }
    const issues = confirmationValidationIssues(hydratedDraft);
    if (issues.length > 0) {
      validationFocusKeyRef.current = confirmationValidationFocusKey(issues[0]!.fieldKey);
      setSubmissionError(null);
      setValidationAttempted(true);
      return;
    }
    const candidate = confirmationPayload(hydratedDraft, FINGERPRINT_PLACEHOLDER_REQUEST_ID);
    if (!candidate) return;
    intentRef.current = bindConfirmationIntent(intentRef.current, candidate, createClientRequestId);
    const payload = { ...candidate, client_request_id: intentRef.current.requestId };
    submittingRef.current = true; setSubmitting(true); setValidationAttempted(false); setSubmissionError(null);
    try {
      const response = await runtime.ocr.confirmNutritionLabel(payload);
      await queryClient.invalidateQueries({ queryKey: ["foods"] });
      if (mountedRef.current && !successClaimedRef.current) {
        successClaimedRef.current = true;
        if (draftStateKey && onDraftStateChange) {
          onDraftStateChange(draftStateKey, CLEAN_DRAFT_STATUS);
        }
        onCreated(response.food.id);
      }
    } catch (caught) {
      if (confirmationErrorCode(caught) === "ocr_confirmation_idempotency_conflict") {
        intentRef.current = null;
      }
      submittingRef.current = false;
      if (mountedRef.current) {
        validationFocusKeyRef.current = null;
        setValidationAttempted(false);
        setSubmitting(false);
        setSubmissionError(confirmationErrorMessage(caught));
      }
    }
  };

  const handleReviewShow = () => {
    if (!reviewPresented) return;
    reviewModalPresentedRef.current = true;
    reviewFocusedItemKeyRef.current = directedReviewItemKey(currentReviewItem);
  };

  return <View style={styles.screen}>
    <View accessibilityElementsHidden={reviewPresented} importantForAccessibility={reviewPresented ? "no-hide-descendants" : "auto"} style={styles.screenContent}>
      <KeyboardSafeScrollView ref={scrollRef} contentContainerStyle={styles.content}>{(focusProps) => <>
      <View style={styles.header}><Text ref={headingRef} accessibilityRole="header" style={styles.title}>Confirm nutrition</Text><AccessiblePressable accessibilityLabel="Cancel confirmation" disabled={submitting} onPress={cancel}><Text style={styles.link}>Cancel</Text></AccessiblePressable></View>
      <Text accessibilityLiveRegion="polite" style={styles.notice}>Review flagged values. The image is not uploaded or saved.</Text>
      <Text accessibilityRole="header" style={styles.section}>Food</Text>
      <LabeledField {...focusProps("ocr.name")} label="Food name" validationTarget="ocr.name" required disabled={submitting} invalid={issuesByField.has("food.name")} error={issuesByField.get("food.name")?.message ?? null} value={draft.name} onChangeText={(name) => setDraft({ ...draft, name })} placeholder="Food name" placeholderTextColor={theme.colors.placeholder} inputStyle={styles.input}/>
      <LabeledField {...focusProps("ocr.brand")} label="Brand" validationTarget="ocr.brand" disabled={submitting} value={draft.brand} onChangeText={(brand) => setDraft({ ...draft, brand })} placeholder="Brand" placeholderTextColor={theme.colors.placeholder} inputStyle={styles.input}/>
      <LabeledField {...focusProps("ocr.notes")} label="Notes" validationTarget="ocr.notes" disabled={submitting} value={draft.notes} onChangeText={(notes) => setDraft({ ...draft, notes })} placeholder="Notes" placeholderTextColor={theme.colors.placeholder} inputStyle={styles.input}/>
      <Text accessibilityRole="header" style={styles.section}>Serving</Text>
      <OcrServingEditor
        value={{
          servingDisplay: draft.servingDisplay,
          servingQuantity: draft.servingQuantity,
          servingUnit: draft.servingUnit,
          gramWeight: draft.gramWeight,
        }}
        onChange={(patch) => setDraft((current) => ({ ...current, ...patch }))}
        disabled={submitting}
        focusProps={focusProps}
        quantityError={issuesByField.get("serving.quantity")?.message ?? null}
        unitError={issuesByField.get("serving.unit")?.message ?? null}
        gramWeightError={issuesByField.get("serving.gram_weight")?.message ?? null}
      />
      <Text accessibilityRole="header" style={styles.section}>Nutrition per label serving</Text>
      {fields.map((field) => <View key={field.fieldKey} style={[styles.card, field.decision === "unresolved" && styles.flagged, field.decision === "omitted" && styles.omitted]}>
        <NutrientAmountRow
          {...focusProps(`ocr.field.${field.fieldKey}`)}
          label={field.label}
          validationTarget={`ocr.field.${field.fieldKey}`}
          unit={field.unit}
          disabled={submitting}
          reviewRequired={field.decision === "unresolved"}
          invalid={issuesByField.has(field.fieldKey)}
          error={issuesByField.get(field.fieldKey)?.message ?? null}
          action={renderFieldActions(field)}
          value={field.confirmedValue}
          onChangeText={(value) => replaceField(updateReview(field, value))}
          keyboardType="decimal-pad"
          placeholder="0"
          placeholderTextColor={theme.colors.placeholder}
        />
      </View>)}
      <AccessiblePressable accessibilityLabel="Add missing nutrient" disabled={submitting || nutrientQuery.isLoading || nutrientQuery.isError} onPress={() => setShowMissingNutrients((current) => !current)} style={styles.secondaryButton}><Text style={styles.link}>Add missing nutrient</Text></AccessiblePressable>
      {showMissingNutrients ? <View style={styles.picker}><Text accessibilityRole="header" style={styles.fieldLabel}>Choose a nutrient</Text>{availableNutrients.map((nutrient) => <AccessiblePressable key={nutrient.id} accessibilityLabel={`Add ${nutrient.display_name}`} disabled={submitting} onPress={() => { setDraft((current) => addManualNutrient(current, nutrient)); setShowMissingNutrients(false); }} style={styles.pickerOption}><Text style={styles.link}>{nutrient.display_name} ({nutrient.default_unit})</Text></AccessiblePressable>)}{availableNutrients.length === 0 ? <Text style={styles.meta}>All canonical nutrients are already in this review.</Text> : null}</View> : null}
      {draft.unknownNutrients.length ? <><Text accessibilityRole="header" style={styles.section}>Unknown rows</Text>{draft.unknownNutrients.map((item, index) => <View key={`${item.originalName}-${index}`} style={[styles.card, !item.dismissed && styles.flagged, item.dismissed && styles.omitted]}><Text accessible accessibilityLabel={`Unknown nutrient ${item.originalName}, ${item.dismissed ? "dismissed" : "unresolved"}`} style={styles.fieldLabel}>{item.originalName}</Text><AccessiblePressable accessibilityLabel={`Dismiss unknown nutrient ${item.originalName}`} disabled={submitting || item.dismissed} onPress={() => dismissUnknown(index)}><Text style={styles.link}>{item.dismissed ? "Dismissed" : "Dismiss after review"}</Text></AccessiblePressable></View>)}</> : null}
      {displayedError ? <Text ref={errorRef} accessibilityLiveRegion="none" accessibilityRole="alert" style={styles.error}>{displayedError}</Text> : null}
    </>}</KeyboardSafeScrollView>
      <View testID="nutrition-confirmation-actions" style={styles.saveBar}>
        <AccessiblePressable
          testID="nutrition-confirmation-retake-island"
          accessibilityLabel="Retake nutrition label photo"
          accessibilityHint="Discards this unsubmitted review and opens the camera for a replacement photo"
          disabled={submitting}
          onPress={retake}
          style={[styles.retakeIsland, submitting && styles.disabled]}
        ><Text style={styles.retakeLabel}>Retake photo</Text></AccessiblePressable>
        <AccessiblePressable
          ref={reviewTriggerRef}
          testID="nutrition-confirmation-primary-action"
          busy={submitting}
          accessibilityLabel={submitting ? "Creating Food" : reviewItems.length > 0 ? directedReviewActionCopy(reviewItems.length) : "Create Food"}
          accessibilityHint={reviewItems.length > 0 ? "Opens the focused review for unresolved nutrition items" : "Creates the food, then opens logging confirmation when started from Add Food"}
          onPress={reviewItems.length > 0 ? () => setDirectedReviewVisible(true) : submit}
          style={[styles.button, submitting && styles.disabled]}
        ><Text style={styles.buttonText}>{submitting ? "Creating Food…" : reviewItems.length > 0 ? directedReviewActionCopy(reviewItems.length) : "Create Food"}</Text></AccessiblePressable>
      </View>
    </View>
    <AccessibleModal
      visible={reviewPresented}
      title="Review nutrition"
      onRequestClose={() => setDirectedReviewVisible(false)}
      busy={submitting}
      onShow={handleReviewShow}
      initialFocusRef={currentReviewItem?.kind === "field" ? reviewFieldRef : reviewHeadingRef}
      returnFocusRef={reviewTriggerRef}
      fallbackFocusRef={headingRef}
      backdropStyle={styles.reviewBackdrop}
      contentStyle={styles.reviewModal}
      scrollContentStyle={styles.reviewContent}
      scrollable
      headingStyle={styles.reviewTitle}
      testID="nutrition-directed-review"
    >
      <Text style={styles.reviewProgress}>{reviewItems.length} item{reviewItems.length === 1 ? "" : "s"} remaining</Text>
      {currentReviewItem?.kind === "field" ? <View style={styles.reviewItemCard}>
        <NutrientAmountRow
          ref={reviewFieldRef}
          label={currentReviewItem.field.label}
          validationTarget={`ocr.directed.${currentReviewItem.field.fieldKey}`}
          unit={currentReviewItem.field.unit}
          disabled={submitting}
          reviewRequired
          invalid={issuesByField.has(currentReviewItem.field.fieldKey)}
          error={issuesByField.get(currentReviewItem.field.fieldKey)?.message ?? null}
          action={renderFieldActions(currentReviewItem.field, true)}
          testID="nutrition-directed-review-amount"
          value={currentReviewItem.field.confirmedValue}
          onChangeText={(value) => updateDirectedReviewValue(currentReviewItem.field, value)}
          keyboardType="decimal-pad"
          placeholder="0"
          placeholderTextColor={theme.colors.placeholder}
        />
      </View> : currentReviewItem?.kind === "unknown" ? <View style={styles.reviewItemCard}>
        <Text ref={reviewHeadingRef} accessibilityRole="header" style={styles.reviewItemTitle}>{currentReviewItem.label}</Text>
        <Text style={styles.reviewInstruction}>Dismiss this unrecognized nutrient before creating the Food.</Text>
        <AccessiblePressable accessibilityLabel={`Dismiss unknown nutrient ${currentReviewItem.label}`} disabled={submitting} onPress={() => dismissUnknown(currentReviewItem.index)}><Text style={styles.link}>Dismiss</Text></AccessiblePressable>
      </View> : null}
      <AccessiblePressable
        accessibilityLabel="Retake nutrition label photo"
        accessibilityHint="Discards this unsubmitted review and opens the camera for a replacement photo"
        disabled={submitting}
        onPress={retake}
        style={styles.reviewClose}
      ><Text style={styles.link}>Retake photo</Text></AccessiblePressable>
      <AccessiblePressable accessibilityLabel="Close nutrition review" disabled={submitting} onPress={() => setDirectedReviewVisible(false)} style={styles.reviewClose}><Text style={styles.link}>Continue editing</Text></AccessiblePressable>
    </AccessibleModal>
  </View>;
}

function createStyles(theme: ReturnType<typeof useAppTheme>) { return StyleSheet.create({
  button: { alignItems: "center", backgroundColor: theme.colors.primaryActionBackground, borderRadius: 8, minHeight: 48, justifyContent: "center", width: "100%" },
  buttonText: { color: theme.colors.primaryActionForeground, fontSize: 16, fontWeight: "700" }, card: { backgroundColor: theme.colors.surface, borderColor: theme.colors.border, borderRadius: 8, borderWidth: 1, gap: 8, padding: 12 },
  content: { gap: 10, padding: 16, paddingBottom: 184 }, disabled: { opacity: 0.65 }, error: { color: theme.colors.errorText }, fieldLabel: { color: theme.colors.text, flex: 1, fontSize: 16, fontWeight: "700" }, flagged: { borderColor: theme.colors.warningText, borderWidth: 1 }, flex: { flex: 1 },
  header: { alignItems: "center", flexDirection: "row", flexWrap: "wrap", justifyContent: "space-between" }, input: { backgroundColor: theme.colors.input, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, color: theme.colors.text, minHeight: 44, padding: 10 }, link: { color: theme.colors.accent, fontWeight: "600" }, meta: { color: theme.colors.secondaryText }, notice: { color: theme.colors.secondaryText }, row: { alignItems: "center", flexDirection: "row", flexWrap: "wrap", gap: 10 },
  reviewBackdrop: { backgroundColor: "rgba(0, 0, 0, 0.45)", padding: 16 }, reviewClose: { alignSelf: "flex-start" }, reviewContent: { padding: 16 }, reviewInstruction: { color: theme.colors.secondaryText }, reviewItemCard: { backgroundColor: theme.colors.surface, borderColor: theme.colors.warningText, borderRadius: 8, borderWidth: 1, gap: 10, padding: 14 }, reviewItemTitle: { color: theme.colors.text, fontSize: 18, fontWeight: "700" }, reviewModal: { backgroundColor: theme.colors.background, borderRadius: 12, maxHeight: "88%" }, reviewProgress: { color: theme.colors.secondaryText }, reviewTitle: { color: theme.colors.text, fontSize: 20, fontWeight: "800" }, saveBar: { paddingBottom: 8, paddingHorizontal: 16, paddingTop: 10, position: "relative" }, screen: { backgroundColor: theme.colors.background, flex: 1 }, screenContent: { flex: 1 }, section: { color: theme.colors.text, fontSize: 19, fontWeight: "800", marginTop: 8 }, title: { color: theme.colors.text, fontSize: 25, fontWeight: "800" },
  omitted: { opacity: 0.7 },
  picker: { borderColor: theme.colors.border, borderRadius: 8, borderWidth: 1, gap: 8, padding: 12 },
  pickerOption: { justifyContent: "center", minHeight: 44 },
  secondaryButton: { alignItems: "flex-start", justifyContent: "center", minHeight: 44 },
  retakeIsland: {
    alignItems: "center",
    backgroundColor: theme.colors.primaryActionBackground,
    borderColor: theme.colors.primaryActionBorder,
    borderRadius: 25,
    borderWidth: 1,
    bottom: 76,
    elevation: 5,
    justifyContent: "center",
    minHeight: 50,
    paddingHorizontal: 18,
    position: "absolute",
    right: 16,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.22,
    shadowRadius: 5,
    zIndex: 3,
  },
  retakeLabel: { color: theme.colors.primaryActionForeground, fontSize: 16, fontWeight: "700" },
}); }

function confirmationValidationFocusKey(fieldKey: string | null): string | null {
  if (fieldKey === "food.name") return "ocr.name";
  if (fieldKey === "serving.quantity") return "ocr.servingQuantity";
  if (fieldKey === "serving.unit") return "ocr.servingUnit";
  if (fieldKey === "serving.gram_weight") return "ocr.gramWeight";
  return fieldKey?.startsWith("nutrient.") ? `ocr.field.${fieldKey}` : null;
}
