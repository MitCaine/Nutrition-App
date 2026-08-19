jest.mock("@tanstack/react-query", () => ({
  ...jest.requireActual("@tanstack/react-query"),
  useMutation: jest.fn(),
  useQueryClient: jest.fn(),
}));

jest.mock(
  "../src/runtime/NutritionRuntimeContext",
  () => ({
    useNutritionRuntime: jest.fn(),
  }),
);

import {
  QueryClient,
  QueryObserver,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";

import {
  historyRangeQueryKey,
  historyRangeQueryOptions,
  historyRangeReadState,
  invalidateHistoryRangesForDates,
} from "../src/features/history/historyQuery";
import {
  useLogMutations,
} from "../src/features/logging/hooks/useLogs";
import type {
  DailyLog,
  DailyLogCompleteInput,
  DailyLogCompletion,
  DailyLogCreateInput,
  DailyLogDeleteInput,
  DailyLogUpdateInput,
  HistoryRangeEvidence,
} from "../src/features/logging/api/types";
import type {
  NutritionRuntime,
} from "../src/runtime/NutritionRuntime";
import type {
  RuntimeAuthorityIdentity,
} from "../src/runtime/authorityIdentity";
import {
  useNutritionRuntime,
} from "../src/runtime/NutritionRuntimeContext";

const mockUseMutation =
  useMutation as unknown as jest.Mock;
const mockUseQueryClient =
  useQueryClient as unknown as jest.Mock;
const mockUseNutritionRuntime =
  useNutritionRuntime as unknown as jest.Mock;

const LOCAL: RuntimeAuthorityIdentity = {
  kind: "local",
  recoveryScope: "local-sqlite",
};

const LOCAL_OTHER_SCOPE:
  RuntimeAuthorityIdentity = {
    kind: "local",
    recoveryScope: "local-sqlite-other",
  };

const REMOTE: RuntimeAuthorityIdentity = {
  kind: "remote",
  recoveryScope:
    "remote:http://example.test:owner-a",
};

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: Infinity,
      },
    },
  });
}

function makeEvidence(
  startDate: string,
  endDate: string,
  marker = startDate,
): HistoryRangeEvidence {
  return {
    startDate,
    endDate,
    firstLoggedDate: marker,
    days: [
      {
        date: endDate,
        hasLogs: false,
        isComplete: false,
        nutrients: [],
      },
    ],
  };
}

function makeLog(
  loggedDate: string,
  id = "log-1",
): DailyLog {
  return {
    id,
    food_item_id: "food-1",
    source_food_available: true,
    logged_date: loggedDate,
    amount_quantity: "1",
    amount_unit: "serving",
  };
}

function makeRuntime(
  authority: RuntimeAuthorityIdentity,
  overrides: Partial<
    NutritionRuntime["dailyLogs"]
  > = {},
): NutritionRuntime {
  const dailyLogs = {
    list: jest.fn(),
    listFuture: jest.fn(),
    listRecentEntries: jest.fn(),
    create: jest.fn(),
    update: jest.fn(),
    getEditContext: jest.fn(),
    delete: jest.fn(),
    getMutationStatus: jest.fn(),
    getHistoryRange: jest.fn(),
    getDailySummary: jest.fn(),
    markDayComplete: jest.fn(),
    ...overrides,
  } as unknown as NutritionRuntime["dailyLogs"];

  return {
    authority,
    dailyLogs,
  } as unknown as NutritionRuntime;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;

  const promise = new Promise<T>(
    (resolvePromise, rejectPromise) => {
      resolve = resolvePromise;
      reject = rejectPromise;
    },
  );

  return {
    promise,
    resolve,
    reject,
  };
}

async function flush(): Promise<void> {
  await new Promise<void>(
    (resolve) => setTimeout(resolve, 0),
  );
}

async function waitFor(
  condition: () => boolean,
): Promise<void> {
  for (let index = 0; index < 100; index += 1) {
    if (condition()) {
      return;
    }
    await flush();
  }

  throw new Error(
    "Timed out waiting for query state.",
  );
}

function seedHistory(
  queryClient: QueryClient,
  authority: RuntimeAuthorityIdentity,
  startDate: string,
  endDate: string,
) {
  const key = historyRangeQueryKey(
    authority,
    startDate,
    endDate,
  );

  queryClient.setQueryData(
    key,
    makeEvidence(startDate, endDate),
  );

  return key;
}

