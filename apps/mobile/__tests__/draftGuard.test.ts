import {
  CLEAN_DRAFT_STATUS,
  draftExitDecision,
  draftObjectsEqual,
} from "../src/shared/navigation/draftGuard";
import {
  emptyRecipeDraft,
  recipeDraftSemanticallyEqual,
} from "../src/features/recipes/utils/recipeDraft";
import { foodFormDirtyFingerprint } from "../src/features/foods/hooks/useFoodForm";
import type { ServingFormValue } from "../src/features/foods/hooks/useFoodForm";

test("draft exit decision allows pristine state, confirms dirty state, and blocks busy state", () => {
  expect(draftExitDecision([CLEAN_DRAFT_STATUS])).toBe("allow");

  expect(draftExitDecision([
    { dirty: true, busy: false },
  ])).toBe("confirm-discard");

  expect(draftExitDecision([
    { dirty: true, busy: true },
  ])).toBe("blocked-busy");

  expect(draftExitDecision([
    { dirty: true, busy: false },
    { dirty: false, busy: true },
  ])).toBe("blocked-busy");
});

test("generic draft equality clears when a draft returns to its original semantic object", () => {
  const initial = { name: "Food", notes: "", amount: "1" };
  const changed = { ...initial, amount: "2" };
  const restored = { ...changed, amount: "1" };

  expect(draftObjectsEqual(initial, changed)).toBe(false);
  expect(draftObjectsEqual(initial, restored)).toBe(true);
});

test("Recipe dirty semantics ignore client identity but detect persisted authoring changes", () => {
  const initial = emptyRecipeDraft();
  const changed = { ...initial, name: "Soup" };

  expect(recipeDraftSemanticallyEqual(initial, changed)).toBe(false);
  expect(recipeDraftSemanticallyEqual(initial, { ...changed, name: "" })).toBe(true);
});

test("Food dirty fingerprint ignores client keys but includes unresolved serving review state", () => {
  const baseServing: ServingFormValue = {
    key: "client-a",
    label: "100 g",
    quantity: "100",
    unit: "g",
    gram_weight: "100",
    is_default: true,
    isBaseAmount: true,
    labelMode: "automatic",
  };

  const initial = foodFormDirtyFingerprint({
    fields: { name: "Bread", brand: "", notes: "" },
    servings: [baseServing],
    nutrients: [],
  });

  const differentKey = foodFormDirtyFingerprint({
    fields: { name: "Bread", brand: "", notes: "" },
    servings: [{ ...baseServing, key: "client-b" }],
    nutrients: [],
  });

  const unresolved = foodFormDirtyFingerprint({
    fields: { name: "Bread", brand: "", notes: "" },
    servings: [{
      ...baseServing,
      consistencyWarning: "review required",
    }],
    nutrients: [],
  });

  expect(differentKey).toBe(initial);
  expect(unresolved).not.toBe(initial);
});
