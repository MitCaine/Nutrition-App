import AsyncStorage from "@react-native-async-storage/async-storage";
import { AppState, type AppStateStatus } from "react-native";
import type { QueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import type {
  CompleteDailyLogsRuntime,
  DailyLogsRuntime,
} from "../../../runtime/NutritionRuntime";
import type { RuntimeAuthorityIdentity } from "../../../runtime/authorityIdentity";
import { RuntimeError } from "../../../runtime/RuntimeError";
import type {
  DailyLog,
  DailyLogCompleteInput,
  DailyLogCompletion,
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

// Keep the established storage key so version-2 unresolved work can be
// upgraded in place rather than becoming an orphaned parallel journal.
export const LOG_MUTATION_RECOVERY_STORAGE_KEY = "nutrition.log-mutation-recovery.v2";
export const LOG_MUTATION_RECOVERY_VERSION = 3;
const PREVIOUS_LOG_MUTATION_RECOVERY_VERSION = 2;

const INITIAL_RETRY_DELAY_MS = 2_000;
const MAX_RETRY_DELAY_MS = 60_000;

export type LogMutationRecoveryMutation = "create" | "edit" | "move" | "delete" | "complete";
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
  | { operation: "delete"; log_id: string; input: DailyLogDeleteInput }
  | { operation: "complete"; input: DailyLogCompleteInput };

/** Immutable, presentation-only identity captured when an intent is reviewed. */
export type RecoveryDisplayContext = Readonly<{
  item_name: string | null;
  amount_label: string | null;
  meal_label: string | null;
}>;

export type LogMutationRecoveryRecord = {
  version: typeof LOG_MUTATION_RECOVERY_VERSION;
  owner_scope: string;
  id: string;
  client_request_id: string;
  mutation_type: LogMutationRecoveryMutation;
  target_id: string | null;
  display_context: RecoveryDisplayContext;
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

export type LogMutationRecoveryDependencies = Readonly<{
  authority: RuntimeAuthorityIdentity;
  dailyLogs: Pick<
    DailyLogsRuntime,
    "getMutationStatus" | "create" | "update" | "delete"
  > & Partial<Pick<CompleteDailyLogsRuntime, "markDayComplete">>;
}>;

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
const journalListenersByScope = new Map<string, Set<() => void>>();
const cachedStateByScope = new Map<string, RecoveryJournalState>();
const bootstrapStartedScopes = new Set<string>();

function unloadedRecoveryState(): RecoveryJournalState {
  return {
    ready: false,
    unknownVersion: false,
    malformedRecordCount: 0,
    storageError: false,
    records: [],
  };
}

function cachedStateForScope(recoveryScope: string): RecoveryJournalState {
  return cachedStateByScope.get(recoveryScope) ?? unloadedRecoveryState();
}

function enqueueStorage<T>(work: () => Promise<T>): Promise<T> {
  const next = storageQueue.then(work, work);
  storageQueue = next.then(() => undefined, () => undefined);
  return next;
}

function notifyJournalChanged(recoveryScope: string): void {
  for (const listener of journalListenersByScope.get(recoveryScope) ?? []) listener();
}

function isPayload(value: unknown, allowComplete: boolean): value is RecoveryPayload {
  if (typeof value !== "object" || value === null || !("operation" in value)) return false;
  const candidate = value as { operation?: unknown; input?: unknown; log_id?: unknown };
  if (candidate.operation === "create") return typeof candidate.input === "object" && candidate.input !== null;
  if (allowComplete && candidate.operation === "complete") {
    return typeof candidate.input === "object" && candidate.input !== null;
  }
  return (
    (candidate.operation === "update" || candidate.operation === "delete")
    && typeof candidate.log_id === "string"
    && typeof candidate.input === "object"
    && candidate.input !== null
  );
}

function boundedDisplayValue(value: unknown, maximumCodePoints: number): string | null {
  if (typeof value !== "string") return null;
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) return null;
  const points = Array.from(normalized);
  return points.length > maximumCodePoints
    ? `${points.slice(0, Math.max(0, maximumCodePoints - 1)).join("")}…`
    : normalized;
}

function normalizedDisplayContext(value: unknown): RecoveryDisplayContext {
  const candidate = typeof value === "object" && value !== null
    ? value as Partial<RecoveryDisplayContext>
    : {};
  return {
    item_name: boundedDisplayValue(candidate.item_name, 160),
    amount_label: boundedDisplayValue(candidate.amount_label, 80),
    meal_label: boundedDisplayValue(candidate.meal_label, 80),
  };
}

type StoredCompatibleRecoveryRecord = Omit<LogMutationRecoveryRecord, "version" | "display_context"> & {
  version: number;
  display_context?: unknown;
};

function isAuthoritativeRecord(
  value: unknown,
  expectedVersion: number,
): value is StoredCompatibleRecoveryRecord {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<StoredCompatibleRecoveryRecord>;
  const currentVersion = expectedVersion === LOG_MUTATION_RECOVERY_VERSION;
  const allowedMutations = currentVersion
    ? ["create", "edit", "move", "delete", "complete"]
    : ["create", "edit", "move", "delete"];
  return (
    candidate.version === expectedVersion
    && typeof candidate.owner_scope === "string"
    && typeof candidate.id === "string"
    && typeof candidate.client_request_id === "string"
    && allowedMutations.includes(candidate.mutation_type as string)
    && (typeof candidate.target_id === "string" || candidate.target_id === null)
    && typeof candidate.source_date === "string"
    && (typeof candidate.destination_date === "string" || candidate.destination_date === null)
    && isPayload(candidate.payload, currentVersion)
    && typeof candidate.created_at === "string"
    && (typeof candidate.last_reconciliation_attempt === "string" || candidate.last_reconciliation_attempt === null)
    && typeof candidate.reconciliation_attempts === "number"
    && ["prepared", "submitted", "reconciling", "confirmed_non_commit", "dismissed"].includes(candidate.state as string)
    && (typeof candidate.dismissed_at === "string" || candidate.dismissed_at === null)
    && (candidate.dismissed_from_state === undefined || candidate.dismissed_from_state === null || ["prepared", "submitted", "reconciling", "confirmed_non_commit"].includes(candidate.dismissed_from_state as string))
  );
}

function normalizeStoredRecord(record: StoredCompatibleRecoveryRecord): LogMutationRecoveryRecord {
  return {
    ...record,
    version: LOG_MUTATION_RECOVERY_VERSION,
    display_context: normalizedDisplayContext(record.display_context),
  } as LogMutationRecoveryRecord;
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

function setCachedState(recoveryScope: string, next: RecoveryJournalState): void {
  cachedStateByScope.set(recoveryScope, next);
  notifyJournalChanged(recoveryScope);
}

type ReadResult = {
  envelope: StoredEnvelope | null;
  records: LogMutationRecoveryRecord[];
  opaqueRecords: unknown[];
  health: RecoveryJournalHealth;
};

async function readStored(storage: RecoveryStorage, recoveryScope: string): Promise<ReadResult> {
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
    if (
      envelope.version !== LOG_MUTATION_RECOVERY_VERSION
      && envelope.version !== PREVIOUS_LOG_MUTATION_RECOVERY_VERSION
    ) {
      return {
        envelope,
        records: [],
        opaqueRecords: [parsed],
        health: { ready: false, unknownVersion: true, malformedRecordCount: 0, storageError: false },
      };
    }
    const valid = envelope.records.filter((record) => isAuthoritativeRecord(record, envelope.version));
    const normalized = valid.map(normalizeStoredRecord);
    return {
      envelope,
      records: stableRecords(normalized.filter((record) => record.owner_scope === recoveryScope)),
      opaqueRecords: envelope.records.filter((record) => !isAuthoritativeRecord(record, envelope.version)),
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
  recoveryScope: string,
): Promise<void> {
  if (existing.health.unknownVersion || existing.health.storageError) {
    throw new RecoveryStorageError("Recovery journal is not writable in its current state.");
  }
  const sourceVersion = existing.envelope?.version ?? LOG_MUTATION_RECOVERY_VERSION;
  const otherOwnerRecords = (existing.envelope?.records ?? [])
    .filter((record) => isAuthoritativeRecord(record, sourceVersion))
    .map((record) => normalizeStoredRecord(record as StoredCompatibleRecoveryRecord))
    .filter((record) => record.owner_scope !== recoveryScope);
  const payload = {
    version: LOG_MUTATION_RECOVERY_VERSION,
    records: [...existing.opaqueRecords, ...otherOwnerRecords, ...stableRecords(records)],
  } satisfies StoredEnvelope;
  await storage.setItem(LOG_MUTATION_RECOVERY_STORAGE_KEY, JSON.stringify(payload));
}

export function getRecoveryJournalState(
  authority: RuntimeAuthorityIdentity,
): RecoveryJournalState {
  const state = cachedStateForScope(authority.recoveryScope);
  return { ...state, records: [...state.records] };
}

export function getRecoveryJournalHealth(
  authority: RuntimeAuthorityIdentity,
): RecoveryJournalHealth {
  const { records: _records, ...health } = cachedStateForScope(authority.recoveryScope);
  return health;
}

function beginLogMutationRecoveryBootstrap(authority: RuntimeAuthorityIdentity): void {
  const recoveryScope = authority.recoveryScope;
  if (bootstrapStartedScopes.has(recoveryScope)) return;
  bootstrapStartedScopes.add(recoveryScope);
  setCachedState(recoveryScope, {
    ...cachedStateForScope(recoveryScope),
    ready: false,
  });
}

export function subscribeToLogMutationRecovery(
  authority: RuntimeAuthorityIdentity,
  listener: () => void,
): () => void {
  const recoveryScope = authority.recoveryScope;
  const listeners = journalListenersByScope.get(recoveryScope) ?? new Set<() => void>();
  listeners.add(listener);
  journalListenersByScope.set(recoveryScope, listeners);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) journalListenersByScope.delete(recoveryScope);
  };
}

export async function loadLogMutationRecoveryJournal(
  authority: RuntimeAuthorityIdentity,
  storage: RecoveryStorage = defaultStorage,
): Promise<LogMutationRecoveryRecord[]> {
  return enqueueStorage(async () => {
    const result = await readStored(storage, authority.recoveryScope);
    setCachedState(authority.recoveryScope, { ...result.health, records: result.records });
    return result.records;
  });
}

export function useLogMutationRecoveryJournal(
  authority: RuntimeAuthorityIdentity,
): RecoveryJournalState {
  const recoveryScope = authority.recoveryScope;
  const [snapshot, setSnapshot] = useState<{
    recoveryScope: string;
    state: RecoveryJournalState;
  }>(() => ({ recoveryScope, state: getRecoveryJournalState(authority) }));
  useEffect(() => {
    let active = true;
    beginLogMutationRecoveryBootstrap(authority);
    const update = () => {
      if (active) {
        setSnapshot({ recoveryScope, state: getRecoveryJournalState(authority) });
      }
    };
    const unsubscribe = subscribeToLogMutationRecovery(authority, update);
    update();
    void loadLogMutationRecoveryJournal(authority).then(update);
    return () => {
      active = false;
      unsubscribe();
    };
  }, [authority, recoveryScope]);
  return snapshot.recoveryScope === recoveryScope
    ? snapshot.state
    : getRecoveryJournalState(authority);
}

export async function upsertLogMutationRecoveryRecord(
  record: LogMutationRecoveryRecord,
  storage: RecoveryStorage = defaultStorage,
): Promise<void> {
  await enqueueStorage(async () => {
    const existing = await readStored(storage, record.owner_scope);
    const records = stableRecords([
      ...existing.records.filter((candidate) => candidate.id !== record.id),
      record,
    ]);
    await writeStored(storage, existing, records, record.owner_scope);
    setCachedState(record.owner_scope, {
      ...existing.health,
      ready: existing.health.malformedRecordCount === 0,
      records,
    });
  });
}

export async function removeLogMutationRecoveryRecord(
  record: LogMutationRecoveryRecord,
  storage: RecoveryStorage = defaultStorage,
): Promise<void> {
  await enqueueStorage(async () => {
    const existing = await readStored(storage, record.owner_scope);
    const records = existing.records.filter((candidate) => candidate.id !== record.id);
    await writeStored(storage, existing, records, record.owner_scope);
    setCachedState(record.owner_scope, {
      ...existing.health,
      ready: existing.health.malformedRecordCount === 0,
      records,
    });
  });
}

export async function removeLogMutationRecoveryRecordById(
  id: string,
  authority: RuntimeAuthorityIdentity,
  storage: RecoveryStorage = defaultStorage,
): Promise<void> {
  await enqueueStorage(async () => {
    const existing = await readStored(storage, authority.recoveryScope);
    const records = existing.records.filter((candidate) => candidate.id !== id);
    await writeStored(storage, existing, records, authority.recoveryScope);
    setCachedState(authority.recoveryScope, {
      ...existing.health,
      ready: existing.health.malformedRecordCount === 0,
      records,
    });
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
  authority: RuntimeAuthorityIdentity;
  clientRequestId: string;
  mutationType: LogMutationRecoveryMutation;
  targetId?: string | null;
  /** Legacy construction alias retained for in-process callers during bounded evolution. */
  logId?: string | null;
  sourceDate: string;
  destinationDate?: string | null;
  displayContext: RecoveryDisplayContext;
  payload?: RecoveryPayload;
  createdAt?: string;
}): LogMutationRecoveryRecord {
  const createdAt = input.createdAt ?? new Date().toISOString();
  const targetId = input.targetId ?? input.logId ?? null;
  let payload = input.payload;
  if (!payload) {
    if (input.mutationType === "complete") {
      throw new RecoveryStorageError("Complete recovery requires the exact submitted payload.");
    }
    payload = input.mutationType === "create"
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
        : { operation: "update", log_id: targetId ?? "", input: { client_request_id: input.clientRequestId } };
  }
  return {
    version: LOG_MUTATION_RECOVERY_VERSION,
    owner_scope: input.authority.recoveryScope,
    id: `${input.mutationType}:${input.clientRequestId}`,
    client_request_id: input.clientRequestId,
    mutation_type: input.mutationType,
    target_id: targetId,
    display_context: normalizedDisplayContext(input.displayContext),
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
  if (error instanceof RuntimeError) {
    return error.mutationOutcome === "unresolved";
  }
  return true;
}

function operationFor(record: LogMutationRecoveryRecord): DailyLogMutationStatus["operation"] {
  if (record.payload.operation === "complete") return "complete";
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
    status?.completion?.logged_date,
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
  } else if (record.payload.operation !== "complete" && status.result) {
    projectConfirmedLog(queryClient, status.source_logged_date ?? record.source_date, status.result);
  }
  refreshAffectedDates(queryClient, record, status);
}

export async function reconcileLogMutationRecoveryRecord(
  record: LogMutationRecoveryRecord,
  queryClient: QueryClient | null,
  dependencies: LogMutationRecoveryDependencies,
  options: {
    statusReader?: DailyLogsRuntime["getMutationStatus"];
    storage?: RecoveryStorage;
  } = {},
): Promise<RecoveryReconcileResult> {
  if (record.owner_scope !== dependencies.authority.recoveryScope) return "pending";
  const storage = options.storage ?? defaultStorage;
  try {
    const status = options.statusReader
      ? await options.statusReader(record.client_request_id, operationFor(record))
      : await dependencies.dailyLogs.getMutationStatus(
          record.client_request_id,
          operationFor(record),
        );
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
  dependencies: LogMutationRecoveryDependencies,
  storage: RecoveryStorage = defaultStorage,
): Promise<RecoveryReconcileResult> {
  if (record.owner_scope !== dependencies.authority.recoveryScope) return "pending";
  const submitted = { ...record, state: "submitted" as const, dismissed_at: null, dismissed_from_state: null };
  await upsertLogMutationRecoveryRecord(submitted, storage);
  try {
    let result: DailyLog | undefined;
    let completion: DailyLogCompletion | undefined;
    if (submitted.payload.operation === "create") {
      result = await dependencies.dailyLogs.create(submitted.payload.input);
    } else if (submitted.payload.operation === "update") {
      result = await dependencies.dailyLogs.update(submitted.payload.log_id, submitted.payload.input);
    } else if (submitted.payload.operation === "delete") {
      await dependencies.dailyLogs.delete(submitted.payload.log_id, submitted.payload.input);
    } else {
      if (!dependencies.dailyLogs.markDayComplete) return "pending";
      completion = await dependencies.dailyLogs.markDayComplete(submitted.payload.input);
    }
    const status: DailyLogMutationStatus = {
      operation: operationFor(submitted),
      client_request_id: submitted.client_request_id,
      status: "confirmed_success",
      log_id: submitted.payload.operation === "complete" ? null : result?.id ?? submitted.target_id,
      result: result ?? null,
      completion: completion ?? null,
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

function isNutritionChangingRecovery(record: LogMutationRecoveryRecord): boolean {
  if (record.mutation_type === "complete") return false;
  if (record.mutation_type === "create" || record.mutation_type === "move" || record.mutation_type === "delete") {
    return true;
  }
  if (record.payload.operation !== "update") return false;
  return ["amount_quantity", "amount_unit", "serving_definition_id"].some((field) =>
    Object.prototype.hasOwnProperty.call(record.payload.input, field));
}

/** Pure workflow gate for E4-07: unresolved nutrition work blocks Complete on either affected date. */
export function hasUnresolvedNutritionMutationForDate(
  records: readonly LogMutationRecoveryRecord[],
  loggedDate: string,
): boolean {
  return records.some((record) => {
    const actionable = recoveryActionableState(record);
    if (actionable === "confirmed_non_commit") return false;
    if (actionable !== "prepared" && actionable !== "submitted" && actionable !== "reconciling") {
      return false;
    }
    if (!isNutritionChangingRecovery(record)) return false;
    return record.source_date === loggedDate || record.destination_date === loggedDate;
  });
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
  statusReader?: DailyLogsRuntime["getMutationStatus"];
  retryDelayMs?: number;
};

export function startLogMutationRecovery(
  queryClient: QueryClient,
  dependencies: LogMutationRecoveryDependencies,
  options: RecoveryManagerOptions = {},
): () => void {
  beginLogMutationRecoveryBootstrap(dependencies.authority);
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
      const state = await loadLogMutationRecoveryJournal(dependencies.authority, storage)
        .then(() => getRecoveryJournalState(dependencies.authority));
      if (!state.ready) {
        return;
      }
      let hasPending = false;
      for (const record of state.records) {
        if (stopped) break;
        const actionableState = recoveryActionableState(record);
        if (actionableState === "prepared" || actionableState === "confirmed_non_commit") continue;
        const attempted = await markLogMutationRecoveryAttempt(record, storage);
        const outcome = await reconcileLogMutationRecoveryRecord(attempted, queryClient, dependencies, options);
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

  const unsubscribeJournal = subscribeToLogMutationRecovery(dependencies.authority, () => {
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
