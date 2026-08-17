import {
  applyAmountPatch,
  generatedAmountDisplayLabel,
  servingConversionReviewMessage,
  transitionServingUnit,
  UNCONVERTED_SERVING_UNIT_WARNING,
  type AmountFormValue,
  type PreservedVolumeServing,
} from "../src/features/foods/utils/amountForm";

const cupServing = { quantity: "1.5", unit: "cup", gramWeight: "208" };

test("weight -> weight preserves total grams and derives the new quantity from them", () => {
  const toOunces = transitionServingUnit({ quantity: "208", unit: "g", gramWeight: "208" }, "oz");
  expect(toOunces).toEqual({
    quantity: "7.34",
    unit: "oz",
    gramWeight: "208",
    perUnit: "28.349523125",
    preservedVolume: null,
    reviewWarning: null,
    converted: true,
  });

  const backToGrams = transitionServingUnit({ quantity: toOunces.quantity, unit: "oz", gramWeight: toOunces.gramWeight }, "g");
  expect(backToGrams.quantity).toBe("208");
  expect(backToGrams.gramWeight).toBe("208");
  expect(backToGrams.converted).toBe(true);

  expect(transitionServingUnit({ quantity: "208", unit: "g", gramWeight: "208" }, "lb").quantity).toBe("0.46");
  expect(transitionServingUnit({ quantity: "208", unit: "g", gramWeight: "208" }, "kg").quantity).toBe("0.21");
});

test("repeated weight conversions derive from preserved grams and do not drift", () => {
  let state = { quantity: "208", unit: "g", gramWeight: "208" };
  for (let hop = 0; hop < 5; hop += 1) {
    state = transitionServingUnit(state, "oz");
    expect(state.gramWeight).toBe("208");
    state = transitionServingUnit(state, "g");
    expect(state.gramWeight).toBe("208");
    expect(state.quantity).toBe("208");
  }
});

test("weight servings without explicit grams keep the exact derived anchor, not the rounded quantity", () => {
  const toGrams = transitionServingUnit({ quantity: "0.5", unit: "oz", gramWeight: "" }, "g");
  expect(toGrams.quantity).toBe("14");
  expect(toGrams.gramWeight).toBe("14.174762");
  expect(toGrams.perUnit).toBe("1");

  const backToOunces = transitionServingUnit(
    { quantity: toGrams.quantity, unit: "g", gramWeight: toGrams.gramWeight },
    "oz",
  );
  expect(backToOunces.quantity).toBe("0.5");
  expect(backToOunces.gramWeight).toBe("14.174762");

  let state = { quantity: "0.5", unit: "oz", gramWeight: "" };
  for (let hop = 0; hop < 5; hop += 1) {
    state = transitionServingUnit(state, "g");
    expect(state.gramWeight).toBe("14.174762");
    expect(state.quantity).toBe("14");
    state = transitionServingUnit(state, "oz");
    expect(state.gramWeight).toBe("14.174762");
    expect(state.quantity).toBe("0.5");
  }
});

test("small weight servings separate the practical quantity from the authoritative grams", () => {
  const toGrams = transitionServingUnit({ quantity: "0.05", unit: "oz", gramWeight: "" }, "g");
  expect(toGrams.quantity).toBe("1");
  expect(toGrams.gramWeight).toBe("1.417476");

  const backToOunces = transitionServingUnit(
    { quantity: toGrams.quantity, unit: "g", gramWeight: toGrams.gramWeight },
    "oz",
  );
  expect(backToOunces.quantity).toBe("0.05");
  expect(backToOunces.gramWeight).toBe("1.417476");

  const smallKilograms = transitionServingUnit({ quantity: "0.125", unit: "kg", gramWeight: "" }, "g");
  expect(smallKilograms.quantity).toBe("125");
  expect(smallKilograms.gramWeight).toBe("125");
});

