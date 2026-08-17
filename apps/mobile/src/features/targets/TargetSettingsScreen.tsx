import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { useAppTheme } from "../../app/theme/AppTheme";
import { KeyboardSafeScrollView } from "../../shared/forms/KeyboardSafeScrollView";
import { BackButton } from "../../shared/components/BackButton";
import { TransientSuccessBanner } from "../../shared/components/TransientSuccessBanner";
import { formatDisplayNumber } from "../../shared/nutrition/display";
import type { TargetConfiguration } from "./api/types";
import { targetErrorMessage } from "./targetErrors";
import {
  EMPTY_TARGET_DRAFT,
  targetDraft,
  targetDraftError,
  targetInput,
  targetUnavailableMessage,
} from "./targetModel";
import { useNutritionRuntime } from "../../runtime/NutritionRuntimeContext";
import {
  draftObjectsEqual,
  useDraftStatusReporter,
  type DraftStatusReporter,
} from "../../shared/navigation/draftGuard";

const ACTIVITY = [
  {
    value: "sedentary",
    label: "Sedentary",
    description: "Mostly seated with little intentional activity.",
    multiplier: "1.4",
  },
  {
    value: "lightly_active",
    label: "Lightly active",
    description: "Some routine walking or light exercise.",
    multiplier: "1.6",
  },
  {
    value: "active",
    label: "Active",
    description: "Regular moderate activity.",
    multiplier: "1.8",
  },
  {
    value: "very_active",
    label: "Very active",
    description: "Substantial daily activity or frequent demanding exercise.",
    multiplier: "2.0",
  },
] as const;

const CONDITION_OPTIONS = [
  { value: "pregnant", label: "Pregnant" },
  { value: "lactating", label: "Lactating" },
] as const;

const PERSONAL_TARGETS = [
  ["calories", "Calories", "kcal"],
  ["protein", "Protein", "g"],
  ["totalCarbohydrate", "Carbohydrate", "g"],
  ["totalFat", "Fat", "g"],
] as const;

const authorityLabel = (authority: string) =>
  authority === "daily_value"
    ? "FDA Daily Value"
    : authority.replaceAll("_", " ");

