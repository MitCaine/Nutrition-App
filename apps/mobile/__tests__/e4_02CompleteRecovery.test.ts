import type { DailyLogMutationStatus } from "../src/features/logging/api/types";
import {
  createLogMutationRecoveryRecord,
  hasUnresolvedNutritionMutationForDate,
  loadLogMutationRecoveryJournal,
  reconcileLogMutationRecoveryRecord,
  retryLogMutationRecoveryRecord,
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
