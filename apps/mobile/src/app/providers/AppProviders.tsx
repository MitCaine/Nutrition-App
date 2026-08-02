import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { useEffect, type PropsWithChildren } from "react";
import { AppThemeProvider } from "../theme/AppTheme";
import { beginLogMutationRecoveryBootstrap, startLogMutationRecovery } from "../../features/logging/recovery/logMutationRecovery";

const queryClient = new QueryClient();

function LogMutationRecoveryBootstrap() {
  const client = useQueryClient();
  useEffect(() => startLogMutationRecovery(client), [client]);
  return null;
}

export function AppProviders({ children }: PropsWithChildren) {
  beginLogMutationRecoveryBootstrap();
  return (
    <QueryClientProvider client={queryClient}>
      <LogMutationRecoveryBootstrap />
      <AppThemeProvider>{children}</AppThemeProvider>
    </QueryClientProvider>
  );
}
