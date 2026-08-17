import { useEffect, useMemo, useRef, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { useAppTheme } from "../../../app/theme/AppTheme";
import { AccessiblePressable } from "../../../shared/accessibility/AccessiblePressable";
import { LabeledField } from "../../../shared/forms/LabeledField";
import type { FocusTargetRegistration } from "../../../shared/forms/KeyboardSafeScrollView";
import { ServingUnitPicker } from "../../foods/components/ServingUnitPicker";
import {
  amountHasKnownGramWeight,
  amountUnitCategory,
  compactExactDecimalForEditing,
  divideAmountValues,
  exactCurrentGrams,
  recalculateCurrentForReferenceEdit,
  currentVolumeAnchor,
  scaledCurrentGrams,
  formatServingGramForDisplay,
  formatServingQuantityForDisplay,
  generatedAmountDisplayLabel,
  massGramEquivalent,
  multiplyAmountValues,
  normalizeServingQuantityInput,
  referenceMeasurementLabel,
  servingUnitDisplay,
  servingConversionReviewMessage,
  transitionServingUnit,
  UNCONVERTED_SERVING_UNIT_WARNING,
  type AmountLabelMode,
  type PreservedVolumeServing,
} from "../../foods/utils/amountForm";
import type { NutritionConfirmationDraft } from "../api/types";

type ServingValue = Pick<
  NutritionConfirmationDraft,
  "servingDisplay" | "servingQuantity" | "servingUnit" | "gramWeight" | "servingReferenceQuantity" | "servingReferenceUnit" | "servingReferenceGramWeight" | "servingConversionReviewRequired"
>;

type ServingPatch = Partial<ServingValue>;

type Props = {
  value: ServingValue;
  onChange: (patch: ServingPatch) => void;
  disabled?: boolean;
  focusProps: (key: string) => FocusTargetRegistration;
  quantityError?: string | null;
  gramWeightError?: string | null;
};

type ReferenceDraft = { quantity: string; unit: string; gramWeight: string };
type Representation = { quantity: string; unit: string };
type CurrentScalingAnchor = { quantity: string; unit: string; gramWeight: string };

/** Structured serving authoring for OCR confirmation without changing OCR payload authority.
 * The confirmed reference measurement is persisted separately from the current serving
 * representation. Compatible representation edits keep that reference; resolving a unit that
 * cannot be converted establishes a new measured reference explicitly supplied by the user. */
export function OcrServingEditor({
  value,
  onChange,
  disabled = false,
  focusProps,
  quantityError,
  gramWeightError,
}: Props) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const recoveredServing = recoverServingDisplay(value.servingDisplay);
  const initialQuantity = shouldRecoverQuantity(value.servingQuantity, recoveredServing?.quantity)
    ? recoveredServing!.quantity
    : value.servingQuantity;
  const initialUnit = shouldRecoverUnit(value.servingUnit, recoveredServing?.unit)
    ? recoveredServing!.unit
    : value.servingUnit;
  const initialGramWeight = !value.gramWeight.trim() && recoveredServing?.gramWeight
    ? recoveredServing.gramWeight
    : value.gramWeight;
  const [referenceDraft, setReferenceDraft] = useState<ReferenceDraft | null>(() => {
    const seeded = { quantity: initialQuantity, unit: initialUnit, gramWeight: initialGramWeight };
    return referenceValid(seeded) ? null : seeded;
  });
  const [representation, setRepresentation] = useState<Representation>(() => ({
    quantity: formatServingQuantityForDisplay(initialQuantity),
    unit: initialUnit,
  }));
  const [preservedVolume, setPreservedVolume] = useState<PreservedVolumeServing | null>(null);
  const [currentScalingAnchor, setCurrentScalingAnchor] = useState<CurrentScalingAnchor | null>(null);
  const [reviewWarning, setReviewWarning] = useState<string | null>(() =>
    value.servingConversionReviewRequired ? UNCONVERTED_SERVING_UNIT_WARNING : null,
  );
  // A parsed OCR display is source material for recovery, not a user customization:
  // structured servings label automatically until the user explicitly customizes.
  const [labelMode, setLabelMode] = useState<AmountLabelMode>(() =>
    value.servingDisplay.trim() && !recoveredServing ? "manual" : "automatic",
  );
  const initialRecoveryRef = useRef<ServingPatch | null | undefined>(undefined);
  if (initialRecoveryRef.current === undefined) {
    const patch: ServingPatch = {};
    if (initialQuantity !== value.servingQuantity) patch.servingQuantity = initialQuantity;
    if (initialUnit !== value.servingUnit) patch.servingUnit = initialUnit;
    if (initialGramWeight !== value.gramWeight) patch.gramWeight = initialGramWeight;
    // OCR source display text is provenance/recovery input, not a user-authored custom label.
    // Clear parseable structured text so persistence uses the current automatic representation.
    if (recoveredServing && value.servingDisplay.trim()) patch.servingDisplay = "";
    const derivedWeight = !initialGramWeight.trim() && amountUnitCategory(initialUnit) === "weight"
      ? massGramEquivalent(normalizeServingQuantityInput(initialQuantity) ?? initialQuantity, initialUnit)
      : null;
    if (derivedWeight) patch.gramWeight = derivedWeight;
    initialRecoveryRef.current = Object.keys(patch).length > 0 ? patch : null;
  }
  const recoveryPending = initialRecoveryRef.current !== null;
  const referenceConfirmed = referenceDraft === null;
  const canonicalRepresentationQuantity = normalizeServingQuantityInput(representation.quantity) ?? value.servingQuantity;
  const automaticLabel = generatedAmountDisplayLabel(canonicalRepresentationQuantity, representation.unit);
  const displayLabel = labelMode === "manual"
    ? value.servingDisplay.trim() || automaticLabel
    : automaticLabel;
  const unitFocus = focusProps("ocr.servingUnit");
  const referenceUnitFocus = focusProps("ocr.referenceUnit");

  useEffect(() => {
    const patch = initialRecoveryRef.current;
    if (!patch) return;
    initialRecoveryRef.current = null;
    onChange(patch);
  }, [onChange]);

  function updateReferenceDraft(patch: Partial<ReferenceDraft>) {
    setReferenceDraft((current) => ({ ...(current ?? draftFromValue()), ...patch }));
  }

  function confirmReference() {
    const draft = referenceDraft ?? draftFromValue();
    const quantity = normalizeServingQuantityInput(draft.quantity);
    const unit = draft.unit.trim();
    // Weight-unit references derive their gram total exactly; validation and confirmation
    // use the same derived value.
    const gramWeight = draft.gramWeight.trim() || (unit ? massGramEquivalent(quantity ?? "", unit) || "" : "");
    if (!quantity || !unit || !gramWeight) return;
    const newReference = { quantity, unit, gramWeight };
    const previousReference = draftFromValue();
    const currentEstablished = Boolean(normalizeServingQuantityInput(value.servingQuantity)) && Boolean(value.servingUnit.trim());
    setReferenceDraft(null);
    setPreservedVolume(null);
    setCurrentScalingAnchor(null);

    if (!currentEstablished) {
      onChange({
        servingQuantity: quantity,
        servingUnit: unit,
        gramWeight,
        servingReferenceQuantity: quantity,
        servingReferenceUnit: unit,
        servingReferenceGramWeight: gramWeight,
        servingConversionReviewRequired: false,
      });
      setRepresentation({ quantity: formatServingQuantityForDisplay(quantity), unit });
      setReviewWarning(null);
      return;
    }

    const recalculated = recalculateCurrentForReferenceEdit(
      { quantity: value.servingQuantity, unit: value.servingUnit, gramWeight: value.gramWeight },
      previousReference,
      newReference,
    );
    const nextCurrent = recalculated
      ? { quantity: recalculated.quantity, unit: value.servingUnit, gramWeight: recalculated.gramWeight }
      : { quantity, unit, gramWeight };
    // Explicit reference confirmation wins over an incompatible stale representation. When the
    // old current unit cannot be recalculated against the new reference, reset current to the
    // reference instead of arming conversion review and risking a later re-promotion with stale
    // grams from the old current amount.
    onChange({
      servingQuantity: nextCurrent.quantity,
      servingUnit: nextCurrent.unit,
      gramWeight: nextCurrent.gramWeight,
      servingReferenceQuantity: quantity,
      servingReferenceUnit: unit,
      servingReferenceGramWeight: gramWeight,
      servingConversionReviewRequired: false,
    });
    setRepresentation({
      quantity: formatServingQuantityForDisplay(nextCurrent.quantity),
      unit: nextCurrent.unit,
    });
    setReviewWarning(null);
  }

  function cancelReferenceEdit() {
    setReferenceDraft(null);
  }

  function editReference() {
    setReferenceDraft(draftFromValue());
  }

  function updateRepresentationQuantity(rawQuantity: string) {
    setRepresentation((current) => ({ ...current, quantity: rawQuantity }));
    const quantity = normalizeServingQuantityInput(rawQuantity);
    const reference = draftFromValue();
    const currentIsValidAnchor = Boolean(normalizeServingQuantityInput(value.servingQuantity))
      && amountHasKnownGramWeight({ gram_weight: value.gramWeight || null })
      && Boolean(representation.unit.trim());
    const fallbackScalingAnchor = currentScalingAnchor?.unit === representation.unit
      ? currentScalingAnchor
      : currentIsValidAnchor
        ? { quantity: value.servingQuantity, unit: representation.unit, gramWeight: value.gramWeight }
        : null;

    // Preserve the last established current relationship across real keyboard replacement
    // sequences such as "2" -> "" -> "0" -> "0." -> "0.5".
    if (!reviewWarning && !currentScalingAnchor && fallbackScalingAnchor) {
      setCurrentScalingAnchor(fallbackScalingAnchor);
    }

    if (!quantity) {
      onChange({ servingQuantity: rawQuantity });
      return;
    }

    let nextGrams: string | null = null;
    if (!reviewWarning && representation.unit.trim()) {
      const category = amountUnitCategory(representation.unit);
      nextGrams = category === "count" || category === "custom"
        ? (fallbackScalingAnchor
            ? scaledCurrentGrams(fallbackScalingAnchor.quantity, fallbackScalingAnchor.gramWeight, quantity)
            : null)
        : exactCurrentGrams(quantity, representation.unit, { quantity: reference.quantity, unit: reference.unit, gramWeight: reference.gramWeight || "0" })
          ?? (fallbackScalingAnchor
            ? scaledCurrentGrams(fallbackScalingAnchor.quantity, fallbackScalingAnchor.gramWeight, quantity)
            : null);
    }

    const resolvesReview = Boolean(reviewWarning);
    const promotedReference: ServingPatch = resolvesReview && amountHasKnownGramWeight({ gram_weight: value.gramWeight || null })
      ? {
          servingReferenceQuantity: quantity,
          servingReferenceUnit: representation.unit,
          servingReferenceGramWeight: value.gramWeight,
        }
      : referencePatchIfMissing();
    onChange({
      servingQuantity: quantity,
      ...(representation.unit !== value.servingUnit ? { servingUnit: representation.unit } : {}),
      ...(nextGrams ? { gramWeight: nextGrams } : {}),
      ...promotedReference,
      ...(resolvesReview ? { servingConversionReviewRequired: false } : {}),
    });

    if (resolvesReview) {
      // A refused conversion has no defensible relationship to the old reference. Once the user
      // supplies the missing quantity, that explicit unit/quantity/gram relationship becomes the
      // stable reference for the confirmed serving.
      if (amountHasKnownGramWeight({ gram_weight: value.gramWeight || null })) {
        setCurrentScalingAnchor({ quantity, unit: representation.unit, gramWeight: value.gramWeight });
      }
      setReviewWarning(null);
    }
    setPreservedVolume(null);
  }

  function updateRepresentationUnit(servingUnit: string) {
    const quantity = normalizeServingQuantityInput(representation.quantity) ?? value.servingQuantity;
    const transition = transitionServingUnit(
      {
        quantity,
        unit: representation.unit,
        gramWeight: value.gramWeight,
        preservedVolume: preservedVolume ?? currentVolumeAnchor(
          { quantity, unit: representation.unit, gramWeight: value.gramWeight },
          draftFromValue(),
        ),
      },
      servingUnit,
    );
    setRepresentation({ quantity: formatServingQuantityForDisplay(transition.quantity), unit: servingUnit });
    setPreservedVolume(transition.preservedVolume);
    setCurrentScalingAnchor(null);
    setReviewWarning(transition.reviewWarning);
    onChange({
      servingQuantity: transition.quantity,
      servingUnit,
      gramWeight: transition.gramWeight,
      ...referencePatchIfMissing(),
      servingConversionReviewRequired: Boolean(transition.reviewWarning),
    });
  }

  function useAutomaticLabel() {
    setLabelMode("automatic");
    onChange({ servingDisplay: "" });
  }

  function customizeLabel() {
    setLabelMode("manual");
    onChange({ servingDisplay: value.servingDisplay.trim() || automaticLabel });
  }

  function draftFromValue(): ReferenceDraft {
    return {
      quantity: compactExactDecimalForEditing(value.servingReferenceQuantity ?? value.servingQuantity),
      unit: value.servingReferenceUnit ?? value.servingUnit,
      gramWeight: compactExactDecimalForEditing(value.servingReferenceGramWeight ?? value.gramWeight),
    };
  }

  function referencePatchIfMissing(): ServingPatch {
    if (value.servingReferenceQuantity != null && value.servingReferenceUnit != null && value.servingReferenceGramWeight != null) return {};
    const reference = draftFromValue();
    if (!referenceValid(reference)) return {};
    return {
      servingReferenceQuantity: normalizeServingQuantityInput(reference.quantity) ?? reference.quantity,
      servingReferenceUnit: reference.unit.trim(),
      servingReferenceGramWeight: reference.gramWeight.trim(),
    };
  }

  const draft = referenceDraft ?? draftFromValue();
  const draftGramsReadOnly = amountUnitCategory(draft.unit) === "weight";
  const draftGrams = draftGramsReadOnly
    ? massGramEquivalent(normalizeServingQuantityInput(draft.quantity) ?? draft.quantity, draft.unit) ?? ""
    : draft.gramWeight;
  return (
    <View style={styles.card}>
      <Text style={styles.meta}>
        Confirm the measured serving relationship from the label, then adjust how it is displayed. Compatible current units are recalculated from the reference. If an edited reference is incompatible with the current unit, the current serving resets to that new reference.
      </Text>

      {referenceDraft ? (
        <View style={styles.referenceEditor}>
          <Text accessibilityRole="header" style={styles.fieldLabel}>Reference measurement</Text>
          <Text style={styles.meta}>For example, 2/3 cup = 55 g.</Text>

          <View style={styles.twoColumn}>
            <LabeledField
              containerStyle={styles.flex}
              label="Reference quantity"
              accessibilityLabel="Reference quantity"
              validationTarget="ocr.servingQuantity"
              {...focusProps("ocr.servingQuantity")}
              required
              disabled={disabled}
              invalid={Boolean(quantityError)}
              error={quantityError}
              value={draft.quantity}
              onChangeText={(quantity) => updateReferenceDraft({ quantity })}
              keyboardType="numbers-and-punctuation"
              placeholder="e.g. 2/3"
              placeholderTextColor={theme.colors.placeholder}
              inputStyle={styles.input}
              hint="Enter a decimal, fraction, or mixed fraction, such as 1 1/2."
            />
            <ServingUnitPicker
              value={draft.unit}
              onChange={(unit) => updateReferenceDraft({ unit })}
              accessibilityLabel="Reference unit"
              contextLabel="reference measurement"
              disabled={disabled}
              containerStyle={styles.flex}
              focusRef={referenceUnitFocus.ref}
              onFocus={referenceUnitFocus.onFocus}
            />
          </View>

          <LabeledField
            label="Reference grams"
            accessibilityLabel="Reference grams"
            validationTarget="ocr.gramWeight"
            {...focusProps("ocr.gramWeight")}
            required
            disabled={disabled}
            readOnly={draftGramsReadOnly}
            invalid={Boolean(gramWeightError)}
            error={gramWeightError}
            value={draftGrams}
            onChangeText={(gramWeight) => updateReferenceDraft({ gramWeight })}
            keyboardType="decimal-pad"
            placeholder={draftGramsReadOnly ? "Calculated" : "e.g. 55"}
            placeholderTextColor={theme.colors.placeholder}
            inputStyle={[styles.input, draftGramsReadOnly && styles.calculatedInput]}
            hint={draftGramsReadOnly
              ? "Weight-unit totals are calculated from the reference quantity."
              : "Total gram weight of the reference amount."}
          />

          <View style={styles.actions}>
            <AccessiblePressable
              accessibilityLabel="Confirm reference measurement"
              disabled={disabled || !referenceDraftValid(draft, draftGrams)}
              onPress={confirmReference}
              style={[styles.compactButton, (disabled || !referenceDraftValid(draft, draftGrams)) && styles.disabled]}
            >
              <Text style={styles.link}>Confirm</Text>
            </AccessiblePressable>
            {referenceValid(draftFromValue()) ? (
              <AccessiblePressable
                accessibilityLabel="Cancel editing reference measurement"
                disabled={disabled}
                onPress={cancelReferenceEdit}
                style={styles.compactButton}
              >
                <Text style={styles.link}>Cancel</Text>
              </AccessiblePressable>
            ) : null}
          </View>
        </View>
      ) : (
        <View style={styles.referenceRow}>
          <View style={styles.flex}>
            <Text accessibilityRole="header" style={styles.fieldLabel}>Reference measurement</Text>
            <Text style={styles.referenceValue}>
              {referenceMeasurementLabel(draftFromValue())}
            </Text>
          </View>
          <AccessiblePressable
            accessibilityLabel="Edit reference measurement"
            disabled={disabled}
            onPress={editReference}
            style={styles.compactButton}
          >
            <Text style={styles.link}>Edit</Text>
          </AccessiblePressable>
        </View>
      )}

      {referenceConfirmed ? (
        <View style={styles.representationEditor}>
          <Text style={styles.meta}>Change how the serving is shown. Compatible units keep the same reference. If a unit cannot be converted, entering its quantity makes that relationship the new reference.</Text>

          <View style={styles.twoColumn}>
            <LabeledField
              containerStyle={styles.flex}
              label="Quantity"
              accessibilityLabel="Serving quantity"
              validationTarget="ocr.servingQuantity"
              {...focusProps("ocr.servingQuantity")}
              required
              disabled={disabled}
              invalid={Boolean(quantityError)}
              error={quantityError}
              value={representation.quantity}
              onChangeText={updateRepresentationQuantity}
              keyboardType="numbers-and-punctuation"
              placeholder="e.g. 2/3"
              placeholderTextColor={theme.colors.placeholder}
              inputStyle={styles.input}
              hint="Editing the quantity authors a new amount for this serving."
            />
            <ServingUnitPicker
              value={representation.unit}
              onChange={updateRepresentationUnit}
              accessibilityLabel="Serving unit"
              contextLabel={displayLabel || "nutrition label serving"}
              disabled={disabled}
              containerStyle={styles.flex}
              focusRef={unitFocus.ref}
              onFocus={unitFocus.onFocus}
            />
          </View>

          <View style={styles.previewCard}>
            <Text style={styles.fieldLabel}>Will appear as</Text>
            <Text style={styles.previewText}>{servingPreview(displayLabel, value.gramWeight)}</Text>
            {servingWeightSummary(value, representation, reviewWarning) ? (
              <Text style={styles.meta}>{servingWeightSummary(value, representation, reviewWarning)}</Text>
            ) : null}
          </View>

          {reviewWarning ? <Text style={styles.warning}>{servingConversionReviewMessage(representation.unit, value.gramWeight)}</Text> : null}
        </View>
      ) : null}

      {labelMode === "manual" ? (
        <View style={styles.labelEditor}>
          <View style={styles.labelHeader}>
            <Text style={styles.fieldLabel}>Custom display name</Text>
            <AccessiblePressable
              accessibilityLabel={`Use automatic label for ${displayLabel || "label serving"}`}
              disabled={disabled}
              onPress={useAutomaticLabel}
            >
              <Text style={styles.link}>Use automatic</Text>
            </AccessiblePressable>
          </View>
          <LabeledField
            label="Custom display name"
            accessibilityLabel="Serving label"
            validationTarget="ocr.servingDisplay"
            {...focusProps("ocr.servingDisplay")}
            disabled={disabled}
            value={value.servingDisplay}
            onChangeText={(servingDisplay) => onChange({ servingDisplay })}
            placeholder={automaticLabel ? `e.g. ${automaticLabel}, prepared` : "Custom display name"}
            placeholderTextColor={theme.colors.placeholder}
            inputStyle={styles.input}
          />
        </View>
      ) : (
        <AccessiblePressable
          accessibilityLabel={`Customize label for ${displayLabel || "label serving"}`}
          disabled={disabled}
          onPress={customizeLabel}
          style={styles.compactLink}
        >
          <Text style={styles.link}>Customize display name</Text>
        </AccessiblePressable>
      )}
    </View>
  );
}

