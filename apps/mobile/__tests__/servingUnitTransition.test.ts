import {
  applyAmountPatch,
  generatedAmountDisplayLabel,
  transitionServingUnit,
  UNCONVERTED_SERVING_UNIT_WARNING,
  type AmountFormValue,
  type PreservedVolumeServing,
} from "../src/features/foods/utils/amountForm";

const cupServing = { quantity: "1.5", unit: "cup", gramWeight: "208" };

test("weight -> weight preserves total grams and derives the new quantity from them", () => {
  const toOunces = transitionServingUnit({ quantity: "208", unit: "g", gramWeight: "208" }, "oz");
  expect(toOunces).toEqual({
    quantity: "7.336984",
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

  expect(transitionServingUnit({ quantity: "208", unit: "g", gramWeight: "208" }, "lb").quantity).toBe("0.458562");
  expect(transitionServingUnit({ quantity: "208", unit: "g", gramWeight: "208" }, "kg").quantity).toBe("0.208");
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

test("volume -> volume converts deterministically and preserves known grams", () => {
  const toTbsp = transitionServingUnit(cupServing, "tbsp");
  expect(toTbsp.quantity).toBe("24");
  expect(toTbsp.gramWeight).toBe("208");
  expect(toTbsp.converted).toBe(true);

  const backToCup = transitionServingUnit({ quantity: toTbsp.quantity, unit: "tbsp", gramWeight: "208" }, "cup");
  expect(backToCup.quantity).toBe("1.5");
  expect(backToCup.gramWeight).toBe("208");
  expect(backToCup.perUnit).toBe("138.666667");
});

test("volume -> weight derives the weight quantity from known grams, not the volume number", () => {
  const toOunces = transitionServingUnit(cupServing, "oz");
  expect(toOunces.quantity).toBe("7.336984");
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
  expect(refused.quantity).toBe("208");
  expect(refused.gramWeight).toBe("208");
  expect(refused.perUnit).toBe("");
  expect(refused.reviewWarning).toBe(UNCONVERTED_SERVING_UNIT_WARNING);
});

test("weight or volume -> count/custom never fabricates a conversion and never erases grams", () => {
  const fromWeight = transitionServingUnit({ quantity: "7.336984", unit: "oz", gramWeight: "208" }, "piece");
  expect(fromWeight).toEqual({
    quantity: "7.336984",
    unit: "piece",
    gramWeight: "208",
    perUnit: "",
    preservedVolume: null,
    reviewWarning: UNCONVERTED_SERVING_UNIT_WARNING,
    converted: false,
  });

  const fromVolume = transitionServingUnit(cupServing, "scoop");
  expect(fromVolume.converted).toBe(false);
  expect(fromVolume.quantity).toBe("1.5");
  expect(fromVolume.gramWeight).toBe("208");
  expect(fromVolume.preservedVolume).toEqual({ quantity: "1.5", unit: "cup" });
});

test("count/custom -> weight derives from known grams; -> volume or other count units refuses", () => {
  const toWeight = transitionServingUnit({ quantity: "5", unit: "piece", gramWeight: "208" }, "oz");
  expect(toWeight.quantity).toBe("7.336984");
  expect(toWeight.gramWeight).toBe("208");
  expect(toWeight.converted).toBe(true);

  const toVolume = transitionServingUnit({ quantity: "5", unit: "piece", gramWeight: "208" }, "cup");
  expect(toVolume.converted).toBe(false);
  expect(toVolume.quantity).toBe("5");
  expect(toVolume.gramWeight).toBe("208");
  expect(toVolume.reviewWarning).toBe(UNCONVERTED_SERVING_UNIT_WARNING);
});

test("distinct count/custom units are unresolved renames, never equivalent conversions", () => {
  const pieceToSlice = transitionServingUnit({ quantity: "5", unit: "piece", gramWeight: "208" }, "slice");
  expect(pieceToSlice.converted).toBe(false);
  expect(pieceToSlice.quantity).toBe("5");
  expect(pieceToSlice.gramWeight).toBe("208");
  expect(pieceToSlice.perUnit).toBe("");
  expect(pieceToSlice.reviewWarning).toBe(UNCONVERTED_SERVING_UNIT_WARNING);

  const scoopToBowl = transitionServingUnit({ quantity: "2", unit: "scoop", gramWeight: "30" }, "bowl");
  expect(scoopToBowl.converted).toBe(false);
  expect(scoopToBowl.quantity).toBe("2");
  expect(scoopToBowl.gramWeight).toBe("30");
  expect(scoopToBowl.reviewWarning).toBe(UNCONVERTED_SERVING_UNIT_WARNING);

  const pieceToCustom = transitionServingUnit({ quantity: "5", unit: "piece", gramWeight: "208" }, "scoop");
  expect(pieceToCustom.converted).toBe(false);
  expect(pieceToCustom.reviewWarning).toBe(UNCONVERTED_SERVING_UNIT_WARNING);

  const customToPiece = transitionServingUnit({ quantity: "2", unit: "scoop", gramWeight: "30" }, "piece");
  expect(customToPiece.converted).toBe(false);
  expect(customToPiece.quantity).toBe("2");
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
  expect(refused.quantity).toBe("2");
  expect(refused.gramWeight).toBe("");
  expect(refused.reviewWarning).toBe(UNCONVERTED_SERVING_UNIT_WARNING);
});

test("automatic labels follow the converted quantity while the transition itself stays display-agnostic", () => {
  const toOunces = transitionServingUnit(cupServing, "oz");
  expect(generatedAmountDisplayLabel(toOunces.quantity, "oz")).toBe("7.337 oz");
  expect(generatedAmountDisplayLabel("7.336984", "oz")).not.toContain("7.336984");
  expect(toOunces.quantity).toBe("7.336984");
});

test("transitionServingUnit never mutates its inputs", () => {
  const current = { quantity: "1.5", unit: "cup", gramWeight: "208", preservedVolume: null as PreservedVolumeServing | null };
  transitionServingUnit(current, "oz");
  transitionServingUnit(current, "piece");
  expect(current).toEqual({ quantity: "1.5", unit: "cup", gramWeight: "208", preservedVolume: null });
});

test("applyAmountPatch keeps an explicit unit-transition gram weight authoritative", () => {
  const serving: AmountFormValue = {
    key: "portion-1", label: "1.5 cup", quantity: "1.5", unit: "cup", gram_weight: "208",
    is_default: false, isBaseAmount: false, labelMode: "automatic",
  };
  const converted = applyAmountPatch(serving, { quantity: "7.336984", unit: "oz", gram_weight: "208" });
  expect(converted.gram_weight).toBe("208");
  expect(converted.quantity).toBe("7.336984");
  expect(converted.label).toBe("7.336984 oz");

  const directEdit = applyAmountPatch(serving, { quantity: "4", unit: "oz" });
  expect(directEdit.gram_weight).toBe("113.398093");

  const manual = applyAmountPatch({ ...serving, label: "Morning bowl", labelMode: "manual" }, { quantity: "7.336984", unit: "oz", gram_weight: "208" });
  expect(manual.label).toBe("Morning bowl");
});
