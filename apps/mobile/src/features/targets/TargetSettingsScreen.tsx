import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { useAppTheme } from "../../app/theme/AppTheme";
import { KeyboardSafeScrollView } from "../../shared/forms/KeyboardSafeScrollView";
import { getTargets, resetTargetOverride, updateTargets } from "./api/targetApi";
import type { TargetConfiguration } from "./api/types";
import { EMPTY_TARGET_DRAFT, targetDraft, targetDraftError, targetInput, targetUnavailableMessage } from "./targetModel";
import { targetErrorMessage } from "./targetErrors";

const ACTIVITY = ["sedentary", "lightly_active", "active", "very_active"] as const;
const CONTEXTS = ["general_adult", "pregnant", "lactating", "specialized_medical"] as const;
const authorityLabel = (authority: string) => authority === "daily_value" ? "FDA Daily Value" : authority.replaceAll("_", " ");

export function TargetSettingsScreen({ onBack }: { onBack: () => void }) {
  const theme = useAppTheme(); const styles = useMemo(() => createStyles(theme), [theme]);
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["targets"], queryFn: getTargets });
  const [draft, setDraft] = useState(EMPTY_TARGET_DRAFT);
  const [result, setResult] = useState<TargetConfiguration | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const initialized = useRef(false); const submittingRef = useRef(false);

  useEffect(() => {
    if (query.data && !initialized.current) {
      initialized.current = true; setResult(query.data); setDraft(targetDraft(query.data));
    }
  }, [query.data]);

  const save = async () => {
    if (submittingRef.current) return;
    const validation = targetDraftError(draft);
    if (validation) { setError(validation); return; }
    submittingRef.current = true; setSubmitting(true); setError(null);
    try {
      const next = await updateTargets(targetInput(draft));
      setResult(next); setDraft(targetDraft(next));
      await queryClient.invalidateQueries({ queryKey: ["targets"] });
    } catch (caught) {
      setError(targetErrorMessage(caught));
    } finally {
      submittingRef.current = false; setSubmitting(false);
    }
  };

  const reset = async (nutrientId: string) => {
    if (submittingRef.current) return;
    submittingRef.current = true; setSubmitting(true); setError(null);
    try {
      const next = await resetTargetOverride(nutrientId);
      const draftKey = nutrientId === "total_carbohydrate" ? "totalCarbohydrate" : nutrientId === "total_fat" ? "totalFat" : nutrientId;
      setResult(next); setDraft((current) => ({ ...current, [draftKey]: "" }));
      await queryClient.invalidateQueries({ queryKey: ["targets"] });
    } catch (caught) {
      setError(targetErrorMessage(caught));
    } finally {
      submittingRef.current = false; setSubmitting(false);
    }
  };

  if (query.isLoading && !result) return <View style={styles.screen}><Text style={styles.text}>Loading nutrition targets…</Text></View>;
  if (query.isError && !result) return <View style={styles.screen}><Text accessibilityRole="alert" style={styles.error}>Could not load nutrition targets.</Text><Pressable accessibilityRole="button" accessibilityLabel="Back from nutrition targets" onPress={onBack}><Text style={styles.link}>Back</Text></Pressable></View>;
  const estimate = result?.estimatedMaintenanceCalories;

  return <View style={styles.screen}>
    <KeyboardSafeScrollView contentContainerStyle={styles.content}>{() => <>
      <View style={styles.header}><Pressable accessibilityRole="button" accessibilityLabel="Back from nutrition targets" accessibilityState={{ disabled: submitting }} disabled={submitting} onPress={onBack}><Text style={styles.link}>Back</Text></Pressable><Text accessibilityRole="header" style={styles.title}>Nutrition targets</Text></View>
      <Text style={styles.notice}>FDA Daily Values are regulatory references. Personal targets are optional estimates or your manual overrides.</Text>
      <Text accessibilityRole="header" style={styles.section}>Estimated maintenance calories</Text>
      <Text style={styles.notice}>General informational estimate only—not medical advice. No weight-loss or weight-gain adjustment is applied.</Text>
      <TextInput editable={!submitting} accessibilityLabel="Birth date" accessibilityState={{ disabled: submitting }} value={draft.birthDate} onChangeText={(birthDate) => setDraft({ ...draft, birthDate })} placeholder="YYYY-MM-DD" placeholderTextColor={theme.colors.placeholder} style={styles.input}/>
      <TextInput editable={!submitting} accessibilityLabel="Height in centimeters" accessibilityState={{ disabled: submitting }} value={draft.heightCm} onChangeText={(heightCm) => setDraft({ ...draft, heightCm })} keyboardType="decimal-pad" placeholder="Height (cm)" placeholderTextColor={theme.colors.placeholder} style={styles.input}/>
      <TextInput editable={!submitting} accessibilityLabel="Weight in kilograms" accessibilityState={{ disabled: submitting }} value={draft.weightKg} onChangeText={(weightKg) => setDraft({ ...draft, weightKg })} keyboardType="decimal-pad" placeholder="Weight (kg)" placeholderTextColor={theme.colors.placeholder} style={styles.input}/>
      <View accessibilityRole="radiogroup"><Text style={styles.label}>Sex used by estimation equation</Text>{(["female", "male"] as const).map((value) => <Pressable key={value} disabled={submitting} accessibilityRole="radio" accessibilityLabel={`Equation sex ${value}`} accessibilityState={{ checked: draft.sexForEquation === value, disabled: submitting }} onPress={() => setDraft({ ...draft, sexForEquation: value })} style={styles.choice}><Text style={styles.text}>{value === "female" ? "Female" : "Male"}</Text></Pressable>)}</View>
      <View accessibilityRole="radiogroup"><Text style={styles.label}>Activity level</Text>{ACTIVITY.map((value) => <Pressable key={value} disabled={submitting} accessibilityRole="radio" accessibilityLabel={`Activity ${value.replaceAll("_", " ")}`} accessibilityState={{ checked: draft.activityLevel === value, disabled: submitting }} onPress={() => setDraft({ ...draft, activityLevel: value })} style={styles.choice}><Text style={styles.text}>{value.replaceAll("_", " ")}</Text></Pressable>)}</View>
      <View accessibilityRole="radiogroup"><Text style={styles.label}>Estimation context</Text>{CONTEXTS.map((value) => <Pressable key={value} disabled={submitting} accessibilityRole="radio" accessibilityLabel={`Estimation context ${value.replaceAll("_", " ")}`} accessibilityState={{ checked: draft.energyEstimationContext === value, disabled: submitting }} onPress={() => setDraft({ ...draft, energyEstimationContext: value })} style={styles.choice}><Text style={styles.text}>{value === "general_adult" ? "General adult" : value.replaceAll("_", " ")}</Text></Pressable>)}</View>
      <Text accessibilityLiveRegion="polite" style={styles.result}>{estimate?.availability === "available" ? `Estimated maintenance calories: ${estimate.amount} kcal/day (calculated estimate)` : targetUnavailableMessage(estimate?.reasonCode ?? null)}</Text>
      <Text accessibilityRole="header" style={styles.section}>Optional personal targets</Text>
      <Text style={styles.notice}>Manual targets take precedence and are never replaced when profile inputs change. Leave blank to use an estimate or FDA Daily Value when available.</Text>
      {([['calories', 'Calories', 'kcal'], ['protein', 'Protein', 'g'], ['totalCarbohydrate', 'Carbohydrate', 'g'], ['totalFat', 'Fat', 'g']] as const).map(([key, label, unit]) => { const nutrientId = key === 'totalCarbohydrate' ? 'total_carbohydrate' : key === 'totalFat' ? 'total_fat' : key; const effective = result?.effectiveTargets.find((item) => item.nutrientId === nutrientId); return <View key={key}><View style={styles.targetRow}><TextInput editable={!submitting} accessibilityLabel={`${label} personal target`} accessibilityState={{ disabled: submitting }} value={draft[key]} onChangeText={(value) => setDraft({ ...draft, [key]: value })} keyboardType="decimal-pad" placeholder={`${label} (${unit}/day)`} placeholderTextColor={theme.colors.placeholder} style={[styles.input, styles.flex]}/><Pressable accessibilityRole="button" accessibilityLabel={`Reset ${label} personal target`} disabled={submitting || !draft[key]} accessibilityState={{ disabled: submitting || !draft[key] }} onPress={() => reset(nutrientId)}><Text style={styles.link}>Reset</Text></Pressable></View><Text accessibilityLabel={`${label} effective target authority ${effective ? authorityLabel(effective.authority) : "unavailable"}`} style={styles.notice}>{effective?.amount ? `Effective: ${effective.amount} ${effective.unit}/day · ${authorityLabel(effective.authority)}` : "Effective target unavailable"}</Text></View>; })}
      <Text style={styles.notice}>Micronutrient comparisons use FDA Daily Values ({result?.dailyValueCatalogVersion ?? "loading"}), not personal estimates.</Text>
      {error ? <Text accessibilityRole="alert" accessibilityLiveRegion="assertive" style={styles.error}>{error}</Text> : null}
      <Pressable accessibilityRole="button" accessibilityLabel={submitting ? "Saving nutrition targets" : "Save nutrition targets"} accessibilityState={{ disabled: submitting, busy: submitting }} disabled={submitting} onPress={save} style={[styles.button, submitting && styles.disabled]}><Text style={styles.buttonText}>{submitting ? "Saving…" : "Save targets"}</Text></Pressable>
    </>}</KeyboardSafeScrollView>
  </View>;
}

