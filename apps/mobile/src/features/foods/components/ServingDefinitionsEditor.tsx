import { useEffect, useMemo, useState, type ReactNode } from "react";
import { StyleSheet, Text, View } from "react-native";
import { useAppTheme } from "../../../app/theme/AppTheme";
import { AccessiblePressable } from "../../../shared/accessibility/AccessiblePressable";
import { LabeledField } from "../../../shared/forms/LabeledField";
import { servingFocusKey } from "../../../shared/forms/focusTargets";
import type { FocusTargetRegistration } from "../../../shared/forms/KeyboardSafeScrollView";
import type { ServingFormValue } from "../hooks/useFoodForm";
import {
  amountHasKnownGramWeight,
  amountUnitCategory,
  compactExactDecimalForEditing,
  DEFAULT_AMOUNT_WEIGHT_MESSAGE,
  derivedServingPerUnitText,
  formatServingGramForDisplay,
  formatServingLabelForDisplay,
  generatedAmountDisplayLabel,
  generatedAmountLabel,
  normalizeServingQuantityInput,
  referenceMeasurementLabel,
  exactCurrentGrams,
  recalculateCurrentForReferenceEdit,
  scaledCurrentGrams,
  servingConversionReviewMessage,
  currentVolumeAnchor,
  transitionServingUnit,
  UNCONVERTED_SERVING_UNIT_WARNING,
  type PreservedVolumeServing,
} from "../utils/amountForm";
import { ServingUnitPicker } from "./ServingUnitPicker";

type Props = {
  servings: ServingFormValue[];
  updateServing: (key: string, patch: Partial<ServingFormValue>) => void;
  addServing: () => string;
  removeServing: (key: string) => void;
  focusProps: (key: string) => FocusTargetRegistration;
  invalidServingKey?: string | null;
  defaultAmountError?: { key: string; message: string } | null;
  validationTarget?: string | null;
  validationError?: string | null;
};

type ReferenceDraft = { quantity: string; unit: string; gramWeight: string };
type CurrentScalingAnchor = { quantity: string; unit: string; gramWeight: string };
type PendingEquivalenceDraft = {
  targetUnit: string;
  quantity: string;
  gramWeight: string;
  previousConsistencyWarning?: string;
};

/** The serving row persists the current representation. The optional reference_* triplet
 * separately persists the stable measurement the user established for conversion/scaling. */