function referenceValid(draft: ReferenceDraft): boolean {
  return Boolean(normalizeServingQuantityInput(draft.quantity)) && Boolean(draft.unit.trim()) && Number(draft.gramWeight) > 0 && Number.isFinite(Number(draft.gramWeight));
}

function referenceDraftValid(draft: ReferenceDraft, derivedGrams: string): boolean {
  const grams = draft.gramWeight.trim() || derivedGrams;
  return Boolean(normalizeServingQuantityInput(draft.quantity)) && Boolean(draft.unit.trim()) && Number(grams) > 0 && Number.isFinite(Number(grams));
}

function servingPreview(displayLabel: string, gramWeight: string): string {
  if (!displayLabel) return "Enter a reference measurement to preview this serving.";
  if (!positiveDecimal(gramWeight) || labelIncludesGramWeight(displayLabel)) return displayLabel;
  return `${displayLabel} (${formatServingGramForDisplay(gramWeight)} g)`;
}

function servingWeightSummary(value: ServingValue, representation: Representation, reviewWarning: string | null): string {
  if (!positiveDecimal(value.gramWeight)) return "Gram weight not set";
  const displayTotal = formatServingGramForDisplay(value.gramWeight);
  if (amountUnitCategory(representation.unit) === "weight") return `${displayTotal} g total`;
  if (reviewWarning) return `${displayTotal} g total`;
  const quantity = normalizeServingQuantityInput(representation.quantity);
  if (!quantity) return `${displayTotal} g total`;
  const perUnit = divideAmountValues(value.gramWeight, quantity);
  if (!perUnit) return `${displayTotal} g total`;
  return `${formatServingGramForDisplay(perUnit)} g per ${servingUnitDisplay(representation.unit)} · ${displayTotal} g total`;
}

