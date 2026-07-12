import {
  effectiveSearchQuery,
  scheduleDebouncedSearch,
  SEARCH_DEBOUNCE_MS,
} from "../src/features/foods/hooks/useDebouncedSearchQuery";

afterEach(() => {
  jest.useRealTimers();
});

test("rapid input commits only the final effective search query", () => {
  jest.useFakeTimers();
  const commit = jest.fn();
  const cancelFirst = scheduleDebouncedSearch("ground", commit);
  cancelFirst();
  scheduleDebouncedSearch("ground beef", commit);

  jest.advanceTimersByTime(SEARCH_DEBOUNCE_MS);

  expect(commit).toHaveBeenCalledTimes(1);
  expect(commit).toHaveBeenCalledWith("ground beef");
});

test("empty input clears the effective query immediately", () => {
  expect(effectiveSearchQuery("", "ground beef")).toBe("");
  expect(effectiveSearchQuery("   ", "ground beef")).toBe("");
});
