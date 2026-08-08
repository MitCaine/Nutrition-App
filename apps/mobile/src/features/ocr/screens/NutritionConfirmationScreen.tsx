import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { useAppTheme } from "../../../app/theme/AppTheme";
import { createClientRequestId } from "../../logging/utils/clientRequestId";
import { KeyboardSafeScrollView, type KeyboardSafeScrollViewHandle } from "../../../shared/forms/KeyboardSafeScrollView";
import { LabeledField } from "../../../shared/forms/LabeledField";
import { AccessiblePressable } from "../../../shared/accessibility/AccessiblePressable";
import { useAccessibilityAnnouncement } from "../../../shared/accessibility/announcements";
import { focusAccessibilityElement, useAccessibilityScreenFocus } from "../../../shared/accessibility/focus";
import type { ConfirmationField, NutritionConfirmationDraft } from "../api/types";
import { confirmationPayload, confirmationValidationError, updateReview } from "../confirmation/confirmationModel";
import { bindConfirmationIntent, type ConfirmationIntent } from "../confirmation/confirmationIntent";
import { confirmationErrorCode, confirmationErrorMessage } from "../confirmation/confirmationErrors";
import { useNutritionRuntime } from "../../../runtime/NutritionRuntimeContext";

const FINGERPRINT_PLACEHOLDER_REQUEST_ID = "00000000-0000-4000-8000-000000000000";

function showsUseValueAction(field: ConfirmationField): boolean {
  return field.decision === "unresolved"
    || field.decision === "edited"
    || (field.decision === "omitted" && field.suggestedValue !== null);
}

