import { AppNavigator } from "./app/navigation/AppNavigator";
import { AppProviders } from "./app/providers/AppProviders";
import { StatusBar } from "react-native";
import { useMemo } from "react";
import { loadExpoPublicConfig, type MobileRuntimeConfig } from "../config/runtimeConfig";
import { statusBarStyle, useAppTheme } from "./app/theme/AppTheme";
import {
  ApplicationRuntimeBootstrap,
  RuntimeBootstrapStatus,
} from "./runtime/RuntimeBootstrapGate";

function ThemedApp() {
  const theme = useAppTheme();
  return <><StatusBar barStyle={statusBarStyle(theme)} backgroundColor={theme.colors.background} /><AppNavigator /></>;
}

function ProductionApp() {
  const configured = useMemo<
    { ok: true; configuration: MobileRuntimeConfig } | { ok: false; error: string }
  >(() => {
    try {
      return {
        ok: true,
        configuration: loadExpoPublicConfig({
          EXPO_PUBLIC_NUTRITION_DATA_AUTHORITY: process.env.EXPO_PUBLIC_NUTRITION_DATA_AUTHORITY,
          EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE: process.env.EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE,
          EXPO_PUBLIC_NUTRITION_API_URL: process.env.EXPO_PUBLIC_NUTRITION_API_URL,
          EXPO_PUBLIC_NUTRITION_PRIVATE_AUTH_TOKEN: process.env.EXPO_PUBLIC_NUTRITION_PRIVATE_AUTH_TOKEN,
        }),
      };
    } catch (error) {
      return {
        ok: false,
        error: error instanceof Error ? error.message : "Mobile configuration is invalid.",
      };
    }
  }, []);

  if (!configured.ok) {
    return <RuntimeBootstrapStatus kind="failure" message={configured.error} />;
  }

  const renderRuntime = (runtime: Parameters<typeof AppProviders>[0]["runtime"]) => (
    <AppProviders runtime={runtime}>
      <ThemedApp />
    </AppProviders>
  );
  if (configured.configuration.dataAuthority === "local") {
    // Preserve remote startup isolation: evaluate the SQLite/import gate only
    // after configuration has selected local authority.
    const { LocalFirstStartRuntimeBootstrap } = require("./transfer/e2_15/LocalFirstStartGate") as
      typeof import("./transfer/e2_15/LocalFirstStartGate");
    return <LocalFirstStartRuntimeBootstrap>{renderRuntime}</LocalFirstStartRuntimeBootstrap>;
  }
  return (
    <ApplicationRuntimeBootstrap configuration={configured.configuration}>
      {renderRuntime}
    </ApplicationRuntimeBootstrap>
  );
}

export default function App() {
  return <ProductionApp />;
}
