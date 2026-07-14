import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useRef, useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { useAppTheme } from "../../../app/theme/AppTheme";
import { createClientRequestId } from "../../logging/utils/clientRequestId";
import { KeyboardSafeScrollView } from "../../../shared/forms/KeyboardSafeScrollView";
import { confirmNutritionLabel } from "../api/ocrApi";
import type { ConfirmationField, NutritionConfirmationDraft } from "../api/types";
import { confirmationPayload, confirmationValidationError, updateReview } from "../confirmation/confirmationModel";

export function NutritionConfirmationScreen({ initialDraft, onCancel, onCreated }: {
  initialDraft: NutritionConfirmationDraft;
  onCancel: () => void;
  onCreated: (foodId: string) => void;
}) {
  const theme = useAppTheme(); const styles = useMemo(() => createStyles(theme), [theme]);
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(initialDraft);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const submittingRef = useRef(false);
  const requestId = useRef(createClientRequestId());
  const fields = [draft.calories, ...draft.nutrients];

  const replaceField = (next: ConfirmationField) => setDraft((current) => next.nutrientId === "calories"
    ? { ...current, calories: next }
    : { ...current, nutrients: current.nutrients.map((field) => field.fieldKey === next.fieldKey ? next : field) });

  const submit = async () => {
    if (submittingRef.current) return;
    const validation = confirmationValidationError(draft);
    if (validation) { setError(validation); return; }
    const payload = confirmationPayload(draft, requestId.current);
    if (!payload) return;
    submittingRef.current = true; setSubmitting(true); setError(null);
    try {
      const response = await confirmNutritionLabel(payload);
      await queryClient.invalidateQueries({ queryKey: ["foods"] });
      onCreated(response.food.id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not create the scanned Food.");
    } finally {
      submittingRef.current = false; setSubmitting(false);
    }
  };

  return <View style={styles.screen}>
    <KeyboardSafeScrollView contentContainerStyle={styles.content}>{() => <>
      <View style={styles.header}><Text style={styles.title}>Confirm nutrition</Text><Pressable disabled={submitting} onPress={onCancel}><Text style={styles.link}>Cancel</Text></Pressable></View>
      <Text style={styles.notice}>Review flagged values. The image is not uploaded or saved.</Text>
      <Text style={styles.section}>Food</Text>
      <TextInput editable={!submitting} accessibilityLabel="Food name" value={draft.name} onChangeText={(name) => setDraft({ ...draft, name })} placeholder="Food name (required)" placeholderTextColor={theme.colors.placeholder} style={styles.input}/>
      <TextInput editable={!submitting} value={draft.brand} onChangeText={(brand) => setDraft({ ...draft, brand })} placeholder="Brand" placeholderTextColor={theme.colors.placeholder} style={styles.input}/>
      <TextInput editable={!submitting} value={draft.notes} onChangeText={(notes) => setDraft({ ...draft, notes })} placeholder="Notes" placeholderTextColor={theme.colors.placeholder} style={styles.input}/>
      <Text style={styles.section}>Serving</Text>
      <TextInput editable={!submitting} value={draft.servingDisplay} onChangeText={(servingDisplay) => setDraft({ ...draft, servingDisplay })} placeholder="Serving label" placeholderTextColor={theme.colors.placeholder} style={styles.input}/>
      <View style={styles.row}><TextInput editable={!submitting} value={draft.servingQuantity} onChangeText={(servingQuantity) => setDraft({ ...draft, servingQuantity })} keyboardType="decimal-pad" placeholder="Quantity" placeholderTextColor={theme.colors.placeholder} style={[styles.input, styles.flex]}/><TextInput editable={!submitting} value={draft.servingUnit} onChangeText={(servingUnit) => setDraft({ ...draft, servingUnit })} placeholder="Unit" placeholderTextColor={theme.colors.placeholder} style={[styles.input, styles.flex]}/></View>
      <TextInput editable={!submitting} accessibilityLabel="Serving grams" value={draft.gramWeight} onChangeText={(gramWeight) => setDraft({ ...draft, gramWeight })} keyboardType="decimal-pad" placeholder="Equivalent grams (required)" placeholderTextColor={theme.colors.placeholder} style={styles.input}/>
      <Text style={styles.section}>Nutrition per label serving</Text>
      {fields.map((field) => <View key={field.fieldKey} style={[styles.card, field.decision === "unresolved" && styles.flagged]}>
        <View style={styles.row}><Text style={styles.fieldLabel}>{field.label}</Text><Text style={styles.meta}>{field.unit ?? ""}</Text></View>
        {(field.decision === "unresolved" || field.parseStatus === "ambiguous" || field.confidence < 0.8 || field.comparison) ? <Text style={styles.warning}>{field.comparison ? "Less-than value needs an exact replacement or omission" : `Review required · ${Math.round(field.confidence * 100)}% confidence`}</Text> : null}
        <TextInput editable={!submitting && field.decision !== "omitted"} accessibilityLabel={`${field.label} amount`} value={field.confirmedValue} onChangeText={(value) => replaceField(updateReview(field, value))} keyboardType="decimal-pad" style={styles.input}/>
        <View style={styles.actions}><Pressable disabled={submitting} onPress={() => replaceField(updateReview(field, field.confirmedValue, field.confirmedValue === (field.suggestedValue ?? "") ? "accepted" : "edited"))}><Text style={styles.link}>Use value</Text></Pressable><Pressable disabled={submitting || field.nutrientId === "calories"} onPress={() => replaceField({ ...field, decision: "omitted", confirmedValue: "", resolution: field.parseStatus === "ambiguous" || field.comparison ? "omitted after review" : field.resolution })}><Text style={styles.link}>Omit</Text></Pressable></View>
        <Text style={styles.source}>Source: {field.sourceText || "No source line"}</Text>
      </View>)}
      {draft.unknownNutrients.length ? <><Text style={styles.section}>Unknown rows</Text>{draft.unknownNutrients.map((item, index) => <View key={`${item.originalName}-${index}`} style={styles.card}><Text style={styles.fieldLabel}>{item.originalName}</Text><Text style={styles.source}>{item.sourceText}</Text><Pressable disabled={submitting} onPress={() => setDraft({ ...draft, unknownNutrients: draft.unknownNutrients.map((entry, itemIndex) => itemIndex === index ? { ...entry, dismissed: true } : entry) })}><Text style={styles.link}>{item.dismissed ? "Dismissed" : "Dismiss after review"}</Text></Pressable></View>)}</> : null}
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
    </>}</KeyboardSafeScrollView>
    <View style={styles.saveBar}><Pressable disabled={submitting} accessibilityRole="button" onPress={submit} style={[styles.button, submitting && styles.disabled]}><Text style={styles.buttonText}>{submitting ? "Creating Food…" : "Create Food"}</Text></Pressable></View>
  </View>;
}

function createStyles(theme: ReturnType<typeof useAppTheme>) { return StyleSheet.create({
  actions: { flexDirection: "row", gap: 24 }, button: { alignItems: "center", backgroundColor: theme.colors.primaryActionBackground, borderRadius: 8, minHeight: 48, justifyContent: "center" },
  buttonText: { color: theme.colors.primaryActionForeground, fontSize: 16, fontWeight: "700" }, card: { backgroundColor: theme.colors.surface, borderColor: theme.colors.border, borderRadius: 8, borderWidth: 1, gap: 8, padding: 12 },
  content: { gap: 10, padding: 16, paddingBottom: 120 }, disabled: { opacity: 0.65 }, error: { color: theme.colors.errorText }, fieldLabel: { color: theme.colors.text, flex: 1, fontSize: 16, fontWeight: "700" }, flagged: { borderColor: theme.colors.warningText, borderWidth: 2 }, flex: { flex: 1 },
  header: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" }, input: { backgroundColor: theme.colors.input, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, color: theme.colors.text, minHeight: 44, padding: 10 }, link: { color: theme.colors.accent, fontWeight: "600" }, meta: { color: theme.colors.secondaryText }, notice: { color: theme.colors.secondaryText }, row: { alignItems: "center", flexDirection: "row", gap: 10 },
  saveBar: { backgroundColor: theme.colors.surface, borderTopColor: theme.colors.border, borderTopWidth: 1, padding: 12 }, screen: { backgroundColor: theme.colors.background, flex: 1 }, section: { color: theme.colors.text, fontSize: 19, fontWeight: "800", marginTop: 8 }, source: { color: theme.colors.secondaryText, fontSize: 12 }, title: { color: theme.colors.text, fontSize: 25, fontWeight: "800" }, warning: { color: theme.colors.warningText, fontSize: 13 },
}); }