test("volume -> volume converts deterministically and preserves known grams", () => {
  const toTbsp = transitionServingUnit(cupServing, "tbsp");
  expect(toTbsp.quantity).toBe("24");
  expect(toTbsp.gramWeight).toBe("208");
  expect(toTbsp.converted).toBe(true);
  expect(toTbsp.preservedVolume).toEqual({ quantity: "1.5", unit: "cup" });

  const backToCup = transitionServingUnit(
    { quantity: toTbsp.quantity, unit: "tbsp", gramWeight: "208", preservedVolume: toTbsp.preservedVolume },
    "cup",
  );
  expect(backToCup.quantity).toBe("1.5");
  expect(backToCup.gramWeight).toBe("208");
  expect(backToCup.perUnit).toBe("138.666667");
});

test("rounded volume conversions restore from the preserved anchor instead of drifting", () => {
  const toTbsp = transitionServingUnit({ quantity: "0.5", unit: "tsp", gramWeight: "2.5" }, "tbsp");
  expect(toTbsp.quantity).toBe("0.17");
  expect(toTbsp.preservedVolume).toEqual({ quantity: "0.5", unit: "tsp" });
  const backToTsp = transitionServingUnit(
    { quantity: toTbsp.quantity, unit: "tbsp", gramWeight: "2.5", preservedVolume: toTbsp.preservedVolume },
    "tsp",
  );
  expect(backToTsp.quantity).toBe("0.5");
  expect(backToTsp.gramWeight).toBe("2.5");

  const quarter = transitionServingUnit({ quantity: "0.25", unit: "tsp", gramWeight: "1.25" }, "tbsp");
  expect(quarter.quantity).toBe("0.08");
  expect(transitionServingUnit(
    { quantity: quarter.quantity, unit: "tbsp", gramWeight: "1.25", preservedVolume: quarter.preservedVolume },
    "tsp",
  ).quantity).toBe("0.25");
});

test("multi-hop volume conversions keep deriving from the same anchor without drift", () => {
  let state: { quantity: string; unit: string; gramWeight: string; preservedVolume: PreservedVolumeServing | null } = {
    quantity: "0.5", unit: "tsp", gramWeight: "2.5", preservedVolume: null,
  };
  state = transitionServingUnit(state, "ml");
  expect(state.quantity).toBe("2");
  state = transitionServingUnit(state, "tbsp");
  expect(state.quantity).toBe("0.17");
  state = transitionServingUnit(state, "cup");
  expect(state.quantity).toBe("0.01");
  state = transitionServingUnit(state, "tsp");
  expect(state.quantity).toBe("0.5");
  expect(state.gramWeight).toBe("2.5");
  expect(state.preservedVolume).toEqual({ quantity: "0.5", unit: "tsp" });
});

test("leaving volume keeps the older anchor instead of the rounded quantity", () => {
  const toTbsp = transitionServingUnit({ quantity: "0.5", unit: "tsp", gramWeight: "2.5" }, "tbsp");
  const toOunces = transitionServingUnit(
    { quantity: toTbsp.quantity, unit: "tbsp", gramWeight: "2.5", preservedVolume: toTbsp.preservedVolume },
    "oz",
  );
  expect(toOunces.quantity).toBe("0.09");
  expect(toOunces.preservedVolume).toEqual({ quantity: "0.5", unit: "tsp" });
  const restored = transitionServingUnit(
    { quantity: toOunces.quantity, unit: "oz", gramWeight: "2.5", preservedVolume: toOunces.preservedVolume },
    "tsp",
  );
  expect(restored.quantity).toBe("0.5");
  expect(restored.gramWeight).toBe("2.5");
});

type AnchoredServingState = { quantity: string; unit: string; gramWeight: string; preservedVolume: PreservedVolumeServing | null };

