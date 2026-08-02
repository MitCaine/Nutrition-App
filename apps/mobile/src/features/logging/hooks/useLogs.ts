import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { createLog, deleteLog, getDailySummary, getLogEditContext, listFutureEntries, listLogs, listRecentEntries, updateLog } from "../api/logApi";
import type { DailyLog, DailyLogDeleteInput, DailyLogUpdateInput, DailySummary, RecentEntry } from "../api/types";

export type DailyLogReadState =
  | { kind: "initial-loading"; data: null; retry: () => void }
  | { kind: "initial-failure"; data: null; error: unknown; retry: () => void }
  | { kind: "empty"; data: []; retry: () => void }
  | { kind: "success"; data: DailyLog[]; retry: () => void }
  | { kind: "refreshing"; data: DailyLog[]; retry: () => void }
  | { kind: "refresh-failure"; data: DailyLog[]; error: unknown; retry: () => void };

type DailyLogQueryLike = {
  data?: DailyLog[];
  error?: unknown;
  isError: boolean;
  isFetching: boolean;
  isLoading: boolean;
  isRefetchError?: boolean;
  refetch: () => unknown;
};

type DailySummaryQueryLike = {
  data?: DailySummary;
  error?: unknown;
  isError: boolean;
  isFetching: boolean;
  isLoading: boolean;
  isRefetchError?: boolean;
  refetch: () => unknown;
};

export type DailySummaryReadState =
  | { kind: "initial-loading"; data: null; retry: () => void }
  | { kind: "initial-failure"; data: null; error: unknown; retry: () => void }
  | { kind: "unavailable"; data: null; retry: () => void }
  | { kind: "empty"; data: DailySummary; retry: () => void }
  | { kind: "success"; data: DailySummary; retry: () => void }
  | { kind: "refreshing"; data: DailySummary; retry: () => void }
  | { kind: "refresh-failure"; data: DailySummary; error: unknown; retry: () => void };

/** Translate React Query flags into one explicit, presentation-safe read state. */
export function dailyLogReadState(query: DailyLogQueryLike): DailyLogReadState {
  const retry = () => { void query.refetch(); };
  if (!query.data && query.isError) {
    return { kind: "initial-failure", data: null, error: query.error, retry };
  }
  if (query.data && (query.isRefetchError || (query.isError && !query.isLoading))) {
    return { kind: "refresh-failure", data: query.data, error: query.error, retry };
  }
  if (!query.data) {
    return { kind: "initial-loading", data: null, retry };
  }
  if (query.data && query.isFetching) {
    return { kind: "refreshing", data: query.data, retry };
  }
  if (query.data?.length === 0) {
    return { kind: "empty", data: [], retry };
  }
  return { kind: "success", data: query.data ?? [], retry };
}

/**
 * Translate the totals query into a state that cannot mistake an unavailable
 * entry projection for confirmed zero nutrition. The entry read is supplied
 * as a presentation relationship; its cache is never merged with totals.
 */
export function dailySummaryReadState(
  query: DailySummaryQueryLike,
  entriesKnown: boolean,
): DailySummaryReadState {
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
  if (query.data.totals.length === 0) {
    return { kind: "empty", data: query.data, retry };
  }
  return { kind: "success", data: query.data, retry };
}

export function invalidateLogDateCaches(queryClient: QueryClient, date: string) {
  queryClient.invalidateQueries({ queryKey: ["logs", date] });
  queryClient.invalidateQueries({ queryKey: ["daily-summary", date] });
  queryClient.invalidateQueries({ queryKey: ["target-comparison", date] });
}

export function invalidateFoodRecents(queryClient: QueryClient) {
  queryClient.invalidateQueries({ queryKey: ["foods", "recent"] });
}

/** Recent Entries is an event projection and must refresh after any log mutation. */
export function invalidateRecentEntries(queryClient: QueryClient) {
  queryClient.invalidateQueries({ queryKey: ["logs", "recent-entries"] });
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
    queryClient.setQueryData<DailyLog[]>(["future-logs", previousDate], (logs) =>
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
  queryClient.setQueryData<DailyLog[]>(["future-logs", date], (logs) =>
    logs?.filter((log) => log.id !== logId),
  );
}

export function useDailyLogs(date: string, enabled = true) {
  return useQuery({ queryKey: ["logs", date], queryFn: () => listLogs(date), enabled });
}

export function useFutureLogs(date: string, enabled = true) {
  return useQuery({ queryKey: ["future-logs", date], queryFn: () => listFutureEntries(date), enabled });
}

export function useRecentEntries() {
  return useQuery<RecentEntry[]>({
    queryKey: ["logs", "recent-entries"],
    queryFn: listRecentEntries,
  });
}

export function useDailySummary(date: string, enabled = true) {
  return useQuery({ queryKey: ["daily-summary", date], queryFn: () => getDailySummary(date), enabled });
}

export function useLogEditContext(logId: string | null, enabled = true) {
  return useQuery({
    queryKey: ["logs", logId, "edit-context"],
    queryFn: () => getLogEditContext(logId as string),
    enabled: Boolean(logId) && enabled,
  });
}

export function useLogMutations(date: string) {
  const queryClient = useQueryClient();
  const invalidate = () => invalidateLogDateCaches(queryClient, date);
  const invalidateUse = () => {
    invalidate();
    invalidateFoodRecents(queryClient);
    invalidateRecentEntries(queryClient);
  };
  const projectDelete = (logId: string, sourceDate = date) => {
    projectConfirmedDelete(queryClient, sourceDate, logId);
    invalidateLogDateCaches(queryClient, sourceDate);
    queryClient.invalidateQueries({ queryKey: ["future-logs", sourceDate] });
    invalidateFoodRecents(queryClient);
    invalidateRecentEntries(queryClient);
  };
  const refreshDate = (sourceDate: string) => {
    void queryClient.refetchQueries({ queryKey: ["logs", sourceDate] });
    void queryClient.refetchQueries({ queryKey: ["future-logs", sourceDate] });
    void queryClient.refetchQueries({ queryKey: ["daily-summary", sourceDate] });
    void queryClient.refetchQueries({ queryKey: ["target-comparison", sourceDate] });
  };
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
          queryClient.invalidateQueries({ queryKey: ["future-logs", date] });
        }
      },
    }),
    deleteLog: useMutation({
      mutationFn: (
        variables: string | { logId: string; input?: DailyLogDeleteInput },
      ) => {
        const { logId, input } = typeof variables === "string"
          ? { logId: variables, input: undefined }
          : variables;
        return deleteLog(logId, input);
      },
      onSuccess: (_result, variables) => {
        projectDelete(
          typeof variables === "string" ? variables : variables.logId,
        );
      },
    }),
    projectDelete,
    refreshDate,
  };
}
