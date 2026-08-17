import { allocateDuplicateFoodName } from "../src/features/foods/utils/foodDuplicateName";

test("duplicate name allocates the lowest available suffix", () => {
  expect(allocateDuplicateFoodName(
    "Oatmeal",
    ["Oatmeal", "Oatmeal Copy", "Oatmeal Copy 3"],
    false,
  )).toBe("Oatmeal Copy 2");
});

test("duplicate of duplicate advances without Copy Copy", () => {
  expect(allocateDuplicateFoodName(
    "Oatmeal Copy 2",
    ["Oatmeal", "Oatmeal Copy", "Oatmeal Copy 2", "Oatmeal Copy 3"],
    true,
  )).toBe("Oatmeal Copy 4");
});

test("literal Copy suffix is preserved for a non-duplicate source", () => {
  expect(allocateDuplicateFoodName(
    "Recipe Copy",
    ["Recipe Copy"],
    false,
  )).toBe("Recipe Copy Copy");
});
