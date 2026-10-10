import { QueryClient } from "@tanstack/react-query";

declare const require: (moduleName: string) => {
  readFileSync(path: string, encoding: "utf8"): string;
};
const { readFileSync } = require("fs");

import type { DailyLogMutationStatus } from "../src/features/logging/api/types";
import { parseDailyLogMutationStatus } from "../src/features/logging/api/logResponseSchemas";
import {
  createLogMutationRecoveryRecord,
  hasUnresolvedNutritionMutationForDate,
  loadLogMutationRecoveryJournal,
  reconcileLogMutationRecoveryRecord,
  retryLogMutationRecoveryRecord,
  startLogMutationRecovery,
  upsertLogMutationRecoveryRecord,
  type LogMutationRecoveryRecord,
  type RecoveryStorage,
} from "../src/features/logging/recovery/logMutationRecovery";
import { remoteAuthorityIdentity } from "../src/runtime/authorityIdentity";
import { RuntimeError } from "../src/runtime/RuntimeError";

const AUTHORITY = remoteAuthorityIdentity("e4-02-owner");
const REQUEST_ID = "22222222-2222-4222-8222-222222222222";

function memoryStorage(initial?: string): RecoveryStorage & { value: string | null } {
  const state = { value: initial ?? null };
  return {
    get value() { return state.value; },
    getItem: jest.fn(async () => state.value),
    setItem: jest.fn(async (_key: string, value: string) => { state.value = value; }),
    removeItem: jest.fn(async () => { state.value = null; }),
  };
}

function completeRecord(state: LogMutationRecoveryRecord["state"] = "submitted") {
  return {
    ...createLogMutationRecoveryRecord({
      authority: AUTHORITY,
      clientRequestId: REQUEST_ID,
      mutationType: "complete",
      sourceDate: "2026-08-18",
      displayContext: { item_name: null, amount_label: null, meal_label: null },
      payload: {
        operation: "complete",
        input: {
          client_request_id: REQUEST_ID,
          calendar_revision: 4,
          logged_date: "2026-08-18",
        },
      },
    }),
    state,
  } as LogMutationRecoveryRecord;
}

function dependencies(overrides: Record<string, unknown> = {}) {
  return {
    authority: AUTHORITY,
    dailyLogs: {
      getMutationStatus: jest.fn(),
      create: jest.fn(),
      update: jest.fn(),
      delete: jest.fn(),
      markDayComplete: jest.fn(),
      ...overrides,
    },
  };
}

