import { useQuery } from "@tanstack/react-query";

import { getDailyTargetComparison } from "../api/targetApi";
import type { DailyTargetComparison } from "../api/types";

export const dailyTargetComparisonQueryKey = (date: string) => ["target-comparison", date] as const;

type TargetComparisonQueryLike = {
  data?: DailyTargetComparison;
  error?: unknown;
  isError: boolean;
  isFetching: boolean;
  isLoading: boolean;
  isRefetchError?: boolean;
  refetch: () => unknown;
};

export type TargetProgressReadState =
  | { kind: "initial-loading"; data: null; retry: () => void }
  | { kind: "initial-failure"; data: null; error: unknown; retry: () => void }
  | { kind: "unavailable"; data: null; retry: () => void }
  | { kind: "empty"; data: DailyTargetComparison; retry: () => void }
  | { kind: "success"; data: DailyTargetComparison; retry: () => void }
  | { kind: "refreshing"; data: DailyTargetComparison; retry: () => void }
  | { kind: "refresh-failure"; data: DailyTargetComparison; error: unknown; retry: () => void };

/**
 * Keep target progress independent from the entries cache while preventing
 * unknown entry intake from being presented as a successful zero progress.
 */
export function targetProgressReadState(
  query: TargetComparisonQueryLike,
  entriesKnown: boolean,
): TargetProgressReadState {
  const retry = () => { void query.refetch(); };
  if (!query.data && query.isError) {
    return { kind: "initial-failure", data: null, error: query.error, retry };
  }
  if (!query.data && query.isLoading) {
    return { kind: "initial-loading", data: null, retry };
  }
  if (!entriesKnown) {
    return { kind: "unavailable", data: null, retry };
  }
  if (query.data && (query.isRefetchError || (query.isError && !query.isLoading))) {
    return { kind: "refresh-failure", data: query.data, error: query.error, retry };
  }
  if (query.data && query.isFetching) {
    return { kind: "refreshing", data: query.data, retry };
  }
  if (!query.data) {
    return entriesKnown
      ? { kind: "initial-loading", data: null, retry }
      : { kind: "unavailable", data: null, retry };
  }
  if (query.data.comparisons.length === 0) {
    return { kind: "empty", data: query.data, retry };
  }
  return { kind: "success", data: query.data, retry };
}

export function useDailyTargetComparison(date: string) {
  return useQuery({
    queryKey: dailyTargetComparisonQueryKey(date),
    queryFn: () => getDailyTargetComparison(date),
  });
}
