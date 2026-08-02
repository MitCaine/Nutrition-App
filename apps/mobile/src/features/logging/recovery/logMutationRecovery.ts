import AsyncStorage from "@react-native-async-storage/async-storage";
import { AppState, type AppStateStatus } from "react-native";
import type { QueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { clientOwnerScope, ApiError } from "../../../shared/api/client";
import {
  createLog,
  deleteLog,
  getLogMutationStatus,
  updateLog,
} from "../api/logApi";
import type {
  DailyLog,
  DailyLogCreateInput,
  DailyLogDeleteInput,
  DailyLogMutationStatus,
  DailyLogUpdateInput,
} from "../api/types";
import {
  invalidateFoodRecents,
  invalidateLogDateCaches,
  invalidateRecentEntries,
  projectConfirmedDelete,
  projectConfirmedLog,
} from "../hooks/useLogs";
import { logEditErrorCode } from "../utils/logEditErrors";

export const LOG_MUTATION_RECOVERY_STORAGE_KEY = "nutrition.log-mutation-recovery.v2";
// The exact-payload schema is a new durable shape. Older journals must remain
// opaque and locked rather than being interpreted as unrestricted work.
export const LOG_MUTATION_RECOVERY_VERSION = 2;

const INITIAL_RETRY_DELAY_MS = 2_000;
const MAX_RETRY_DELAY_MS = 60_000;

export type LogMutationRecoveryMutation = "create" | "edit" | "move" | "delete";
export type LogMutationRecoveryState =
  | "prepared"
  | "submitted"
  | "reconciling"
  | "confirmed_non_commit"
  | "dismissed";

export type LogMutationRecoveryActionableState = Exclude<LogMutationRecoveryState, "dismissed">;

export type RecoveryPayload =
  | { operation: "create"; input: DailyLogCreateInput }
  | { operation: "update"; log_id: string; input: Partial<DailyLogUpdateInput> }
  | { operation: "delete"; log_id: string; input: DailyLogDeleteInput };

export type LogMutationRecoveryRecord = {
  version: typeof LOG_MUTATION_RECOVERY_VERSION;
  owner_scope: string;
  id: string;
  client_request_id: string;
  mutation_type: LogMutationRecoveryMutation;
  target_id: string | null;
  source_date: string;
  destination_date: string | null;
  payload: RecoveryPayload;
  created_at: string;
  last_reconciliation_attempt: string | null;
  reconciliation_attempts: number;
  state: LogMutationRecoveryState;
  dismissed_at: string | null;
  /** Retains the actionable state while a prompt is hidden by dismissal. */
  dismissed_from_state?: Exclude<LogMutationRecoveryState, "dismissed"> | null;
};

export type RecoveryStorage = Pick<
  typeof AsyncStorage,
  "getItem" | "setItem" | "removeItem"
>;

type StoredEnvelope = {
  version: number;
  records: unknown[];
};

export type RecoveryJournalHealth = {
  ready: boolean;
  unknownVersion: boolean;
  malformedRecordCount: number;
  storageError: boolean;
};

export type RecoveryJournalState = RecoveryJournalHealth & {
  records: LogMutationRecoveryRecord[];
};

export type RecoveryReconcileResult =
  | "confirmed"
  | "discarded"
  | "pending"
  | "retryable";

export class RecoveryStorageError extends Error {
  constructor(message = "Local recovery storage is unavailable.") {
    super(message);
    this.name = "RecoveryStorageError";
  }
}

/** Resolve a hidden record's underlying lifecycle without changing its UX state. */
export function recoveryActionableState(
  record: LogMutationRecoveryRecord,
): LogMutationRecoveryActionableState {
  if (record.state !== "dismissed") return record.state;
  // Journals written before dismissed_from_state was introduced represented
  // unresolved submissions. Treat them conservatively as submitted.
  return record.dismissed_from_state ?? "submitted";
}

const defaultStorage: RecoveryStorage = AsyncStorage;
let storageQueue: Promise<void> = Promise.resolve();
const journalListeners = new Set<() => void>();
let cachedState: RecoveryJournalState = {
  ready: true,
  unknownVersion: false,
  malformedRecordCount: 0,
  storageError: false,
  records: [],
};
let bootstrapStarted = false;

function enqueueStorage<T>(work: () => Promise<T>): Promise<T> {
  const next = storageQueue.then(work, work);
  storageQueue = next.then(() => undefined, () => undefined);
  return next;
}

function notifyJournalChanged(): void {
  for (const listener of journalListeners) listener();
}

function isPayload(value: unknown): value is RecoveryPayload {
  if (typeof value !== "object" || value === null || !("operation" in value)) return false;
  const candidate = value as { operation?: unknown; input?: unknown; log_id?: unknown };
  if (candidate.operation === "create") return typeof candidate.input === "object" && candidate.input !== null;
  return (
    (candidate.operation === "update" || candidate.operation === "delete")
    && typeof candidate.log_id === "string"
    && typeof candidate.input === "object"
    && candidate.input !== null
  );
}

function isRecord(value: unknown): value is LogMutationRecoveryRecord {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<LogMutationRecoveryRecord>;
  return (
    candidate.version === LOG_MUTATION_RECOVERY_VERSION
    && typeof candidate.owner_scope === "string"
    && typeof candidate.id === "string"
    && typeof candidate.client_request_id === "string"
    && ["create", "edit", "move", "delete"].includes(candidate.mutation_type as string)
    && (typeof candidate.target_id === "string" || candidate.target_id === null)
    && typeof candidate.source_date === "string"
    && (typeof candidate.destination_date === "string" || candidate.destination_date === null)
    && isPayload(candidate.payload)
    && typeof candidate.created_at === "string"
    && (typeof candidate.last_reconciliation_attempt === "string" || candidate.last_reconciliation_attempt === null)
    && typeof candidate.reconciliation_attempts === "number"
    && ["prepared", "submitted", "reconciling", "confirmed_non_commit", "dismissed"].includes(candidate.state as string)
    && (typeof candidate.dismissed_at === "string" || candidate.dismissed_at === null)
    && (candidate.dismissed_from_state === undefined || candidate.dismissed_from_state === null || ["prepared", "submitted", "reconciling", "confirmed_non_commit"].includes(candidate.dismissed_from_state as string))
  );
}

function stableRecords(records: LogMutationRecoveryRecord[]): LogMutationRecoveryRecord[] {
  const unique = new Map<string, LogMutationRecoveryRecord>();
  for (const record of records) {
    if (!unique.has(record.id)) unique.set(record.id, record);
  }
  return [...unique.values()].sort((left, right) => {
    const created = left.created_at.localeCompare(right.created_at);
    return created || left.id.localeCompare(right.id);
  });
}

function setCachedState(next: RecoveryJournalState): void {
  cachedState = next;
  notifyJournalChanged();
}

type ReadResult = {
  envelope: StoredEnvelope | null;
  records: LogMutationRecoveryRecord[];
  opaqueRecords: unknown[];
  health: RecoveryJournalHealth;
};

async function readStored(storage: RecoveryStorage): Promise<ReadResult> {
  try {
    const raw = await storage.getItem(LOG_MUTATION_RECOVERY_STORAGE_KEY);
    if (!raw) {
      return {
        envelope: null,
        records: [],
        opaqueRecords: [],
        health: { ready: true, unknownVersion: false, malformedRecordCount: 0, storageError: false },
      };
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      return {
        envelope: null,
        records: [],
        opaqueRecords: [raw],
        health: { ready: false, unknownVersion: false, malformedRecordCount: 1, storageError: false },
      };
    }
    if (typeof parsed !== "object" || parsed === null || !("version" in parsed) || !("records" in parsed) || !Array.isArray((parsed as { records?: unknown }).records)) {
      return {
        envelope: null,
        records: [],
        opaqueRecords: [parsed],
        health: { ready: false, unknownVersion: false, malformedRecordCount: 1, storageError: false },
      };
    }
    const envelope = parsed as StoredEnvelope;
    if (envelope.version !== LOG_MUTATION_RECOVERY_VERSION) {
      return {
        envelope,
        records: [],
        opaqueRecords: [parsed],
        health: { ready: false, unknownVersion: true, malformedRecordCount: 0, storageError: false },
      };
    }
    const valid = envelope.records.filter(isRecord);
    return {
      envelope,
      records: stableRecords(valid.filter((record) => record.owner_scope === clientOwnerScope())),
      opaqueRecords: envelope.records.filter((record) => !isRecord(record)),
      health: {
        ready: envelope.records.length === valid.length,
        unknownVersion: false,
        malformedRecordCount: envelope.records.length - valid.length,
        storageError: false,
      },
    };
  } catch {
    return {
      envelope: null,
      records: [],
      opaqueRecords: [],
      health: { ready: false, unknownVersion: false, malformedRecordCount: 0, storageError: true },
    };
  }
}

async function writeStored(
  storage: RecoveryStorage,
  existing: ReadResult,
  records: LogMutationRecoveryRecord[],
): Promise<void> {
  if (existing.health.unknownVersion || existing.health.storageError) {
    throw new RecoveryStorageError("Recovery journal is not writable in its current state.");
  }
  const otherOwnerRecords = (existing.envelope?.records ?? []).filter((record) =>
    isRecord(record) && record.owner_scope !== clientOwnerScope());
  const payload = {
    version: LOG_MUTATION_RECOVERY_VERSION,
    records: [...existing.opaqueRecords, ...otherOwnerRecords, ...stableRecords(records)],
  } satisfies StoredEnvelope;
  await storage.setItem(LOG_MUTATION_RECOVERY_STORAGE_KEY, JSON.stringify(payload));
}

export function getRecoveryJournalState(): RecoveryJournalState {
  return { ...cachedState, records: [...cachedState.records] };
}

export function getRecoveryJournalHealth(): RecoveryJournalHealth {
  const { records: _records, ...health } = cachedState;
  return health;
}

export function beginLogMutationRecoveryBootstrap(): void {
  if (bootstrapStarted) return;
  bootstrapStarted = true;
  cachedState = {
    ...cachedState,
    ready: false,
  };
}

export function subscribeToLogMutationRecovery(listener: () => void): () => void {
  journalListeners.add(listener);
  return () => journalListeners.delete(listener);
}

export async function loadLogMutationRecoveryJournal(
  storage: RecoveryStorage = defaultStorage,
): Promise<LogMutationRecoveryRecord[]> {
  return enqueueStorage(async () => {
    const result = await readStored(storage);
    setCachedState({ ...result.health, records: result.records });
    return result.records;
  });
}

export function useLogMutationRecoveryJournal(): RecoveryJournalState {
  const [state, setState] = useState<RecoveryJournalState>(getRecoveryJournalState);
  useEffect(() => {
    let active = true;
    const update = () => {
      if (active) setState(getRecoveryJournalState());
    };
    const unsubscribe = subscribeToLogMutationRecovery(update);
    void loadLogMutationRecoveryJournal().then(update);
    return () => {
      active = false;
      unsubscribe();
    };
  }, []);
  return state;
}

export async function upsertLogMutationRecoveryRecord(
  record: LogMutationRecoveryRecord,
  storage: RecoveryStorage = defaultStorage,
): Promise<void> {
  await enqueueStorage(async () => {
    const existing = await readStored(storage);
    const records = stableRecords([
      ...existing.records.filter((candidate) => candidate.id !== record.id),
      record,
    ]);
    await writeStored(storage, existing, records);
    setCachedState({ ...existing.health, ready: existing.health.malformedRecordCount === 0, records });
  });
}

export async function removeLogMutationRecoveryRecord(
  recordOrId: LogMutationRecoveryRecord | string,
  storage: RecoveryStorage = defaultStorage,
): Promise<void> {
  const id = typeof recordOrId === "string" ? recordOrId : recordOrId.id;
  await enqueueStorage(async () => {
    const existing = await readStored(storage);
    const records = existing.records.filter((candidate) => candidate.id !== id);
    await writeStored(storage, existing, records);
    setCachedState({ ...existing.health, ready: existing.health.malformedRecordCount === 0, records });
  });
}

export async function dismissLogMutationRecoveryRecord(
  record: LogMutationRecoveryRecord,
  storage: RecoveryStorage = defaultStorage,
): Promise<void> {
  await upsertLogMutationRecoveryRecord({
    ...record,
    state: "dismissed",
    dismissed_at: new Date().toISOString(),
    dismissed_from_state: record.state === "dismissed" ? record.dismissed_from_state ?? null : record.state,
  }, storage);
}

export async function markLogMutationRecoveryAttempt(
  record: LogMutationRecoveryRecord,
  storage: RecoveryStorage = defaultStorage,
): Promise<LogMutationRecoveryRecord> {
  const dismissed = record.state === "dismissed";
  const nextRecord: LogMutationRecoveryRecord = {
    ...record,
    last_reconciliation_attempt: new Date().toISOString(),
    reconciliation_attempts: record.reconciliation_attempts + 1,
    state: dismissed ? "dismissed" : "reconciling",
    dismissed_from_state: dismissed ? "reconciling" : null,
  };
  await upsertLogMutationRecoveryRecord(nextRecord, storage);
  return nextRecord;
}

function markRecoverySubmitted(record: LogMutationRecoveryRecord): LogMutationRecoveryRecord {
  return record.state === "dismissed"
    ? { ...record, state: "dismissed", dismissed_from_state: "submitted" }
    : { ...record, state: "submitted", dismissed_from_state: null };
}

/**
 * Crash-safe foreground boundary: a prepared intent is durably committed,
 * then explicitly marked submitted, before the network request is sent.
 */
export async function persistRecoveryBeforeTransmission(
  record: LogMutationRecoveryRecord,
  storage: RecoveryStorage = defaultStorage,
): Promise<LogMutationRecoveryRecord> {
  try {
    await upsertLogMutationRecoveryRecord(record, storage);
    const submitted: LogMutationRecoveryRecord = {
      ...record,
      state: "submitted",
    };
    await upsertLogMutationRecoveryRecord(submitted, storage);
    return submitted;
  } catch (error) {
    if (error instanceof RecoveryStorageError) throw error;
    throw new RecoveryStorageError();
  }
}

export function createLogMutationRecoveryRecord(input: {
  clientRequestId: string;
  mutationType: LogMutationRecoveryMutation;
  targetId?: string | null;
  /** Legacy construction alias retained for in-process callers during the bounded correction. */
  logId?: string | null;
  sourceDate: string;
  destinationDate?: string | null;
  payload?: RecoveryPayload;
  createdAt?: string;
}): LogMutationRecoveryRecord {
  const createdAt = input.createdAt ?? new Date().toISOString();
  const targetId = input.targetId ?? input.logId ?? null;
  const payload: RecoveryPayload = input.payload ?? (input.mutationType === "create"
    ? {
        operation: "create",
        input: {
          client_request_id: input.clientRequestId,
          food_item_id: "",
          logged_date: input.sourceDate,
          amount_quantity: "1",
          amount_unit: "g",
        },
      }
    : input.mutationType === "delete"
      ? { operation: "delete", log_id: targetId ?? "", input: { client_request_id: input.clientRequestId } }
      : { operation: "update", log_id: targetId ?? "", input: { client_request_id: input.clientRequestId } });
  return {
    version: LOG_MUTATION_RECOVERY_VERSION,
    owner_scope: clientOwnerScope(),
    id: `${input.mutationType}:${input.clientRequestId}`,
    client_request_id: input.clientRequestId,
    mutation_type: input.mutationType,
    target_id: targetId,
    source_date: input.sourceDate,
    destination_date: input.destinationDate ?? null,
    payload,
    created_at: createdAt,
    last_reconciliation_attempt: null,
    reconciliation_attempts: 0,
    state: "prepared",
    dismissed_at: null,
    dismissed_from_state: null,
  };
}

export function isUncertainLogMutationError(error: unknown): boolean {
  if (error instanceof RecoveryStorageError) return false;
  if (error instanceof ApiError) {
    return error.status >= 500
      || error.status === 408
      || logEditErrorCode(error) === "log_mutation_unresolved";
  }
  return true;
}

function operationFor(record: LogMutationRecoveryRecord): DailyLogMutationStatus["operation"] {
  return record.payload.operation === "create"
    ? "create"
    : record.payload.operation === "delete"
      ? "delete"
      : "update";
}

function affectedDates(record: LogMutationRecoveryRecord, status?: DailyLogMutationStatus): string[] {
  return Array.from(new Set([
    record.source_date,
    record.destination_date,
    status?.source_logged_date,
    status?.destination_logged_date,
    status?.result?.logged_date,
  ].filter((value): value is string => Boolean(value))));
}

function refreshAffectedDates(queryClient: QueryClient, record: LogMutationRecoveryRecord, status?: DailyLogMutationStatus): void {
  for (const date of affectedDates(record, status)) {
    invalidateLogDateCaches(queryClient, date);
    queryClient.invalidateQueries({ queryKey: ["future-logs", date] });
  }
  invalidateFoodRecents(queryClient);
  invalidateRecentEntries(queryClient);
}

function projectConfirmedRecovery(
  queryClient: QueryClient | null,
  record: LogMutationRecoveryRecord,
  status: DailyLogMutationStatus,
): void {
  if (queryClient === null) return;
  if (record.payload.operation === "delete") {
    const logId = status.log_id ?? record.target_id;
    if (logId) projectConfirmedDelete(queryClient, record.source_date, logId);
  } else if (status.result) {
    projectConfirmedLog(queryClient, status.source_logged_date ?? record.source_date, status.result);
  }
  refreshAffectedDates(queryClient, record, status);
}

export async function reconcileLogMutationRecoveryRecord(
  record: LogMutationRecoveryRecord,
  queryClient: QueryClient | null,
  options: {
    statusReader?: typeof getLogMutationStatus;
    storage?: RecoveryStorage;
  } = {},
): Promise<RecoveryReconcileResult> {
  const storage = options.storage ?? defaultStorage;
  try {
    const status = await (options.statusReader ?? getLogMutationStatus)(record.client_request_id, operationFor(record));
    if (status.status === "confirmed_success") {
      projectConfirmedRecovery(queryClient, record, status);
      await removeLogMutationRecoveryRecord(record, storage);
      return "confirmed";
    }
    if (status.status === "confirmed_non_commit") {
      await upsertLogMutationRecoveryRecord({
        ...record,
        state: record.state === "dismissed" ? "dismissed" : "confirmed_non_commit",
        dismissed_from_state: record.state === "dismissed" ? "confirmed_non_commit" : null,
      }, storage);
      return "retryable";
    }
    if (status.status === "conflict") {
      if (queryClient) refreshAffectedDates(queryClient, record, status);
      await removeLogMutationRecoveryRecord(record, storage);
      return "discarded";
    }
    return "pending";
  } catch {
    return "pending";
  }
}

export async function retryLogMutationRecoveryRecord(
  record: LogMutationRecoveryRecord,
  queryClient: QueryClient | null,
  storage: RecoveryStorage = defaultStorage,
): Promise<RecoveryReconcileResult> {
  const submitted = { ...record, state: "submitted" as const, dismissed_at: null, dismissed_from_state: null };
  await upsertLogMutationRecoveryRecord(submitted, storage);
  try {
    let result: DailyLog | undefined;
    if (submitted.payload.operation === "create") {
      result = await createLog(submitted.payload.input);
    } else if (submitted.payload.operation === "update") {
      result = await updateLog(submitted.payload.log_id, submitted.payload.input);
    } else {
      await deleteLog(submitted.payload.log_id, submitted.payload.input);
    }
    const status: DailyLogMutationStatus = {
      operation: operationFor(submitted),
      client_request_id: submitted.client_request_id,
      status: "confirmed_success",
      log_id: result?.id ?? submitted.target_id,
      result: result ?? null,
      source_logged_date: submitted.source_date,
      destination_logged_date: result?.logged_date ?? submitted.destination_date,
    };
    projectConfirmedRecovery(queryClient, submitted, status);
    await removeLogMutationRecoveryRecord(submitted, storage);
    return "confirmed";
  } catch (error) {
    if (isUncertainLogMutationError(error)) return "pending";
    if (queryClient) refreshAffectedDates(queryClient, submitted);
    await removeLogMutationRecoveryRecord(submitted, storage);
    return "discarded";
  }
}

export function recoveryRecordsOverlap(
  record: LogMutationRecoveryRecord,
  candidate: { mutationType: LogMutationRecoveryMutation; sourceDate: string; destinationDate?: string | null; targetId?: string | null; foodId?: string | null },
): boolean {
  if (record.target_id && candidate.targetId && record.target_id === candidate.targetId) return true;
  if (record.source_date !== candidate.sourceDate && record.destination_date !== candidate.sourceDate && record.source_date !== candidate.destinationDate && record.destination_date !== candidate.destinationDate) return false;
  if (record.mutation_type !== "create" || candidate.mutationType !== "create") return Boolean(record.target_id && candidate.targetId && record.target_id === candidate.targetId);
  if (!candidate.foodId || record.payload.operation !== "create") return true;
  return record.payload.input.food_item_id === candidate.foodId;
}

export function hasOverlappingRecovery(
  records: LogMutationRecoveryRecord[],
  candidate: Parameters<typeof recoveryRecordsOverlap>[1],
): LogMutationRecoveryRecord | null {
  return records.find((record) => recoveryRecordsOverlap(record, candidate)) ?? null;
}

export type RecoveryManagerOptions = {
  storage?: RecoveryStorage;
  statusReader?: typeof getLogMutationStatus;
  retryDelayMs?: number;
};

export function startLogMutationRecovery(
  queryClient: QueryClient,
  options: RecoveryManagerOptions = {},
): () => void {
  const storage = options.storage ?? defaultStorage;
  const baseDelay = options.retryDelayMs ?? INITIAL_RETRY_DELAY_MS;
  let stopped = false;
  let running = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let retryNumber = 0;
  let journalDirty = false;

  const schedule = (delay: number) => {
    if (stopped || timer !== null) return;
    const scheduled = setTimeout(() => {
      timer = null;
      void run();
    }, delay);
    timer = scheduled;
    // Jest/Node timers should not keep a test process alive after the manager
    // is stopped. React Native timer handles do not expose unref().
    if (typeof scheduled === "object" && scheduled !== null && "unref" in scheduled) {
      (scheduled as { unref: () => void }).unref();
    }
  };

  const run = async () => {
    if (stopped || running) return;
    running = true;
    journalDirty = false;
    try {
      const state = await loadLogMutationRecoveryJournal(storage).then(() => getRecoveryJournalState());
      if (!state.ready) {
        return;
      }
      let hasPending = false;
      for (const record of state.records) {
        if (stopped) break;
        const actionableState = recoveryActionableState(record);
        if (actionableState === "prepared" || actionableState === "confirmed_non_commit") continue;
        const attempted = await markLogMutationRecoveryAttempt(record, storage);
        const outcome = await reconcileLogMutationRecoveryRecord(attempted, queryClient, options);
        if (outcome === "confirmed" || outcome === "discarded") {
          retryNumber = 0;
        } else if (outcome === "retryable") {
          // Confirmed non-commit is intentionally user-retryable, not an
          // automatically replayed offline queue item.
        } else {
          await upsertLogMutationRecoveryRecord(markRecoverySubmitted(attempted), storage);
          hasPending = true;
        }
      }
      if (hasPending) {
        retryNumber += 1;
        schedule(Math.min(MAX_RETRY_DELAY_MS, baseDelay * (2 ** Math.min(retryNumber - 1, 5))));
      }
    } catch {
      retryNumber += 1;
      schedule(Math.min(MAX_RETRY_DELAY_MS, baseDelay * (2 ** Math.min(retryNumber - 1, 5))));
    } finally {
      running = false;
      if (journalDirty) schedule(250);
    }
  };

  const unsubscribeJournal = subscribeToLogMutationRecovery(() => {
    if (running) journalDirty = true;
    else schedule(250);
  });
  const appStateSubscription = AppState.addEventListener("change", (nextState: AppStateStatus) => {
    if (nextState === "active") void run();
  });
  void run();

  return () => {
    stopped = true;
    journalDirty = false;
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    unsubscribeJournal();
    appStateSubscription.remove();
  };
}
