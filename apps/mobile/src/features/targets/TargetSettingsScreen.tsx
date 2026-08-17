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
import { NUTRIENT_CATALOG } from "../../shared/nutrition/catalog";
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
  targetDraftMode,
  targetDraftOverrideValue,
  targetInput,
  targetUnavailableMessage,
  resetTargetDraftOverride,
  setTargetDraftMode,
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

const SECONDARY_NUTRIENTS =
  NUTRIENT_CATALOG.filter(
    (nutrient) =>
      !PRIMARY_NUTRIENT_IDS.has(
        nutrient.id,
      ),
  );

const TRACKING_MODES = [
  {
    value: "recommended",
    label: "Recommended",
  },
  {
    value: "custom",
    label: "Custom",
  },
  {
    value: "amount_only",
    label: "Amount only",
  },
  {
    value: "ignored",
    label: "Hidden",
  },
] as const;

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
    return "Hidden";
  }

  if (
    target.trackingMode
      === "amount_only"
    && target.reasonCode
      === "target_reference_not_established"
  ) {
    return (
      "No established target · "
      + "Amount only by default"
    );
  }

  if (
    target.trackingMode
      === "amount_only"
  ) {
    return "Amount only";
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
  const [
    showMoreNutrients,
    setShowMoreNutrients,
  ] = useState(false);
  const [
    nutrientSearch,
    setNutrientSearch,
  ] = useState("");

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

  const estimate =
    result?.estimatedMaintenanceCalories;

  const configuredSecondary =
    new Set([
      ...Object.keys(
        draft
          .additionalManualOverrides,
      ),
      ...Object.keys(
        draft.trackingPreferences,
      ),
      ...Object.keys(
        draft.modeSelections,
      ),
    ]);

  const normalizedSearch =
    nutrientSearch
      .trim()
      .toLowerCase();

  const secondaryCandidates =
    normalizedSearch
      ? SECONDARY_NUTRIENTS.filter(
          (nutrient) =>
            nutrient.display_name
              .toLowerCase()
              .includes(
                normalizedSearch,
              )
            || nutrient.id
              .toLowerCase()
              .includes(
                normalizedSearch,
              ),
        )
      : SECONDARY_NUTRIENTS.filter(
          (nutrient) =>
            configuredSecondary.has(
              nutrient.id,
            ),
        );

  const visibleSecondaryNutrients =
    secondaryCandidates.slice(0, 8);

  const hasMoreSecondaryMatches =
    secondaryCandidates.length > 8;

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
              Optional personal targets
            </Text>

            <Text style={styles.notice}>
              Manual targets take precedence and are never replaced when
              profile inputs change. Leave blank to use a supported RDA or AI,
              estimated calories, or an FDA Daily Value fallback when available.
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

              const mode =
                result
                  ? targetDraftMode(
                      draft,
                      result,
                      nutrientId,
                    )
                  : "recommended";

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
                    accessibilityRole="radiogroup"
                    accessibilityLabel={`${label} tracking mode ${TRACKING_MODES.find((option) => option.value === mode)?.label ?? mode}`}
                    style={styles.modeRow}
                  >
                    {TRACKING_MODES.map(
                      (option) => {
                        const selected =
                          mode
                          === option.value;

                        return (
                          <Pressable
                            key={
                              option.value
                            }
                            accessibilityRole="radio"
                            accessibilityLabel={`${label} tracking mode ${option.label}`}
                            accessibilityState={{
                              checked:
                                selected,
                              disabled:
                                submitting,
                            }}
                            disabled={
                              submitting
                            }
                            onPress={() =>
                              result
                                ? setDraft(
                                    (
                                      current,
                                    ) =>
                                      setTargetDraftMode(
                                        current,
                                        result,
                                        nutrientId,
                                        option.value,
                                      ),
                                  )
                                : undefined
                            }
                            style={({
                              pressed,
                            }) => [
                              styles
                                .modeChoice,
                              selected
                                && styles
                                  .modeChoiceSelected,
                              pressed
                                && styles
                                  .choicePressed,
                            ]}
                          >
                            <Text
                              style={[
                                styles
                                  .modeChoiceText,
                                selected
                                  && styles
                                    .choiceTextSelected,
                              ]}
                            >
                              {
                                option.label
                              }
                            </Text>
                          </Pressable>
                        );
                      },
                    )}
                  </View>

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

            <View
              style={
                styles.managerSection
              }
            >
              <View
                style={
                  styles.managerHeader
                }
              >
                <View
                  style={
                    styles
                      .managerHeaderCopy
                  }
                >
                  <Text
                    accessibilityRole="header"
                    style={styles.section}
                  >
                    More nutrients
                  </Text>

                  <Text
                    style={
                      styles.notice
                    }
                  >
                    Configure vitamins,
                    minerals, fatty
                    acids, and other
                    catalog nutrients
                    without showing the
                    full catalog at
                    once.
                  </Text>
                </View>

                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={
                    showMoreNutrients
                      ? "Hide more nutrient controls"
                      : "Show more nutrient controls"
                  }
                  accessibilityState={{
                    expanded:
                      showMoreNutrients,
                    disabled:
                      submitting,
                  }}
                  disabled={
                    submitting
                  }
                  onPress={() =>
                    setShowMoreNutrients(
                      (shown) =>
                        !shown,
                    )
                  }
                  style={
                    styles
                      .managerToggle
                  }
                >
                  <Text
                    style={
                      styles.link
                    }
                  >
                    {showMoreNutrients
                      ? "Hide"
                      : "Manage"}
                  </Text>
                </Pressable>
              </View>

              {showMoreNutrients ? (
                <>
                  <TextInput
                    editable={
                      !submitting
                    }
                    accessibilityLabel="Search nutrients to configure"
                    accessibilityState={{
                      disabled:
                        submitting,
                    }}
                    value={
                      nutrientSearch
                    }
                    onChangeText={
                      setNutrientSearch
                    }
                    placeholder="Search nutrients"
                    placeholderTextColor={
                      theme.colors
                        .placeholder
                    }
                    style={
                      styles.input
                    }
                  />

                  {!normalizedSearch
                    && visibleSecondaryNutrients
                      .length === 0 ? (
                    <Text
                      style={
                        styles.notice
                      }
                    >
                      Search for a
                      nutrient to
                      configure it.
                      Explicit custom,
                      amount-only, or
                      hidden choices
                      will remain listed
                      here.
                    </Text>
                  ) : null}

                  {normalizedSearch
                    && visibleSecondaryNutrients
                      .length === 0 ? (
                    <Text
                      accessibilityLiveRegion="polite"
                      style={
                        styles.notice
                      }
                    >
                      No matching
                      nutrients.
                    </Text>
                  ) : null}

                  {visibleSecondaryNutrients.map(
                    (nutrient) => {
                      const effective =
                        result
                          ?.effectiveTargets
                          .find(
                            (item) =>
                              item
                                .nutrientId
                              === nutrient
                                .id,
                          );

                      const mode =
                        result
                          ? targetDraftMode(
                              draft,
                              result,
                              nutrient
                                .id,
                            )
                          : "recommended";

                      const customValue =
                        targetDraftOverrideValue(
                          draft,
                          nutrient.id,
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
                          style={
                            styles
                              .nutrientCard
                          }
                        >
                          <View
                            style={
                              styles
                                .nutrientHeading
                            }
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
                              accessibilityLabel={`${nutrient.display_name} current tracking state ${TRACKING_MODES.find((option) => option.value === mode)?.label ?? mode}`}
                              style={
                                styles
                                  .stateLabel
                              }
                            >
                              {
                                TRACKING_MODES
                                  .find(
                                    (
                                      option,
                                    ) =>
                                      option
                                        .value
                                      === mode,
                                  )
                                  ?.label
                                ?? mode
                              }
                            </Text>
                          </View>

                          <Text
                            style={
                              styles
                                .notice
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
                              {`Reference source: ${source}`}
                            </Text>
                          ) : null}

                          <View
                            accessibilityRole="radiogroup"
                            accessibilityLabel={`${nutrient.display_name} tracking mode ${TRACKING_MODES.find((option) => option.value === mode)?.label ?? mode}`}
                            style={
                              styles
                                .modeRow
                            }
                          >
                            {TRACKING_MODES.map(
                              (
                                option,
                              ) => {
                                const selected =
                                  mode
                                  === option
                                    .value;

                                return (
                                  <Pressable
                                    key={
                                      option
                                        .value
                                    }
                                    accessibilityRole="radio"
                                    accessibilityLabel={`${nutrient.display_name} tracking mode ${option.label}`}
                                    accessibilityState={{
                                      checked:
                                        selected,
                                      disabled:
                                        submitting,
                                    }}
                                    disabled={
                                      submitting
                                    }
                                    onPress={() =>
                                      result
                                        ? setDraft(
                                            (
                                              current,
                                            ) =>
                                              setTargetDraftMode(
                                                current,
                                                result,
                                                nutrient.id,
                                                option.value,
                                              ),
                                          )
                                        : undefined
                                    }
                                    style={({
                                      pressed,
                                    }) => [
                                      styles
                                        .modeChoice,
                                      selected
                                        && styles
                                          .modeChoiceSelected,
                                      pressed
                                        && styles
                                          .choicePressed,
                                    ]}
                                  >
                                    <Text
                                      style={[
                                        styles
                                          .modeChoiceText,
                                        selected
                                          && styles
                                            .choiceTextSelected,
                                      ]}
                                    >
                                      {
                                        option
                                          .label
                                      }
                                    </Text>
                                  </Pressable>
                                );
                              },
                            )}
                          </View>

                          {mode
                            === "custom" ? (
                            <TextInput
                              editable={
                                !submitting
                              }
                              accessibilityLabel={`${nutrient.display_name} custom target`}
                              accessibilityState={{
                                disabled:
                                  submitting,
                              }}
                              value={
                                customValue
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
                                      nutrient.id,
                                      value,
                                    ),
                                )
                              }
                              keyboardType="decimal-pad"
                              placeholder={`${nutrient.display_name} (${nutrient.default_unit}/day)`}
                              placeholderTextColor={
                                theme
                                  .colors
                                  .placeholder
                              }
                              style={
                                styles.input
                              }
                            />
                          ) : null}
                        </View>
                      );
                    },
                  )}

                  {hasMoreSecondaryMatches ? (
                    <Text
                      style={
                        styles.notice
                      }
                    >
                      More matches are
                      available. Refine
                      the search to
                      narrow the list.
                    </Text>
                  ) : null}
                </>
              ) : null}
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
