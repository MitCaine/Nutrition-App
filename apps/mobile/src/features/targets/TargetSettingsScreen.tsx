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
import {
  getTargets,
  resetTargetOverride,
  updateTargets,
} from "./api/targetApi";
import type { TargetConfiguration } from "./api/types";
import { targetErrorMessage } from "./targetErrors";
import {
  EMPTY_TARGET_DRAFT,
  targetDraft,
  targetDraftError,
  targetInput,
  targetUnavailableMessage,
} from "./targetModel";

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

const CONTEXTS = [
  "general_adult",
  "pregnant",
  "lactating",
  "specialized_medical",
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

const contextLabel = (context: (typeof CONTEXTS)[number]) =>
  context === "general_adult"
    ? "General adult"
    : context.replaceAll("_", " ");

export function TargetSettingsScreen({
  onBack,
}: {
  onBack: () => void;
}) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ["targets"],
    queryFn: getTargets,
  });

  const [draft, setDraft] = useState(EMPTY_TARGET_DRAFT);
  const [result, setResult] = useState<TargetConfiguration | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const initialized = useRef(false);
  const submittingRef = useRef(false);

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

    const validation = targetDraftError(draft);

    if (validation) {
      setError(validation);
      return;
    }

    submittingRef.current = true;
    setSubmitting(true);
    setError(null);

    try {
      const next = await updateTargets(targetInput(draft));

      setResult(next);
      setDraft(targetDraft(next));

      await queryClient.invalidateQueries({ queryKey: ["targets"] });
      await queryClient.invalidateQueries({
        queryKey: ["target-comparison"],
      });
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

    try {
      const next = await resetTargetOverride(nutrientId);
      const draftKey =
        nutrientId === "total_carbohydrate"
          ? "totalCarbohydrate"
          : nutrientId === "total_fat"
            ? "totalFat"
            : nutrientId;

      setResult(next);
      setDraft((current) => ({
        ...current,
        [draftKey]: "",
      }));

      await queryClient.invalidateQueries({ queryKey: ["targets"] });
      await queryClient.invalidateQueries({
        queryKey: ["target-comparison"],
      });
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

        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Back from nutrition targets"
          onPress={onBack}
        >
          <Text style={styles.link}>Back</Text>
        </Pressable>
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
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Back from nutrition targets"
                accessibilityState={{ disabled: submitting }}
                disabled={submitting}
                onPress={onBack}
              >
                <Text style={styles.link}>Back</Text>
              </Pressable>

              <Text accessibilityRole="header" style={styles.title}>
                Nutrition targets
              </Text>
            </View>

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

            <TextInput
              editable={!submitting}
              accessibilityLabel="Birth date"
              accessibilityState={{ disabled: submitting }}
              value={draft.birthDate}
              onChangeText={(birthDate) =>
                setDraft((current) => ({ ...current, birthDate }))
              }
              placeholder="YYYY-MM-DD"
              placeholderTextColor={theme.colors.placeholder}
              style={styles.input}
            />

            <TextInput
              editable={!submitting}
              accessibilityLabel="Height in centimeters"
              accessibilityState={{ disabled: submitting }}
              value={draft.heightCm}
              onChangeText={(heightCm) =>
                setDraft((current) => ({ ...current, heightCm }))
              }
              keyboardType="decimal-pad"
              placeholder="Height (cm)"
              placeholderTextColor={theme.colors.placeholder}
              style={styles.input}
            />

            <TextInput
              editable={!submitting}
              accessibilityLabel="Weight in kilograms"
              accessibilityState={{ disabled: submitting }}
              value={draft.weightKg}
              onChangeText={(weightKg) =>
                setDraft((current) => ({ ...current, weightKg }))
              }
              keyboardType="decimal-pad"
              placeholder="Weight (kg)"
              placeholderTextColor={theme.colors.placeholder}
              style={styles.input}
            />

            <View accessibilityRole="radiogroup" style={styles.choiceGroup}>
              <Text style={styles.label}>Sex used by estimation equation</Text>

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
                      }))
                    }
                    style={({ pressed }) => [
                      styles.choice,
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

            <View accessibilityRole="radiogroup" style={styles.choiceGroup}>
              <Text style={styles.label}>Activity level</Text>

              <Text style={styles.notice}>
                Activity categories are estimates. The multiplier adjusts the
                resting estimate; actual energy needs may differ.
              </Text>

              {ACTIVITY.map((option) => {
                const selected = draft.activityLevel === option.value;

                return (
                  <Pressable
                    key={option.value}
                    disabled={submitting}
                    accessibilityRole="radio"
                    accessibilityLabel={`Activity ${option.label}, ${option.description} Resting estimate multiplier ${option.multiplier}`}
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
                      {option.label} · {option.multiplier}
                    </Text>

                    <Text style={styles.notice}>{option.description}</Text>
                  </Pressable>
                );
              })}
            </View>

            <View accessibilityRole="radiogroup" style={styles.choiceGroup}>
              <Text style={styles.label}>Estimation context</Text>

              {CONTEXTS.map((value) => {
                const selected = draft.energyEstimationContext === value;

                return (
                  <Pressable
                    key={value}
                    disabled={submitting}
                    accessibilityRole="radio"
                    accessibilityLabel={`Estimation context ${contextLabel(value)}`}
                    accessibilityState={{
                      checked: selected,
                      disabled: submitting,
                    }}
                    onPress={() =>
                      setDraft((current) => ({
                        ...current,
                        energyEstimationContext: value,
                      }))
                    }
                    style={({ pressed }) => [
                      styles.choice,
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
                      {contextLabel(value)}
                    </Text>
                  </Pressable>
                );
              })}
            </View>

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

              return (
                <View key={key}>
                  <View style={styles.targetRow}>
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
                      style={[styles.input, styles.flex]}
                    />

                    <Pressable
                      accessibilityRole="button"
                      accessibilityLabel={`Reset ${label} personal target`}
                      disabled={submitting || !draft[key]}
                      accessibilityState={{
                        disabled: submitting || !draft[key],
                      }}
                      onPress={() => reset(nutrientId)}
                    >
                      <Text style={styles.link}>Reset</Text>
                    </Pressable>
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
                      ? `Effective: ${effective.amount} ${effective.unit}/day · ${authorityLabel(effective.authority)}`
                      : "Effective target unavailable"}
                  </Text>
                </View>
              );
            })}

            <Text style={styles.notice}>
              Micronutrient comparisons use FDA Daily Values (
              {result?.dailyValueCatalogVersion ?? "loading"}), not personal
              estimates.
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
      backgroundColor: theme.colors.surface,
      borderColor: theme.colors.border,
      borderRadius: 6,
      borderWidth: 1,
      minHeight: 48,
      padding: 12,
    },
    choiceGroup: {
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
      paddingBottom: 80,
    },
    disabled: {
      opacity: 0.6,
    },
    error: {
      color: theme.colors.errorText,
    },
    flex: {
      flex: 1,
    },
    header: {
      gap: 8,
    },
    input: {
      backgroundColor: theme.colors.input,
      borderColor: theme.colors.border,
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
    targetRow: {
      alignItems: "center",
      flexDirection: "row",
      gap: 8,
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
