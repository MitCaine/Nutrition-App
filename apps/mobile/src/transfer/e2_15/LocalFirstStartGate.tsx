import { useEffect, useRef, useState, type ReactNode } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import type { NutritionRuntime } from "../../runtime/NutritionRuntime";
import type { OpenLocalRuntimeHandle } from "../../runtime/local/localRuntimeFoundation";
import { E2_15_MAXIMUM_TRANSFER_BYTES, E2_15_SECTION_NAMES } from "./transferPackage";
import {
  LocalFirstStartBootstrapError,
  prepareLocalFirstStart,
  type LocalFirstStartCoordinator,
} from "./localFirstStartCoordinator";
import type { TransferImportResult } from "./transferImporter";

type CachedSelection = Readonly<{
  name: string;
  size: number | null;
  readText(): Promise<string>;
  remove(): Promise<void>;
}>;

type GateDependencies = Readonly<{
  prepare(): Promise<LocalFirstStartCoordinator>;
  pickCachedTransfer(): Promise<CachedSelection | null>;
}>;

const defaultDependencies: GateDependencies = {
  prepare: () => prepareLocalFirstStart(),
  async pickCachedTransfer() {
    const { getDocumentAsync } = require("expo-document-picker") as typeof import("expo-document-picker");
    const result = await getDocumentAsync({
      type: "application/json",
      copyToCacheDirectory: true,
      multiple: false,
    });
    if (result.canceled) return null;
    const asset = result.assets[0];
    if (!asset) return null;
    const { File } = require("expo-file-system") as typeof import("expo-file-system");
    const file = new File(asset.uri);
    return {
      name: asset.name,
      size: asset.size ?? null,
      readText: () => file.text(),
      remove: async () => { file.delete(); },
    };
  },
};

type State =
  | { kind: "opening" }
  | { kind: "choice"; message: string | null }
  | { kind: "progress"; message: string }
  | { kind: "success"; handle: OpenLocalRuntimeHandle; transferResult: TransferImportResult }
  | { kind: "ready"; handle: OpenLocalRuntimeHandle }
  | { kind: "post_commit_failure"; message: string; transferResult: TransferImportResult }
  | { kind: "failure"; message: string };

function message(error: unknown): string {
  return error instanceof Error ? error.message : "Local nutrition startup failed.";
}

function TransferEvidence({ result }: { result: TransferImportResult }) {
  const sectionCounts = E2_15_SECTION_NAMES
    .map((name) => `${name}: ${result.sectionCounts[name]}`)
    .join("\n");
  return (
    <View accessibilityLabel="Committed transfer evidence" style={styles.evidence}>
      <Text style={styles.evidenceLabel}>Overall SHA-256 digest</Text>
      <Text selectable style={styles.digest}>{result.overallDigest}</Text>
      <Text style={styles.evidenceLabel}>Section counts</Text>
      <Text selectable style={styles.counts}>{sectionCounts}</Text>
    </View>
  );
}

