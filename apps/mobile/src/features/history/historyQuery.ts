import {
  useQuery,
} from "@tanstack/react-query";
import type {
  QueryClient,
  QueryKey,
} from "@tanstack/react-query";

import type {
  HistoryRangeEvidence,
} from "../logging/api/types";
import type {
  NutritionRuntime,
} from "../../runtime/NutritionRuntime";
import type {
  RuntimeAuthorityIdentity,
} from "../../runtime/authorityIdentity";
import {
  useNutritionRuntime,
} from "../../runtime/NutritionRuntimeContext";

export const HISTORY_RANGE_QUERY_NAMESPACE =
  "history-range" as const;

export type HistoryRangeQueryKey = readonly [
  typeof HISTORY_RANGE_QUERY_NAMESPACE,
  RuntimeAuthorityIdentity["kind"],
  string,
  string,
  string,
];

export type HistoryRangeRuntime = Readonly<{
  authority: RuntimeAuthorityIdentity;
  dailyLogs: Pick<
    NutritionRuntime["dailyLogs"],
    "getHistoryRange"
  >;
}>;

export type HistoryRangeReadState =
  | {
      kind: "initial-loading";
      data: null;
      retry: () => void;
    }
  | {
      kind: "initial-failure";
      data: null;
      error: unknown;
      retry: () => void;
    }
  | {
      kind: "success";
      data: HistoryRangeEvidence;
      retry: () => void;
    }
  | {
      kind: "refreshing";
      data: HistoryRangeEvidence;
      retry: () => void;
    }
  | {
      kind: "refresh-failure";
      data: HistoryRangeEvidence;
      error: unknown;
      retry: () => void;
    };

type HistoryRangeQueryLike = {
  data?: HistoryRangeEvidence;
  error?: unknown;
  isError: boolean;
  isFetching: boolean;
  isLoading: boolean;
  isRefetchError?: boolean;
  refetch: () => unknown;
};

export function historyRangeQueryKey(
  authority: RuntimeAuthorityIdentity,
  startDate: string,
  endDate: string,
): HistoryRangeQueryKey {
  return [
    HISTORY_RANGE_QUERY_NAMESPACE,
    authority.kind,
    authority.recoveryScope,
    startDate,
    endDate,
  ];
}

export function historyRangeQueryOptions(
  runtime: HistoryRangeRuntime,
  startDate: string,
  endDate: string,
) {
  return {
    queryKey: historyRangeQueryKey(
      runtime.authority,
      startDate,
      endDate,
    ),
    queryFn: () =>
      runtime.dailyLogs.getHistoryRange(
        startDate,
        endDate,
      ),
  };
}

export function useHistoryRange(
  startDate: string,
  endDate: string,
  enabled = true,
) {
  const runtime = useNutritionRuntime();

  return useQuery({
    ...historyRangeQueryOptions(
      runtime,
      startDate,
      endDate,
    ),
    enabled,
  });
}

export function historyRangeReadState(
  query: HistoryRangeQueryLike,
): HistoryRangeReadState {
  const retry = () => {
    void query.refetch();
  };

  if (!query.data && query.isError) {
    return {
      kind: "initial-failure",
      data: null,
      error: query.error,
      retry,
    };
  }

  if (
    query.data
    && (
      query.isRefetchError
      || (query.isError && !query.isLoading)
    )
  ) {
    return {
      kind: "refresh-failure",
      data: query.data,
      error: query.error,
      retry,
    };
  }

  if (!query.data) {
    return {
      kind: "initial-loading",
      data: null,
      retry,
    };
  }

  if (query.isFetching) {
    return {
      kind: "refreshing",
      data: query.data,
      retry,
    };
  }

  return {
    kind: "success",
    data: query.data,
    retry,
  };
}

function parseHistoryRangeQueryKey(
  queryKey: QueryKey,
): HistoryRangeQueryKey | null {
  if (
    !Array.isArray(queryKey)
    || queryKey.length !== 5
    || queryKey[0]
      !== HISTORY_RANGE_QUERY_NAMESPACE
    || (
      queryKey[1] !== "local"
      && queryKey[1] !== "remote"
    )
    || typeof queryKey[2] !== "string"
    || typeof queryKey[3] !== "string"
    || typeof queryKey[4] !== "string"
  ) {
    return null;
  }

  return queryKey as unknown as HistoryRangeQueryKey;
}

export async function invalidateHistoryRangesForDates(
  queryClient: QueryClient,
  authority: RuntimeAuthorityIdentity,
  affectedDates: readonly string[],
): Promise<void> {
  const dates = [...new Set(affectedDates)];

  if (dates.length === 0) {
    return;
  }

  await queryClient.invalidateQueries({
    predicate: (query) => {
      const key = parseHistoryRangeQueryKey(
        query.queryKey,
      );

      if (key === null) {
        return false;
      }

      const [
        ,
        kind,
        recoveryScope,
        startDate,
        endDate,
      ] = key;

      if (
        kind !== authority.kind
        || recoveryScope
          !== authority.recoveryScope
      ) {
        return false;
      }

      return dates.some(
        (date) =>
          startDate <= date
          && date <= endDate,
      );
    },
  });
}