function recoverServingDisplay(display: string): { quantity: string; unit: string; gramWeight: string | null } | null {
  const match = display.trim().match(/^(\d+\s+\d+\s*\/\s*\d+|\d+\s*\/\s*\d+|\d+(?:[.,]\d+)?)\s+([^()\d]+?)(?:\s*\(\s*(\d+(?:[.,]\d+)?)\s*g\s*\))?$/i);
  if (!match) return null;
  const quantityText = match[1].trim().replace(/\s*\/\s*/g, "/").replace(/\s+/g, " ");
  const quantity = normalizeServingQuantityInput(quantityText);
  const unit = match[2].trim().replace(/\s+/g, " ").toLowerCase();
  if (!quantity || !unit) return null;
  const gramWeight = match[3]?.replace(",", ".") ?? null;
  return { quantity, unit, gramWeight };
}

function shouldRecoverQuantity(current: string, recovered: string | undefined): boolean {
  if (!recovered) return false;
  const currentNormalized = normalizeServingQuantityInput(current);
  return !currentNormalized || (currentNormalized === "1" && recovered !== "1");
}

function shouldRecoverUnit(current: string, recovered: string | undefined): boolean {
  if (!recovered) return false;
  const normalized = current.trim().toLowerCase();
  return !normalized || (normalized === "serving" && recovered !== "serving");
}

