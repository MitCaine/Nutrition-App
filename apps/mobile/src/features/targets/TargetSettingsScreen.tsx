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
import { RouteScreenHeader } from "../../shared/components/RouteScreenHeader";
import { TransientSuccessBanner } from "../../shared/components/TransientSuccessBanner";
import { formatDisplayNumber } from "../../shared/nutrition/display";
import { NUTRIENT_CATALOG } from "../../shared/nutrition/catalog";
import {
  canonicalNutrientParentId,
  groupCanonicalNutrientsBySection,
  nutrientVisibleDepth,
} from "../../shared/nutrition/nutrientSections";
import type { TargetConfiguration } from "./api/types";
import {
  targetBasisLabel,
  targetSourceVersionLabel,
} from "./targetReference";
import { targetErrorMessage } from "./targetErrors";
import {
  EMPTY_TARGET_DRAFT,
  targetDraft,
  targetDraftError,
  targetDraftOverrideValue,
  targetInput,
  targetUnavailableMessage,
  resetTargetDraftOverride,
  setTargetDraftOverride,
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


const PRIMARY_NUTRIENT_IDS =
  new Set([
    "calories",
    "protein",
    "total_carbohydrate",
    "total_fat",
  ]);

const SECONDARY_NUTRIENT_SECTIONS =
  groupCanonicalNutrientsBySection(
    NUTRIENT_CATALOG.filter(
      (nutrient) =>
        !PRIMARY_NUTRIENT_IDS.has(
          nutrient.id,
        ),
    ),
    (nutrient) => nutrient.id,
  );

const SECONDARY_NUTRIENT_IDS =
  new Set(
    SECONDARY_NUTRIENT_SECTIONS
      .flatMap(
        (section) =>
          section.items.map(
            (nutrient) =>
              nutrient.id,
          ),
      ),
  );

function savedTargetSummary(
  target:
    | TargetConfiguration[
        "effectiveTargets"
      ][number]
    | undefined,
): string {
  if (!target) {
    return "No saved target information";
  }

  if (
    target.trackingMode === "ignored"
  ) {
    return "Not shown in daily tracking";
  }

  if (
    target.trackingMode
      === "amount_only"
    && target.reasonCode
      === "target_reference_not_established"
  ) {
    return (
      "No established daily goal · "
      + "total consumed is still tracked"
    );
  }

  if (
    target.trackingMode
      === "amount_only"
  ) {
    return (
      "No daily goal · "
      + "total consumed is still tracked"
    );
  }

  if (
    target.reasonCode
      === "target_profile_incomplete"
  ) {
    return (
      "Recommended target unavailable"
      + " · Complete profile"
    );
  }

  if (
    target.reasonCode
      === "target_estimate_unsupported_age"
    || target.reasonCode
      === "target_estimate_unsupported_context"
  ) {
    return (
      "Recommended target unavailable"
      + " for this profile"
    );
  }

  if (
    target.amount === null
  ) {
    return "Recommended target unavailable";
  }

  return (
    `${formatDisplayNumber(
      target.amount,
      {
        maxFractionDigits: 1,
      },
    )} ${target.unit}/day`
    + ` · ${targetBasisLabel(target)}`
  );
}

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

  const reset = (nutrientId: string) => {
    if (submittingRef.current) {
      return;
    }

    setError(null);
    setSuccessMessage(null);
    setDraft((current) =>
      resetTargetDraftOverride(current, nutrientId)
    );
  };

  if (query.isLoading && !result) {
    return (
      <View style={styles.screen}>
        <RouteScreenHeader
          title="Nutrition targets"
          titleStyle={styles.title}
          leading={(
            <BackButton
              accessibilityLabel="Back from nutrition targets"
              onPress={onBack}
            />
          )}
        />
        <View style={styles.loadingContent}>
          <Text style={styles.text}>
            Loading nutrition targets…
          </Text>
        </View>
      </View>
    );
  }

  if (query.isError && !result) {
    return (
      <View style={styles.screen}>
        <RouteScreenHeader
          title="Nutrition targets"
          titleStyle={styles.title}
          leading={(
            <BackButton
              accessibilityLabel="Back from nutrition targets"
              onPress={onBack}
            />
          )}
        />
        <View style={styles.loadingContent}>
          <Text
            accessibilityRole="alert"
            style={styles.error}
          >
            Could not load nutrition targets.
          </Text>
        </View>
      </View>
    );
  }

  const estimate =
    result?.estimatedMaintenanceCalories;

  return (
    <View style={styles.screen}>
      <RouteScreenHeader
        title="Nutrition targets"
        titleStyle={styles.title}
        leading={(
          <BackButton
            accessibilityLabel="Back from nutrition targets"
            disabled={submitting}
            onPress={onBack}
          />
        )}
      />

      <KeyboardSafeScrollView contentContainerStyle={styles.content}>
        {() => (
          <>
            <TransientSuccessBanner
                message={successMessage}
                onExpired={() => setSuccessMessage(null)}
            />

            <Text style={styles.notice}>
              Changes on this screen remain drafts until you choose Save targets.
              Reset clears a manual target only in this draft; it does not change
              the saved target until you save.
            </Text>

            <Text style={styles.notice}>
              Dietary Reference Intakes use personalized RDA or AI
              recommendations when your profile supports them. FDA Daily
              Values remain regulatory fallback references, and manual targets
              take precedence over both.
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
              Optional custom targets
            </Text>

            <Text style={styles.notice}>
              Leave a field blank to use the recommended target. Enter a value
              only when you want to override that recommendation.
            </Text>

            {PERSONAL_TARGETS.map(([key, label, unit]) => {
              const nutrientId =
                key === "totalCarbohydrate"
                  ? "total_carbohydrate"
                  : key === "totalFat"
                    ? "total_fat"
                    : key;

              const effective =
                result?.effectiveTargets.find(
                  (item) =>
                    item.nutrientId
                    === nutrientId,
                );

              const persistedOverride =
                persistedDraft[key];

              const draftOverride =
                targetDraftOverrideValue(
                  draft,
                  nutrientId,
                );

              const effectiveBasis =
                effective
                  ? targetBasisLabel(
                      effective,
                    )
                  : "Unavailable";

              const effectiveSource =
                effective
                  ? targetSourceVersionLabel(
                      effective,
                      result
                        ?.dailyValueCatalogVersion,
                    )
                  : null;

              const hasManualOverride =
                Boolean(draftOverride);

              const resetPending =
                Boolean(
                  persistedOverride,
                )
                && !draftOverride;

              const manualChangePending =
                Boolean(draftOverride)
                && draftOverride
                  !== persistedOverride;

              return (
                <View
                  key={key}
                  style={styles.targetField}
                >
                  <Text
                    style={styles.fieldLabel}
                  >
                    {label}
                  </Text>

                  <View
                    style={
                      styles
                        .targetInputContainer
                    }
                  >
                    <TextInput
                      editable={
                        !submitting
                      }
                      accessibilityLabel={`${label} personal target`}
                      accessibilityState={{
                        disabled:
                          submitting,
                      }}
                      value={
                        draftOverride
                      }
                      onChangeText={(
                        value,
                      ) =>
                        setDraft(
                          (
                            current,
                          ) =>
                            setTargetDraftOverride(
                              current,
                              nutrientId,
                              value,
                            ),
                        )
                      }
                      keyboardType="decimal-pad"
                      placeholder={`${label} (${unit}/day)`}
                      placeholderTextColor={
                        theme.colors
                          .placeholder
                      }
                      style={[
                        styles.input,
                        styles
                          .targetInput,
                      ]}
                    />

                    {hasManualOverride ? (
                      <Pressable
                        accessibilityRole="button"
                        accessibilityLabel={`Reset ${label} target`}
                        accessibilityHint="Clears this manual target in the draft. Choose Save targets to apply the reset."
                        disabled={
                          submitting
                        }
                        accessibilityState={{
                          disabled:
                            submitting,
                        }}
                        onPress={() =>
                          reset(
                            nutrientId,
                          )
                        }
                        style={
                          styles
                            .resetAction
                        }
                      >
                        <Text
                          style={
                            styles.link
                          }
                        >
                          Reset
                        </Text>
                      </Pressable>
                    ) : null}
                  </View>

                  {resetPending ? (
                    <Text
                      accessibilityLabel={`${label} target reset pending save`}
                      style={
                        styles.pending
                      }
                    >
                      Reset pending ·
                      Save targets to
                      apply.
                    </Text>
                  ) : manualChangePending ? (
                    <Text
                      accessibilityLabel={`${label} manual target change pending save`}
                      style={
                        styles.pending
                      }
                    >
                      {`Pending manual target: ${draftOverride} ${unit}/day · Save targets to apply.`}
                    </Text>
                  ) : null}

                  <Text
                    accessibilityLabel={`${label} current saved effective target basis ${effectiveBasis}`}
                    style={styles.notice}
                  >
                    {effective?.amount
                      ? `Current saved effective: ${formatDisplayNumber(effective.amount, { maxFractionDigits: 1 })} ${effective.unit}/day · ${effectiveBasis}`
                      : `Current saved effective: ${savedTargetSummary(effective)}`}
                  </Text>

                  {effectiveSource ? (
                    <Text
                      accessibilityLabel={`${label} target source version ${effectiveSource}`}
                      style={
                        styles.notice
                      }
                    >
                      {`Reference source: ${effectiveSource}`}
                    </Text>
                  ) : null}
                </View>
              );
            })}

            <View style={styles.managerSection}>
              <Text
                accessibilityRole="header"
                style={styles.section}
              >
                Additional nutrients
              </Text>

              <Text style={styles.notice}>
                By default, Daily Log shows the full supported nutrient
                catalog. Recommended values are selected automatically when an
                authoritative daily goal is available. Nutrients without an
                established daily goal still show total consumed.
              </Text>

              {SECONDARY_NUTRIENT_SECTIONS.map(
                (section) => (
                  <View
                    key={section.id}
                    style={
                      styles.nutrientSection
                    }
                  >
                    {section.label ? (
                      <Text
                        accessibilityRole="header"
                        style={
                          styles
                            .nutrientGroupHeading
                        }
                      >
                        {section.label}
                      </Text>
                    ) : null}

                    {section.items.map(
                      (nutrient) => {
                        const effective =
                          result
                            ?.effectiveTargets
                            .find(
                              (item) =>
                                item.nutrientId
                                === nutrient.id,
                            );

                        const source =
                          effective
                            ? targetSourceVersionLabel(
                                effective,
                                result
                                  ?.dailyValueCatalogVersion,
                              )
                            : null;

                        return (
                          <View
                            key={
                              nutrient.id
                            }
                            style={[
                              styles
                                .nutrientCard,
                              (() => {
                                const depth =
                                  nutrientVisibleDepth(
                                    nutrient.id,
                                    SECONDARY_NUTRIENT_IDS,
                                    canonicalNutrientParentId,
                                  );

                                return depth > 0
                                  ? {
                                      marginLeft:
                                        depth * 16,
                                    }
                                  : undefined;
                              })(),
                            ]}
                          >
                            <Text
                              style={
                                styles
                                  .fieldLabel
                              }
                            >
                              {
                                nutrient
                                  .display_name
                              }
                            </Text>

                            <Text
                              accessibilityLabel={`${nutrient.display_name} saved target summary`}
                              style={
                                styles.notice
                              }
                            >
                              {savedTargetSummary(
                                effective,
                              )}
                            </Text>

                            {source ? (
                              <Text
                                style={
                                  styles
                                    .notice
                                }
                              >
                                {
                                  `Reference source: ${source}`
                                }
                              </Text>
                            ) : null}
                          </View>
                        );
                      },
                    )}
                  </View>
                ),
              )}
            </View>

            <Text style={styles.notice}>
              Nutrient comparisons use personalized RDA or AI recommendations
              when supported, then FDA Daily Values as fallback references.
            </Text>

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
    loadingContent: {
      padding: 16,
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
    managerHeader: {
      alignItems: "flex-start",
      flexDirection: "row",
      gap: 8,
      justifyContent: "space-between",
    },
    managerHeaderCopy: {
      flex: 1,
      gap: 4,
    },
    managerSection: {
      gap: 8,
    },
    managerToggle: {
      alignItems: "center",
      justifyContent: "center",
      minHeight: 44,
    },
    modeChoice: {
      alignItems: "center",
      backgroundColor: theme.colors.surface,
      borderColor: theme.colors.border,
      borderRadius: 6,
      borderWidth: 1,
      flexBasis: 105,
      flexGrow: 1,
      justifyContent: "center",
      minHeight: 40,
      paddingHorizontal: 8,
      paddingVertical: 7,
    },
    modeChoiceSelected: {
      backgroundColor: theme.colors.selectedNavigationBackground,
      borderColor: theme.colors.accent,
    },
    modeChoiceText: {
      color: theme.colors.text,
      fontSize: 13,
      textAlign: "center",
    },
    modeRow: {
      flexDirection: "row",
      flexWrap: "wrap",
      gap: 6,
    },
    notice: {
      color: theme.colors.secondaryText,
    },
    result: {
      color: theme.colors.text,
      fontWeight: "700",
    },
    pending: {
      color: theme.colors.warningText,
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
    nutrientGroupHeading: {
      borderBottomColor:
        theme.colors.border,
      borderBottomWidth: 2,
      color: theme.colors.text,
      fontSize: 16,
      fontWeight: "800",
      letterSpacing: 0.8,
      marginTop: 14,
      paddingBottom: 6,
      textTransform: "uppercase",
    },
    nutrientSection: {
      gap: 8,
    },
    nutrientCard: {
      backgroundColor: theme.colors.surface,
      borderColor: theme.colors.border,
      borderRadius: 8,
      borderWidth: 1,
      gap: 7,
      padding: 10,
    },
    nutrientHeading: {
      alignItems: "center",
      flexDirection: "row",
      gap: 8,
      justifyContent: "space-between",
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
    stateLabel: {
      color: theme.colors.accent,
      fontSize: 12,
      fontWeight: "700",
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
