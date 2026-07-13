import {
  isMainTabRoot,
  mainTabForRoute,
  MAIN_TAB_ACCESSIBILITY_LABELS,
  settingsOriginForRoute,
  swipeDestination,
  tabSelectionDestination,
} from "../src/app/navigation/mainTabs";

test("main and nested routes select the correct bottom tab", () => {
  expect(mainTabForRoute("foods")).toBe("foods");
  expect(mainTabForRoute("food-detail")).toBe("foods");
  expect(mainTabForRoute("daily-log")).toBe("daily-log");
  expect(mainTabForRoute("edit-log")).toBe("daily-log");
  expect(mainTabForRoute("recipes")).toBe("recipes");
  expect(mainTabForRoute("recipe-detail")).toBe("recipes");
});

test("selecting another tab navigates while selecting the active tab is a no-op", () => {
  expect(tabSelectionDestination("foods", "daily-log")).toBe("daily-log");
  expect(tabSelectionDestination("daily-log", "recipes")).toBe("recipes");
  expect(tabSelectionDestination("recipes", "foods")).toBe("foods");
  expect(tabSelectionDestination("foods", "foods")).toBeNull();
});

test("horizontal swipes follow tab order and stop at boundaries", () => {
  expect(swipeDestination("foods", -80)).toBe("daily-log");
  expect(swipeDestination("daily-log", -80)).toBe("recipes");
  expect(swipeDestination("recipes", 80)).toBe("daily-log");
  expect(swipeDestination("daily-log", 80)).toBe("foods");
  expect(swipeDestination("foods", 80)).toBe("foods");
  expect(swipeDestination("recipes", -80)).toBe("recipes");
  expect(swipeDestination("daily-log", 30)).toBe("daily-log");
});

test("top-level swipes are enabled only on root tab screens", () => {
  expect(isMainTabRoot("foods")).toBe(true);
  expect(isMainTabRoot("daily-log")).toBe(true);
  expect(isMainTabRoot("recipes")).toBe(true);
  expect(isMainTabRoot("food-detail")).toBe(false);
  expect(isMainTabRoot("recipe-detail")).toBe(false);
  expect(isMainTabRoot("edit-log")).toBe(false);
  expect(isMainTabRoot("settings")).toBe(false);
});

test("Settings preserves the root tab that opened it", () => {
  expect(settingsOriginForRoute("foods")).toBe("foods");
  expect(settingsOriginForRoute("daily-log")).toBe("daily-log");
  expect(settingsOriginForRoute("recipes")).toBe("recipes");
});

test("each tab has an explicit accessibility label", () => {
  expect(MAIN_TAB_ACCESSIBILITY_LABELS).toEqual({
    foods: "Foods tab",
    "daily-log": "Daily Log tab",
    recipes: "Recipes tab",
  });
});