export function LocalFirstStartRuntimeBootstrap({
  children,
  dependencies = defaultDependencies,
}: {
  children(runtime: NutritionRuntime): ReactNode;
  dependencies?: GateDependencies;
}) {
  const [state, setState] = useState<State>({ kind: "opening" });
  const coordinator = useRef<LocalFirstStartCoordinator | null>(null);
  const runtimeHandle = useRef<OpenLocalRuntimeHandle | null>(null);

  useEffect(() => {
    let active = true;
    void dependencies.prepare().then(async (prepared) => {
      if (!active) {
        await prepared.close();
        return;
      }
      coordinator.current = prepared;
      if (prepared.state === "existing_data") {
      const handle = await prepared.continueExisting();
        runtimeHandle.current = handle;
        if (active) setState({ kind: "ready", handle });
        else await handle.close();
      } else {
      setState({ kind: "choice", message: null });
      }
    }).catch((error: unknown) => {
      if (active) setState({ kind: "failure", message: message(error) });
    });
    return () => {
      active = false;
      const handle = runtimeHandle.current;
      runtimeHandle.current = null;
      if (handle) void handle.close();
      else if (coordinator.current) void coordinator.current.close();
    };
  }, [dependencies]);

  const startEmpty = async () => {
    if (!coordinator.current) return;
    setState({ kind: "progress", message: "Starting an empty local profile…" });
    try {
      const handle = await coordinator.current.startEmpty();
      runtimeHandle.current = handle;
      setState({ kind: "ready", handle });
    } catch (error) {
      setState({ kind: "failure", message: message(error) });
    }
  };

  const importTransfer = async () => {
    if (!coordinator.current) return;
    let selection: CachedSelection | null = null;
    setState({ kind: "progress", message: "Choose a Nutrition transfer file…" });
    try {
      selection = await dependencies.pickCachedTransfer();
      if (!selection) {
        setState({ kind: "choice", message: null });
        return;
      }
      if (!selection.name.endsWith(".nutrition-transfer.json")) {
        throw new Error("Choose a .nutrition-transfer.json file.");
      }
      if (selection.size !== null && selection.size > E2_15_MAXIMUM_TRANSFER_BYTES) {
        throw new Error("The transfer file exceeds the 64 MiB maximum.");
      }
      setState({ kind: "progress", message: "Validating transfer file…" });
      const document = await selection.readText();
      setState({ kind: "progress", message: "Importing local nutrition data…" });
      const imported = await coordinator.current.importTransfer(document, {
        onCheckpoint(checkpoint) {
          if (checkpoint.startsWith("qualification_")) {
            setState({ kind: "progress", message: "Qualifying imported nutrition data…" });
          }
        },
      });
      runtimeHandle.current = imported.handle;
      setState({ kind: "success", handle: imported.handle, transferResult: imported.transferResult });
    } catch (error) {
      if (error instanceof LocalFirstStartBootstrapError) {
        setState({
          kind: "post_commit_failure",
          message: `${error.message} ${message(error.cause)}`,
          transferResult: error.transferResult,
        });
      } else {
        setState({ kind: "choice", message: message(error) });
      }
    } finally {
      if (selection) await selection.remove().catch(() => undefined);
    }
  };

  const retryLocalStartup = async () => {
    if (!coordinator.current) return;
    setState({ kind: "progress", message: "Retrying local startup…" });
    try {
      const imported = await coordinator.current.retryLocalStartup();
      runtimeHandle.current = imported.handle;
      setState({ kind: "success", handle: imported.handle, transferResult: imported.transferResult });
    } catch (error) {
      if (error instanceof LocalFirstStartBootstrapError) {
        setState({
          kind: "post_commit_failure",
          message: `${error.message} ${message(error.cause)}`,
          transferResult: error.transferResult,
        });
      } else {
        setState({ kind: "failure", message: message(error) });
      }
    }
  };

  if (state.kind === "ready") return <>{children(state.handle)}</>;
  if (state.kind === "opening" || state.kind === "progress") {
    const progressMessage = state.kind === "opening" ? "Checking local nutrition data…" : state.message;
    return (
      <View accessibilityLiveRegion="polite" style={styles.container}>
        <ActivityIndicator accessibilityLabel={progressMessage} />
        <Text style={styles.body}>{progressMessage}</Text>
      </View>
    );
  }
  if (state.kind === "failure") {
    return <View accessibilityRole="alert" style={styles.container}><Text style={styles.failure}>{state.message}</Text></View>;
  }
  if (state.kind === "success") {
    return (
      <View accessibilityLiveRegion="polite" style={styles.container}>
        <Text accessibilityRole="header" style={styles.title}>Transfer complete</Text>
        <Text style={styles.body}>
          Your local nutrition data passed qualification. Delete the original transfer file manually after confirming your data.
        </Text>
        <TransferEvidence result={state.transferResult} />
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Continue to Nutrition App"
          onPress={() => setState({ kind: "ready", handle: state.handle })}
          style={styles.primaryButton}
        >
          <Text style={styles.primaryLabel}>Continue</Text>
        </Pressable>
      </View>
    );
  }
  if (state.kind === "post_commit_failure") {
    return (
      <View accessibilityLiveRegion="polite" style={styles.container}>
        <Text accessibilityRole="header" style={styles.title}>Transfer committed; local startup incomplete</Text>
        <Text accessibilityRole="alert" style={styles.failure}>{state.message}</Text>
        <Text style={styles.body}>
          The imported data remains in the local database. Retry local startup to continue; the transfer will not be imported again.
        </Text>
        <TransferEvidence result={state.transferResult} />
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Retry local startup"
          onPress={() => { void retryLocalStartup(); }}
          style={styles.primaryButton}
        >
          <Text style={styles.primaryLabel}>Retry local startup</Text>
        </Pressable>
      </View>
    );
  }
  return (
    <View style={styles.container}>
      <Text accessibilityRole="header" style={styles.title}>Set up local nutrition data</Text>
      <Text style={styles.body}>
        Import your one-time PostgreSQL transfer, or explicitly start with an empty local profile.
      </Text>
      {state.message ? <Text accessibilityRole="alert" style={styles.failure}>{state.message}</Text> : null}
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Import transfer file"
        accessibilityHint="Choose a Nutrition transfer file and validate it before importing."
        onPress={() => { void importTransfer(); }}
        style={styles.primaryButton}
      >
        <Text style={styles.primaryLabel}>Import transfer file</Text>
      </Pressable>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Start with empty local profile"
        accessibilityHint="Create a new empty local profile without importing remote data."
        onPress={() => { void startEmpty(); }}
        style={styles.secondaryButton}
      >
        <Text style={styles.secondaryLabel}>Start with empty local profile</Text>
      </Pressable>
      <Text style={styles.notice}>
        The app deletes only its temporary cache copy. It never deletes your original transfer file.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: "stretch",
    backgroundColor: "#f8fafc",
    flex: 1,
    justifyContent: "center",
    padding: 24,
  },
  title: { color: "#17202a", fontSize: 24, fontWeight: "700", marginBottom: 12 },
  body: { color: "#344054", fontSize: 16, lineHeight: 24, marginBottom: 20 },
  failure: { color: "#b42318", marginBottom: 16 },
  evidence: { marginBottom: 20 },
  evidenceLabel: { color: "#344054", fontSize: 13, fontWeight: "700", marginBottom: 4 },
  digest: { color: "#17202a", fontFamily: "monospace", fontSize: 13, marginBottom: 12 },
  counts: { color: "#17202a", fontFamily: "monospace", fontSize: 12, lineHeight: 17 },
  primaryButton: { alignItems: "center", backgroundColor: "#176b57", borderRadius: 8, padding: 14 },
  primaryLabel: { color: "#ffffff", fontSize: 16, fontWeight: "700" },
  secondaryButton: { alignItems: "center", borderColor: "#176b57", borderRadius: 8, borderWidth: 1, marginTop: 12, padding: 14 },
  secondaryLabel: { color: "#176b57", fontSize: 16, fontWeight: "700" },
  notice: { color: "#475467", fontSize: 13, lineHeight: 19, marginTop: 18 },
});
