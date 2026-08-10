import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ActivityIndicator, StyleSheet, Text, View } from "react-native";
import type { MobileRuntimeConfig } from "../../config/runtimeConfig";

import type { NutritionRuntime } from "./NutritionRuntime";
import {
  ApplicationRuntimeSelectionManager,
  SupersededRuntimeSelectionError,
  bootstrapApplicationRuntime,
  type ApplicationRuntimeHandle,
} from "./applicationRuntimeBootstrap";

type BootstrapState =
  | { kind: "loading"; selectionKey: string }
  | { kind: "ready"; selectionKey: string; runtime: NutritionRuntime }
  | { kind: "failure"; selectionKey: string; message: string };

function configurationIdentity(configuration: MobileRuntimeConfig): string {
  return configuration.dataAuthority === "local"
    ? JSON.stringify(["local", configuration.deploymentMode])
    : JSON.stringify([
      "remote",
      configuration.deploymentMode,
      configuration.apiBaseUrl,
      configuration.privateAuthToken ?? null,
    ]);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Nutrition runtime initialization failed.";
}

export function RuntimeBootstrapStatus({
  kind,
  message,
}: {
  kind: "loading" | "failure";
  message: string;
}) {
  return (
    <View
      accessibilityLiveRegion="polite"
      accessibilityRole={kind === "failure" ? "alert" : undefined}
      style={styles.container}
    >
      {kind === "loading" ? <ActivityIndicator accessibilityLabel={message} /> : null}
      <Text style={kind === "failure" ? styles.failure : styles.message}>{message}</Text>
    </View>
  );
}

export function ApplicationRuntimeBootstrap({
  configuration,
  bootstrap = bootstrapApplicationRuntime,
  children,
}: {
  configuration: MobileRuntimeConfig;
  bootstrap?: (configuration: MobileRuntimeConfig) => Promise<ApplicationRuntimeHandle>;
  children(runtime: NutritionRuntime): ReactNode;
}) {
  const manager = useMemo(() => new ApplicationRuntimeSelectionManager(bootstrap), [bootstrap]);
  const selectionKey = configurationIdentity(configuration);
  const [state, setState] = useState<BootstrapState>({
    kind: "loading",
    selectionKey,
  });

  useEffect(() => {
    let active = true;
    setState({ kind: "loading", selectionKey });
    void manager.select(configuration).then(
      (handle) => {
        if (active) {
          setState({
            kind: "ready",
            selectionKey,
            runtime: handle.runtime,
          });
        }
      },
      (error: unknown) => {
        if (active && !(error instanceof SupersededRuntimeSelectionError)) {
          setState({
            kind: "failure",
            selectionKey,
            message: errorMessage(error),
          });
        }
      },
    );
    return () => { active = false; };
  }, [manager, selectionKey]);

  useEffect(() => () => { void manager.dispose(); }, [manager]);

  if (state.selectionKey !== selectionKey || state.kind === "loading") {
    return <RuntimeBootstrapStatus kind="loading" message={`Starting ${configuration.dataAuthority} nutrition data…`} />;
  }
  if (state.kind === "failure") {
    return <RuntimeBootstrapStatus kind="failure" message={state.message} />;
  }
  return <>{children(state.runtime)}</>;
}

const styles = StyleSheet.create({
  container: {
    alignItems: "center",
    backgroundColor: "#f8fafc",
    flex: 1,
    justifyContent: "center",
    padding: 24,
  },
  message: {
    color: "#17202a",
    marginTop: 12,
    textAlign: "center",
  },
  failure: {
    color: "#b42318",
    textAlign: "center",
  },
});