export function NutritionConfirmationScreen({ initialDraft, onCancel, onCreated }: {
  initialDraft: NutritionConfirmationDraft;
  onCancel: () => void;
  onCreated: (foodId: string) => void;
}) {
  const runtime = useNutritionRuntime();
  const theme = useAppTheme(); const styles = useMemo(() => createStyles(theme), [theme]);
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(initialDraft);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const submittingRef = useRef(false);
  const mountedRef = useRef(true);
  const cancelClaimedRef = useRef(false);
  const successClaimedRef = useRef(false);
  const intentRef = useRef<ConfirmationIntent | null>(null);
  const scrollRef = useRef<KeyboardSafeScrollViewHandle>(null);
  const headingRef = useRef<Text>(null);
  const errorRef = useRef<Text>(null);
  const validationFocusKeyRef = useRef<string | null>(null);
  const announce = useAccessibilityAnnouncement();
  const fields = [draft.calories, ...draft.nutrients];
  useAccessibilityScreenFocus({ active: true, routeKey: "nutrition-confirmation", targetRef: headingRef });

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    if (!error) return;
    const cancelAnnouncement = announce(error, { key: "nutrition-confirmation-error", kind: "error", priority: "assertive" });
    const focusKey = validationFocusKeyRef.current;
    validationFocusKeyRef.current = null;
    const focusedField = focusKey ? scrollRef.current?.focusTarget(focusKey) : false;
    const cancelFocus = focusedField ? null : focusAccessibilityElement(errorRef.current, { focusKeyboardTarget: false });
    return () => { cancelAnnouncement(); cancelFocus?.(); };
  }, [announce, error]);

  const replaceField = (next: ConfirmationField) => setDraft((current) => next.nutrientId === "calories"
    ? { ...current, calories: next }
    : { ...current, nutrients: current.nutrients.map((field) => field.fieldKey === next.fieldKey ? next : field) });

  const cancel = () => {
    if (submittingRef.current || cancelClaimedRef.current) return;
    cancelClaimedRef.current = true;
    onCancel();
  };

  const submit = async () => {
    if (submittingRef.current || cancelClaimedRef.current || successClaimedRef.current) return;
    const validation = confirmationValidationError(draft);
    if (validation) { validationFocusKeyRef.current = confirmationValidationFocusKey(validation, draft); setError(validation); return; }
    const candidate = confirmationPayload(draft, FINGERPRINT_PLACEHOLDER_REQUEST_ID);
    if (!candidate) return;
    intentRef.current = bindConfirmationIntent(intentRef.current, candidate, createClientRequestId);
    const payload = { ...candidate, client_request_id: intentRef.current.requestId };
    submittingRef.current = true; setSubmitting(true); setError(null);
    try {
      const response = await runtime.ocr.confirmNutritionLabel(payload);
      await queryClient.invalidateQueries({ queryKey: ["foods"] });
      if (mountedRef.current && !successClaimedRef.current) {
        successClaimedRef.current = true;
        onCreated(response.food.id);
      }
    } catch (caught) {
      if (confirmationErrorCode(caught) === "ocr_confirmation_idempotency_conflict") {
        intentRef.current = null;
      }
      submittingRef.current = false;
      if (mountedRef.current) {
        validationFocusKeyRef.current = null;
        setSubmitting(false);
        setError(confirmationErrorMessage(caught));
      }
    }
  };

  return <View style={styles.screen}>
    <KeyboardSafeScrollView ref={scrollRef} contentContainerStyle={styles.content}>{(focusProps) => <>
      <View style={styles.header}><Text ref={headingRef} accessibilityRole="header" style={styles.title}>Confirm nutrition</Text><AccessiblePressable accessibilityLabel="Cancel confirmation" disabled={submitting} onPress={cancel}><Text style={styles.link}>Cancel</Text></AccessiblePressable></View>
      <Text accessibilityLiveRegion="polite" style={styles.notice}>Review flagged values. The image is not uploaded or saved.</Text>
      <Text accessibilityRole="header" style={styles.section}>Food</Text>
      <LabeledField {...focusProps("ocr.name")} label="Food name" validationTarget="ocr.name" required disabled={submitting} invalid={error === "Food name is required."} error={error === "Food name is required." ? error : null} value={draft.name} onChangeText={(name) => setDraft({ ...draft, name })} placeholder="Food name" placeholderTextColor={theme.colors.placeholder} inputStyle={styles.input}/>
      <LabeledField {...focusProps("ocr.brand")} label="Brand" validationTarget="ocr.brand" disabled={submitting} value={draft.brand} onChangeText={(brand) => setDraft({ ...draft, brand })} placeholder="Brand" placeholderTextColor={theme.colors.placeholder} inputStyle={styles.input}/>
      <LabeledField {...focusProps("ocr.notes")} label="Notes" validationTarget="ocr.notes" disabled={submitting} value={draft.notes} onChangeText={(notes) => setDraft({ ...draft, notes })} placeholder="Notes" placeholderTextColor={theme.colors.placeholder} inputStyle={styles.input}/>
      <Text accessibilityRole="header" style={styles.section}>Serving</Text>
      <LabeledField {...focusProps("ocr.servingDisplay")} label="Serving label" validationTarget="ocr.servingDisplay" disabled={submitting} value={draft.servingDisplay} onChangeText={(servingDisplay) => setDraft({ ...draft, servingDisplay })} placeholder="Serving label" placeholderTextColor={theme.colors.placeholder} inputStyle={styles.input}/>
      <View style={styles.row}><LabeledField containerStyle={styles.flex} {...focusProps("ocr.servingQuantity")} label="Serving quantity" validationTarget="ocr.servingQuantity" required disabled={submitting} invalid={error === "Enter a positive decimal serving quantity."} error={error === "Enter a positive decimal serving quantity." ? error : null} value={draft.servingQuantity} onChangeText={(servingQuantity) => setDraft({ ...draft, servingQuantity })} keyboardType="decimal-pad" placeholder="Quantity" placeholderTextColor={theme.colors.placeholder} inputStyle={styles.input}/><LabeledField containerStyle={styles.flex} {...focusProps("ocr.servingUnit")} label="Serving unit" validationTarget="ocr.servingUnit" disabled={submitting} value={draft.servingUnit} onChangeText={(servingUnit) => setDraft({ ...draft, servingUnit })} placeholder="Unit" placeholderTextColor={theme.colors.placeholder} inputStyle={styles.input}/></View>
      <LabeledField {...focusProps("ocr.gramWeight")} label="Serving grams" validationTarget="ocr.gramWeight" required disabled={submitting} invalid={error === "Enter a positive gram weight for the label serving."} error={error === "Enter a positive gram weight for the label serving." ? error : null} value={draft.gramWeight} onChangeText={(gramWeight) => setDraft({ ...draft, gramWeight })} keyboardType="decimal-pad" placeholder="Equivalent grams" placeholderTextColor={theme.colors.placeholder} inputStyle={styles.input}/>
      <Text accessibilityRole="header" style={styles.section}>Nutrition per label serving</Text>
      {fields.map((field) => <View key={field.fieldKey} style={[styles.card, field.decision === "unresolved" && styles.flagged, field.decision === "omitted" && styles.omitted]}>
        <View style={styles.row}><Text accessible accessibilityLabel={`${field.label}, review state ${field.decision}`} style={styles.fieldLabel}>{field.label}</Text><Text style={styles.meta}>{field.unit ?? ""}</Text></View>
        {(field.decision === "unresolved" || field.parseStatus === "ambiguous" || field.confidence < 0.8 || field.comparison) ? <Text style={styles.warning}>{field.comparison ? "Less-than value needs an exact replacement or omission" : `Review required · ${Math.round(field.confidence * 100)}% confidence`}</Text> : null}
        <Text style={styles.meta}>Review state: {field.decision}</Text>
        <LabeledField {...focusProps(`ocr.field.${field.fieldKey}`)} label={`${field.label} amount`} validationTarget={`ocr.field.${field.fieldKey}`} disabled={submitting || field.decision === "omitted"} invalid={Boolean(error?.startsWith(field.label))} error={error?.startsWith(field.label) ? error : null} value={field.confirmedValue} onChangeText={(value) => replaceField(updateReview(field, value))} keyboardType="decimal-pad" inputStyle={styles.input}/>
        <View style={styles.actions}>{showsUseValueAction(field) ? <AccessiblePressable accessibilityLabel={`Use ${field.label} value`} disabled={submitting} onPress={() => { const value = field.decision === "omitted" ? field.suggestedValue ?? "" : field.confirmedValue; replaceField(updateReview(field, value, value === (field.suggestedValue ?? "") ? "accepted" : "edited")); }}><Text style={styles.link}>Use value</Text></AccessiblePressable> : null}<AccessiblePressable accessibilityLabel={`Omit ${field.label}`} disabled={submitting || field.nutrientId === "calories"} onPress={() => replaceField({ ...field, decision: "omitted", confirmedValue: "", resolution: field.parseStatus === "ambiguous" || field.comparison ? "omitted after review" : field.resolution })}><Text style={styles.link}>Omit</Text></AccessiblePressable></View>
        <Text accessible={false} style={styles.source}>Source: {field.sourceText || "No source line"}</Text>
      </View>)}
      {draft.unknownNutrients.length ? <><Text accessibilityRole="header" style={styles.section}>Unknown rows</Text>{draft.unknownNutrients.map((item, index) => <View key={`${item.originalName}-${index}`} style={[styles.card, item.dismissed && styles.omitted]}><Text accessible accessibilityLabel={`Unknown nutrient ${item.originalName}, ${item.dismissed ? "dismissed" : "unresolved"}`} style={styles.fieldLabel}>{item.originalName}</Text><Text accessible={false} style={styles.source}>{item.sourceText}</Text><AccessiblePressable accessibilityLabel={`Dismiss unknown nutrient ${item.originalName}`} accessibilityState={{ selected: item.dismissed }} disabled={submitting || item.dismissed} onPress={() => setDraft({ ...draft, unknownNutrients: draft.unknownNutrients.map((entry, itemIndex) => itemIndex === index ? { ...entry, dismissed: true } : entry) })}><Text style={styles.link}>{item.dismissed ? "Dismissed" : "Dismiss after review"}</Text></AccessiblePressable></View>)}</> : null}
      {error && !["Food name is required.", "Enter a positive decimal serving quantity.", "Enter a positive gram weight for the label serving."].includes(error) && !fields.some((field) => error.startsWith(field.label)) ? <Text ref={errorRef} accessibilityLiveRegion="none" accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
    </>}</KeyboardSafeScrollView>
    <View style={styles.saveBar}><AccessiblePressable busy={submitting} accessibilityLabel={submitting ? "Creating Food" : "Create Food"} accessibilityHint="Creates the food, then opens logging confirmation when started from Add Food" onPress={submit} style={[styles.button, submitting && styles.disabled]}><Text style={styles.buttonText}>{submitting ? "Creating Food…" : "Create Food"}</Text></AccessiblePressable></View>
  </View>;
}

