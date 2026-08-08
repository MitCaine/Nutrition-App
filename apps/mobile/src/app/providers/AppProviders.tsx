import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { useEffect, type PropsWithChildren } from "react";
import { AppThemeProvider } from "../theme/AppTheme";
import { startLogMutationRecovery } from "../../features/logging/recovery/logMutationRecovery";
import type { NutritionRuntime } from "../../runtime/NutritionRuntime";
import { NutritionRuntimeProvider } from "../../runtime/NutritionRuntimeContext";
import { remoteNutritionRuntime } from "../../runtime/remote/remoteNutritionRuntime";

const queryClient = new QueryClient();

function LogMutationRecoveryBootstrap({ runtime }: { runtime: NutritionRuntime }) {
  const client = useQueryClient();
  useEffect(() => startLogMutationRecovery(client, {
    authority: runtime.authority,
    dailyLogs: runtime.dailyLogs,
  }), [client, runtime.authority, runtime.dailyLogs]);
  return null;
}

export function AppProviders({
  children,
  runtime = remoteNutritionRuntime,
}: PropsWithChildren<{ runtime?: NutritionRuntime }>) {
  return (
    <NutritionRuntimeProvider runtime={runtime}>
      <QueryClientProvider client={queryClient}>
        <LogMutationRecoveryBootstrap runtime={runtime} />
        <AppThemeProvider>{children}</AppThemeProvider>
      </QueryClientProvider>
    </NutritionRuntimeProvider>
  );
}
