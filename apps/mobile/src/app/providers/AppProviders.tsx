import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type PropsWithChildren } from "react";
import { AppThemeProvider } from "../theme/AppTheme";
import { startLogMutationRecovery } from "../../features/logging/recovery/logMutationRecovery";
import type { NutritionRuntime } from "../../runtime/NutritionRuntime";
import { NutritionRuntimeProvider } from "../../runtime/NutritionRuntimeContext";

function LogMutationRecoveryBootstrap({ runtime }: { runtime: NutritionRuntime }) {
  const client = useQueryClient();
  useEffect(() => startLogMutationRecovery(client, {
    authority: runtime.authority,
    dailyLogs: runtime.dailyLogs,
  }), [client, runtime.authority, runtime.dailyLogs]);
  return null;
}

function AuthorityScopedProviders({
  children,
  runtime,
}: PropsWithChildren<{ runtime: NutritionRuntime }>) {
  const [queryClient] = useState(() => new QueryClient());
  useEffect(() => () => queryClient.clear(), [queryClient]);
  return (
    <NutritionRuntimeProvider runtime={runtime}>
      <QueryClientProvider client={queryClient}>
        <LogMutationRecoveryBootstrap runtime={runtime} />
        <AppThemeProvider>{children}</AppThemeProvider>
      </QueryClientProvider>
    </NutritionRuntimeProvider>
  );
}

export function AppProviders({
  children,
  runtime,
}: PropsWithChildren<{ runtime: NutritionRuntime }>) {
  const authorityKey = `${runtime.authority.kind}:${runtime.authority.recoveryScope}`;
  return (
    <AuthorityScopedProviders key={authorityKey} runtime={runtime}>
      {children}
    </AuthorityScopedProviders>
  );
}
