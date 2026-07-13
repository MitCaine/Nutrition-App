import {
  createClientServingKey,
  formatServingFormNumber,
  servingPayloadNumber,
  updateServingValues,
  type ServingFormValue,
} from "../src/features/foods/hooks/useFoodForm";

test("serving form trims raw decimals for initial display", () => {
  expect(formatServingFormNumber("100.000000")).toBe("100");
  expect(formatServingFormNumber("85.000000")).toBe("85");
  expect(formatServingFormNumber("1.250000")).toBe("1.25");
  expect(formatServingFormNumber(null)).toBe("");
});

test("serving form preserves original precision for unchanged values", () => {
  expect(servingPayloadNumber("100", "100.000000")).toBe("100.000000");
  expect(servingPayloadNumber("85", "85.000000")).toBe("85.000000");
  expect(servingPayloadNumber("86", "85.000000")).toBe("86");
});

const servings: ServingFormValue[] = [
  { key: "persisted-serving", label: "1 cup", quantity: "1", unit: "cup", gram_weight: "170", is_default: true },
  { key: "client-serving", label: "1 scoop", quantity: "1", unit: "scoop", gram_weight: "30", is_default: false },
];

test("editing one serving preserves stable keys and unrelated row identity", () => {
  const next = updateServingValues(servings, "client-serving", { label: "2 scoops" });
  expect(next.map((serving) => serving.key)).toEqual(["persisted-serving", "client-serving"]);
  expect(next[0]).toBe(servings[0]);
  expect(next[1]).not.toBe(servings[1]);
  expect(next[1].label).toBe("2 scoops");
});

test("setting default only replaces rows whose default state changes", () => {
  const third = { ...servings[1], key: "unchanged-third" };
  const next = updateServingValues([...servings, third], "client-serving", { is_default: true });
  expect(next[0]).not.toBe(servings[0]);
  expect(next[1].is_default).toBe(true);
  expect(next[2]).toBe(third);
});

test("new serving client keys are stable-value-independent and unique", () => {
  const first = createClientServingKey();
  const second = createClientServingKey();
  expect(first).not.toBe(second);
  expect(first).toMatch(/^client-serving-\d+$/);
});