export function TargetSettingsScreen({
  onBack,
  draftStateKey,
  onDraftStateChange,
}: {
  onBack: () => void;
  draftStateKey?: string;
  onDraftStateChange?: DraftStatusReporter;
}) {
  const runtime = useNutritionRuntime();
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ["targets"],
    queryFn: () => runtime.targets.getConfiguration(),
  });

  const [draft, setDraft] = useState(EMPTY_TARGET_DRAFT);
  const [result, setResult] = useState<TargetConfiguration | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const initialized = useRef(false);
  const submittingRef = useRef(false);

  const persistedDraft = result ? targetDraft(result) : EMPTY_TARGET_DRAFT;
  const isDirty = !draftObjectsEqual(draft, persistedDraft);

  useDraftStatusReporter({
    draftKey: draftStateKey,
    dirty: isDirty,
    busy: submitting,
    reporter: onDraftStateChange,
  });

  useEffect(() => {
    if (!query.data || initialized.current) {
      return;
    }

    initialized.current = true;
    setResult(query.data);
    setDraft(targetDraft(query.data));
  }, [query.data]);

  const save = async () => {
    if (submittingRef.current) {
      return;
    }

    setSuccessMessage(null);

    const validation = targetDraftError(draft);

    if (validation) {
      setError(validation);
      return;
    }

    submittingRef.current = true;
    setSubmitting(true);
    setError(null);


    try {
      const next = await runtime.targets.updateConfiguration(targetInput(draft));

      setResult(next);
      setDraft(targetDraft(next));

      await queryClient.invalidateQueries({ queryKey: ["targets"] });
      await queryClient.invalidateQueries({
        queryKey: ["target-comparison"],
      });
      setSuccessMessage("Nutrition targets saved.");
    } catch (caught) {
      setError(targetErrorMessage(caught));
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  const reset = async (nutrientId: string) => {
    if (submittingRef.current) {
      return;
    }

    submittingRef.current = true;
    setSubmitting(true);
    setError(null);
    setSuccessMessage(null);


    try {
      const next = await runtime.targets.resetOverride(nutrientId);
      const draftKey =
        nutrientId === "total_carbohydrate"
          ? "totalCarbohydrate"
          : nutrientId === "total_fat"
            ? "totalFat"
            : nutrientId;
      const nutrientLabel =
          nutrientId === "total_carbohydrate"
              ? "Carbohydrate"
              : nutrientId === "total_fat"
                  ? "Fat"
                  : nutrientId === "calories"
                      ? "Calories"
                      : nutrientId === "protein"
                          ? "Protein"
                          : "Nutrition";

      setResult(next);
      setDraft((current) => ({
        ...current,
        [draftKey]: "",
      }));

      await queryClient.invalidateQueries({ queryKey: ["targets"] });
      await queryClient.invalidateQueries({
        queryKey: ["target-comparison"],
      });
      setSuccessMessage(`${nutrientLabel} target reset.`);
    } catch (caught) {
      setError(targetErrorMessage(caught));
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  if (query.isLoading && !result) {
    return (
      <View style={styles.screen}>
        <Text style={styles.text}>Loading nutrition targets…</Text>
      </View>
    );
  }

  if (query.isError && !result) {
    return (
      <View style={styles.screen}>
        <Text accessibilityRole="alert" style={styles.error}>
          Could not load nutrition targets.
        </Text>

        <BackButton accessibilityLabel="Back from nutrition targets" onPress={onBack} />
      </View>
    );
  }

  const estimate = result?.estimatedMaintenanceCalories;

  return (
    <View style={styles.screen}>
      <KeyboardSafeScrollView contentContainerStyle={styles.content}>
        {() => (
          <>
            <View style={styles.header}>
              <BackButton accessibilityLabel="Back from nutrition targets" disabled={submitting} onPress={onBack} />

              <Text accessibilityRole="header" style={styles.title}>
                Nutrition targets
              </Text>
            </View>

            <TransientSuccessBanner
                message={successMessage}
                onExpired={() => setSuccessMessage(null)}
            />

            <Text style={styles.notice}>
              FDA Daily Values are regulatory references. Personal targets are
              optional estimates or your manual overrides.
            </Text>

            <Text accessibilityRole="header" style={styles.section}>
              Estimated maintenance calories
            </Text>

            <Text style={styles.notice}>
              General informational estimate only—not medical advice. No
              weight-loss or weight-gain adjustment is applied.
            </Text>

            <View style={styles.profileRow}>
              <View style={[styles.profileField, styles.profileFieldWide]}>
                <Text style={styles.profileFieldLabel}>Birth date (MM-DD-YYYY)</Text>
                <TextInput
                  editable={!submitting}
                  accessibilityLabel="Birth date"
                  accessibilityState={{ disabled: submitting }}
                  value={draft.birthDate}
                  onChangeText={(birthDate) =>
                    setDraft((current) => ({ ...current, birthDate }))
                  }
                  placeholderTextColor={theme.colors.placeholder}
                  style={[styles.input, styles.profileInput]}
                />
              </View>

              <View style={styles.profileField}>
                <Text style={styles.profileFieldLabel}>Height (in)</Text>
                <TextInput
                  editable={!submitting}
                  accessibilityLabel="Height in inches"
                  accessibilityState={{ disabled: submitting }}
                  value={draft.heightIn}
                  onChangeText={(heightIn) =>
                    setDraft((current) => ({ ...current, heightIn }))
                  }
                  keyboardType="decimal-pad"
                  placeholderTextColor={theme.colors.placeholder}
                  style={[styles.input, styles.profileInput]}
                />
              </View>

              <View style={styles.profileField}>
                <Text style={styles.profileFieldLabel}>Weight (lb)</Text>
                <TextInput
                  editable={!submitting}
                  accessibilityLabel="Weight in pounds"
                  accessibilityState={{ disabled: submitting }}
                  value={draft.weightLb}
                  onChangeText={(weightLb) =>
                    setDraft((current) => ({ ...current, weightLb }))
                  }
                  keyboardType="decimal-pad"
                  placeholderTextColor={theme.colors.placeholder}
                  style={[styles.input, styles.profileInput]}
                />
              </View>
            </View>

            <View accessibilityRole="radiogroup" style={styles.choiceGroup}>
              <Text style={styles.label}>Sex used by estimation equation</Text>

              <View style={styles.choiceRow}>
                {(["male", "female"] as const).map((value) => {
                  const selected = draft.sexForEquation === value;

                  return (
                    <Pressable
                      key={value}
                      disabled={submitting}
                      accessibilityRole="radio"
                      accessibilityLabel={`Equation sex ${value}`}
                      accessibilityState={{
                        checked: selected,
                        disabled: submitting,
                      }}
                      onPress={() =>
                        setDraft((current) => ({
                          ...current,
                          sexForEquation: value,
                          energyEstimationContext: value === "male"
                            ? "general_adult"
                            : current.energyEstimationContext,
                        }))
                      }
                      style={({ pressed }) => [
                        styles.choice,
                        styles.choiceEqual,
                        selected && styles.choiceSelected,
                        pressed && styles.choicePressed,
                      ]}
                    >
                      <Text
                        style={[
                          styles.text,
                          selected && styles.choiceTextSelected,
                        ]}
                      >
                        {value === "female" ? "Female" : "Male"}
                      </Text>
                    </Pressable>
                  );
                })}
              </View>
            </View>

            <View accessibilityRole="radiogroup" style={styles.choiceGroup}>
              <Text style={styles.label}>Activity level</Text>

              <View style={styles.choiceGrid}>
                {ACTIVITY.map((option) => {
                  const selected = draft.activityLevel === option.value;

                  return (
                    <Pressable
                      key={option.value}
                      disabled={submitting}
                      accessibilityRole="radio"
                      accessibilityLabel={`Activity ${option.label}`}
                      accessibilityState={{
                        checked: selected,
                        disabled: submitting,
                      }}
                      onPress={() =>
                        setDraft((current) => ({
                          ...current,
                          activityLevel: option.value,
                        }))
                      }
                      style={({ pressed }) => [
                        styles.choice,
                        styles.gridChoice,
                        selected && styles.choiceSelected,
                        pressed && styles.choicePressed,
                      ]}
                    >
                      <Text
                        style={[
                          styles.text,
                          selected && styles.choiceTextSelected,
                        ]}
                      >
                        {option.label}
                      </Text>
                    </Pressable>
                  );
                })}
              </View>
            </View>

            {draft.sexForEquation === "female" ? (
              <View accessibilityRole="radiogroup" style={styles.choiceGroup}>
                <Text style={styles.label}>Optional conditions</Text>

                <View style={styles.choiceGrid}>
                  {CONDITION_OPTIONS.map((option) => {
                    const selected = draft.energyEstimationContext === option.value;

                    return (
                      <Pressable
                        key={option.value}
                        disabled={submitting}
                        accessibilityRole="radio"
                        accessibilityLabel={`${option.label} condition`}
                        accessibilityState={{
                          checked: selected,
                          disabled: submitting,
                        }}
                        onPress={() =>
                          setDraft((current) => ({
                            ...current,
                            energyEstimationContext: selected ? "general_adult" : option.value,
                          }))
                        }
                        style={({ pressed }) => [
                          styles.choice,
                          styles.gridChoice,
                          selected && styles.choiceSelected,
                          pressed && styles.choicePressed,
                        ]}
                      >
                        <Text
                          style={[
                            styles.text,
                            selected && styles.choiceTextSelected,
                          ]}
                        >
                          {option.label}
                        </Text>
                      </Pressable>
                    );
                  })}
                </View>
              </View>
            ) : null}

            <Text accessibilityLiveRegion="polite" style={styles.result}>
              {estimate?.availability === "available"
                ? `Estimated maintenance calories: ${estimate.amount} kcal/day (calculated estimate)`
                : targetUnavailableMessage(estimate?.reasonCode ?? null)}
            </Text>

            <Text accessibilityRole="header" style={styles.section}>
              Optional personal targets
            </Text>

            <Text style={styles.notice}>
              Manual targets take precedence and are never replaced when
              profile inputs change. Leave blank to use an estimate or FDA Daily
              Value when available.
            </Text>

            {PERSONAL_TARGETS.map(([key, label, unit]) => {
              const nutrientId =
                key === "totalCarbohydrate"
                  ? "total_carbohydrate"
                  : key === "totalFat"
                    ? "total_fat"
                    : key;

              const effective = result?.effectiveTargets.find(
                (item) => item.nutrientId === nutrientId,
              );

              const hasManualOverride = Boolean(draft[key]);

              return (
                <View key={key} style={styles.targetField}>
                  <View style={styles.targetInputContainer}>
                    <TextInput
                      editable={!submitting}
                      accessibilityLabel={`${label} personal target`}
                      accessibilityState={{ disabled: submitting }}
                      value={draft[key]}
                      onChangeText={(value) =>
                        setDraft((current) => ({
                          ...current,
                          [key]: value,
                        }))
                      }
                      keyboardType="decimal-pad"
                      placeholder={`${label} (${unit}/day)`}
                      placeholderTextColor={theme.colors.placeholder}
                      style={[styles.input, styles.targetInput]}
                    />

                    {hasManualOverride ? (
                      <Pressable
                        accessibilityRole="button"
                        accessibilityLabel={`Reset ${label} target`}
                        accessibilityHint="Clears the manual target override"
                        disabled={submitting}
                        accessibilityState={{ disabled: submitting }}
                        onPress={() => reset(nutrientId)}
                        style={styles.resetAction}
                      >
                        <Text style={styles.link}>Reset</Text>
                      </Pressable>
                    ) : null}
                  </View>

                  <Text
                    accessibilityLabel={`${label} effective target authority ${
                      effective
                        ? authorityLabel(effective.authority)
                        : "unavailable"
                    }`}
                    style={styles.notice}
                  >
                    {effective?.amount
                      ? `Effective: ${formatDisplayNumber(effective.amount, { maxFractionDigits: 1 })} ${effective.unit}/day · ${authorityLabel(effective.authority)}`
                      : "Effective target unavailable"}
                  </Text>
                </View>
              );
            })}

            <Text style={styles.notice}>Micronutrient comparisons use FDA Daily Values.</Text>

            {error ? (
              <Text
                accessibilityRole="alert"
                accessibilityLiveRegion="assertive"
                style={styles.error}
              >
                {error}
              </Text>
            ) : null}

            <Pressable
              accessibilityRole="button"
              accessibilityLabel={
                submitting
                  ? "Saving nutrition targets"
                  : "Save nutrition targets"
              }
              accessibilityState={{
                disabled: submitting,
                busy: submitting,
              }}
              disabled={submitting}
              onPress={save}
              style={[styles.button, submitting && styles.disabled]}
            >
              <Text style={styles.buttonText}>
                {submitting ? "Saving…" : "Save targets"}
              </Text>
            </Pressable>
          </>
        )}
      </KeyboardSafeScrollView>
    </View>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    button: {
      alignItems: "center",
      backgroundColor: theme.colors.primaryActionBackground,
      borderRadius: 8,
      justifyContent: "center",
      minHeight: 48,
    },
    buttonText: {
      color: theme.colors.primaryActionForeground,
      fontWeight: "700",
    },
    choice: {
      alignItems: "center",
      backgroundColor: theme.colors.surface,
      borderColor: theme.colors.border,
      borderRadius: 6,
      borderWidth: 1,
      justifyContent: "center",
      minHeight: 48,
      padding: 12,
    },
    choiceEqual: {
      flex: 1,
    },
    choiceGroup: {
      gap: 8,
    },
    choiceRow: {
      flexDirection: "row",
      gap: 8,
    },
    choiceGrid: {
      flexDirection: "row",
      flexWrap: "wrap",
      gap: 8,
    },
    choicePressed: {
      opacity: 0.75,
    },
    choiceSelected: {
      backgroundColor: theme.colors.selectedNavigationBackground,
      borderColor: theme.colors.accent,
    },
    choiceTextSelected: {
      color: theme.colors.accent,
      fontWeight: "700",
    },
    content: {
      gap: 10,
      padding: 16,
      paddingBottom: 16,
    },
    disabled: {
      opacity: 0.6,
    },
    error: {
      color: theme.colors.errorText,
    },
    fieldLabel: {
      color: theme.colors.text,
      fontWeight: "700",
    },
    gridChoice: {
      flexBasis: 140,
      flexGrow: 1,
      minWidth: 140,
    },
    header: {
      gap: 8,
    },
    input: {
      backgroundColor: theme.colors.secondarySurface,
      borderColor: theme.colors.searchInputBorder,
      borderRadius: 6,
      borderWidth: 1,
      color: theme.colors.text,
      minHeight: 44,
      padding: 10,
    },
    label: {
      color: theme.colors.text,
      fontWeight: "700",
      marginBottom: 4,
    },
    link: {
      color: theme.colors.accent,
      fontWeight: "600",
      padding: 10,
    },
    notice: {
      color: theme.colors.secondaryText,
    },
    result: {
      color: theme.colors.text,
      fontWeight: "700",
    },
    profileField: {
      flexBasis: 80,
      flexGrow: 0,
      flexShrink: 0,
      gap: 4,
      width: 80,
    },
    profileFieldWide: {
      flexBasis: 0,
      flexGrow: 1,
      flexShrink: 1,
      minWidth: 0,
    },
    profileFieldLabel: {
      color: theme.colors.text,
      fontSize: 12,
      fontWeight: "700",
    },
    profileInput: {
      minWidth: 0,
      width: "100%",
    },
    profileRow: {
      alignItems: "flex-start",
      flexDirection: "row",
      flexWrap: "nowrap",
      gap: 8,
    },
    resetAction: {
      alignItems: "center",
      justifyContent: "center",
      minHeight: 44,
      paddingRight: 4,
    },
    screen: {
      backgroundColor: theme.colors.background,
      flex: 1,
    },
    section: {
      color: theme.colors.text,
      fontSize: 19,
      fontWeight: "800",
      marginTop: 8,
    },
    targetField: {
      gap: 6,
      marginBottom: 4,
    },
    targetInput: {
      backgroundColor: "transparent",
      borderWidth: 0,
      flex: 1,
      minWidth: 0,
    },
    targetInputContainer: {
      alignItems: "center",
      backgroundColor: theme.colors.input,
      borderColor: theme.colors.border,
      borderRadius: 6,
      borderWidth: 1,
      flexDirection: "row",
      minHeight: 44,
    },
    text: {
      color: theme.colors.text,
    },
    title: {
      color: theme.colors.text,
      fontSize: 28,
      fontWeight: "800",
    },
  });
}
