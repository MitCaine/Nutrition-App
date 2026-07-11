import {
  collapseCustomServing,
  expandCustomServing,
  isCustomServingExpanded,
} from "../src/features/recipes/utils/customServingState";

test("custom serving editor is collapsed by default and expands explicitly", () => {
  const initial = {};
  expect(isCustomServingExpanded(initial, "ingredient-1")).toBe(false);

  const expanded = expandCustomServing(initial, "ingredient-1");
  expect(isCustomServingExpanded(expanded, "ingredient-1")).toBe(true);
  expect(isCustomServingExpanded(initial, "ingredient-1")).toBe(false);
});

test("custom serving editor can be collapsed after cancel or mode change", () => {
  const expanded = expandCustomServing({}, "ingredient-1");
  const collapsed = collapseCustomServing(expanded, "ingredient-1");
  expect(isCustomServingExpanded(collapsed, "ingredient-1")).toBe(false);
});
