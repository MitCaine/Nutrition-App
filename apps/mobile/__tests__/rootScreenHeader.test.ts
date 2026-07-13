import { OPEN_SETTINGS_ACCESSIBILITY_LABEL, ROOT_SCREEN_TITLES } from "../src/shared/components/rootScreenHeaderModel";

test("the shared root header defines all root screen titles", () => {
  expect(ROOT_SCREEN_TITLES).toEqual({
    foods: "Saved Foods",
    "daily-log": "Daily Log",
    recipes: "Recipes",
  });
});

test("the Settings action has an explicit accessibility label", () => {
  expect(OPEN_SETTINGS_ACCESSIBILITY_LABEL).toBe("Open settings");
});
