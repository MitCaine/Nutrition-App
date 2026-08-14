export const MAIN_TABS = ["foods", "daily-log", "recipes"] as const;

export type MainTab = (typeof MAIN_TABS)[number];

export const MAIN_TAB_ACCESSIBILITY_LABELS: Record<MainTab, string> = {
  foods: "Foods tab",
  "daily-log": "Daily Log tab",
  recipes: "Recipes tab",
};

const FOOD_ROUTES = new Set(["foods", "new-food", "food-detail", "edit-food", "log-food", "usda-preview"]);
const DAILY_LOG_ROUTES = new Set([
  "daily-log",
  "edit-log",
  "add-food",
  "add-custom-food",
  "add-scan",
  "add-ocr-confirm",
  "add-usda-preview",
  "add-log-food",
]);
const RECIPE_ROUTES = new Set([
  "recipes",
  "new-recipe",
  "recipe-detail",
  "edit-recipe",
  "ingredient-picker",
  "recipe-usda-search",
  "recipe-usda-preview",
]);

export function mainTabForRoute(routeName: string): MainTab {
  if (RECIPE_ROUTES.has(routeName)) {
    return "recipes";
  }
  if (DAILY_LOG_ROUTES.has(routeName)) {
    return "daily-log";
  }
  if (FOOD_ROUTES.has(routeName)) {
    return "foods";
  }
  return "foods";
}

export function isMainTabRoot(routeName: string): routeName is MainTab {
  return MAIN_TABS.includes(routeName as MainTab);
}

export function settingsOriginForRoute(routeName: string): MainTab {
  return mainTabForRoute(routeName);
}

export function tabSelectionDestination(current: MainTab, selected: MainTab, dismissOverlay = false): MainTab | null {
  if (current === selected) {
    return dismissOverlay ? selected : null;
  }
  return selected;
}

export function swipeDestination(current: MainTab, deltaX: number, threshold = 60): MainTab {
  if (Math.abs(deltaX) < threshold) {
    return current;
  }
  const currentIndex = MAIN_TABS.indexOf(current);
  const direction = deltaX < 0 ? 1 : -1;
  const nextIndex = Math.min(MAIN_TABS.length - 1, Math.max(0, currentIndex + direction));
  return MAIN_TABS[nextIndex];
}