test("re-entering volume through a different unit keeps the anchor until a verbatim restore", () => {
  // A: 0.5 tsp -> Tbsp -> oz -> cup -> tsp restores exactly, with no drift from 0.01 cup.
  let state: AnchoredServingState = { quantity: "0.5", unit: "tsp", gramWeight: "2.5", preservedVolume: null };
  state = transitionServingUnit(state, "tbsp");
  expect(state.quantity).toBe("0.17");
  state = transitionServingUnit(state, "oz");
  expect(state.quantity).toBe("0.09");
  state = transitionServingUnit(state, "cup");
  expect(state.quantity).toBe("0.01");
  // C: the original anchor survives the oz -> cup re-entry.
  expect(state.preservedVolume).toEqual({ quantity: "0.5", unit: "tsp" });
  // D: the subsequent cup -> tsp restore is verbatim.
  state = transitionServingUnit(state, "tsp");
  expect(state.quantity).toBe("0.5");
  expect(state.gramWeight).toBe("2.5");
  expect(state.preservedVolume).toEqual({ quantity: "0.5", unit: "tsp" });

  // B: 0.25 tsp -> oz -> Tbsp -> tsp restores 0.25.
  let quarter: AnchoredServingState = { quantity: "0.25", unit: "tsp", gramWeight: "1.25", preservedVolume: null };
  quarter = transitionServingUnit(quarter, "oz");
  expect(quarter.quantity).toBe("0.04");
  quarter = transitionServingUnit(quarter, "tbsp");
  expect(quarter.quantity).toBe("0.08");
  quarter = transitionServingUnit(quarter, "tsp");
  expect(quarter.quantity).toBe("0.25");
  expect(quarter.gramWeight).toBe("1.25");
});

test("a verbatim re-entry into the anchor unit consumes the transient anchor", () => {
  // E: 0.5 tsp -> oz -> tsp restores verbatim and clears the anchor.
  let state: AnchoredServingState = { quantity: "0.5", unit: "tsp", gramWeight: "2.5", preservedVolume: null };
  state = transitionServingUnit(state, "oz");
  state = transitionServingUnit(state, "tsp");
  expect(state.quantity).toBe("0.5");
  expect(state.gramWeight).toBe("2.5");
  expect(state.preservedVolume).toBeNull();
});

test("a manually edited quantity replaces the volume anchor on the next transition", () => {
  // The editor clears the anchor when the user edits the quantity; the edited value is the
  // new authored representation and later conversions derive from it, not the stale one.
  const manual = transitionServingUnit({ quantity: "0.3", unit: "tbsp", gramWeight: "5" }, "tsp");
  expect(manual.preservedVolume).toEqual({ quantity: "0.3", unit: "tbsp" });
  expect(manual.quantity).toBe("0.9");
});

test("volume -> weight derives the weight quantity from known grams, not the volume number", () => {
  const toOunces = transitionServingUnit(cupServing, "oz");
  expect(toOunces.quantity).toBe("7.34");
  expect(toOunces.gramWeight).toBe("208");
  expect(toOunces.converted).toBe(true);
  expect(toOunces.preservedVolume).toEqual({ quantity: "1.5", unit: "cup" });
});

test("weight -> volume restores a preserved volume representation instead of clearing grams", () => {
  const preserved: PreservedVolumeServing = { quantity: "1.5", unit: "cup" };
  const restored = transitionServingUnit({ quantity: "7.336984", unit: "oz", gramWeight: "208", preservedVolume: preserved }, "cup");
  expect(restored.quantity).toBe("1.5");
  expect(restored.gramWeight).toBe("208");
  expect(restored.perUnit).toBe("138.666667");
  expect(restored.preservedVolume).toBeNull();
  expect(restored.converted).toBe(true);

  const detoured = transitionServingUnit(cupServing, "piece");
  expect(detoured.preservedVolume).toEqual({ quantity: "1.5", unit: "cup" });
  const restoredFromCount = transitionServingUnit(
    { quantity: detoured.quantity, unit: "piece", gramWeight: detoured.gramWeight, preservedVolume: detoured.preservedVolume },
    "cup",
  );
  expect(restoredFromCount.quantity).toBe("1.5");
  expect(restoredFromCount.gramWeight).toBe("208");
});

