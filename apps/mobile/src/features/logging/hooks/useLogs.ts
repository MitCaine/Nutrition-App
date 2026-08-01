import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { createLog, deleteLog, getDailySummary, getLogEditContext, listLogs, updateLog } from "../api/logApi";
import type { DailyLog, DailyLogUpdateInput } from "../api/types";

export function invalidateLogDateCaches(queryClient: QueryClient, date: string) {
  queryClient.invalidateQueries({ queryKey: ["logs", date] });
  queryClient.invalidateQueries({ queryKey: ["daily-summary", date] });
  queryClient.invalidateQueries({ queryKey: ["target-comparison", date] });
}

export function invalidateFoodRecents(queryClient: QueryClient) {
  queryClient.invalidateQueries({ queryKey: ["foods", "recent"] });
}

/**
 * Project a confirmed server response before independent read refreshes run.
 * The cache is never treated as proof of commit; it is only the immediate
 * rendering of a response already confirmed by the mutation endpoint.
 */
export function projectConfirmedLog(
  queryClient: QueryClient,
  previousDate: string,
  result: DailyLog,
): void {
  if (result.logged_date !== previousDate) {
    queryClient.setQueryData<DailyLog[]>(["logs", previousDate], (logs) =>
      logs?.filter((log) => log.id !== result.id),
    );
  }
  queryClient.setQueryData<DailyLog[]>(["logs", result.logged_date], (logs) => {
    if (!logs) return [result];
    const index = logs.findIndex((log) => log.id === result.id);
    if (index < 0) return [...logs, result];
    return logs.map((log) => (log.id === result.id ? result : log));
  });
}

/** Project a confirmed permanent deletion while the surrounding reads refresh independently. */
export function projectConfirmedDelete(
  queryClient: QueryClient,
  date: string,
  logId: string,
): void {
  queryClient.setQueryData<DailyLog[]>(["logs", date], (logs) =>
    logs?.filter((log) => log.id !== logId),
  );
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
    createLog: useMutation({
      mutationFn: createLog,
      onSuccess: (result) => { projectConfirmedLog(queryClient, date, result); invalidateUse(); },
    }),
    updateLog: useMutation({
      mutationFn: ({ logId, input }: { logId: string; input: Partial<DailyLogUpdateInput> }) =>
        updateLog(logId, input),
      onSuccess: (result) => {
        projectConfirmedLog(queryClient, date, result);
        invalidate();
        if (result.logged_date !== date) {
          invalidateLogDateCaches(queryClient, result.logged_date);
        }
      },
    }),
    deleteLog: useMutation({
      mutationFn: (
        variables: string | { logId: string; input?: Parameters<typeof deleteLog>[1] },
      ) => {
        const { logId, input } = typeof variables === "string"
          ? { logId: variables, input: undefined }
          : variables;
        return deleteLog(logId, input);
      },
      onSuccess: (_result, variables) => {
        projectConfirmedDelete(
          queryClient,
          date,
          typeof variables === "string" ? variables : variables.logId,
        );
        invalidateUse();
      },
    }),
  };
}
