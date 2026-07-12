import { isCurrentSearchQuery, restoredSearchOffset, unifiedFoodSearchSections } from "../src/features/foods/utils/unifiedFoodSearch";

const ready = {
  savedLoading: false,
  usdaLoading: false,
  savedError: false,
  usdaError: false,
};

test("empty query shows the normal saved-food list without USDA", () => {
  expect(unifiedFoodSearchSections({ query: "", savedCount: 3, usdaCount: 0, ...ready })).toEqual({
    showSavedHeading: false,
    showUsdaSection: false,
    showNoFoodsFound: false,
  });
});

test("matching saved foods are labeled before the USDA section", () => {
  expect(unifiedFoodSearchSections({ query: "beef", savedCount: 2, usdaCount: 4, ...ready })).toEqual({
    showSavedHeading: true,
    showUsdaSection: true,
    showNoFoodsFound: false,
  });
});

test("no saved matches still allows USDA results", () => {
  expect(unifiedFoodSearchSections({ query: "beef", savedCount: 0, usdaCount: 4, ...ready })).toEqual({
    showSavedHeading: false,
    showUsdaSection: true,
    showNoFoodsFound: false,
  });
});

test("clearing the query immediately removes the USDA section", () => {
  expect(unifiedFoodSearchSections({ query: "", savedCount: 2, usdaCount: 4, ...ready }).showUsdaSection).toBe(false);
});

test("source-specific failures and loading do not produce a global no-results state", () => {
  expect(unifiedFoodSearchSections({
    query: "beef",
    savedCount: 2,
    usdaCount: 0,
    ...ready,
    usdaError: true,
  })).toMatchObject({ showSavedHeading: true, showUsdaSection: true, showNoFoodsFound: false });

  expect(unifiedFoodSearchSections({
    query: "beef",
    savedCount: 0,
    usdaCount: 0,
    ...ready,
    usdaLoading: true,
  })).toMatchObject({ showUsdaSection: true, showNoFoodsFound: false });
});

test("a completed search with no local or USDA matches shows one concise empty state", () => {
  expect(unifiedFoodSearchSections({ query: "zzzz", savedCount: 0, usdaCount: 0, ...ready }).showNoFoodsFound).toBe(true);
});

test("the helper never changes the visible query", () => {
  const query = "ground beef 80/20";
  unifiedFoodSearchSections({ query, savedCount: 0, usdaCount: 1, ...ready });
  expect(query).toBe("ground beef 80/20");
});

test("stale debounced results are hidden until they match visible input", () => {
  expect(isCurrentSearchQuery("ground beef", "ground")).toBe(false);
  expect(unifiedFoodSearchSections({
    query: "ground beef",
    savedCount: 2,
    usdaCount: 4,
    ...ready,
    isCurrent: false,
  })).toEqual({ showSavedHeading: false, showUsdaSection: false, showNoFoodsFound: false });
});

test("scroll restoration is scoped to the exact raw query", () => {
  const session = { query: "ground beef 80/20", offset: 420 };
  expect(restoredSearchOffset("ground beef 80/20", session)).toBe(420);
  expect(restoredSearchOffset("ground beef", session)).toBe(0);
  expect(restoredSearchOffset("", session)).toBe(0);
});