function labelIncludesGramWeight(label: string): boolean {
  return /\(\s*[0-9]+(?:\.[0-9]+)?\s*(g|gram|grams)\s*\)$/i.test(label.trim());
}

function positiveDecimal(value: string): boolean {
  const numeric = Number(value);
  return value.trim() !== "" && Number.isFinite(numeric) && numeric > 0;
}

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    actions: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
    calculatedInput: { color: theme.colors.secondaryText },
    card: { backgroundColor: theme.colors.surface, borderColor: theme.colors.border, borderRadius: 8, borderWidth: 1, gap: 12, padding: 12 },
    compactButton: { alignItems: "center", borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, justifyContent: "center", minHeight: 44, paddingHorizontal: 12, paddingVertical: 8 },
    compactLink: { alignSelf: "flex-start", minHeight: 44, justifyContent: "center" },
    disabled: { opacity: 0.55 },
    fieldLabel: { color: theme.colors.secondaryText, fontSize: 13, fontWeight: "700" },
    flex: { flex: 1, minWidth: 140 },
    input: { backgroundColor: theme.colors.input, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, color: theme.colors.text, fontSize: 16, minHeight: 44, paddingHorizontal: 10, paddingVertical: 10 },
    labelEditor: { gap: 8 },
    labelHeader: { alignItems: "center", flexDirection: "row", flexWrap: "wrap", gap: 8, justifyContent: "space-between" },
    link: { color: theme.colors.accent, fontWeight: "700" },
    meta: { color: theme.colors.secondaryText, fontSize: 13 },
    previewCard: { backgroundColor: theme.colors.secondarySurface, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, gap: 4, padding: 10 },
    previewText: { color: theme.colors.text, fontSize: 16, fontWeight: "700" },
    referenceEditor: { backgroundColor: theme.colors.secondarySurface, borderColor: theme.colors.border, borderRadius: 8, borderWidth: 1, gap: 10, padding: 10 },
    referenceRow: { alignItems: "center", backgroundColor: theme.colors.secondarySurface, borderColor: theme.colors.border, borderRadius: 8, borderWidth: 1, flexDirection: "row", flexWrap: "wrap", gap: 8, padding: 10 },
    referenceValue: { color: theme.colors.text, fontSize: 16, fontWeight: "700" },
    representationEditor: { gap: 12 },
    twoColumn: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
    warning: { color: theme.colors.warningText, fontSize: 13 },
  });
}
