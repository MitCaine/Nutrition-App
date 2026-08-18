import AsyncStorage from "@react-native-async-storage/async-storage";
import { QueryClient } from "@tanstack/react-query";
import React from "react";
import TestRenderer, { act } from "react-test-renderer";

import {
  createLogMutationRecoveryRecord,
  getRecoveryJournalState,
  hasOverlappingRecovery,
  loadLogMutationRecoveryJournal,
  LOG_MUTATION_RECOVERY_VERSION,
  removeLogMutationRecoveryRecord,
  startLogMutationRecovery,
  subscribeToLogMutationRecovery,
  useLogMutationRecoveryJournal,
  type LogMutationRecoveryRecord,
  type RecoveryJournalState,
  type RecoveryStorage,
} from "../src/features/logging/recovery/logMutationRecovery";
import {
  localAuthorityIdentity,
  remoteAuthorityIdentity,
} from "../src/runtime/authorityIdentity";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise; });
  return { promise, resolve };
}

function memoryStorage(records: unknown[]): RecoveryStorage & { value: string | null } {
  const state = {
    value: JSON.stringify({ version: LOG_MUTATION_RECOVERY_VERSION, records }) as string | null,
  };
  return {
    get value() { return state.value; },
    set value(value: string | null) { state.value = value; },
    getItem: jest.fn(async () => state.value),
    setItem: jest.fn(async (_key: string, value: string) => { state.value = value; }),
    removeItem: jest.fn(async () => { state.value = null; }),
  };
}

function recoveryRecord(
  authority: ReturnType<typeof localAuthorityIdentity> | ReturnType<typeof remoteAuthorityIdentity>,
  clientRequestId: string,
): LogMutationRecoveryRecord {
  return createLogMutationRecoveryRecord({
    authority,
    clientRequestId,
    mutationType: "create",
    sourceDate: "2026-08-09",
    displayContext: {
      item_name: `${authority.kind} food`,
      amount_label: "1 serving",
      meal_label: "Breakfast",
    },
    payload: {
      operation: "create",
      input: {
        client_request_id: clientRequestId,
        food_item_id: "same-food",
        logged_date: "2026-08-09",
        amount_quantity: "1",
        amount_unit: "serving",
      },
    },
  });
}

test("remote state cannot appear while a newly selected local journal is pending", async () => {
  const remote = remoteAuthorityIdentity("remote:test-owner");
  const local = localAuthorityIdentity("00000000-0000-4000-8000-000000000001");
  const remoteRecord = recoveryRecord(remote, "remote-pending-request");
  const envelope = JSON.stringify({
    version: LOG_MUTATION_RECOVERY_VERSION,
    records: [remoteRecord],
  });
  const remoteStorage = {
    getItem: jest.fn(async () => envelope),
    setItem: jest.fn(async () => undefined),
    removeItem: jest.fn(async () => undefined),
  };
  await loadLogMutationRecoveryJournal(remote, remoteStorage);
  expect(getRecoveryJournalState(remote).records).toEqual([remoteRecord]);

  const localRead = deferred<string | null>();
  (AsyncStorage.getItem as jest.Mock).mockImplementationOnce(() => localRead.promise);
  let observed: RecoveryJournalState | null = null;
  function Probe() {
    observed = useLogMutationRecoveryJournal(local);
    return null;
  }

  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(Probe));
    await Promise.resolve();
  });

  expect(observed).toEqual(expect.objectContaining({ ready: false, records: [] }));

  await act(async () => {
    localRead.resolve(envelope);
    await localRead.promise;
  });
  expect(observed).toEqual(expect.objectContaining({ ready: true, records: [] }));
  await act(async () => { renderer.unmount(); });
});

test("local state cannot appear while a newly selected remote journal is pending", async () => {
  const local = localAuthorityIdentity("00000000-0000-4000-8000-000000000002");
  const remote = remoteAuthorityIdentity("remote:second-test-owner");
  const localRecord = recoveryRecord(local, "local-pending-request");
  const envelope = JSON.stringify({
    version: LOG_MUTATION_RECOVERY_VERSION,
    records: [localRecord],
  });
  await loadLogMutationRecoveryJournal(local, memoryStorage([localRecord]));
  expect(getRecoveryJournalState(local).records).toEqual([localRecord]);

  const remoteRead = deferred<string | null>();
  (AsyncStorage.getItem as jest.Mock).mockImplementationOnce(() => remoteRead.promise);
  let observed: RecoveryJournalState | null = null;
  function Probe() {
    observed = useLogMutationRecoveryJournal(remote);
    return null;
  }

  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(Probe));
    await Promise.resolve();
  });
  expect(observed).toEqual(expect.objectContaining({ ready: false, records: [] }));

  await act(async () => {
    remoteRead.resolve(envelope);
    await remoteRead.promise;
  });
  expect(observed).toEqual(expect.objectContaining({ ready: true, records: [] }));
  await act(async () => { renderer.unmount(); });
});

