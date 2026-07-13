import {
  createFocusTargetRegistry,
  nutrientFocusKey,
  servingFocusKey,
} from "../src/shared/forms/focusTargets";

test("serving focus keys are unique across rows and fields", () => {
  const firstRow = ["label", "quantity", "unit", "gramWeight"].map((field) =>
    servingFocusKey("row-1", field as "label" | "quantity" | "unit" | "gramWeight"),
  );
  const secondRow = ["label", "quantity", "unit", "gramWeight"].map((field) =>
    servingFocusKey("row-2", field as "label" | "quantity" | "unit" | "gramWeight"),
  );
  expect(new Set(firstRow).size).toBe(4);
  expect(new Set([...firstRow, ...secondRow]).size).toBe(8);
});

test("serving and nutrient focus namespaces cannot collide", () => {
  expect(servingFocusKey("protein", "quantity")).not.toBe(nutrientFocusKey("protein"));
});

test("focus registry resolves the exact ref without overwriting other fields", () => {
  const registry = createFocusTargetRegistry<object>();
  const label = {};
  const quantity = {};
  expect(registry.assign(servingFocusKey("row-1", "label"), label)).toBe(false);
  expect(registry.assign(servingFocusKey("row-1", "quantity"), quantity)).toBe(false);
  expect(registry.resolve(servingFocusKey("row-1", "label"))).toBe(label);
  expect(registry.resolve(servingFocusKey("row-1", "quantity"))).toBe(quantity);
});

test("an unresolved focus target performs no callback or scrolling work", () => {
  const registry = createFocusTargetRegistry<object>();
  const scroll = jest.fn();
  expect(registry.withTarget("missing", scroll)).toBe(false);
  expect(scroll).not.toHaveBeenCalled();
});
