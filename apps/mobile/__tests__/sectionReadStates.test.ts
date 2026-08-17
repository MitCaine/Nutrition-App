import type { DailySummary } from "../src/features/logging/api/types";
import { dailySummaryReadState } from "../src/features/logging/hooks/useLogs";
import type { DailyTargetComparison } from "../src/features/targets/api/types";
import { targetProgressReadState } from "../src/features/targets/hooks/useDailyTargetComparison";

const summary: DailySummary = { logged_date: "2026-07-08", totals: [] };
const comparison: DailyTargetComparison = {
  date: "2026-07-08",
  dailyValueCatalogVersion: "fda_daily_values_2016_v1",
  driDatasetVersion: "nasem_dri_adults_2026_v1",
  targetDirectionSemanticsVersion: "target_directions_2026_v1",
  comparisons: [],
};

function query<T>(data?: T) {
  return {
    data,
    error: undefined,
    isError: false,
    isFetching: false,
    isLoading: false,
    isRefetchError: false,
    refetch: jest.fn(),
  };
}

test("totals expose independent loading, empty, success, refresh, failure, and unknown states", () => {
  expect(dailySummaryReadState({ ...query<DailySummary>(), isLoading: true }, true).kind).toBe("initial-loading");
  expect(dailySummaryReadState(query<DailySummary>(), true).kind).toBe("initial-loading");
  expect(dailySummaryReadState({ ...query<DailySummary>(), isError: true, error: new Error("offline") }, true).kind).toBe("initial-failure");
  expect(dailySummaryReadState(query(summary), true).kind).toBe("empty");
  const knownSummary = { ...summary, totals: [{ nutrientId: "calories", amountKnown: "100", amountEstimated: "0", unit: "kcal" as const, hasUnknownContributors: false, unknownContributorCount: 0 }] };
  expect(dailySummaryReadState(query(knownSummary), true).kind).toBe("success");
  expect(dailySummaryReadState({ ...query(knownSummary), isFetching: true }, true).kind).toBe("refreshing");
  expect(dailySummaryReadState({ ...query(knownSummary), isError: true, isRefetchError: true, error: new Error("offline") }, true).kind).toBe("refresh-failure");
  const unknown = dailySummaryReadState({ ...query(knownSummary), isFetching: true }, false);
  expect(unknown.kind).toBe("unavailable");
  expect(unknown.data).toBeNull();
});

test("target progress remains independent but cannot claim zero while entries are unknown", () => {
  expect(targetProgressReadState({ ...query<DailyTargetComparison>(), isLoading: true }, true).kind).toBe("initial-loading");
  expect(targetProgressReadState(query<DailyTargetComparison>(), true).kind).toBe("initial-loading");
  expect(targetProgressReadState({ ...query<DailyTargetComparison>(), isError: true, error: new Error("offline") }, true).kind).toBe("initial-failure");
  expect(targetProgressReadState(query(comparison), true).kind).toBe("empty");
  const knownComparison = { ...comparison, comparisons: [{ nutrientId: "calories", consumedAmount: "0", targetAmount: "2000", unit: "kcal" as const, percentage: "0", authority: "calculated_estimate" as const, direction: "target" as const, trackingMode: "recommended" as const, status: "available" as const, reasonCode: null, noteCode: null, hasUnknownContributors: false, referenceType: null, sourceVersion: null, sourceId: null, calculationBasis: null }] };
  expect(targetProgressReadState(query(knownComparison), true).kind).toBe("success");
  expect(targetProgressReadState({ ...query(knownComparison), isFetching: true }, true).kind).toBe("refreshing");
  expect(targetProgressReadState({ ...query(knownComparison), isError: true, isRefetchError: true, error: new Error("offline") }, true).kind).toBe("refresh-failure");
  const unknown = targetProgressReadState(query(comparison), false);
  expect(unknown.kind).toBe("unavailable");
  expect(unknown.data).toBeNull();
  unknown.retry();
});

test("retrying one section invokes only that section's read operation", () => {
  const totalsRefetch = jest.fn();
  const targetRefetch = jest.fn();
  const totals = dailySummaryReadState({ ...query<DailySummary>(), isError: true, refetch: totalsRefetch }, true);
  const targets = targetProgressReadState({ ...query(comparison), refetch: targetRefetch }, true);

  totals.retry();
  expect(totalsRefetch).toHaveBeenCalledTimes(1);
  expect(targetRefetch).not.toHaveBeenCalled();
  expect(targets.kind).toBe("empty");
});
