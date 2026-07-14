import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { createLog, deleteLog, getDailySummary, getLogEditContext, listLogs, updateLog } from "../api/logApi";
import type { DailyLogUpdateInput } from "../api/types";

export function invalidateLogDateCaches(queryClient: QueryClient, date: string) {
  queryClient.invalidateQueries({ queryKey: ["logs", date] });
  queryClient.invalidateQueries({ queryKey: ["daily-summary", date] });
  queryClient.invalidateQueries({ queryKey: ["target-comparison", date] });
}

export function invalidateFoodRecents(queryClient: QueryClient) {
  queryClient.invalidateQueries({ queryKey: ["foods", "recent"] });
}

export function useDailyLogs(date: string) {
  return useQuery({ queryKey: ["logs", date], queryFn: () => listLogs(date) });
}

export function useDailySummary(date: string) {
  return useQuery({ queryKey: ["daily-summary", date], queryFn: () => getDailySummary(date) });
}

export function useLogEditContext(logId: string | null) {
  return useQuery({
    queryKey: ["logs", logId, "edit-context"],
    queryFn: () => getLogEditContext(logId as string),
    enabled: Boolean(logId),
  });
}

export function useLogMutations(date: string) {
  const queryClient = useQueryClient();
  const invalidate = () => invalidateLogDateCaches(queryClient, date);
  const invalidateUse = () => { invalidate(); invalidateFoodRecents(queryClient); };
  return {
    createLog: useMutation({ mutationFn: createLog, onSuccess: invalidateUse }),
    updateLog: useMutation({
      mutationFn: ({ logId, input }: { logId: string; input: Partial<DailyLogUpdateInput> }) =>
        updateLog(logId, input),
      onSuccess: invalidate,
    }),
    deleteLog: useMutation({ mutationFn: deleteLog, onSuccess: invalidateUse }),
  };
}