describe("E4-02 Complete recovery", () => {
  test("version-2 unresolved log work remains readable and upgrades on the next write", async () => {
    const legacy = {
      version: 2,
      owner_scope: AUTHORITY.recoveryScope,
      id: "edit:legacy-request",
      client_request_id: "legacy-request",
      mutation_type: "edit",
      target_id: "log-1",
      display_context: { item_name: "Food", amount_label: "1 serving", meal_label: "Dinner" },
      source_date: "2026-08-18",
      destination_date: null,
      payload: {
        operation: "update",
        log_id: "log-1",
        input: { client_request_id: "legacy-request", amount_quantity: "2" },
      },
      created_at: "2026-08-18T19:00:00.000Z",
      last_reconciliation_attempt: null,
      reconciliation_attempts: 0,
      state: "submitted",
      dismissed_at: null,
      dismissed_from_state: null,
    };
    const storage = memoryStorage(JSON.stringify({ version: 2, records: [legacy] }));

    const [loaded] = await loadLogMutationRecoveryJournal(AUTHORITY, storage);
    expect(loaded).toEqual(expect.objectContaining({
      version: 3,
      client_request_id: "legacy-request",
      mutation_type: "edit",
      state: "submitted",
    }));
    expect(hasUnresolvedNutritionMutationForDate([loaded], "2026-08-18")).toBe(true);

    const complete = completeRecord("prepared");
    const result = await retryLogMutationRecoveryRecord(
      { ...complete, state: "confirmed_non_commit" },
      null,
      dependencies({
        markDayComplete: jest.fn(async () => ({
          logged_date: "2026-08-18",
          completed_at: "2026-08-18T20:00:00.000000Z",
        })),
      }),
      storage,
    );
    expect(result).toBe("confirmed");
    expect(JSON.parse(storage.value as string).version).toBe(3);
    expect(JSON.parse(storage.value as string).records).toEqual([
      expect.objectContaining({ client_request_id: "legacy-request", version: 3 }),
    ]);
  });

  test("Complete status reconciliation uses the existing mutation-status channel", async () => {
    const storage = memoryStorage();
    const record = completeRecord();
    const statusReader = jest.fn(async (): Promise<DailyLogMutationStatus> => ({
      operation: "complete",
      client_request_id: REQUEST_ID,
      status: "confirmed_success",
      log_id: null,
      result: null,
      completion: {
        logged_date: "2026-08-18",
        completed_at: "2026-08-18T20:00:00.000000Z",
      },
    }));

    const outcome = await reconcileLogMutationRecoveryRecord(
      record,
      null,
      dependencies(),
      { storage, statusReader },
    );

    expect(outcome).toBe("confirmed");
    expect(statusReader).toHaveBeenCalledWith(REQUEST_ID, "complete");
    expect(await loadLogMutationRecoveryJournal(AUTHORITY, storage)).toEqual([]);
  });

  test("exact Complete payload is retried through dailyLogs.markDayComplete", async () => {
    const storage = memoryStorage();
    const record = { ...completeRecord(), state: "confirmed_non_commit" as const };
    const markDayComplete = jest.fn(async () => ({
      logged_date: "2026-08-18",
      completed_at: "2026-08-18T20:00:00.000000Z",
    }));

    const outcome = await retryLogMutationRecoveryRecord(
      record,
      null,
      dependencies({ markDayComplete }),
      storage,
    );

    expect(outcome).toBe("confirmed");
    expect(markDayComplete).toHaveBeenCalledWith(record.payload.operation === "complete" ? record.payload.input : null);
  });

  test("confirmed Complete retry remains confirmed when recovery cleanup storage fails", async () => {
    const backing = memoryStorage();
    let writeCount = 0;

    const storage: RecoveryStorage = {
      getItem: backing.getItem,
      removeItem: backing.removeItem,
      setItem: jest.fn(
        async (
          key: string,
          value: string,
        ) => {
          writeCount += 1;

          // First write persists submitted state.
          // Second write is confirmed-success cleanup.
          if (writeCount === 2) {
            throw new Error(
              "recovery cleanup unavailable",
            );
          }

          await backing.setItem(
            key,
            value,
          );
        },
      ),
    };

    const record = {
      ...completeRecord(),
      state: "confirmed_non_commit" as const,
    };

    const markDayComplete = jest.fn(
      async () => ({
        logged_date: "2026-08-18",
        completed_at:
          "2026-08-18T20:00:00.000000Z",
      }),
    );

    const outcome =
      await retryLogMutationRecoveryRecord(
        record,
        null,
        dependencies({
          markDayComplete,
        }),
        storage,
      );

    expect(outcome).toBe("confirmed");
    expect(markDayComplete)
      .toHaveBeenCalledTimes(1);

    // Cleanup failed, so durable submitted evidence may remain.
    // It must be reconciled later rather than reclassifying the
    // already-authoritative success as non-commit or unresolved.
    const [persisted] =
      await loadLogMutationRecoveryJournal(
        AUTHORITY,
        storage,
      );

    expect(persisted).toEqual(
      expect.objectContaining({
        client_request_id:
          REQUEST_ID,
        state: "submitted",
        payload: record.payload,
      }),
    );
  });

  test("a repeated confirmed non-commit preserves the same Complete retry intent", async () => {
    const storage = memoryStorage();
    const record = {
      ...completeRecord(),
      state: "confirmed_non_commit" as const,
    };

    const markDayComplete = jest.fn(
      async () => {
        throw new RuntimeError({
          kind: "conflict",
          code: "complete_not_committed",
          message: "Complete was not committed.",
          retryable: true,
          mutationOutcome: "confirmed_non_commit",
        });
      },
    );

    const outcome =
      await retryLogMutationRecoveryRecord(
        record,
        null,
        dependencies({ markDayComplete }),
        storage,
      );

    expect(outcome).toBe("retryable");
    expect(markDayComplete).toHaveBeenCalledWith(
      record.payload.operation === "complete"
        ? record.payload.input
        : null,
    );

    const [persisted] =
      await loadLogMutationRecoveryJournal(
        AUTHORITY,
        storage,
      );

    expect(persisted).toEqual(
      expect.objectContaining({
        client_request_id: REQUEST_ID,
        state: "confirmed_non_commit",
        payload: record.payload,
      }),
    );
  });

  test("same-date gate blocks only unresolved nutrition-changing work", () => {
    const create = createLogMutationRecoveryRecord({
      authority: AUTHORITY,
      clientRequestId: "create-request",
      mutationType: "create",
      sourceDate: "2026-08-18",
      displayContext: { item_name: null, amount_label: null, meal_label: null },
    });
    const move = createLogMutationRecoveryRecord({
      authority: AUTHORITY,
      clientRequestId: "move-request",
      mutationType: "move",
      targetId: "log-1",
      sourceDate: "2026-08-17",
      destinationDate: "2026-08-18",
      displayContext: { item_name: null, amount_label: null, meal_label: null },
      payload: {
        operation: "update",
        log_id: "log-1",
        input: { client_request_id: "move-request", logged_date: "2026-08-18" },
      },
    });
    const noteEdit = createLogMutationRecoveryRecord({
      authority: AUTHORITY,
      clientRequestId: "note-request",
      mutationType: "edit",
      targetId: "log-2",
      sourceDate: "2026-08-18",
      displayContext: { item_name: null, amount_label: null, meal_label: null },
      payload: {
        operation: "update",
        log_id: "log-2",
        input: { client_request_id: "note-request", notes: "metadata only" },
      },
    });
    const confirmedNonCommit = { ...create, state: "confirmed_non_commit" as const };
    const complete = completeRecord("submitted");

    expect(hasUnresolvedNutritionMutationForDate([create], "2026-08-18")).toBe(true);
    expect(hasUnresolvedNutritionMutationForDate([move], "2026-08-17")).toBe(true);
    expect(hasUnresolvedNutritionMutationForDate([move], "2026-08-18")).toBe(true);
    expect(hasUnresolvedNutritionMutationForDate([noteEdit], "2026-08-18")).toBe(false);
    expect(hasUnresolvedNutritionMutationForDate([confirmedNonCommit], "2026-08-18")).toBe(false);
    expect(hasUnresolvedNutritionMutationForDate([complete], "2026-08-18")).toBe(false);
  });
});

