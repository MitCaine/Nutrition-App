import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { createLog, deleteLog, getDailySummary, listLogs, updateLog } from "../api/logApi";
import type { DailyLogInput } from "../api/types";

export function useDailyLogs(date: string) {
  return useQuery({ queryKey: ["logs", date], queryFn: () => listLogs(date) });
}

export function useDailySummary(date: string) {
  return useQuery({ queryKey: ["daily-summary", date], queryFn: () => getDailySummary(date) });
}

export function useLogMutations(date: string) {
  const queryClient = useQueryClient();
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["logs", date] });
    queryClient.invalidateQueries({ queryKey: ["daily-summary", date] });
  };
  return {
    createLog: useMutation({ mutationFn: createLog, onSuccess: invalidate }),
    updateLog: useMutation({
      mutationFn: ({ logId, input }: { logId: string; input: Partial<DailyLogInput> }) =>
        updateLog(logId, input),
      onSuccess: invalidate,
    }),
    deleteLog: useMutation({ mutationFn: deleteLog, onSuccess: invalidate }),
  };
}