export function ServingDefinitionsEditor({ servings, updateServing, addServing, removeServing, focusProps, invalidServingKey, defaultAmountError, validationTarget, validationError }: Props) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const baseAmount = servings.find((serving) => serving.isBaseAmount);
  const portions = servings.filter((serving) => !serving.isBaseAmount);
  const [expandedKey, setExpandedKey] = useState<string | null>(() => portions.find((serving) => serving.consistencyWarning)?.key ?? null);
  const [preservedVolumes, setPreservedVolumes] = useState<Record<string, PreservedVolumeServing | null>>({});
  const [reviewWarnings, setReviewWarnings] = useState<Record<string, string | null>>({});
  // A review warning is presentation/validation state. Promotion authority is tracked separately
  // so the first user-authored quantity can consume an incompatible-unit transition exactly once.
  // Otherwise a stale warning from the parent form can incorrectly promote every later quantity edit.
  const [pendingReferencePromotions, setPendingReferencePromotions] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(portions
      .filter((serving) => serving.consistencyWarning === UNCONVERTED_SERVING_UNIT_WARNING)
      .map((serving) => [serving.key, true])),
  );
  const [currentScalingAnchors, setCurrentScalingAnchors] = useState<Record<string, CurrentScalingAnchor | null>>({});
  const [referenceDrafts, setReferenceDrafts] = useState<Record<string, ReferenceDraft | undefined>>({});
  const [pendingEquivalences, setPendingEquivalences] = useState<
    Record<string, PendingEquivalenceDraft | undefined>
  >({});

  useEffect(() => {
    if (invalidServingKey && !servings.find((serving) => serving.key === invalidServingKey)?.isBaseAmount) {
      setExpandedKey(invalidServingKey);
    }
  }, [invalidServingKey, servings]);

  function openEditor(serving: ServingFormValue) {
    setExpandedKey(serving.key);
  }

  function activeReviewWarning(serving: ServingFormValue): string | null {
    // An explicit local null means the review was resolved. Do not fall back to a stale
    // consistencyWarning from the parent render while React is committing the same edit.
    if (Object.prototype.hasOwnProperty.call(reviewWarnings, serving.key)) {
      return reviewWarnings[serving.key] ?? null;
    }
    return serving.consistencyWarning === UNCONVERTED_SERVING_UNIT_WARNING
      ? UNCONVERTED_SERVING_UNIT_WARNING
      : null;
  }

  // The persisted current representation is the serving row's quantity/unit/gram_weight;
  // the reference measurement persists in the reference_* fields (defaulting to the current
  // values for servings saved before reference fields existed).
  function referenceOf(serving: ServingFormValue) {
    return {
      quantity: serving.reference_quantity ?? serving.quantity,
      unit: serving.reference_unit ?? serving.unit,
      gramWeight: serving.reference_gram_weight ?? serving.gram_weight ?? "",
    };
  }

  function referenceConfirmed(serving: ServingFormValue): boolean {
    const reference = referenceOf(serving);
    return Boolean(normalizeServingQuantityInput(reference.quantity)) && Boolean(reference.unit.trim()) && amountHasKnownGramWeight({ gram_weight: reference.gramWeight });
  }

  function currentMatchesReference(serving: ServingFormValue, reference = referenceOf(serving)): boolean {
    const currentQuantity = normalizeServingQuantityInput(serving.quantity);
    const referenceQuantity = normalizeServingQuantityInput(reference.quantity);
    const currentGrams = normalizeServingQuantityInput(serving.gram_weight ?? "");
    const referenceGrams = normalizeServingQuantityInput(reference.gramWeight);
    return Boolean(currentQuantity)
      && currentQuantity === referenceQuantity
      && serving.unit.trim().toLowerCase() === reference.unit.trim().toLowerCase()
      && Boolean(currentGrams)
      && currentGrams === referenceGrams;
  }

  function updateReferenceDraft(serving: ServingFormValue, patch: Partial<ReferenceDraft>) {
    setReferenceDrafts((current) => ({
      ...current,
      [serving.key]: { ...(current[serving.key] ?? draftFromServing(serving)), ...patch },
    }));
  }

  function confirmReference(serving: ServingFormValue) {
    const draft = referenceDrafts[serving.key] ?? draftFromServing(serving);
    const referenceQuantity = normalizeServingQuantityInput(draft.quantity);
    if (!referenceQuantity || !draft.unit.trim() || !draft.gramWeight.trim() || Number(draft.gramWeight) <= 0) return;
    const newReference = { quantity: referenceQuantity, unit: draft.unit.trim(), gramWeight: draft.gramWeight.trim() };
    const previousReference = referenceOf(serving);
    const currentUnestablished = !normalizeServingQuantityInput(serving.quantity) || !serving.unit.trim();
    setReferenceDrafts((current) => ({ ...current, [serving.key]: undefined }));
    // Transient conversion anchors belong to the old reference and must never resurrect it.
    setPreservedVolumes((current) => ({ ...current, [serving.key]: null }));
    setCurrentScalingAnchors((current) => ({ ...current, [serving.key]: null }));
    setPendingReferencePromotions((current) => ({ ...current, [serving.key]: false }));

    if (currentUnestablished) {
      updateServing(serving.key, {
        quantity: newReference.quantity,
        unit: newReference.unit,
        gram_weight: newReference.gramWeight,
        reference_quantity: newReference.quantity,
        reference_unit: newReference.unit,
        reference_gram_weight: newReference.gramWeight,
        consistencyWarning: serving.consistencyWarning === UNCONVERTED_SERVING_UNIT_WARNING
          ? undefined
          : serving.consistencyWarning,
      });
      setReviewWarnings((current) => ({ ...current, [serving.key]: null }));
      return;
    }

    const recalculated = recalculateCurrentForReferenceEdit(
      { quantity: serving.quantity, unit: serving.unit, gramWeight: serving.gram_weight },
      previousReference,
      newReference,
    );
    // An explicit reference edit is authoritative. If the existing current representation
    // cannot be recalculated against the new reference (for example 8 tsp -> 1 piece), there
    // is no defensible relationship to preserve. Reset the current representation to the new
    // reference instead of entering conversion review, which could later overwrite the user's
    // explicitly confirmed reference with stale current grams.
    updateServing(serving.key, {
      quantity: recalculated ? recalculated.quantity : newReference.quantity,
      unit: recalculated ? serving.unit : newReference.unit,
      gram_weight: recalculated ? recalculated.gramWeight : newReference.gramWeight,
      reference_quantity: newReference.quantity,
      reference_unit: newReference.unit,
      reference_gram_weight: newReference.gramWeight,
      consistencyWarning: serving.consistencyWarning === UNCONVERTED_SERVING_UNIT_WARNING
        ? undefined
        : serving.consistencyWarning,
    });
    setReviewWarnings((current) => ({ ...current, [serving.key]: null }));
  }

  function editReference(serving: ServingFormValue) {
    setReferenceDrafts((current) => ({ ...current, [serving.key]: draftFromServing(serving) }));
  }

  function cancelReferenceEdit(serving: ServingFormValue) {
    setReferenceDrafts((current) => ({ ...current, [serving.key]: undefined }));
  }

  function beginPendingEquivalence(
    serving: ServingFormValue,
    targetUnit: string,
    transitionGramWeight: string,
  ) {
    const existingDraft = pendingEquivalences[serving.key];
    const reference = referenceOf(serving);

    const authoritativeGrams = amountHasKnownGramWeight({
      gram_weight: transitionGramWeight,
    })
      ? transitionGramWeight.trim()
      : amountHasKnownGramWeight(serving)
        ? (serving.gram_weight ?? "").trim()
        : exactCurrentGrams(serving.quantity, serving.unit, reference)
          ?? reference.gramWeight.trim();

    const previousWarning =
      existingDraft?.previousConsistencyWarning
      ?? serving.consistencyWarning;

    setPendingEquivalences((current) => ({
      ...current,
      [serving.key]: {
        targetUnit,
        quantity:
          existingDraft?.targetUnit === targetUnit
            ? existingDraft.quantity
            : "",
        gramWeight: authoritativeGrams,
        previousConsistencyWarning:
          previousWarning === UNCONVERTED_SERVING_UNIT_WARNING
            ? undefined
            : previousWarning,
      },
    }));

    // The sentinel blocks Save while the local draft is unresolved, but
    // quantity/unit/reference authority remains exactly as it was.
    updateServing(serving.key, {
      consistencyWarning: UNCONVERTED_SERVING_UNIT_WARNING,
    });

    setReferenceDrafts((current) => ({
      ...current,
      [serving.key]: undefined,
    }));
    setReviewWarnings((current) => ({
      ...current,
      [serving.key]: UNCONVERTED_SERVING_UNIT_WARNING,
    }));
    setPendingReferencePromotions((current) => ({
      ...current,
      [serving.key]: false,
    }));
  }

  function cancelPendingEquivalence(serving: ServingFormValue) {
    const pending = pendingEquivalences[serving.key];
    if (!pending) return;

    updateServing(serving.key, {
      consistencyWarning: pending.previousConsistencyWarning,
    });

    setPendingEquivalences((current) => ({
      ...current,
      [serving.key]: undefined,
    }));
    setReviewWarnings((current) => ({
      ...current,
      [serving.key]: null,
    }));
    setPendingReferencePromotions((current) => ({
      ...current,
      [serving.key]: false,
    }));
  }

  function confirmPendingEquivalence(serving: ServingFormValue) {
    const pending = pendingEquivalences[serving.key];
    if (!pending) return;

    const quantity = normalizeServingQuantityInput(pending.quantity);
    if (
      !quantity
      || !pending.targetUnit.trim()
      || !amountHasKnownGramWeight({ gram_weight: pending.gramWeight })
    ) {
      return;
    }

    // This explicit confirmation is the authority boundary. Intermediate
    // keyboard values never reach persisted/current serving state.
    updateServing(serving.key, {
      quantity,
      unit: pending.targetUnit,
      gram_weight: pending.gramWeight,
      reference_quantity: quantity,
      reference_unit: pending.targetUnit,
      reference_gram_weight: pending.gramWeight,
      consistencyWarning: pending.previousConsistencyWarning,
    });

    setPendingEquivalences((current) => ({
      ...current,
      [serving.key]: undefined,
    }));
    setReviewWarnings((current) => ({
      ...current,
      [serving.key]: null,
    }));
    setPendingReferencePromotions((current) => ({
      ...current,
      [serving.key]: false,
    }));
    setPreservedVolumes((current) => ({
      ...current,
      [serving.key]: null,
    }));
    setCurrentScalingAnchors((current) => ({
      ...current,
      [serving.key]: null,
    }));
  }

  function updateRepresentationQuantity(serving: ServingFormValue, rawQuantity: string) {
    const pendingEquivalence = pendingEquivalences[serving.key];
    if (pendingEquivalence) {
      setPendingEquivalences((current) => ({
        ...current,
        [serving.key]: {
          ...pendingEquivalence,
          quantity: rawQuantity,
        },
      }));
      return;
    }

    const quantity = normalizeServingQuantityInput(rawQuantity);
    const reference = referenceOf(serving);
    const unresolved = Boolean(activeReviewWarning(serving));
    const pendingReferencePromotion = pendingReferencePromotions[serving.key] === true;
    const category = amountUnitCategory(serving.unit);
    const existingScalingAnchor = currentScalingAnchors[serving.key];
    const currentIsValidAnchor = Boolean(normalizeServingQuantityInput(serving.quantity))
      && amountHasKnownGramWeight(serving)
      && Boolean(serving.unit.trim());
    const fallbackScalingAnchor = existingScalingAnchor?.unit === serving.unit
      ? existingScalingAnchor
      : currentIsValidAnchor
        ? { quantity: serving.quantity, unit: serving.unit, gramWeight: serving.gram_weight ?? "" }
        : null;

    // Real keyboards replace text through intermediate invalid values ("", "0", "0.").
    // Capture the last established current relationship before those events can overwrite it,
    // so a later valid count/custom value still scales from the correct grams-per-unit ratio.
    if (!unresolved && !existingScalingAnchor && fallbackScalingAnchor) {
      setCurrentScalingAnchors((current) => ({ ...current, [serving.key]: fallbackScalingAnchor }));
    }

    let nextGrams: string | null = null;
    if (quantity && !unresolved && serving.unit.trim()) {
      nextGrams = category === "count" || category === "custom"
        ? (fallbackScalingAnchor
            ? scaledCurrentGrams(fallbackScalingAnchor.quantity, fallbackScalingAnchor.gramWeight, quantity)
            : null)
        : exactCurrentGrams(quantity, serving.unit, reference)
          ?? (fallbackScalingAnchor
            ? scaledCurrentGrams(fallbackScalingAnchor.quantity, fallbackScalingAnchor.gramWeight, quantity)
            : null);
    }

    const resolvesReview = Boolean(quantity) && unresolved;
    const promotesReference = Boolean(quantity) && pendingReferencePromotion;
    const clearsReview = resolvesReview || promotesReference;
    const promotedReference = promotesReference && amountHasKnownGramWeight(serving)
      ? {
          reference_quantity: quantity!,
          reference_unit: serving.unit,
          reference_gram_weight: serving.gram_weight ?? "",
        }
      : commitReferenceFields(serving);
    updateServing(serving.key, {
      quantity: quantity ?? rawQuantity,
      ...(nextGrams ? { gram_weight: nextGrams } : {}),
      ...promotedReference,
      ...(clearsReview ? { consistencyWarning: undefined } : {}),
    });

    if (promotesReference && amountHasKnownGramWeight(serving)) {
      // A refused conversion has no mathematical relationship to the old reference. Once the
      // user supplies the missing quantity, that explicit unit/quantity/gram relationship becomes
      // the new stable reference for this serving.
      setCurrentScalingAnchors((current) => ({
        ...current,
        [serving.key]: { quantity: quantity!, unit: serving.unit, gramWeight: serving.gram_weight ?? "" },
      }));
      setReviewWarnings((current) => ({ ...current, [serving.key]: null }));
      setPendingReferencePromotions((current) => ({ ...current, [serving.key]: false }));
    } else if (clearsReview) {
      setReviewWarnings((current) => ({ ...current, [serving.key]: null }));
      setPendingReferencePromotions((current) => ({ ...current, [serving.key]: false }));
    }

    setPreservedVolumes((current) => (current[serving.key] ? { ...current, [serving.key]: null } : current));
  }

  function updateRepresentationUnit(serving: ServingFormValue, unit: string) {
    const reference = referenceOf(serving);
    const quantity = normalizeServingQuantityInput(serving.quantity) ?? serving.quantity;
    const transition = transitionServingUnit(
      {
        quantity,
        unit: serving.unit,
        gramWeight: serving.gram_weight ?? "",
        preservedVolume: preservedVolumes[serving.key] ?? currentVolumeAnchor(
          { quantity, unit: serving.unit, gramWeight: serving.gram_weight },
          reference,
        ),
      },
      unit,
    );

    if (transition.reviewWarning) {
      beginPendingEquivalence(serving, unit, transition.gramWeight);
      return;
    }

    // A defensible automatic conversion can commit immediately.
    setPendingEquivalences((current) => ({
      ...current,
      [serving.key]: undefined,
    }));

    updateServing(serving.key, {
      quantity: transition.quantity,
      unit,
      gram_weight: transition.gramWeight,
      ...commitReferenceFields(serving),
      consistencyWarning:
        serving.consistencyWarning === UNCONVERTED_SERVING_UNIT_WARNING
          ? undefined
          : serving.consistencyWarning,
    });

    setPreservedVolumes((current) => ({
      ...current,
      [serving.key]: transition.preservedVolume,
    }));
    setCurrentScalingAnchors((current) => ({
      ...current,
      [serving.key]: null,
    }));
    setReviewWarnings((current) => ({
      ...current,
      [serving.key]: null,
    }));
    setPendingReferencePromotions((current) => ({
      ...current,
      [serving.key]: false,
    }));
  }

  function removeServingClean(key: string) {
    setPendingEquivalences((current) => ({ ...current, [key]: undefined }));
    setPreservedVolumes((current) => ({ ...current, [key]: null }));
    setReviewWarnings((current) => ({ ...current, [key]: null }));
    setPendingReferencePromotions((current) => ({ ...current, [key]: false }));
    setCurrentScalingAnchors((current) => ({ ...current, [key]: null }));
    setReferenceDrafts((current) => ({ ...current, [key]: undefined }));
    removeServing(key);
  }

  return (
    <View style={styles.container}>
      {baseAmount ? (
        <View style={styles.baseRow}>
          <View style={styles.flex}>
            <Text style={styles.eyebrow}>Nutrition base</Text>
            <Text style={styles.baseValue}>100 g</Text>
          </View>
          <DefaultServingControl
            accessibilityLabel={baseAmount.is_default ? "Default amount" : "Set 100 grams as default amount"}
            disabled={false}
            isDefault={baseAmount.is_default}
            onPress={() => updateServing(baseAmount.key, { is_default: true })}
            styles={styles}
          />
        </View>
      ) : null}

      <Text accessibilityRole="header" style={styles.portionsTitle}>Custom serving sizes</Text>
      {portions.length === 0 ? <Text style={styles.meta}>No custom serving sizes yet.</Text> : null}

      {portions.map((serving) => {
        const expanded = serving.key === expandedKey;
        const confirmed = referenceConfirmed(serving);
        const draft = referenceDrafts[serving.key] ?? (confirmed ? undefined : draftFromServing(serving));
        const referenceEditing = draft !== undefined;
        const reference = referenceOf(serving);
        const automaticLabel = confirmed && serving.unit.trim() ? generatedAmountDisplayLabel(serving.quantity, serving.unit) : "";
        const displayLabel = serving.labelMode === "manual" && serving.label.trim()
          ? formatServingLabelForDisplay(serving.label.trim())
          : automaticLabel;
        const referenceLabel = referenceMeasurementLabel(reference);
        const showReferenceBasis = confirmed && !currentMatchesReference(serving, reference);
        const pendingEquivalence = pendingEquivalences[serving.key];
        const reviewWarning = activeReviewWarning(serving);
        const preview = servingPreview(
          serving,
          displayLabel,
          pendingEquivalence ? null : reviewWarning,
        );
        const reviewMessage = reviewWarning
          ? servingConversionReviewMessage(
              pendingEquivalence?.targetUnit ?? serving.unit,
              pendingEquivalence?.gramWeight ?? serving.gram_weight,
            )
          : null;
        const derivedPerUnit = confirmed && !reviewWarning
          ? derivedServingPerUnitText(serving.gram_weight, serving.quantity, serving.unit)
          : null;
        const pendingQuantity = pendingEquivalence
          ? normalizeServingQuantityInput(pendingEquivalence.quantity)
          : null;
        const pendingDisplayLabel = pendingEquivalence && pendingQuantity
          ? generatedAmountDisplayLabel(pendingQuantity, pendingEquivalence.targetUnit)
          : "";
        const representationPreview = pendingEquivalence
          ? pendingDisplayLabel && amountHasKnownGramWeight({ gram_weight: pendingEquivalence.gramWeight })
            ? `${pendingDisplayLabel} (${formatServingGramForDisplay(pendingEquivalence.gramWeight)} g)`
            : "Enter the equivalent quantity to preview this serving size."
          : preview;
        const representationDerivedPerUnit = pendingEquivalence && pendingQuantity
          ? derivedServingPerUnitText(
              pendingEquivalence.gramWeight,
              pendingQuantity,
              pendingEquivalence.targetUnit,
            )
          : derivedPerUnit;
        const unitFocus = focusProps(servingFocusKey(serving.key, "unit"));
        return (
          <View key={serving.key} style={styles.portionCard}>
            <View style={styles.summaryRow}>
              <View style={styles.flex}>
                <Text accessibilityRole="header" style={styles.summaryTitle}>{displayLabel || "New serving size"}</Text>
                {showReferenceBasis ? (
                  <Text style={styles.meta}>{`Based on: ${referenceLabel}`}</Text>
                ) : null}
                <Text style={styles.meta}>{servingWeightSummary(serving, pendingEquivalence ? null : reviewWarning)}</Text>
              </View>
              <DefaultServingControl
                accessibilityLabel={serving.is_default ? "Default amount" : `Set ${displayLabel || "serving size"} as default`}
                disabled={!serving.is_default && !amountHasKnownGramWeight(serving)}
                isDefault={serving.is_default}
                onPress={() => updateServing(serving.key, { is_default: true })}
                styles={styles}
              />
            </View>

            {serving.consistencyWarning
              && serving.consistencyWarning !== UNCONVERTED_SERVING_UNIT_WARNING
              && serving.consistencyWarning !== reviewWarning ? (
              <Text style={styles.warning}>{serving.consistencyWarning}</Text>
            ) : null}
            {reviewMessage ? (
              <View
                accessible
                accessibilityLabel={`Equivalent measurement needed. ${reviewMessage}`}
                style={styles.equivalenceNotice}
              >
                <Text style={styles.equivalenceTitle}>Equivalent measurement needed</Text>
                <Text style={styles.meta}>{reviewMessage}</Text>
              </View>
            ) : null}

            {expanded ? (
              <View style={styles.editor}>
                {referenceEditing && draft ? (
                  <View style={styles.referenceEditor}>
                    <Text accessibilityRole="header" style={styles.fieldLabel}>Reference measurement</Text>
                    <Text style={styles.meta}>Enter a measured food-specific relationship, for example 1 cup = 100 g. Compatible units can then scale from this reference. If the current unit is from a different dimension, confirming the new reference makes that explicit relationship authoritative.</Text>

                    <View style={styles.twoColumn}>
                      <LabeledField
                        containerStyle={styles.flex}
                        label="Reference quantity"
                        validationTarget={`serving.${serving.key}.quantity`}
                        {...focusProps(servingFocusKey(serving.key, "quantity"))}
                        value={draft.quantity}
                        onChangeText={(quantity) => updateReferenceDraft(serving, { quantity })}
                        keyboardType="numbers-and-punctuation"
                        placeholder="e.g. 1"
                        placeholderTextColor={theme.colors.placeholder}
                        inputStyle={styles.input}
                        hint="Enter a decimal, fraction, or mixed fraction, such as 1 1/2."
                      />
                      <ServingUnitPicker
                        value={draft.unit}
                        onChange={(unit) => updateReferenceDraft(serving, { unit })}
                        accessibilityLabel="Reference unit"
                        contextLabel="reference measurement"
                        containerStyle={styles.flex}
                      />
                    </View>

                    <LabeledField
                      label="Reference grams"
                      validationTarget={`serving.${serving.key}.gramWeight`}
                      {...focusProps(servingFocusKey(serving.key, "gramWeight"))}
                      value={draft.gramWeight}
                      onChangeText={(gramWeight) => updateReferenceDraft(serving, { gramWeight })}
                      keyboardType="decimal-pad"
                      placeholder="e.g. 100"
                      placeholderTextColor={theme.colors.placeholder}
                      inputStyle={styles.input}
                      hint="Total gram weight of the reference amount."
                    />

                    <View style={styles.actions}>
                      <AccessiblePressable
                        accessibilityLabel="Confirm reference measurement"
                        disabled={!referenceDraftValid(draft)}
                        onPress={() => confirmReference(serving)}
                        style={[styles.compactButton, !referenceDraftValid(draft) && styles.disabled]}
                      >
                        <Text style={styles.link}>Confirm</Text>
                      </AccessiblePressable>
                      {confirmed ? (
                        <AccessiblePressable
                          accessibilityLabel="Cancel editing reference measurement"
                          onPress={() => cancelReferenceEdit(serving)}
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
                      <Text style={styles.referenceValue}>{referenceLabel}</Text>
                    </View>
                    {!pendingEquivalence ? (
                      <AccessiblePressable
                        accessibilityLabel="Edit reference measurement"
                        onPress={() => editReference(serving)}
                        style={styles.compactButton}
                      >
                        <Text style={styles.link}>Edit</Text>
                      </AccessiblePressable>
                    ) : null}
                  </View>
                )}

                {confirmed ? (
                  <View style={styles.representationEditor}>
                    <Text style={styles.meta}>
                      {pendingEquivalence
                        ? "The current serving stays unchanged while you type. Confirm once the equivalent amount is complete, or cancel to keep the current relationship."
                        : "Change how this serving is shown. Compatible units convert automatically. Different dimensions require an explicit food-specific equivalence."}
                    </Text>

                    <View style={styles.twoColumn}>
                      <LabeledField
                        containerStyle={styles.flex}
                        label={pendingEquivalence ? "Equivalent quantity" : "Quantity"}
                        validationTarget={`serving.${serving.key}.quantity`}
                        {...focusProps(servingFocusKey(serving.key, "quantity"))}
                        value={pendingEquivalence?.quantity ?? serving.quantity}
                        onChangeText={(quantity) => updateRepresentationQuantity(serving, quantity)}
                        keyboardType="numbers-and-punctuation"
                        placeholder="e.g. 2"
                        placeholderTextColor={theme.colors.placeholder}
                        inputStyle={styles.input}
                        hint={pendingEquivalence
                          ? `Enter the complete ${pendingEquivalence.targetUnit} amount. Typing does not change the current serving until you confirm.`
                          : "Editing the quantity authors a new amount for this serving."}
                      />
                      <ServingUnitPicker
                        value={pendingEquivalence?.targetUnit ?? serving.unit}
                        onChange={(unit) => updateRepresentationUnit(serving, unit)}
                        contextLabel={
                          pendingEquivalence
                            ? `equivalent ${pendingEquivalence.targetUnit} measurement`
                            : displayLabel || "serving size"
                        }
                        containerStyle={styles.flex}
                        focusRef={unitFocus.ref}
                        onFocus={unitFocus.onFocus}
                      />
                    </View>

                    {!serving.is_default && !amountHasKnownGramWeight(serving) && defaultAmountError?.key !== serving.key
                      ? <Text style={styles.fieldError}>{DEFAULT_AMOUNT_WEIGHT_MESSAGE}</Text>
                      : null}

                    <View style={styles.previewCard}>
                      <Text style={styles.fieldLabel}>Will appear as</Text>
                      <Text style={styles.previewText}>{representationPreview}</Text>
                      {representationDerivedPerUnit ? (
                        <Text style={styles.meta}>{representationDerivedPerUnit}</Text>
                      ) : null}
                    </View>

                    {pendingEquivalence ? (
                      <View style={styles.actions}>
                        <AccessiblePressable
                          accessibilityLabel="Cancel equivalent measurement"
                          accessibilityHint="Discards this unit change and keeps the current serving relationship."
                          onPress={() => cancelPendingEquivalence(serving)}
                          style={styles.compactButton}
                        >
                          <Text style={styles.link}>Cancel</Text>
                        </AccessiblePressable>

                        <AccessiblePressable
                          accessibilityLabel="Confirm equivalent measurement"
                          accessibilityHint={`Confirms that ${pendingEquivalence.quantity || "this amount"} ${pendingEquivalence.targetUnit} equals ${formatServingGramForDisplay(pendingEquivalence.gramWeight)} grams for this Food.`}
                          disabled={
                            !pendingQuantity
                            || !amountHasKnownGramWeight({
                              gram_weight: pendingEquivalence.gramWeight,
                            })
                          }
                          onPress={() => confirmPendingEquivalence(serving)}
                          style={[
                            styles.compactButton,
                            (!pendingQuantity
                              || !amountHasKnownGramWeight({
                                gram_weight: pendingEquivalence.gramWeight,
                              }))
                              && styles.disabled,
                          ]}
                        >
                          <Text style={styles.link}>Confirm</Text>
                        </AccessiblePressable>
                      </View>
                    ) : null}
                  </View>
                ) : null}

                {serving.labelMode === "manual" ? (
                  <View>
                    <View style={styles.labelHeader}>
                      <Text style={styles.fieldLabel}>Custom display name</Text>
                      <AccessiblePressable accessibilityLabel={`Use automatic label for ${displayLabel || "serving size"}`} onPress={() => updateServing(serving.key, { labelMode: "automatic", label: generatedAmountLabel(serving.quantity, serving.unit) })}>
                        <Text style={styles.link}>Use automatic</Text>
                      </AccessiblePressable>
                    </View>
                    <LabeledField
                      label="Custom display name"
                      validationTarget={`serving.${serving.key}.label`}
                      {...focusProps(servingFocusKey(serving.key, "label"))}
                      value={serving.label}
                      onChangeText={(label) => updateServing(serving.key, { label, labelMode: "manual" })}
                      placeholder={serving.quantity && serving.unit ? `e.g. ${generatedAmountDisplayLabel(serving.quantity, serving.unit)}, thick-cut` : "Custom display name"}
                      placeholderTextColor={theme.colors.placeholder}
                      inputStyle={styles.input}
                    />
                  </View>
                ) : (
                  <AccessiblePressable
                    accessibilityLabel={`Customize label for ${displayLabel || "serving size"}`}
                    onPress={() => updateServing(serving.key, { labelMode: "manual", label: generatedAmountLabel(serving.quantity, serving.unit) })}
                    style={styles.compactLink}
                  >
                    <Text style={styles.link}>Customize display name</Text>
                  </AccessiblePressable>
                )}

                <View style={styles.actions}>
                  <ServingManagementAction accessibilityLabel={`Remove ${displayLabel || "serving size"}`} onPress={() => removeServingClean(serving.key)} styles={styles}>
                    <Text style={styles.removeText}>Remove</Text>
                  </ServingManagementAction>
                  <ServingManagementAction
                    accessibilityLabel={`Finish editing ${displayLabel || "serving size"}`}
                    accessibilityState={{ expanded: true }}
                    onPress={() => setExpandedKey(null)}
                    styles={styles}
                  >
                    <Text style={styles.link}>Done</Text>
                  </ServingManagementAction>
                </View>
              </View>
            ) : (
              <View style={styles.actions}>
                <ServingManagementAction accessibilityLabel={`Edit ${displayLabel || "serving size"}`} accessibilityState={{ expanded: false }} onPress={() => openEditor(serving)} styles={styles}>
                  <Text style={styles.link}>Edit</Text>
                </ServingManagementAction>
                <ServingManagementAction accessibilityLabel={`Remove ${displayLabel || "serving size"}`} onPress={() => removeServingClean(serving.key)} styles={styles}>
                  <Text style={styles.removeText}>Remove</Text>
                </ServingManagementAction>
              </View>
            )}
          </View>
        );
      })}

      <AccessiblePressable
        accessibilityLabel="Add serving size"
        accessibilityHint="Adds and expands a new serving size"
        onPress={() => setExpandedKey(addServing())}
        style={styles.addButton}
      >
        <Text style={styles.addText}>Add serving size</Text>
      </AccessiblePressable>
    </View>
  );
}

function commitReferenceFields(serving: ServingFormValue) {
  const hasAnyReference = serving.reference_quantity != null
    || serving.reference_unit != null
    || serving.reference_gram_weight != null;
  const hasCompleteReference = serving.reference_quantity != null
    && Boolean(serving.reference_unit?.trim())
    && serving.reference_gram_weight != null;
  if (hasCompleteReference || hasAnyReference) return {};
  const quantity = normalizeServingQuantityInput(serving.quantity);
  if (!quantity || !serving.unit.trim() || !amountHasKnownGramWeight(serving)) return {};
  return {
    reference_quantity: quantity,
    reference_unit: serving.unit.trim(),
    reference_gram_weight: serving.gram_weight ?? null,
  };
}

function draftFromServing(serving: ServingFormValue): ReferenceDraft {
  return {
    quantity: compactExactDecimalForEditing(serving.reference_quantity ?? serving.quantity),
    unit: serving.reference_unit ?? serving.unit,
    gramWeight: compactExactDecimalForEditing(serving.reference_gram_weight ?? serving.gram_weight ?? ""),
  };
}

function referenceDraftValid(draft: ReferenceDraft): boolean {
  return Boolean(normalizeServingQuantityInput(draft.quantity)) && Boolean(draft.unit.trim()) && Number(draft.gramWeight) > 0 && Number.isFinite(Number(draft.gramWeight));
}

function servingPreview(
  serving: ServingFormValue,
  displayLabel: string,
  reviewWarning: string | null,
): string {
  if (!displayLabel) {
    return reviewWarning
      ? "Enter the equivalent quantity to preview this serving size."
      : "Enter a reference measurement to preview this serving size.";
  }
  if (!amountHasKnownGramWeight(serving)) return displayLabel;
  return `${displayLabel} (${formatServingGramForDisplay(serving.gram_weight ?? "")} g)`;
}

function servingWeightSummary(serving: ServingFormValue, reviewWarning: string | null): string {
  if (!amountHasKnownGramWeight(serving)) return "Gram weight not set";
  const displayTotal = formatServingGramForDisplay(serving.gram_weight ?? "");
  if (amountUnitCategory(serving.unit) === "weight") return `${displayTotal} g total`;
  if (reviewWarning) return `${displayTotal} g total`;
  const perUnit = derivedServingPerUnitText(serving.gram_weight, serving.quantity, serving.unit);
  if (perUnit) return `${perUnit} · ${displayTotal} g total`;
  return `${displayTotal} g total`;
}

function DefaultServingControl({ accessibilityLabel, disabled, isDefault, onPress, styles }: {
  accessibilityLabel: string;
  disabled: boolean;
  isDefault: boolean;
  onPress: () => void;
  styles: ReturnType<typeof createStyles>;
}) {
  if (isDefault) {
    return (
      <View
        accessible
        accessibilityLabel={accessibilityLabel}
        accessibilityRole="text"
        accessibilityState={{ selected: true }}
        style={styles.defaultControl}
      >
        <View style={[styles.defaultControlSurface, styles.defaultControlSurfaceSelected]}>
          <Text style={styles.defaultControlSelectedText}>✓ Default</Text>
        </View>
      </View>
    );
  }
  return (
    <AccessiblePressable
      accessibilityLabel={accessibilityLabel}
      accessibilityState={{ selected: false }}
      disabled={disabled}
      onPress={onPress}
      style={styles.defaultControl}
    >
      <View style={styles.defaultControlSurface}>
        <Text style={styles.defaultControlText}>Set default</Text>
      </View>
    </AccessiblePressable>
  );
}

function ServingManagementAction({ accessibilityLabel, accessibilityState, children, onPress, styles }: {
  accessibilityLabel: string;
  accessibilityState?: { expanded?: boolean; selected?: boolean };
  children: ReactNode;
  onPress: () => void;
  styles: ReturnType<typeof createStyles>;
}) {
  return (
    <AccessiblePressable accessibilityLabel={accessibilityLabel} accessibilityState={accessibilityState} onPress={onPress} style={styles.managementTarget}>
      <View style={styles.managementSurface}>{children}</View>
    </AccessiblePressable>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    text: { color: theme.colors.text },
    addButton: { alignItems: "center", borderColor: theme.colors.accent, borderRadius: 6, borderWidth: 1, minHeight: 44, paddingHorizontal: 10, paddingVertical: 10 },
    addText: { color: theme.colors.accent, fontWeight: "700" },
    actions: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
    baseRow: { alignItems: "center", backgroundColor: theme.colors.secondarySurface, borderColor: theme.colors.border, borderRadius: 8, borderWidth: 1, flexDirection: "row", flexWrap: "wrap", gap: 8, padding: 12 },
    baseValue: { color: theme.colors.text, fontSize: 16, fontWeight: "700" },
    compactButton: { alignItems: "center", borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, justifyContent: "center", minHeight: 44, paddingHorizontal: 12, paddingVertical: 8 },
    compactLink: { alignSelf: "flex-start", minHeight: 44, justifyContent: "center" },
    container: { gap: 10 },
    defaultControl: { alignItems: "center", justifyContent: "center", minHeight: 44, minWidth: 96 },
    defaultControlSurface: { alignItems: "center", borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, justifyContent: "center", minHeight: 36, minWidth: 96, paddingHorizontal: 12, paddingVertical: 8 },
    defaultControlSurfaceSelected: { backgroundColor: theme.colors.activeBackground, borderColor: theme.colors.accent },
    defaultControlSelectedText: { color: theme.colors.accent, fontWeight: "700" },
    defaultControlText: { color: theme.colors.text },
    disabled: { opacity: 0.55 },
    editor: { borderTopColor: theme.colors.border, borderTopWidth: 1, gap: 12, paddingTop: 12 },
    equivalenceNotice: {
      backgroundColor: theme.colors.secondarySurface,
      borderColor: theme.colors.border,
      borderRadius: 6,
      borderWidth: 1,
      gap: 4,
      padding: 10,
    },
    equivalenceTitle: { color: theme.colors.text, fontSize: 13, fontWeight: "700" },
    eyebrow: { color: theme.colors.secondaryText, fontSize: 12, fontWeight: "700", textTransform: "uppercase" },
    fieldError: { color: theme.colors.errorText, fontSize: 13 },
    fieldLabel: { color: theme.colors.secondaryText, fontSize: 13, fontWeight: "700", marginBottom: 5 },
    flex: { flex: 1, minWidth: 140 },
    input: { backgroundColor: theme.colors.input, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, color: theme.colors.text, fontSize: 16, minHeight: 44, paddingHorizontal: 10, paddingVertical: 10 },
    labelHeader: { alignItems: "center", flexDirection: "row", flexWrap: "wrap", gap: 8, justifyContent: "space-between" },
    link: { color: theme.colors.accent, fontWeight: "700" },
    managementSurface: { alignItems: "center", borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, justifyContent: "center", minHeight: 36, paddingHorizontal: 12, paddingVertical: 8 },
    managementTarget: { alignItems: "center", justifyContent: "center", minHeight: 44 },
    meta: { color: theme.colors.secondaryText, fontSize: 13 },
    portionCard: { backgroundColor: theme.colors.surface, borderColor: theme.colors.border, borderRadius: 8, borderWidth: 1, gap: 8, padding: 12 },
    portionsTitle: { color: theme.colors.text, fontSize: 17, fontWeight: "700", marginTop: 4 },
    previewCard: { backgroundColor: theme.colors.secondarySurface, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, padding: 10 },
    previewText: { color: theme.colors.text, fontSize: 16, fontWeight: "700" },
    referenceEditor: { backgroundColor: theme.colors.secondarySurface, borderColor: theme.colors.border, borderRadius: 8, borderWidth: 1, gap: 10, padding: 10 },
    referenceRow: { alignItems: "center", backgroundColor: theme.colors.secondarySurface, borderColor: theme.colors.border, borderRadius: 8, borderWidth: 1, flexDirection: "row", flexWrap: "wrap", gap: 8, padding: 10 },
    referenceValue: { color: theme.colors.text, fontSize: 16, fontWeight: "700" },
    removeText: { color: theme.colors.destructive, fontWeight: "600" },
    representationEditor: { gap: 12 },
    summaryRow: { alignItems: "center", flexDirection: "row", flexWrap: "wrap", gap: 8 },
    summaryTitle: { color: theme.colors.text, fontSize: 16, fontWeight: "700" },
    twoColumn: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
    warning: { color: theme.colors.warningText, fontSize: 13 },
  });
}