test("weight -> volume without a known volume relationship refuses conversion and keeps grams", () => {
  const refused = transitionServingUnit({ quantity: "208", unit: "g", gramWeight: "208" }, "cup");
  expect(refused.converted).toBe(false);
  expect(refused.quantity).toBe("");
  expect(refused.gramWeight).toBe("208");
  expect(refused.perUnit).toBe("");
  expect(refused.reviewWarning).toBe(UNCONVERTED_SERVING_UNIT_WARNING);
});

test("weight or volume -> count/custom never fabricates a conversion and never erases grams", () => {
  const fromWeight = transitionServingUnit({ quantity: "7.336984", unit: "oz", gramWeight: "208" }, "piece");
  expect(fromWeight).toEqual({
    quantity: "",
    unit: "piece",
    gramWeight: "208",
    perUnit: "",
    preservedVolume: null,
    reviewWarning: UNCONVERTED_SERVING_UNIT_WARNING,
    converted: false,
  });

  const fromVolume = transitionServingUnit(cupServing, "scoop");
  expect(fromVolume.converted).toBe(false);
  expect(fromVolume.quantity).toBe("");
  expect(fromVolume.gramWeight).toBe("208");
  expect(fromVolume.preservedVolume).toEqual({ quantity: "1.5", unit: "cup" });
});

test("count/custom -> weight derives from known grams; -> volume or other count units refuses", () => {
  const toWeight = transitionServingUnit({ quantity: "5", unit: "piece", gramWeight: "208" }, "oz");
  expect(toWeight.quantity).toBe("7.34");
  expect(toWeight.gramWeight).toBe("208");
  expect(toWeight.converted).toBe(true);

  const toVolume = transitionServingUnit({ quantity: "5", unit: "piece", gramWeight: "208" }, "cup");
  expect(toVolume.converted).toBe(false);
  expect(toVolume.quantity).toBe("");
  expect(toVolume.gramWeight).toBe("208");
  expect(toVolume.reviewWarning).toBe(UNCONVERTED_SERVING_UNIT_WARNING);
});

test("distinct count/custom units are unresolved renames, never equivalent conversions", () => {
  const pieceToSlice = transitionServingUnit({ quantity: "5", unit: "piece", gramWeight: "208" }, "slice");
  expect(pieceToSlice.converted).toBe(false);
  expect(pieceToSlice.quantity).toBe("");
  expect(pieceToSlice.gramWeight).toBe("208");
  expect(pieceToSlice.perUnit).toBe("");
  expect(pieceToSlice.reviewWarning).toBe(UNCONVERTED_SERVING_UNIT_WARNING);

  const scoopToBowl = transitionServingUnit({ quantity: "2", unit: "scoop", gramWeight: "30" }, "bowl");
  expect(scoopToBowl.converted).toBe(false);
  expect(scoopToBowl.quantity).toBe("");
  expect(scoopToBowl.gramWeight).toBe("30");
  expect(scoopToBowl.reviewWarning).toBe(UNCONVERTED_SERVING_UNIT_WARNING);

  const pieceToCustom = transitionServingUnit({ quantity: "5", unit: "piece", gramWeight: "208" }, "scoop");
  expect(pieceToCustom.converted).toBe(false);
  expect(pieceToCustom.reviewWarning).toBe(UNCONVERTED_SERVING_UNIT_WARNING);

  const customToPiece = transitionServingUnit({ quantity: "2", unit: "scoop", gramWeight: "30" }, "piece");
  expect(customToPiece.converted).toBe(false);
  expect(customToPiece.quantity).toBe("");
  expect(customToPiece.gramWeight).toBe("30");
  expect(customToPiece.reviewWarning).toBe(UNCONVERTED_SERVING_UNIT_WARNING);

  const sameUnit = transitionServingUnit({ quantity: "2", unit: "scoop", gramWeight: "30" }, "scoop");
  expect(sameUnit.reviewWarning).toBeNull();
  expect(sameUnit.converted).toBe(false);
  expect(sameUnit.quantity).toBe("2");
});