test("overlap reads are isolated to the explicitly requested authority", async () => {
  const local = localAuthorityIdentity("00000000-0000-4000-8000-000000000003");
  const remote = remoteAuthorityIdentity("remote:overlap-owner");
  const localRecord = recoveryRecord(local, "local-overlap-request");
  const remoteRecord = recoveryRecord(remote, "remote-overlap-request");
  const storage = memoryStorage([localRecord, remoteRecord]);

  await loadLogMutationRecoveryJournal(local, storage);
  await loadLogMutationRecoveryJournal(remote, storage);
  const candidate = {
    mutationType: "create" as const,
    sourceDate: "2026-08-09",
    destinationDate: "2026-08-09",
    foodId: "same-food",
  };

  expect(hasOverlappingRecovery(getRecoveryJournalState(local).records, candidate)?.id)
    .toBe(localRecord.id);
  expect(hasOverlappingRecovery(getRecoveryJournalState(remote).records, candidate)?.id)
    .toBe(remoteRecord.id);
});

test("updating one scope preserves the other scope in durable storage and memory", async () => {
  const local = localAuthorityIdentity("00000000-0000-4000-8000-000000000004");
  const remote = remoteAuthorityIdentity("remote:durable-owner");
  const localRecord = recoveryRecord(local, "local-durable-request");
  const remoteRecord = recoveryRecord(remote, "remote-durable-request");
  const storage = memoryStorage([localRecord, remoteRecord]);

  await loadLogMutationRecoveryJournal(local, storage);
  await loadLogMutationRecoveryJournal(remote, storage);
  await removeLogMutationRecoveryRecord(localRecord, storage);

  const durable = JSON.parse(storage.value as string) as {
    version: number;
    records: LogMutationRecoveryRecord[];
  };
  expect(durable.version).toBe(LOG_MUTATION_RECOVERY_VERSION);
  expect(durable.records.map((record) => record.id)).toEqual([remoteRecord.id]);
  expect(getRecoveryJournalState(local).records).toEqual([]);
  expect(getRecoveryJournalState(remote).records).toEqual([remoteRecord]);
});

test("a stopped old manager can finish only into its own scope", async () => {
  const remote = remoteAuthorityIdentity("remote:in-flight-owner");
  const local = localAuthorityIdentity("00000000-0000-4000-8000-000000000005");
  const remoteRecord = {
    ...recoveryRecord(remote, "remote-in-flight-request"),
    state: "submitted" as const,
  };
  const storage = memoryStorage([remoteRecord]);
  const statusEntered = deferred<void>();
  const releaseStatus = deferred<void>();
  const oldWriteCompleted = deferred<void>();
  let writes = 0;
  storage.setItem = jest.fn(async (_key: string, value: string) => {
    storage.value = value;
    writes += 1;
    if (writes === 2) oldWriteCompleted.resolve();
  });
  const remoteStatus = jest.fn(async () => {
    statusEntered.resolve();
    await releaseStatus.promise;
    return {
      operation: "create" as const,
      client_request_id: remoteRecord.client_request_id,
      status: "unresolved" as const,
      log_id: null,
      result: null,
    };
  });
  const localStatus = jest.fn();
  const remoteClient = new QueryClient();
  const localClient = new QueryClient();
  const stopRemote = startLogMutationRecovery(remoteClient, {
    authority: remote,
    dailyLogs: { getMutationStatus: remoteStatus } as never,
  }, { storage, retryDelayMs: 60_000 });
  await statusEntered.promise;
  stopRemote();

  const localReady = deferred<void>();
  let localNotifications = 0;
  const unsubscribeLocal = subscribeToLogMutationRecovery(local, () => {
    localNotifications += 1;
    if (getRecoveryJournalState(local).ready) localReady.resolve();
  });
  const stopLocal = startLogMutationRecovery(localClient, {
    authority: local,
    dailyLogs: { getMutationStatus: localStatus } as never,
  }, { storage, retryDelayMs: 60_000 });
  await localReady.promise;
  const notificationsBeforeOldCompletion = localNotifications;
  expect(getRecoveryJournalState(local)).toEqual(expect.objectContaining({
    ready: true,
    records: [],
  }));

  releaseStatus.resolve();
  await oldWriteCompleted.promise;
  expect(getRecoveryJournalState(local)).toEqual(expect.objectContaining({
    ready: true,
    records: [],
  }));
  expect(localNotifications).toBe(notificationsBeforeOldCompletion);
  expect(localStatus).not.toHaveBeenCalled();

  stopLocal();
  unsubscribeLocal();
  remoteClient.clear();
  localClient.clear();
});
