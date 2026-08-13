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
import { useNutrients } from "../../foods/hooks/useFoods";
import type { ConfirmationField, NutritionConfirmationDraft } from "../api/types";
import { addManualNutrient, confirmationPayload, confirmationValidationIssues, hydrateCanonicalNutrientUnits, omitReview, updateReview } from "../confirmation/confirmationModel";
import { bindConfirmationIntent, type ConfirmationIntent } from "../confirmation/confirmationIntent";
import { confirmationErrorCode, confirmationErrorMessage } from "../confirmation/confirmationErrors";
import { useNutritionRuntime } from "../../../runtime/NutritionRuntimeContext";

const FINGERPRINT_PLACEHOLDER_REQUEST_ID = "00000000-0000-4000-8000-000000000000";

function showsUseValueAction(field: ConfirmationField): boolean {
  return Boolean(field.suggestedValue)
    && (field.decision === "unresolved" || field.decision === "edited" || field.decision === "omitted");
}

function reviewNotice(field: ConfirmationField): { actionable: boolean; message: string } | null {
  if (field.decision === "unresolved") {
    return {
      actionable: true,
      message: field.comparison === "less_than"
        ? "Less-than OCR value requires an exact replacement or omission"
        : `Review required · ${Math.round(field.confidence * 100)}% OCR confidence`,
    };
  }
  if (field.comparison === "less_than") {
    return { actionable: false, message: "OCR value was less than the detected amount" };
  }
  if (field.confidence < 0.8) {
    return { actionable: false, message: `Low OCR confidence · ${Math.round(field.confidence * 100)}%` };
  }
  if (field.parseStatus === "ambiguous") {
    return { actionable: false, message: "OCR result was ambiguous" };
  }
  return null;
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

export function NutritionConfirmationScreen({ initialDraft, onCancel, onCreated }: {
  initialDraft: NutritionConfirmationDraft;
  onCancel: () => void;
  onCreated: (foodId: string) => void;
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
  const hydratedDraft = useMemo(
    () => hydrateCanonicalNutrientUnits(draft, nutrientQuery.data ?? []),
    [draft, nutrientQuery.data],
  );
  const fields = [hydratedDraft.calories, ...hydratedDraft.nutrients];
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
  useAccessibilityScreenFocus({ active: true, routeKey: "nutrition-confirmation", targetRef: headingRef });

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
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

  const cancel = () => {
    if (submittingRef.current || cancelClaimedRef.current) return;
    cancelClaimedRef.current = true;
    onCancel();
  };

  const submit = async () => {
    if (submittingRef.current || cancelClaimedRef.current || successClaimedRef.current) return;
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

  return <View style={styles.screen}>
    <KeyboardSafeScrollView ref={scrollRef} contentContainerStyle={styles.content}>{(focusProps) => <>
      <View style={styles.header}><Text ref={headingRef} accessibilityRole="header" style={styles.title}>Confirm nutrition</Text><AccessiblePressable accessibilityLabel="Cancel confirmation" disabled={submitting} onPress={cancel}><Text style={styles.link}>Cancel</Text></AccessiblePressable></View>
      <Text accessibilityLiveRegion="polite" style={styles.notice}>Review flagged values. The image is not uploaded or saved.</Text>
      <Text accessibilityRole="header" style={styles.section}>Food</Text>
      <LabeledField {...focusProps("ocr.name")} label="Food name" validationTarget="ocr.name" required disabled={submitting} invalid={issuesByField.has("food.name")} error={issuesByField.get("food.name")?.message ?? null} value={draft.name} onChangeText={(name) => setDraft({ ...draft, name })} placeholder="Food name" placeholderTextColor={theme.colors.placeholder} inputStyle={styles.input}/>
      <LabeledField {...focusProps("ocr.brand")} label="Brand" validationTarget="ocr.brand" disabled={submitting} value={draft.brand} onChangeText={(brand) => setDraft({ ...draft, brand })} placeholder="Brand" placeholderTextColor={theme.colors.placeholder} inputStyle={styles.input}/>
      <LabeledField {...focusProps("ocr.notes")} label="Notes" validationTarget="ocr.notes" disabled={submitting} value={draft.notes} onChangeText={(notes) => setDraft({ ...draft, notes })} placeholder="Notes" placeholderTextColor={theme.colors.placeholder} inputStyle={styles.input}/>
      <Text accessibilityRole="header" style={styles.section}>Serving</Text>
      <LabeledField {...focusProps("ocr.servingDisplay")} label="Serving label" validationTarget="ocr.servingDisplay" disabled={submitting} value={draft.servingDisplay} onChangeText={(servingDisplay) => setDraft({ ...draft, servingDisplay })} placeholder="Serving label" placeholderTextColor={theme.colors.placeholder} inputStyle={styles.input}/>
      <View style={styles.row}><LabeledField containerStyle={styles.flex} {...focusProps("ocr.servingQuantity")} label="Serving quantity" validationTarget="ocr.servingQuantity" required disabled={submitting} invalid={issuesByField.has("serving.quantity")} error={issuesByField.get("serving.quantity")?.message ?? null} value={draft.servingQuantity} onChangeText={(servingQuantity) => setDraft({ ...draft, servingQuantity })} keyboardType="decimal-pad" placeholder="Quantity" placeholderTextColor={theme.colors.placeholder} inputStyle={styles.input}/><LabeledField containerStyle={styles.flex} {...focusProps("ocr.servingUnit")} label="Serving unit" validationTarget="ocr.servingUnit" disabled={submitting} value={draft.servingUnit} onChangeText={(servingUnit) => setDraft({ ...draft, servingUnit })} placeholder="Unit" placeholderTextColor={theme.colors.placeholder} inputStyle={styles.input}/></View>
      <LabeledField {...focusProps("ocr.gramWeight")} label="Serving grams" validationTarget="ocr.gramWeight" required disabled={submitting} invalid={issuesByField.has("serving.gram_weight")} error={issuesByField.get("serving.gram_weight")?.message ?? null} value={draft.gramWeight} onChangeText={(gramWeight) => setDraft({ ...draft, gramWeight })} keyboardType="decimal-pad" placeholder="Equivalent grams" placeholderTextColor={theme.colors.placeholder} inputStyle={styles.input}/>
      <Text accessibilityRole="header" style={styles.section}>Nutrition per label serving</Text>
      {fields.map((field) => { const notice = reviewNotice(field); return <View key={field.fieldKey} style={[styles.card, field.decision === "unresolved" && styles.flagged, field.decision === "omitted" && styles.omitted]}>
        <View style={styles.row}><Text accessible accessibilityLabel={`${field.label}, review state ${field.decision}`} style={styles.fieldLabel}>{field.label}</Text><Text style={styles.meta}>{field.unit ?? ""}</Text></View>
        {notice ? <Text style={notice.actionable ? styles.warning : styles.meta}>{notice.message}</Text> : null}
        <Text style={styles.meta}>Review state: {field.decision}</Text>
        <LabeledField {...focusProps(`ocr.field.${field.fieldKey}`)} label={`${field.label} amount`} validationTarget={`ocr.field.${field.fieldKey}`} disabled={submitting} invalid={issuesByField.has(field.fieldKey)} error={issuesByField.get(field.fieldKey)?.message ?? null} value={field.confirmedValue} onChangeText={(value) => replaceField(updateReview(field, value))} keyboardType="decimal-pad" inputStyle={styles.input}/>
        <View style={styles.actions}>{showsUseValueAction(field) ? <AccessiblePressable accessibilityLabel={`Use ${field.label} value`} disabled={submitting} onPress={() => { const value = field.decision === "omitted" ? field.suggestedValue ?? "" : field.confirmedValue; replaceField(updateReview(field, value, value === (field.suggestedValue ?? "") ? "accepted" : "edited")); }}><Text style={styles.link}>Use value</Text></AccessiblePressable> : null}<AccessiblePressable accessibilityLabel={`Omit ${field.label}`} disabled={submitting || field.decision === "omitted"} onPress={() => replaceField(omitReview(field))}><Text style={styles.link}>Omit</Text></AccessiblePressable></View>
        <Text accessible={false} style={styles.source}>Source: {field.sourceText || "No source line"}</Text>
      </View>; })}
      <AccessiblePressable accessibilityLabel="Add missing nutrient" disabled={submitting || nutrientQuery.isLoading || nutrientQuery.isError} onPress={() => setShowMissingNutrients((current) => !current)} style={styles.secondaryButton}><Text style={styles.link}>Add missing nutrient</Text></AccessiblePressable>
      {showMissingNutrients ? <View style={styles.picker}><Text accessibilityRole="header" style={styles.fieldLabel}>Choose a nutrient</Text>{availableNutrients.map((nutrient) => <AccessiblePressable key={nutrient.id} accessibilityLabel={`Add ${nutrient.display_name}`} disabled={submitting} onPress={() => { setDraft((current) => addManualNutrient(current, nutrient)); setShowMissingNutrients(false); }} style={styles.pickerOption}><Text style={styles.link}>{nutrient.display_name} ({nutrient.default_unit})</Text></AccessiblePressable>)}{availableNutrients.length === 0 ? <Text style={styles.meta}>All canonical nutrients are already in this review.</Text> : null}</View> : null}
      {draft.unknownNutrients.length ? <><Text accessibilityRole="header" style={styles.section}>Unknown rows</Text>{draft.unknownNutrients.map((item, index) => <View key={`${item.originalName}-${index}`} style={[styles.card, item.dismissed && styles.omitted]}><Text accessible accessibilityLabel={`Unknown nutrient ${item.originalName}, ${item.dismissed ? "dismissed" : "unresolved"}`} style={styles.fieldLabel}>{item.originalName}</Text><Text accessible={false} style={styles.source}>{item.sourceText}</Text><AccessiblePressable accessibilityLabel={`Dismiss unknown nutrient ${item.originalName}`} accessibilityState={{ selected: item.dismissed }} disabled={submitting || item.dismissed} onPress={() => setDraft({ ...draft, unknownNutrients: draft.unknownNutrients.map((entry, itemIndex) => itemIndex === index ? { ...entry, dismissed: true } : entry) })}><Text style={styles.link}>{item.dismissed ? "Dismissed" : "Dismiss after review"}</Text></AccessiblePressable></View>)}</> : null}
      {displayedError ? <Text ref={errorRef} accessibilityLiveRegion="none" accessibilityRole="alert" style={styles.error}>{displayedError}</Text> : null}
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
  picker: { borderColor: theme.colors.border, borderRadius: 8, borderWidth: 1, gap: 8, padding: 12 },
  pickerOption: { justifyContent: "center", minHeight: 44 },
  secondaryButton: { alignItems: "flex-start", justifyContent: "center", minHeight: 44 },
}); }

function confirmationValidationFocusKey(fieldKey: string | null): string | null {
  if (fieldKey === "food.name") return "ocr.name";
  if (fieldKey === "serving.quantity") return "ocr.servingQuantity";
  if (fieldKey === "serving.gram_weight") return "ocr.gramWeight";
  return fieldKey?.startsWith("nutrient.") ? `ocr.field.${fieldKey}` : null;
}