test("volume -> weight without known grams refuses instead of assuming a density", () => {
  const refused = transitionServingUnit({ quantity: "2", unit: "cup", gramWeight: "" }, "oz");
  expect(refused.converted).toBe(false);
  expect(refused.quantity).toBe("");
  expect(refused.gramWeight).toBe("");
  expect(refused.reviewWarning).toBe(UNCONVERTED_SERVING_UNIT_WARNING);
});

test("automatic labels follow the practically rounded converted quantity", () => {
  const toOunces = transitionServingUnit(cupServing, "oz");
  expect(toOunces.quantity).toBe("7.34");
  expect(generatedAmountDisplayLabel(toOunces.quantity, "oz")).toBe("7.34 oz");
});

test("converted quantities use unit-aware practical precision with trailing zeros removed", () => {
  expect(transitionServingUnit({ quantity: "56.699046", unit: "g", gramWeight: "56.699046" }, "oz").quantity).toBe("2");
  expect(transitionServingUnit({ quantity: "7.34", unit: "oz", gramWeight: "208" }, "g").quantity).toBe("208");
  expect(transitionServingUnit({ quantity: "208", unit: "g", gramWeight: "208" }, "kg").quantity).toBe("0.21");
  expect(transitionServingUnit(cupServing, "ml").quantity).toBe("355");
  expect(transitionServingUnit(cupServing, "l").quantity).toBe("0.35");
  expect(transitionServingUnit(cupServing, "fl oz").quantity).toBe("12");
  expect(transitionServingUnit(cupServing, "tbsp").quantity).toBe("24");
  expect(transitionServingUnit({ quantity: "0.5", unit: "cup", gramWeight: "69" }, "tsp").quantity).toBe("24");

  const toMilliliters = transitionServingUnit(cupServing, "ml");
  expect(toMilliliters.gramWeight).toBe("208");
  expect(toMilliliters.preservedVolume).toEqual({ quantity: "1.5", unit: "cup" });
  const backToCups = transitionServingUnit(
    { quantity: toMilliliters.quantity, unit: "ml", gramWeight: "208", preservedVolume: toMilliliters.preservedVolume },
    "cup",
  );
  expect(backToCups.quantity).toBe("1.5");
  expect(backToCups.gramWeight).toBe("208");
});

test("practical precision applies only to generated conversions; refused unit changes clear stale source quantities", () => {
  const sameUnit = transitionServingUnit({ quantity: "7.336984", unit: "oz", gramWeight: "208" }, "oz");
  expect(sameUnit.quantity).toBe("7.336984");

  const refused = transitionServingUnit({ quantity: "7.336984", unit: "oz", gramWeight: "208" }, "piece");
  expect(refused.quantity).toBe("");
  expect(refused.gramWeight).toBe("208");
});

test("small positive conversions never round to a zero quantity", () => {
  const toGrams = transitionServingUnit({ quantity: "0.01", unit: "oz", gramWeight: "0.283495" }, "g");
  expect(toGrams.quantity).toBe("0.283495");
  expect(Number(toGrams.quantity)).toBeGreaterThan(0);
  expect(toGrams.gramWeight).toBe("0.283495");

  const toMilliliters = transitionServingUnit({ quantity: "0.001", unit: "tsp", gramWeight: "0.005" }, "ml");
  expect(toMilliliters.quantity).toBe("0.004929");
  expect(Number(toMilliliters.quantity)).toBeGreaterThan(0);
  expect(toMilliliters.gramWeight).toBe("0.005");

  const toOunces = transitionServingUnit({ quantity: "0.1", unit: "g", gramWeight: "0.1" }, "oz");
  expect(toOunces.quantity).toBe("0.003527");
  expect(Number(toOunces.quantity)).toBeGreaterThan(0);

  const toKilograms = transitionServingUnit({ quantity: "3", unit: "g", gramWeight: "3" }, "kg");
  expect(toKilograms.quantity).toBe("0.003");
  expect(Number(toKilograms.quantity)).toBeGreaterThan(0);
});