type MutationOption<Variables, Result> = {
  mutationFn: (
    variables: Variables,
  ) => Promise<Result>;
  onSuccess?: (
    result: Result,
    variables: Variables,
  ) => void;
};

type DeleteVariables =
  | string
  | {
      logId: string;
      input?: DailyLogDeleteInput;
    };

type LogMutationHarness = {
  createLog: MutationOption<
    DailyLogCreateInput,
    DailyLog
  >;
  updateLog: MutationOption<
    {
      logId: string;
      input: Partial<DailyLogUpdateInput>;
    },
    DailyLog
  >;
  deleteLog: MutationOption<
    DeleteVariables,
    void
  >;
  completeDay: MutationOption<
    DailyLogCompleteInput,
    DailyLogCompletion
  >;
};

function mutationHarness(
  queryClient: QueryClient,
  runtime: NutritionRuntime,
  date: string,
): LogMutationHarness {
  mockUseQueryClient.mockReturnValue(
    queryClient,
  );
  mockUseNutritionRuntime.mockReturnValue(
    runtime,
  );

  return useLogMutations(
    date,
  ) as unknown as LogMutationHarness;
}

describe(
  "E4-06 History query coherence",
  () => {
    beforeEach(() => {
      mockUseMutation.mockReset();
      mockUseQueryClient.mockReset();
      mockUseNutritionRuntime.mockReset();

      mockUseMutation.mockImplementation(
        (options) => options,
      );
    });

    test(
      "query identity partitions exact range and authority only",
      () => {
        const seven = historyRangeQueryKey(
          LOCAL,
          "2026-08-01",
          "2026-08-07",
        );
        const sevenAgain =
          historyRangeQueryKey(
            LOCAL,
            "2026-08-01",
            "2026-08-07",
          );
        const thirty = historyRangeQueryKey(
          LOCAL,
          "2026-07-09",
          "2026-08-07",
        );
        const paged = historyRangeQueryKey(
          LOCAL,
          "2026-07-25",
          "2026-07-31",
        );
        const remote = historyRangeQueryKey(
          REMOTE,
          "2026-08-01",
          "2026-08-07",
        );
        const otherScope =
          historyRangeQueryKey(
            LOCAL_OTHER_SCOPE,
            "2026-08-01",
            "2026-08-07",
          );

        expect(seven).toEqual([
          "history-range",
          "local",
          "local-sqlite",
          "2026-08-01",
          "2026-08-07",
        ]);
        expect(sevenAgain).toEqual(seven);

        expect(thirty).not.toEqual(seven);
        expect(paged).not.toEqual(seven);
        expect(remote).not.toEqual(seven);
        expect(otherScope).not.toEqual(seven);

        // Presentation mode and current target
        // references are intentionally absent.
        expect(seven).toHaveLength(5);
      },
    );

    test(
      "one exact query function returns raw E4-04 evidence unchanged",
      async () => {
        const evidence = makeEvidence(
          "2026-08-01",
          "2026-08-07",
        );
        const getHistoryRange = jest
          .fn()
          .mockResolvedValue(evidence);
        const runtime = makeRuntime(
          LOCAL,
          { getHistoryRange },
        );

        const options =
          historyRangeQueryOptions(
            runtime,
            "2026-08-01",
            "2026-08-07",
          );

        const result =
          await options.queryFn();

        expect(getHistoryRange)
          .toHaveBeenCalledTimes(1);
        expect(getHistoryRange)
          .toHaveBeenCalledWith(
            "2026-08-01",
            "2026-08-07",
          );
        expect(result).toBe(evidence);
      },
    );

    test(
      "A to B to C switching confines late old responses to old keys",
      async () => {
        const queryClient =
          makeQueryClient();

        const a = deferred<
          HistoryRangeEvidence
        >();
        const b = deferred<
          HistoryRangeEvidence
        >();
        const c = deferred<
          HistoryRangeEvidence
        >();

        const pending = new Map([
          ["2026-08-01", a],
          ["2026-07-09", b],
        ]);

        const local = makeRuntime(
          LOCAL,
          {
            getHistoryRange: jest.fn(
              (
                startDate: string,
              ) => {
                const request =
                  pending.get(startDate);
                if (!request) {
                  throw new Error(
                    "Unexpected range.",
                  );
                }
                return request.promise;
              },
            ),
          },
        );

        const remote = makeRuntime(
          REMOTE,
          {
            getHistoryRange: jest.fn(
              () => c.promise,
            ),
          },
        );

        const evidenceA = makeEvidence(
          "2026-08-01",
          "2026-08-07",
          "A",
        );
        const evidenceB = makeEvidence(
          "2026-07-09",
          "2026-08-07",
          "B",
        );
        const evidenceC = makeEvidence(
          "2026-08-01",
          "2026-08-07",
          "C",
        );

        const observer = new QueryObserver<
          HistoryRangeEvidence,
          Error
        >(
          queryClient,
          historyRangeQueryOptions(
            local,
            "2026-08-01",
            "2026-08-07",
          ),
        );

        const visible:
          HistoryRangeEvidence[] = [];

        const unsubscribe =
          observer.subscribe(
            (result) => {
              if (result.data) {
                visible.push(
                  result.data,
                );
              }
            },
          );

        observer.setOptions(
          historyRangeQueryOptions(
            local,
            "2026-07-09",
            "2026-08-07",
          ),
        );

        observer.setOptions(
          historyRangeQueryOptions(
            remote,
            "2026-08-01",
            "2026-08-07",
          ),
        );

        a.resolve(evidenceA);
        b.resolve(evidenceB);
        await flush();
        await flush();

        expect(
          observer.getCurrentResult().data,
        ).toBeUndefined();
        expect(visible).not.toContain(
          evidenceA,
        );
        expect(visible).not.toContain(
          evidenceB,
        );

        c.resolve(evidenceC);

        await waitFor(
          () =>
            observer
              .getCurrentResult()
              .data === evidenceC,
        );

        expect(
          observer.getCurrentResult().data,
        ).toBe(evidenceC);
        expect(visible).toContain(
          evidenceC,
        );
        expect(visible).not.toContain(
          evidenceA,
        );
        expect(visible).not.toContain(
          evidenceB,
        );

        unsubscribe();
        queryClient.clear();
      },
    );

    test(
      "same-range refresh failure retains only same-range data with explicit failure state",
      async () => {
        const queryClient =
          makeQueryClient();
        const evidence = makeEvidence(
          "2026-08-01",
          "2026-08-07",
        );
        const refreshError =
          new Error("refresh failed");

        const runtime = makeRuntime(
          LOCAL,
          {
            getHistoryRange: jest
              .fn()
              .mockResolvedValueOnce(
                evidence,
              )
              .mockRejectedValueOnce(
                refreshError,
              ),
          },
        );

        const observer = new QueryObserver<
          HistoryRangeEvidence,
          Error
        >(
          queryClient,
          historyRangeQueryOptions(
            runtime,
            "2026-08-01",
            "2026-08-07",
          ),
        );

        const unsubscribe =
          observer.subscribe(() => {});

        await waitFor(
          () =>
            observer
              .getCurrentResult()
              .data === evidence,
        );

        await observer.refetch();

        await waitFor(
          () =>
            observer
              .getCurrentResult()
              .isRefetchError,
        );

        const result =
          observer.getCurrentResult();

        expect(result.data).toBe(
          evidence,
        );

        expect(
          historyRangeReadState(result),
        ).toMatchObject({
          kind: "refresh-failure",
          data: evidence,
          error: refreshError,
        });

        unsubscribe();
        queryClient.clear();
      },
    );

    test(
      "new-range and authority first-load failures never expose another cached range",
      async () => {
        const queryClient =
          makeQueryClient();

        const cachedA = makeEvidence(
          "2026-08-01",
          "2026-08-07",
          "cached-a",
        );

        queryClient.setQueryData(
          historyRangeQueryKey(
            LOCAL,
            "2026-08-01",
            "2026-08-07",
          ),
          cachedA,
        );

        const failedLocal =
          makeRuntime(
            LOCAL,
            {
              getHistoryRange: jest
                .fn()
                .mockRejectedValue(
                  new Error(
                    "new range failed",
                  ),
                ),
            },
          );

        const observer = new QueryObserver<
          HistoryRangeEvidence,
          Error
        >(
          queryClient,
          historyRangeQueryOptions(
            failedLocal,
            "2026-07-09",
            "2026-08-07",
          ),
        );

        const unsubscribe =
          observer.subscribe(() => {});

        await waitFor(
          () =>
            observer
              .getCurrentResult()
              .isError,
        );

        expect(
          observer.getCurrentResult().data,
        ).toBeUndefined();

        expect(
          historyRangeReadState(
            observer.getCurrentResult(),
          ),
        ).toMatchObject({
          kind: "initial-failure",
          data: null,
        });

        const failedRemote =
          makeRuntime(
            REMOTE,
            {
              getHistoryRange: jest
                .fn()
                .mockRejectedValue(
                  new Error(
                    "authority failed",
                  ),
                ),
            },
          );

        observer.setOptions(
          historyRangeQueryOptions(
            failedRemote,
            "2026-08-01",
            "2026-08-07",
          ),
        );

        await waitFor(
          () =>
            observer
              .getCurrentResult()
              .isError,
        );

        expect(
          observer.getCurrentResult().data,
        ).toBeUndefined();

        unsubscribe();
        queryClient.clear();
      },
    );

    test(
      "targeted invalidation is inclusive and authority scoped",
      async () => {
        const queryClient =
          makeQueryClient();

        const startKey = seedHistory(
          queryClient,
          LOCAL,
          "2026-08-03",
          "2026-08-05",
        );
        const endKey = seedHistory(
          queryClient,
          LOCAL,
          "2026-08-01",
          "2026-08-03",
        );
        const interiorKey = seedHistory(
          queryClient,
          LOCAL,
          "2026-08-01",
          "2026-08-05",
        );
        const adjacentKey = seedHistory(
          queryClient,
          LOCAL,
          "2026-08-04",
          "2026-08-06",
        );
        const remoteKey = seedHistory(
          queryClient,
          REMOTE,
          "2026-08-01",
          "2026-08-05",
        );
        const otherScopeKey =
          seedHistory(
            queryClient,
            LOCAL_OTHER_SCOPE,
            "2026-08-01",
            "2026-08-05",
          );

        await invalidateHistoryRangesForDates(
          queryClient,
          LOCAL,
          [
            "2026-08-03",
            "2026-08-03",
          ],
        );

        expect(
          queryClient.getQueryState(
            startKey,
          )?.isInvalidated,
        ).toBe(true);
        expect(
          queryClient.getQueryState(
            endKey,
          )?.isInvalidated,
        ).toBe(true);
        expect(
          queryClient.getQueryState(
            interiorKey,
          )?.isInvalidated,
        ).toBe(true);
        expect(
          queryClient.getQueryState(
            adjacentKey,
          )?.isInvalidated,
        ).toBe(false);
        expect(
          queryClient.getQueryState(
            remoteKey,
          )?.isInvalidated,
        ).toBe(false);
        expect(
          queryClient.getQueryState(
            otherScopeKey,
          )?.isInvalidated,
        ).toBe(false);

        queryClient.clear();
      },
    );

    test(
      "successful create delete and same-date update invalidate containing same-authority History",
      async () => {
        async function exercise(
          operation:
            | "create"
            | "delete"
            | "update",
        ) {
          const queryClient =
            makeQueryClient();

          const localKey = seedHistory(
            queryClient,
            LOCAL,
            "2026-08-01",
            "2026-08-07",
          );
          const remoteKey = seedHistory(
            queryClient,
            REMOTE,
            "2026-08-01",
            "2026-08-07",
          );

          const result =
            makeLog("2026-08-03");

          const runtime = makeRuntime(
            LOCAL,
            {
              create: jest
                .fn()
                .mockResolvedValue(
                  result,
                ),
              update: jest
                .fn()
                .mockResolvedValue(
                  result,
                ),
              delete: jest
                .fn()
                .mockResolvedValue(
                  undefined,
                ),
            },
          );

          const mutations =
            mutationHarness(
              queryClient,
              runtime,
              "2026-08-03",
            );

          if (operation === "create") {
            const input:
              DailyLogCreateInput = {
                client_request_id:
                  "create-1",
                food_item_id: "food-1",
                logged_date:
                  "2026-08-03",
                amount_quantity: "1",
                amount_unit:
                  "serving",
              };

            const created =
              await mutations
                .createLog
                .mutationFn(input);

            mutations
              .createLog
              .onSuccess?.(
                created,
                input,
              );
          } else if (
            operation === "delete"
          ) {
            const deleted =
              await mutations
                .deleteLog
                .mutationFn(
                  "log-1",
                );

            mutations
              .deleteLog
              .onSuccess?.(
                deleted,
                "log-1",
              );
          } else {
            const variables = {
              logId: "log-1",
              input: {
                amount_quantity:
                  "2",
              },
            };

            const updated =
              await mutations
                .updateLog
                .mutationFn(
                  variables,
                );

            mutations
              .updateLog
              .onSuccess?.(
                updated,
                variables,
              );
          }

          await flush();

          expect(
            queryClient.getQueryState(
              localKey,
            )?.isInvalidated,
          ).toBe(true);

          expect(
            queryClient.getQueryState(
              remoteKey,
            )?.isInvalidated,
          ).toBe(false);

          queryClient.clear();
        }

        await exercise("create");
        await exercise("delete");
        await exercise("update");
      },
    );

    test(
      "successful move invalidates both source and destination History ranges only",
      async () => {
        const queryClient =
          makeQueryClient();

        const sourceKey = seedHistory(
          queryClient,
          LOCAL,
          "2026-08-01",
          "2026-08-05",
        );
        const destinationKey =
          seedHistory(
            queryClient,
            LOCAL,
            "2026-08-08",
            "2026-08-12",
          );
        const unrelatedKey =
          seedHistory(
            queryClient,
            LOCAL,
            "2026-08-20",
            "2026-08-25",
          );
        const remoteKey = seedHistory(
          queryClient,
          REMOTE,
          "2026-08-08",
          "2026-08-12",
        );

        const moved =
          makeLog("2026-08-10");

        const runtime = makeRuntime(
          LOCAL,
          {
            update: jest
              .fn()
              .mockResolvedValue(
                moved,
              ),
          },
        );

        const mutations =
          mutationHarness(
            queryClient,
            runtime,
            "2026-08-03",
          );

        const variables = {
          logId: "log-1",
          input: {
            logged_date:
              "2026-08-10",
          },
        };

        const result =
          await mutations
            .updateLog
            .mutationFn(
              variables,
            );

        mutations
          .updateLog
          .onSuccess?.(
            result,
            variables,
          );

        await flush();

        expect(
          queryClient.getQueryState(
            sourceKey,
          )?.isInvalidated,
        ).toBe(true);
        expect(
          queryClient.getQueryState(
            destinationKey,
          )?.isInvalidated,
        ).toBe(true);
        expect(
          queryClient.getQueryState(
            unrelatedKey,
          )?.isInvalidated,
        ).toBe(false);
        expect(
          queryClient.getQueryState(
            remoteKey,
          )?.isInvalidated,
        ).toBe(false);

        queryClient.clear();
      },
    );

    test(
      "Complete assertion and reassertion delegate authoritatively and invalidate containing History",
      async () => {
        const queryClient =
          makeQueryClient();

        const localKey = seedHistory(
          queryClient,
          LOCAL,
          "2026-08-01",
          "2026-08-07",
        );
        const remoteKey = seedHistory(
          queryClient,
          REMOTE,
          "2026-08-01",
          "2026-08-07",
        );

        const completion:
          DailyLogCompletion = {
            logged_date:
              "2026-08-03",
            completed_at:
              "2026-08-03T12:00:00Z",
          };

        const markDayComplete =
          jest
            .fn()
            .mockResolvedValue(
              completion,
            );

        const runtime = makeRuntime(
          LOCAL,
          { markDayComplete },
        );

        const mutations =
          mutationHarness(
            queryClient,
            runtime,
            "2026-08-03",
          );

        const invalidateSpy =
          jest.spyOn(
            queryClient,
            "invalidateQueries",
          );

        for (
          const requestId of [
            "complete-1",
            "complete-2",
          ]
        ) {
          const input:
            DailyLogCompleteInput = {
              client_request_id:
                requestId,
              calendar_revision: 1,
              logged_date:
                "2026-08-03",
            };

          const result =
            await mutations
              .completeDay
              .mutationFn(input);

          mutations
            .completeDay
            .onSuccess?.(
              result,
              input,
            );

          await flush();
        }

        expect(markDayComplete)
          .toHaveBeenCalledTimes(2);

        const historyInvalidations =
          invalidateSpy.mock.calls.filter(
            ([filters]) =>
              typeof (
                filters as {
                  predicate?: unknown;
                }
              ).predicate
              === "function",
          );

        expect(
          historyInvalidations,
        ).toHaveLength(2);

        expect(
          queryClient.getQueryState(
            localKey,
          )?.isInvalidated,
        ).toBe(true);

        expect(
          queryClient.getQueryState(
            remoteKey,
          )?.isInvalidated,
        ).toBe(false);

        queryClient.clear();
      },
    );
  },
);