function createStyles(theme: ReturnType<typeof useAppTheme>) { return StyleSheet.create({
  actions: { flexDirection: "row", gap: 24 }, button: { alignItems: "center", backgroundColor: theme.colors.primaryActionBackground, borderRadius: 8, minHeight: 48, justifyContent: "center" },
  buttonText: { color: theme.colors.primaryActionForeground, fontSize: 16, fontWeight: "700" }, card: { backgroundColor: theme.colors.surface, borderColor: theme.colors.border, borderRadius: 8, borderWidth: 1, gap: 8, padding: 12 },
  content: { gap: 10, padding: 16, paddingBottom: 120 }, disabled: { opacity: 0.65 }, error: { color: theme.colors.errorText }, fieldLabel: { color: theme.colors.text, flex: 1, fontSize: 16, fontWeight: "700" }, flagged: { borderColor: theme.colors.warningText, borderWidth: 2 }, flex: { flex: 1 },
  header: { alignItems: "center", flexDirection: "row", flexWrap: "wrap", justifyContent: "space-between" }, input: { backgroundColor: theme.colors.input, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, color: theme.colors.text, minHeight: 44, padding: 10 }, link: { color: theme.colors.accent, fontWeight: "600" }, meta: { color: theme.colors.secondaryText }, notice: { color: theme.colors.secondaryText }, row: { alignItems: "center", flexDirection: "row", flexWrap: "wrap", gap: 10 },
  saveBar: { backgroundColor: theme.colors.surface, borderTopColor: theme.colors.border, borderTopWidth: 1, padding: 12 }, screen: { backgroundColor: theme.colors.background, flex: 1 }, section: { color: theme.colors.text, fontSize: 19, fontWeight: "800", marginTop: 8 }, source: { color: theme.colors.secondaryText, fontSize: 12 }, title: { color: theme.colors.text, fontSize: 25, fontWeight: "800" }, warning: { color: theme.colors.warningText, fontSize: 13 },
  omitted: { opacity: 0.7 },
}); }

function confirmationValidationFocusKey(error: string, draft: NutritionConfirmationDraft): string | null {
  if (error === "Food name is required.") return "ocr.name";
  if (error === "Enter a positive decimal serving quantity.") return "ocr.servingQuantity";
  if (error === "Enter a positive gram weight for the label serving.") return "ocr.gramWeight";
  const field = [draft.calories, ...draft.nutrients].find((candidate) => error.startsWith(candidate.label));
  return field ? `ocr.field.${field.fieldKey}` : null;
}