type CompletePostgresStatusTrace = {
  schema_version: 1;
  operation: "complete";
  client_request_id: string;
  owner_id: string;
  settlement: "committed" | "rolled_back";
  source_date: string;
  destination_date: null;
  request_payload: Record<string, unknown>;
  writer_backend_pid: number;
  reader_backend_pids: number[];
  returned_before_release: boolean[];
  status_responses: Array<{ status_code: number; body: string }>;
};

const actualPostgresCoupledTest = process.env.GH278_REQUIRE_STATUS_TRACE === "1" ? test : test.skip;

actualPostgresCoupledTest(
  "automatic Complete recovery consumes the actual PostgreSQL status trace after reload",
  async () => {
    const tracePath = process.env.GH278_STATUS_TRACE_PATH;
    if (!tracePath) throw new Error("GH278_STATUS_TRACE_PATH is required for coupled Complete recovery");
    const traces = readFileSync(tracePath, "utf8")
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => JSON.parse(line) as CompletePostgresStatusTrace)
      .filter((trace) => trace.operation === "complete" && trace.settlement === "committed");
    if (traces.length !== 1) {
      throw new Error(`expected one committed PostgreSQL Complete trace; found ${traces.length}`);
    }
    const [trace] = traces;
    if (trace.schema_version !== 1 || trace.status_responses.length !== 3) {
      throw new Error("malformed PostgreSQL Complete status trace");
    }
    if (trace.returned_before_release.join(",") !== "true,true,false") {
      throw new Error("Complete trace does not prove two reads returned before writer release");
    }
    if (trace.reader_backend_pids.slice(0, 2).some((pid) => pid === trace.writer_backend_pid)) {
      throw new Error("Complete trace does not identify independent reader sessions");
    }
    const statuses = trace.status_responses.map(({ status_code, body }) => {
      if (status_code !== 200 || typeof body !== "string") {
        throw new Error("malformed serialized Complete status response");
      }
      return parseDailyLogMutationStatus(JSON.parse(body));
    });
    if (statuses.map((item) => item.status).join(",") !== "unresolved,unresolved,confirmed_success") {
      throw new Error("unexpected serialized PostgreSQL Complete status sequence");
    }
    if (statuses.some(
      (item) => item.operation !== "complete" || item.client_request_id !== trace.client_request_id,
    )) {
      throw new Error("serialized PostgreSQL Complete status identity mismatch");
    }
    if (trace.request_payload.client_request_id !== trace.client_request_id) {
      throw new Error("submitted Complete payload identity mismatch");
    }

    const record = createLogMutationRecoveryRecord({
      authority: AUTHORITY,
      clientRequestId: trace.client_request_id,
      mutationType: "complete",
      sourceDate: trace.source_date,
      displayContext: { item_name: null, amount_label: null, meal_label: null },
      payload: {
        operation: "complete",
        input: trace.request_payload as never,
      },
    });
    const persistedStorage = memoryStorage();
    await upsertLogMutationRecoveryRecord({ ...record, state: "submitted" }, persistedStorage);
    if (!persistedStorage.value) throw new Error("submitted Complete record was not persisted");
    const storage = memoryStorage(persistedStorage.value);
    const queryClient = new QueryClient();
    const date = trace.source_date;
    queryClient.setQueryData(["logs", date], []);
    queryClient.setQueryData(["daily-summary", date], { date });
    queryClient.setQueryData(["target-comparison", date], { date });
    queryClient.setQueryData(["future-logs", date], []);
    queryClient.setQueryData(["foods", "recent"], []);
    queryClient.setQueryData(["logs", "recent-entries"], []);

    const recoveryDependencies = dependencies();
    let statusRead = 0;
    const statusReader = jest.fn(async (requestId: string, operation: DailyLogMutationStatus["operation"]) => {
      statusRead += 1;
      expect(requestId).toBe(trace.client_request_id);
      expect(operation).toBe("complete");
      if (statusRead === 1) throw new Error("simulated transport loss before Complete status read");
      const actualStatus = statuses[statusRead - 2];
      if (!actualStatus) throw new Error("automatic Complete poll exceeded the serialized trace");
      return actualStatus;
    });

    let stop: (() => void) | undefined;
    jest.useFakeTimers();
    try {
      stop = startLogMutationRecovery(queryClient, recoveryDependencies, {
        storage,
        statusReader,
        retryDelayMs: 5,
      });
      for (let index = 0; index < 40; index += 1) await Promise.resolve();
      expect(statusReader).toHaveBeenCalledTimes(1);
      expect((await loadLogMutationRecoveryJournal(AUTHORITY, storage))[0]).toEqual(
        expect.objectContaining({ client_request_id: trace.client_request_id, state: "submitted" }),
      );

      await jest.advanceTimersByTimeAsync(5);
      for (let index = 0; index < 40; index += 1) await Promise.resolve();
      expect(statusReader).toHaveBeenCalledTimes(2);
      expect((await loadLogMutationRecoveryJournal(AUTHORITY, storage))[0]).toEqual(
        expect.objectContaining({ client_request_id: trace.client_request_id, state: "submitted" }),
      );

      await jest.advanceTimersByTimeAsync(10);
      for (let index = 0; index < 40; index += 1) await Promise.resolve();
      expect(statusReader).toHaveBeenCalledTimes(3);
      expect((await loadLogMutationRecoveryJournal(AUTHORITY, storage))[0]).toEqual(
        expect.objectContaining({ client_request_id: trace.client_request_id, state: "submitted" }),
      );

      await jest.advanceTimersByTimeAsync(20);
      for (let index = 0; index < 40; index += 1) await Promise.resolve();
      expect(statusReader).toHaveBeenCalledTimes(4);
      expect(await loadLogMutationRecoveryJournal(AUTHORITY, storage)).toEqual([]);
      expect(statusReader.mock.calls.map((call) => call[1])).toEqual([
        "complete",
        "complete",
        "complete",
        "complete",
      ]);
      expect(record.payload).toEqual({ operation: "complete", input: trace.request_payload });
      expect(statuses[2].completion).toEqual(expect.objectContaining({ logged_date: date }));
      expect(queryClient.getQueryState(["logs", date])?.isInvalidated).toBe(true);
      expect(queryClient.getQueryState(["daily-summary", date])?.isInvalidated).toBe(true);
      expect(queryClient.getQueryState(["target-comparison", date])?.isInvalidated).toBe(true);
      expect(queryClient.getQueryState(["future-logs", date])?.isInvalidated).toBe(true);
      expect(queryClient.getQueryState(["foods", "recent"])?.isInvalidated).toBe(true);
      expect(queryClient.getQueryState(["logs", "recent-entries"])?.isInvalidated).toBe(true);
      expect(recoveryDependencies.dailyLogs.markDayComplete).not.toHaveBeenCalled();
      expect(recoveryDependencies.dailyLogs.create).not.toHaveBeenCalled();
      expect(recoveryDependencies.dailyLogs.update).not.toHaveBeenCalled();
      expect(recoveryDependencies.dailyLogs.delete).not.toHaveBeenCalled();
    } finally {
      stop?.();
      queryClient.clear();
      jest.useRealTimers();
    }
  },
);