test("automatic volume conversions keep recognizable common fractions renderable", () => {
  const twoThirdsCup = transitionServingUnit({ quantity: "10.666667", unit: "tbsp", gramWeight: "90" }, "cup");
  expect(twoThirdsCup.quantity).toBe("0.666666667");
  expect(generatedAmountDisplayLabel(twoThirdsCup.quantity, "cup")).toBe("2/3 cup");
  expect(twoThirdsCup.gramWeight).toBe("90");

  const oneThirdCup = transitionServingUnit({ quantity: "5.333333", unit: "tbsp", gramWeight: "45" }, "cup");
  expect(oneThirdCup.quantity).toBe("0.333333333");
  expect(generatedAmountDisplayLabel(oneThirdCup.quantity, "cup")).toBe("1/3 cup");

  const oneEighthCup = transitionServingUnit({ quantity: "6", unit: "tsp", gramWeight: "30" }, "cup");
  expect(oneEighthCup.quantity).toBe("0.125");
  expect(generatedAmountDisplayLabel(oneEighthCup.quantity, "cup")).toBe("1/8 cup");

  const threeEighthsCup = transitionServingUnit({ quantity: "18", unit: "tsp", gramWeight: "90" }, "cup");
  expect(threeEighthsCup.quantity).toBe("0.375");
  expect(generatedAmountDisplayLabel(threeEighthsCup.quantity, "cup")).toBe("3/8 cup");

  // Non-fraction converted values stay capped at practical precision.
  const capped = transitionServingUnit({ quantity: "5.92", unit: "tbsp", gramWeight: "90" }, "cup");
  expect(capped.quantity).toBe("0.37");
});

// ISSUE_106_EQUIVALENCE_GUIDANCE

test("cross-dimension guidance requests food-specific equivalence without presenting the unit as an error", () => {
  const countGuidance = servingConversionReviewMessage("slice", "100");
  expect(countGuidance).toBe(
    "Enter how many slices equal 100 g. This relationship is specific to this Food.",
  );
  expect(countGuidance).not.toContain("couldn't convert");
  expect(countGuidance).not.toContain("error");

  const volumeGuidance = servingConversionReviewMessage("cup", "100");
  expect(volumeGuidance).toBe(
    "Enter the cup amount that equals 100 g. This relationship is specific to this Food.",
  );
  expect(volumeGuidance).not.toContain("couldn't convert");
});

test("transitionServingUnit never mutates its inputs", () => {
  const current = { quantity: "1.5", unit: "cup", gramWeight: "208", preservedVolume: null as PreservedVolumeServing | null };
  transitionServingUnit(current, "oz");
  transitionServingUnit(current, "piece");
  expect(current).toEqual({ quantity: "1.5", unit: "cup", gramWeight: "208", preservedVolume: null });
});

test("applyAmountPatch keeps explicit grams authoritative across descriptive edits", () => {
  const serving: AmountFormValue = {
    key: "portion-1", label: "1.5 cup", quantity: "1.5", unit: "cup", gram_weight: "208",
    is_default: false, isBaseAmount: false, labelMode: "automatic",
  };
  const converted = applyAmountPatch(serving, { quantity: "7.336984", unit: "oz", gram_weight: "208" });
  expect(converted.gram_weight).toBe("208");
  expect(converted.quantity).toBe("7.336984");
  expect(converted.label).toBe("7.336984 oz");

  const directEdit = applyAmountPatch(serving, { quantity: "4", unit: "oz" });
  expect(directEdit.gram_weight).toBe("208");

  const manual = applyAmountPatch({ ...serving, label: "Morning bowl", labelMode: "manual" }, { quantity: "7.336984", unit: "oz", gram_weight: "208" });
  expect(manual.label).toBe("Morning bowl");
});