function createStyles(theme: ReturnType<typeof useAppTheme>) { return StyleSheet.create({
  button: { alignItems: "center", backgroundColor: theme.colors.primaryActionBackground, borderRadius: 8, justifyContent: "center", minHeight: 48 }, buttonText: { color: theme.colors.primaryActionForeground, fontWeight: "700" }, choice: { backgroundColor: theme.colors.surface, borderBottomColor: theme.colors.border, borderBottomWidth: 1, minHeight: 44, padding: 12 }, content: { gap: 10, padding: 16, paddingBottom: 80 }, disabled: { opacity: 0.6 }, error: { color: theme.colors.errorText }, flex: { flex: 1 }, header: { gap: 8 }, input: { backgroundColor: theme.colors.input, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, color: theme.colors.text, minHeight: 44, padding: 10 }, label: { color: theme.colors.text, fontWeight: "700", marginBottom: 4 }, link: { color: theme.colors.accent, fontWeight: "600", padding: 10 }, notice: { color: theme.colors.secondaryText }, result: { color: theme.colors.text, fontWeight: "700" }, screen: { backgroundColor: theme.colors.background, flex: 1 }, section: { color: theme.colors.text, fontSize: 19, fontWeight: "800", marginTop: 8 }, targetRow: { alignItems: "center", flexDirection: "row", gap: 8 }, text: { color: theme.colors.text }, title: { color: theme.colors.text, fontSize: 28, fontWeight: "800" },
}); }
