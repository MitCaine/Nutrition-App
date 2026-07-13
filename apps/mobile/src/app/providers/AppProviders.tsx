import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { PropsWithChildren } from "react";
import { AppThemeProvider } from "../theme/AppTheme";

const queryClient = new QueryClient();

export function AppProviders({ children }: PropsWithChildren) {
  return <QueryClientProvider client={queryClient}><AppThemeProvider>{children}</AppThemeProvider></QueryClientProvider>;
}
