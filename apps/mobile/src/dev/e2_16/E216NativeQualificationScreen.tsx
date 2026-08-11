import { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import {
  clearE216StageBRestartCheckpoint,
  hasE216FoundationCheckpoint,
  openE216QualificationDatabase,
  readE216StageBRestartCheckpoint,
  resetE216QualificationDatabases,
  writeE216FoundationCheckpoint,
} from "./e216QualificationFoundation";
import {
  completeE216OrdinaryRestart,
  E216_STAGE_B_CASE_DEFINITIONS,
  runE216StageBCase,
  runE216StageBRunAll,
  type E216StageBCaseOutcome,
  type E216StageBCaseResult,
  type E216StageBRestartPending,
} from "./e216StageBQualification";
import {
  E216_STAGE_C_CASE_DEFINITIONS,
  runE216StageCCase,
  runE216StageCRunAll,
  type E216StageCCaseResult,
} from "./e216StageCQualification";
import {
  E216_STAGE_D_CASE_DEFINITIONS,
  armE216StageDCase,
  completeE216StageDCaseAfterRelaunch,
  completeE216StageDPreMutationControlAfterRelaunch,
  isE216StageDCurrentProcessSession,
  prepareE216StageDCase,
  prepareE216StageDPreMutationControl,
  readE216StageDCheckpoint,
  readE216StageDPreMutationControlCheckpoint,
  resetE216StageDQualification,
  type E216StageDCaseId,
  type E216StageDCheckpointMarker,
  type E216StageDPreMutationControlCheckpointMarker,
} from "./e216StageDQualification";
import {
  E216_STAGE_E_CASE_DEFINITIONS,
  readE216StageECheckpoint,
  runE216StageECase,
  type E216StageECaseId,
  type E216StageECaseResult,
  type E216StageECheckpointMarker,
} from "./e216StageEQualification";
import {
  qualifyE216Database,
  serializeE216IntegrityResult,
  type E216DirectIntegrityResult,
} from "./e216DirectIntegrityQualifier";
import type { NutritionDatabaseHandle } from "../../storage/sqlite/migrations";
import { bootstrapOpenedLocalRuntimeFoundation } from "../../runtime/local/localRuntimeFoundation";
import { canonicalJsonStringify } from "../../shared/exact/canonicalValues";

type StageBCaseState = Readonly<{
  status: "idle" | "running" | "passed" | "failed" | "awaiting_relaunch";
  result?: E216StageBCaseResult;
  error?: string;
}>;

type StageCCaseState = Readonly<{
  status: "idle" | "running" | "passed" | "failed";
  result?: E216StageCCaseResult;
  error?: string;
}>;

type StageECaseState = Readonly<{
  status: "idle" | "running" | "passed" | "failed";
  result?: E216StageECaseResult;
  error?: string;
}>;

function initialStageBCaseStates(): Record<(typeof E216_STAGE_B_CASE_DEFINITIONS)[number]["id"], StageBCaseState> {
  return {
    fresh_migration: { status: "idle" },
    valid_v1_reopen: { status: "idle" },
    explicit_close_reopen: { status: "idle" },
    ordinary_restart: { status: "idle" },
  };
}

function initialStageCCaseStates(): Record<(typeof E216_STAGE_C_CASE_DEFINITIONS)[number]["id"], StageCCaseState> {
  return {
    failing_v2_rollback: { status: "idle" },
    future_user_version: { status: "idle" },
    missing_ledger: { status: "idle" },
    mismatched_ledger: { status: "idle" },
  };
}

function initialStageECaseStates(): Record<E216StageECaseId, StageECaseState> {
  return {
    native_path_open_failure: { status: "idle" },
    bounded_sqlite_full: { status: "idle" },
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export default function E216NativeQualificationScreen() {
  const [handle, setHandle] = useState<NutritionDatabaseHandle | null>(null);
  const [result, setResult] = useState<E216DirectIntegrityResult | null>(null);
  const [checkpoint, setCheckpoint] = useState(hasE216FoundationCheckpoint());
  const [stageBCaseStates, setStageBCaseStates] = useState(initialStageBCaseStates);
  const [stageCCaseStates, setStageCCaseStates] = useState(initialStageCCaseStates);
  const [stageECaseStates, setStageECaseStates] = useState(initialStageECaseStates);
  const [stageDMarker, setStageDMarker] = useState<E216StageDCheckpointMarker | null>(null);
  const [stageDControlMarker, setStageDControlMarker] = useState<E216StageDPreMutationControlCheckpointMarker | null>(null);
  const [stageEMarker, setStageEMarker] = useState<E216StageECheckpointMarker | null>(null);
  const [pendingRestart, setPendingRestart] = useState<E216StageBRestartPending | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const handleRef = useRef<NutritionDatabaseHandle | null>(null);
  handleRef.current = handle;
  const stageDFamilyAwaitingTermination = stageDMarker?.state === "awaiting_termination";
  const stageDControlAwaitingTermination = stageDControlMarker?.state === "awaiting_termination";
  const stageDTerminationPending = stageDFamilyAwaitingTermination || stageDControlAwaitingTermination;

  useEffect(() => () => {
    void handleRef.current?.close();
  }, []);

  useEffect(() => {
    try {
      const marker = readE216StageBRestartCheckpoint();
      if (!marker) return;
      setPendingRestart({
        caseId: marker.caseId,
        status: "awaiting_relaunch",
        databaseName: marker.databaseName,
        marker,
      });
      setStageBCaseStates((current) => ({
        ...current,
        ...Object.fromEntries(marker.completedCaseIds.map((caseId) => [caseId, { status: "passed" }])),
        ordinary_restart: { status: "awaiting_relaunch" },
      }));
      setMessage("E2-16B restart checkpoint found. Reopen the isolated database after relaunch.");
    } catch (error) {
      setMessage(`E2-16B checkpoint failed: ${errorMessage(error)}`);
    }
  }, []);

  useEffect(() => {
    try {
      const marker = readE216StageECheckpoint();
      setStageEMarker(marker);
      if (marker?.state === "completed" && marker.result) {
        const completedResult = marker.result;
        setStageECaseStates((current) => ({
          ...current,
          [marker.caseId]: {
            status: completedResult.status === "pass" ? "passed" : "failed",
            result: completedResult,
          },
        }));
        setMessage(`E2-16E ${marker.caseId} completed with ${completedResult.status} status.`);
      } else if (marker) {
        setMessage(`E2-16E ${marker.caseId} is at ${marker.checkpointReached}.`);
      }
    } catch (error) {
      setMessage(`E2-16E checkpoint failed: ${errorMessage(error)}`);
    }
  }, []);

  useEffect(() => {
    try {
      const marker = readE216StageDCheckpoint();
      const controlMarker = readE216StageDPreMutationControlCheckpoint();
      setStageDMarker(marker);
      setStageDControlMarker(controlMarker);
      const awaiting = controlMarker?.state === "awaiting_termination"
        ? controlMarker
        : marker?.state === "awaiting_termination" ? marker : null;
      if (awaiting) {
        setMessage(isE216StageDCurrentProcessSession(awaiting.processSessionId)
          ? `E2-16D ${awaiting.caseId}: HOST ACTION NOW: terminate and launch.`
          : `E2-16D ${awaiting.caseId}: RELAUNCH DETECTED: press COMPLETE RESTART INSPECTION.`);
      } else if (controlMarker?.state === "completed") {
        setMessage(`E2-16D ${controlMarker.caseId} completed with ${controlMarker.result?.status ?? "unknown"} status.`);
      } else if (marker?.state === "ready_to_arm") {
        setMessage(`E2-16D ${marker.caseId} is prepared at the before-mutation checkpoint. Arm it when the host is ready.`);
      } else if (marker?.state === "completed") {
        setMessage(`E2-16D ${marker.caseId} completed with ${marker.result?.status ?? "unknown"} status.`);
      }
    } catch (error) {
      setMessage(`E2-16D checkpoint failed: ${errorMessage(error)}`);
    }
  }, []);

  async function openDatabase(): Promise<void> {
    setBusy(true);
    setMessage(null);
    try {
      const opened = await openE216QualificationDatabase();
      try {
        await bootstrapOpenedLocalRuntimeFoundation(opened);
      } catch (error) {
        await opened.close();
        throw error;
      }
      handleRef.current = opened;
      setHandle(opened);
      setResult(null);
      setMessage("E2-16A qualification database migrated with one synthetic local owner/profile.");
    } catch (error) {
      setMessage(`Open failed: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function runQualifier(): Promise<void> {
    const current = handleRef.current;
    if (!current) {
      setMessage("Open the isolated qualification database first.");
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const next = await qualifyE216Database(current.database);
      setResult(next);
      setMessage(next.status === "pass" ? "Direct integrity qualifier passed." : "Direct integrity qualifier failed.");
    } catch (error) {
      setMessage(`Qualifier failed: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function closeFoundationHandle(): Promise<void> {
    const current = handleRef.current;
    if (!current) return;
    await current.close();
    handleRef.current = null;
    setHandle(null);
  }

  function applyStageBOutcome(outcome: E216StageBCaseOutcome): void {
    if (outcome.status === "awaiting_relaunch") {
      setPendingRestart(outcome);
      setStageBCaseStates((current) => ({
        ...current,
        ordinary_restart: { status: "awaiting_relaunch" },
      }));
      setMessage("Restart checkpoint written. Terminate and relaunch the isolated E2-16 app, then complete the restart case.");
      return;
    }
    setPendingRestart(null);
    setStageBCaseStates((current) => ({
      ...current,
      [outcome.caseId]: {
        status: outcome.status === "pass" ? "passed" : "failed",
        result: outcome,
      },
    }));
    setMessage(
      outcome.status === "pass"
        ? `${outcome.caseId} passed its migration and integrity checks.`
        : `${outcome.caseId} failed its migration or integrity checks.`,
    );
  }

  async function runStageBCase(caseId: (typeof E216_STAGE_B_CASE_DEFINITIONS)[number]["id"]): Promise<void> {
    setBusy(true);
    setMessage(null);
    setStageBCaseStates((current) => ({
      ...current,
      [caseId]: { status: "running" },
    }));
    try {
      await closeFoundationHandle();
      applyStageBOutcome(await runE216StageBCase(caseId));
    } catch (error) {
      setStageBCaseStates((current) => ({
        ...current,
        [caseId]: { status: "failed", error: errorMessage(error) },
      }));
      setMessage(`E2-16B ${caseId} failed: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function runStageBAll(): Promise<void> {
    setBusy(true);
    setMessage(null);
    setStageBCaseStates((current) => Object.fromEntries(
      Object.entries(current).map(([caseId]) => [caseId, { status: "running" }]),
    ) as typeof current);
    try {
      await closeFoundationHandle();
      const run = await runE216StageBRunAll();
      setStageBCaseStates((current) => ({
        ...current,
        ...Object.fromEntries(run.results.map((caseResult) => [caseResult.caseId, {
          status: caseResult.status === "pass" ? "passed" : "failed",
          result: caseResult,
        }])),
        ordinary_restart: { status: "awaiting_relaunch" },
      }));
      setPendingRestart(run.pending);
      setMessage("E2-16B RUN ALL reached the restart checkpoint. Terminate and relaunch the isolated app to continue.");
    } catch (error) {
      setMessage(`E2-16B RUN ALL failed: ${errorMessage(error)}`);
      setStageBCaseStates((current) => Object.fromEntries(
        Object.entries(current).map(([caseId, state]) => [
          caseId,
          state.status === "running" ? { status: "failed", error: errorMessage(error) } : state,
        ]),
      ) as typeof current);
    } finally {
      setBusy(false);
    }
  }

  async function completePendingRestart(): Promise<void> {
    const current = pendingRestart;
    if (!current) return;
    setBusy(true);
    setMessage(null);
    try {
      await closeFoundationHandle();
      const completed = await completeE216OrdinaryRestart(current.marker);
      setStageBCaseStates((states) => ({
        ...states,
        ordinary_restart: {
          status: completed.status === "pass" ? "passed" : "failed",
          result: completed,
        },
      }));
      if (completed.status === "pass") {
        setPendingRestart(null);
        setMessage(current.marker.runAll ? "E2-16B RUN ALL passed after relaunch." : "E2-16B ordinary restart passed.");
      } else {
        setMessage("E2-16B ordinary restart failed its migration or integrity checks. The checkpoint remains retryable.");
      }
    } catch (error) {
      setMessage(`E2-16B restart completion failed: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function runStageCCase(caseId: (typeof E216_STAGE_C_CASE_DEFINITIONS)[number]["id"]): Promise<void> {
    setBusy(true);
    setMessage(null);
    setStageCCaseStates((current) => ({
      ...current,
      [caseId]: { status: "running" },
    }));
    try {
      await closeFoundationHandle();
      const outcome = await runE216StageCCase(caseId);
      setStageCCaseStates((current) => ({
        ...current,
        [caseId]: {
          status: outcome.status === "pass" ? "passed" : "failed",
          result: outcome,
        },
      }));
      setMessage(
        outcome.status === "pass"
          ? `${outcome.caseId} passed its fail-closed checks.`
          : `${outcome.caseId} failed its fail-closed checks.`,
      );
    } catch (error) {
      setStageCCaseStates((current) => ({
        ...current,
        [caseId]: { status: "failed", error: errorMessage(error) },
      }));
      setMessage(`E2-16C ${caseId} failed: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function runStageCAll(): Promise<void> {
    setBusy(true);
    setMessage(null);
    setStageCCaseStates((current) => Object.fromEntries(
      Object.entries(current).map(([caseId]) => [caseId, { status: "running" }]),
    ) as typeof current);
    try {
      await closeFoundationHandle();
      const outcomes = await runE216StageCRunAll();
      setStageCCaseStates((current) => ({
        ...current,
        ...Object.fromEntries(outcomes.map((outcome) => [outcome.caseId, {
          status: outcome.status === "pass" ? "passed" : "failed",
          result: outcome,
        }])),
      }));
      setMessage(
        outcomes.every((outcome) => outcome.status === "pass")
          ? "E2-16C RUN ALL passed its fail-closed checks."
          : "E2-16C RUN ALL completed with one or more failures.",
      );
    } catch (error) {
      setMessage(`E2-16C RUN ALL failed: ${errorMessage(error)}`);
      setStageCCaseStates((current) => Object.fromEntries(
        Object.entries(current).map(([caseId, state]) => [
          caseId,
          state.status === "running" ? { status: "failed", error: errorMessage(error) } : state,
        ]),
      ) as typeof current);
    } finally {
      setBusy(false);
    }
  }

  async function prepareStageDCase(caseId: E216StageDCaseId): Promise<void> {
    setBusy(true);
    setMessage(null);
    try {
      await closeFoundationHandle();
      const marker = await prepareE216StageDCase(caseId);
      setStageDMarker(marker);
      setStageDControlMarker(readE216StageDPreMutationControlCheckpoint());
      setMessage(`${caseId} is durably prepared before mutation. Review the pre-state, then arm the real mutation.`);
    } catch (error) {
      setMessage(`E2-16D ${caseId} preparation failed: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function prepareStageDPreMutationControl(): Promise<void> {
    setBusy(true);
    setMessage(null);
    try {
      await closeFoundationHandle();
      const marker = await prepareE216StageDPreMutationControl();
      setStageDControlMarker(marker);
      setStageDMarker(readE216StageDCheckpoint());
      setMessage("E2-16D pre_mutation_control is durably awaiting termination before the mutation-under-test. Do not arm a mutation.");
    } catch (error) {
      setMessage(`E2-16D pre_mutation_control preparation failed: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function armStageDCase(): Promise<void> {
    setBusy(true);
    setMessage("Arming the real production mutation. Do not terminate until the awaiting_termination marker is visible.");
    try {
      await closeFoundationHandle();
      const marker = await armE216StageDCase((checkpointMarker) => {
        setStageDMarker(checkpointMarker);
        setMessage(`${checkpointMarker.caseId} reached ${checkpointMarker.checkpointReached}. HOST ACTION NOW: terminate and launch. Do not press reset.`);
      });
      setStageDMarker(marker);
      setMessage(`${marker.caseId} reached ${marker.checkpointReached}. HOST ACTION NOW: terminate and launch. Do not press reset.`);
    } catch (error) {
      setBusy(false);
      setMessage(`E2-16D arm failed: ${errorMessage(error)}`);
    }
  }

  async function completeStageDCase(): Promise<void> {
    setBusy(true);
    setMessage(null);
    try {
      await closeFoundationHandle();
      if (stageDControlAwaitingTermination) {
        const completed = await completeE216StageDPreMutationControlAfterRelaunch();
        setStageDControlMarker(readE216StageDPreMutationControlCheckpoint());
        setStageDMarker(readE216StageDCheckpoint());
        setMessage(`${completed.caseId} restart inspection ${completed.status === "pass" ? "passed" : "failed"}.`);
        return;
      }
      const completed = await completeE216StageDCaseAfterRelaunch();
      setStageDMarker(readE216StageDCheckpoint());
      setStageDControlMarker(readE216StageDPreMutationControlCheckpoint());
      setMessage(`${completed.caseId} restart inspection ${completed.status === "pass" ? "passed" : "failed"}.`);
    } catch (error) {
      setMessage(`E2-16D restart inspection failed: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function runStageECase(caseId: E216StageECaseId): Promise<void> {
    setBusy(true);
    setMessage(null);
    setStageECaseStates((current) => ({
      ...current,
      [caseId]: { status: "running" },
    }));
    try {
      await closeFoundationHandle();
      const outcome = await runE216StageECase(caseId);
      setStageEMarker(readE216StageECheckpoint());
      setStageECaseStates((current) => ({
        ...current,
        [caseId]: {
          status: outcome.status === "pass" ? "passed" : "failed",
          result: outcome,
        },
      }));
      setMessage(
        outcome.status === "pass"
          ? `E2-16E ${caseId} passed its native failure and preservation checks.`
          : `E2-16E ${caseId} failed its native failure or preservation checks.`,
      );
    } catch (error) {
      setStageECaseStates((current) => ({
        ...current,
        [caseId]: { status: "failed", error: errorMessage(error) },
      }));
      setMessage(`E2-16E ${caseId} failed: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  function writeCheckpoint(): void {
    try {
      writeE216FoundationCheckpoint();
      setCheckpoint(true);
      setMessage("Host-visible foundation_ready checkpoint written.");
    } catch (error) {
      setMessage(`Checkpoint failed: ${errorMessage(error)}`);
    }
  }

  async function reset(): Promise<void> {
    setBusy(true);
    setMessage(null);
    try {
      await closeFoundationHandle();
      if (Platform.OS === "ios") await resetE216StageDQualification();
      await resetE216QualificationDatabases();
      clearE216StageBRestartCheckpoint();
      setResult(null);
      setCheckpoint(hasE216FoundationCheckpoint());
      setPendingRestart(null);
      setStageBCaseStates(initialStageBCaseStates());
      setStageCCaseStates(initialStageCCaseStates());
      setStageECaseStates(initialStageECaseStates());
      setStageDMarker(null);
      setStageDControlMarker(null);
      setStageEMarker(null);
      setMessage("E2-16A/B/C/D/E isolated databases, checkpoints, and Stage-D journal state reset.");
    } catch (error) {
      setMessage(`Reset failed: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Text style={styles.title}>Nutrition App E2-16</Text>
      <Text style={styles.subtitle}>E2-16A/B/C/D/E native lifecycle, failure, and real process-termination qualification</Text>
      <Text style={styles.warning}>
        Temporary development-only infrastructure. E2-16F+ feature, accessibility,
        and OCR-device scenarios are not implemented here.
      </Text>

      <View style={styles.card}>
        <Text style={styles.heading}>Isolated boundary</Text>
        <Text selectable style={styles.detail}>Bundle: com.portfolio.nutritionapp.e216</Text>
        <Text selectable style={styles.detail}>Foundation database: e2_16_foundation_&lt;platform&gt;.db</Text>
        <Text selectable style={styles.detail}>Stage-B databases: e2_16_&lt;migration|reopen|restart&gt;_&lt;platform&gt;.db</Text>
        <Text selectable style={styles.detail}>Stage-C databases: e2_16_&lt;failure|future|ledger&gt;_ios.db</Text>
        <Text selectable style={styles.detail}>Stage-D database: e2_16_termination_ios.db</Text>
        <Text selectable style={styles.detail}>Stage-E database: e2_16_storage_ios.db (iOS only)</Text>
        <Text style={styles.detail}>Root: Expo SQLite default root / E2-16</Text>
        <Text style={styles.detail}>Normal nutrition.db is never opened or deleted.</Text>
      </View>

      <View style={styles.actions}>
        <Pressable accessibilityRole="button" accessibilityLabel="Open isolated qualification database" style={styles.button} disabled={busy} onPress={() => void openDatabase()}>
          <Text style={styles.buttonText}>OPEN / MIGRATE</Text>
        </Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="Run direct integrity qualifier" style={styles.button} disabled={busy || handle === null} onPress={() => void runQualifier()}>
          <Text style={styles.buttonText}>RUN INTEGRITY QUALIFIER</Text>
        </Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="Write host-visible foundation checkpoint" style={styles.button} disabled={busy} onPress={writeCheckpoint}>
          <Text style={styles.buttonText}>WRITE CHECKPOINT</Text>
        </Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="Reset isolated qualification database" style={[styles.button, styles.resetButton]} disabled={busy} onPress={() => void reset()}>
          <Text style={styles.buttonText}>RESET ALL ISOLATED STATE</Text>
        </Pressable>
      </View>

      <View style={styles.stageCard}>
        <Text style={styles.heading}>E2-16E filesystem and full-database failure (iOS only)</Text>
        <Text style={styles.detail}>
          Each case uses only the disposable Stage-E database. The path case opens the allowlisted database through
          a regular-file directory path; the full case bounds only that database with max_page_count and fills a
          harness-owned table until native SQLITE_FULL. Neither case resets or deletes the database during failure.
        </Text>
        <Text selectable style={styles.status}>
          Marker: {stageEMarker ? `${stageEMarker.caseId} / ${stageEMarker.checkpointReached} / ${stageEMarker.state}` : "none"}
        </Text>
        {E216_STAGE_E_CASE_DEFINITIONS.map((definition) => {
          const state = stageECaseStates[definition.id];
          return (
            <View key={definition.id} style={styles.caseCard}>
              <Text style={styles.caseTitle}>{definition.title}</Text>
              <Text style={styles.detail}>{definition.description}</Text>
              <Text style={styles.status}>Status: {state.status}</Text>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`Run E2-16E ${definition.title}`}
                style={styles.button}
                disabled={busy || Platform.OS !== "ios"}
                onPress={() => void runStageECase(definition.id)}
              >
                <Text style={styles.buttonText}>RUN CASE</Text>
              </Pressable>
              {state.error ? <Text accessibilityRole="alert" style={styles.message}>{state.error}</Text> : null}
              {state.result ? (
                <Text selectable style={styles.result}>{canonicalJsonStringify(state.result)}</Text>
              ) : null}
            </View>
          );
        })}
      </View>

      <View style={styles.stageCard}>
        <Text style={styles.heading}>E2-16B lifecycle qualification</Text>
        <Text style={styles.detail}>
          Each case resets only its fixed Stage-B database, uses the real Expo migration/open/close path,
          and runs the read-only integrity qualifier. RUN ALL pauses at the restart checkpoint for host relaunch.
        </Text>
        <Pressable accessibilityRole="button" accessibilityLabel="Run all E2-16B lifecycle cases" style={[styles.button, styles.runAllButton]} disabled={busy} onPress={() => void runStageBAll()}>
          <Text style={styles.buttonText}>RUN ALL E2-16B CASES</Text>
        </Pressable>
        {E216_STAGE_B_CASE_DEFINITIONS.map((definition) => {
          const state = stageBCaseStates[definition.id];
          const isRestartPending = definition.id === "ordinary_restart" && state.status === "awaiting_relaunch";
          return (
            <View key={definition.id} style={styles.caseCard}>
              <Text style={styles.caseTitle}>{definition.title}</Text>
              <Text style={styles.detail}>{definition.description}</Text>
              <Text style={styles.status}>Status: {state.status}</Text>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={isRestartPending ? "Complete E2-16B ordinary restart" : `Run E2-16B ${definition.title}`}
                style={styles.button}
                disabled={busy}
                onPress={() => isRestartPending ? void completePendingRestart() : void runStageBCase(definition.id)}
              >
                <Text style={styles.buttonText}>{isRestartPending ? "COMPLETE AFTER RELAUNCH" : "RUN CASE"}</Text>
              </Pressable>
              {isRestartPending ? (
                <Text style={styles.restartInstruction}>
                  Host action required: terminate and relaunch the isolated E2-16 app, then press COMPLETE AFTER RELAUNCH. Do not reset.
                </Text>
              ) : null}
              {state.error ? <Text accessibilityRole="alert" style={styles.message}>{state.error}</Text> : null}
              {state.result ? (
                <Text selectable style={styles.result}>{canonicalJsonStringify(state.result)}</Text>
              ) : null}
            </View>
          );
        })}
      </View>

      <View style={styles.stageCard}>
        <Text style={styles.heading}>E2-16D mutation termination (iOS only)</Text>
        <Text style={styles.detail}>
          Prepare writes a durable before-mutation marker. Arm runs the real production mutation. During-transaction
          cases stop on an awaited in-transaction barrier; post-commit cases expose their marker only after the mutation
          promise has committed. Terminate only when state is awaiting_termination.
        </Text>
        <Text selectable style={styles.status}>
          Active family marker: {stageDMarker ? `${stageDMarker.caseId} / ${stageDMarker.checkpointReached} / ${stageDMarker.state}` : "none"}
        </Text>
        {stageDFamilyAwaitingTermination ? (
          <>
            <Text style={styles.restartInstruction}>
              {isE216StageDCurrentProcessSession(stageDMarker!.processSessionId)
                ? "HOST ACTION NOW: terminate and launch."
                : "RELAUNCH DETECTED: press COMPLETE RESTART INSPECTION."}
            </Text>
            {isE216StageDCurrentProcessSession(stageDMarker!.processSessionId) ? (
              <Text style={styles.detail}>
                Run xcrun simctl terminate booted com.portfolio.nutritionapp.e216, then xcrun simctl launch booted com.portfolio.nutritionapp.e216. Do not press reset.
              </Text>
            ) : null}
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Complete E2-16D restart inspection"
              style={styles.button}
              disabled={busy || Platform.OS !== "ios"}
              onPress={() => void completeStageDCase()}
            >
              <Text style={styles.buttonText}>COMPLETE RESTART INSPECTION</Text>
            </Pressable>
          </>
        ) : null}
        <View style={styles.caseCard}>
          <Text style={styles.caseTitle}>Pre-mutation OS-termination control</Text>
          <Text style={styles.detail}>
            One shared iOS control prepares a committed Food fixture, captures the authoritative pre-state,
            and exposes the before_mutation marker without invoking the mutation-under-test.
          </Text>
          <Text selectable style={styles.status}>
            Control marker: {stageDControlMarker ? `${stageDControlMarker.checkpointReached} / ${stageDControlMarker.state}` : "none"}
          </Text>
          {stageDControlAwaitingTermination ? (
            <>
              <Text style={styles.restartInstruction}>
                {isE216StageDCurrentProcessSession(stageDControlMarker!.processSessionId)
                  ? "HOST ACTION NOW: terminate and launch."
                  : "RELAUNCH DETECTED: press COMPLETE RESTART INSPECTION."}
              </Text>
              {isE216StageDCurrentProcessSession(stageDControlMarker!.processSessionId) ? (
                <Text style={styles.detail}>
                  Run xcrun simctl terminate booted com.portfolio.nutritionapp.e216, then xcrun simctl launch booted com.portfolio.nutritionapp.e216. Do not press reset.
                </Text>
              ) : null}
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Complete E2-16D pre-mutation control restart inspection"
                style={styles.button}
                disabled={busy || Platform.OS !== "ios"}
                onPress={() => void completeStageDCase()}
              >
                <Text style={styles.buttonText}>COMPLETE RESTART INSPECTION</Text>
              </Pressable>
            </>
          ) : (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Prepare E2-16D pre-mutation control"
              style={[styles.button, styles.runAllButton]}
              disabled={busy || Platform.OS !== "ios" || stageDTerminationPending}
              onPress={() => void prepareStageDPreMutationControl()}
            >
              <Text style={styles.buttonText}>PREPARE BEFORE-MUTATION CONTROL</Text>
            </Pressable>
          )}
          {stageDControlMarker?.state === "completed" && stageDControlMarker.result ? (
            <Text selectable style={styles.result}>{canonicalJsonStringify(stageDControlMarker.result)}</Text>
          ) : null}
        </View>
        {E216_STAGE_D_CASE_DEFINITIONS.map((definition) => {
          const prepared = stageDMarker?.caseId === definition.id && stageDMarker.state === "ready_to_arm";
          const completed = stageDMarker?.caseId === definition.id && stageDMarker.state === "completed";
          return (
            <View key={definition.id} style={styles.caseCard}>
              <Text style={styles.caseTitle}>{definition.title} — {definition.checkpoint === "during_transaction" ? "during transaction" : "post commit"}</Text>
              <Text style={styles.detail}>{definition.description}</Text>
              <Text selectable style={styles.detail}>Real checkpoint seam: {definition.transactionStage ?? "production mutation promise resolved"}</Text>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`${prepared ? "Arm" : "Prepare"} E2-16D ${definition.id}`}
                style={[styles.button, prepared ? styles.runAllButton : undefined]}
                disabled={busy || Platform.OS !== "ios" || stageDTerminationPending}
                onPress={() => prepared ? void armStageDCase() : void prepareStageDCase(definition.id)}
              >
                <Text style={styles.buttonText}>{prepared ? "ARM REAL MUTATION" : "PREPARE CASE"}</Text>
              </Pressable>
              {prepared ? (
                <Text style={styles.restartInstruction}>
                  The before-mutation marker is durable. Arming will replace it only at the requested transaction/commit checkpoint.
                </Text>
              ) : null}
              {completed && stageDMarker?.result ? (
                <Text selectable style={styles.result}>{canonicalJsonStringify(stageDMarker.result)}</Text>
              ) : null}
            </View>
          );
        })}
      </View>

      <View style={styles.stageCard}>
        <Text style={styles.heading}>E2-16C migration failure qualification (iOS only)</Text>
        <Text style={styles.detail}>
          Each case resets only its fixed Stage-C database before setup, then records logical-state digests,
          physical integrity, rejection evidence, and observed E2-16 reset/delete boundary invocations.
          No Stage-C case runs on Android.
        </Text>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Run all E2-16C migration failure cases"
          style={[styles.button, styles.runAllButton]}
          disabled={busy || Platform.OS !== "ios"}
          onPress={() => void runStageCAll()}
        >
          <Text style={styles.buttonText}>RUN ALL E2-16C CASES</Text>
        </Pressable>
        {E216_STAGE_C_CASE_DEFINITIONS.map((definition) => {
          const state = stageCCaseStates[definition.id];
          return (
            <View key={definition.id} style={styles.caseCard}>
              <Text style={styles.caseTitle}>{definition.title}</Text>
              <Text style={styles.detail}>{definition.description}</Text>
              <Text style={styles.status}>Status: {state.status}</Text>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`Run E2-16C ${definition.title}`}
                style={styles.button}
                disabled={busy || Platform.OS !== "ios"}
                onPress={() => void runStageCCase(definition.id)}
              >
                <Text style={styles.buttonText}>RUN CASE</Text>
              </Pressable>
              {state.error ? <Text accessibilityRole="alert" style={styles.message}>{state.error}</Text> : null}
              {state.result ? (
                <Text selectable style={styles.result}>{canonicalJsonStringify(state.result)}</Text>
              ) : null}
            </View>
          );
        })}
      </View>

      {busy ? <ActivityIndicator accessibilityLabel="E2-16 qualification operation in progress" /> : null}
      <Text style={styles.status}>Database: {handle ? "open" : "closed"}</Text>
      <Text style={styles.status}>Checkpoint: {checkpoint ? "foundation_ready" : "absent"}</Text>
      {message ? <Text accessibilityRole="alert" style={styles.message}>{message}</Text> : null}
      {result ? (
        <View style={styles.resultCard}>
          <Text style={styles.heading}>Bounded qualifier evidence</Text>
          <Text selectable style={styles.result}>{serializeE216IntegrityResult(result)}</Text>
        </View>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: {
    gap: 16,
    padding: 24,
    paddingBottom: 48,
  },
  title: {
    color: "#102a43",
    fontSize: 28,
    fontWeight: "700",
  },
  subtitle: {
    color: "#334e68",
    fontSize: 18,
    fontWeight: "600",
  },
  warning: {
    color: "#7c2d12",
    fontSize: 15,
    lineHeight: 22,
  },
  card: {
    backgroundColor: "#f0f4f8",
    borderRadius: 8,
    gap: 6,
    padding: 16,
  },
  heading: {
    color: "#102a43",
    fontSize: 17,
    fontWeight: "700",
  },
  detail: {
    color: "#243b53",
    fontFamily: "monospace",
    fontSize: 13,
  },
  actions: {
    gap: 10,
  },
  stageCard: {
    backgroundColor: "#eef2ff",
    borderColor: "#a5b4fc",
    borderRadius: 8,
    borderWidth: 1,
    gap: 12,
    padding: 16,
  },
  caseCard: {
    backgroundColor: "#ffffff",
    borderColor: "#cbd5e1",
    borderRadius: 8,
    borderWidth: 1,
    gap: 8,
    padding: 12,
  },
  caseTitle: {
    color: "#1e293b",
    fontSize: 16,
    fontWeight: "700",
  },
  restartInstruction: {
    color: "#7c2d12",
    fontSize: 14,
    lineHeight: 20,
  },
  button: {
    alignItems: "center",
    backgroundColor: "#0b69a3",
    borderRadius: 6,
    minHeight: 48,
    justifyContent: "center",
    paddingHorizontal: 16,
  },
  runAllButton: {
    backgroundColor: "#4c1d95",
  },
  resetButton: {
    backgroundColor: "#9b2c2c",
  },
  buttonText: {
    color: "#ffffff",
    fontSize: 14,
    fontWeight: "700",
  },
  status: {
    color: "#334e68",
    fontSize: 15,
  },
  message: {
    color: "#102a43",
    fontSize: 15,
    lineHeight: 22,
  },
  resultCard: {
    backgroundColor: "#f7fafc",
    borderColor: "#bcccdc",
    borderRadius: 8,
    borderWidth: 1,
    padding: 12,
  },
  result: {
    color: "#102a43",
    fontFamily: "monospace",
    fontSize: 11,
    lineHeight: 16,
  },
});
