import { useQuery } from "@tanstack/react-query";

import { getDailyTargetComparison } from "../api/targetApi";

export const dailyTargetComparisonQueryKey = (date: string) => ["target-comparison", date] as const;

export function useDailyTargetComparison(date: string) {
  return useQuery({
    queryKey: dailyTargetComparisonQueryKey(date),
    queryFn: () => getDailyTargetComparison(date),
  });
}
