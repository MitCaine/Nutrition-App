import AsyncStorage from "@react-native-async-storage/async-storage";
import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { PropsWithChildren } from "react";
import { useColorScheme } from "react-native";
import {
  loadThemePreference,
  resolveColorScheme,
  saveThemePreference,
  type ColorScheme,
  type ThemePreference,
} from "./themePreference";

export type AppTheme = {
  mode: "light" | "dark";
  colors: {
    background: string; surface: string; secondarySurface: string; input: string;
    text: string; secondaryText: string; mutedText: string; border: string;
    accent: string; accentForeground: string; activeBackground: string;
    inactiveForeground: string; successBackground: string; successBorder: string;
    successText: string; warningBackground: string; warningText: string;
    errorText: string; destructive: string; modalBackdrop: string;
    disabledBackground: string; disabledText: string; pressedBackground: string;
    placeholder: string; searchInputSurface: string; searchInputBorder: string;
    navigationSurface: string; navigationBorder: string; controlSecondaryForeground: string;
    listDivider: string;
    primaryActionBackground: string; primaryActionForeground: string; primaryActionBorder: string;
    selectedNavigationBackground: string; selectedNavigationForeground: string;
  };
};

const lightColors: AppTheme["colors"] = {
  background: "#f8fafc", surface: "#ffffff", secondarySurface: "#f2f4f7", input: "#ffffff",
  text: "#17202a", secondaryText: "#5f6875", mutedText: "#78828f", border: "#dfe3e8",
  accent: "#1f6fb2", accentForeground: "#ffffff", activeBackground: "#dbeafe",
  inactiveForeground: "#5f6875", successBackground: "#e6f4ea", successBorder: "#137333",
  successText: "#0b5c2f", warningBackground: "#fff4d6", warningText: "#855000",
  errorText: "#b42318", destructive: "#b42318", modalBackdrop: "rgba(0, 0, 0, 0.35)",
  disabledBackground: "#e5e9ef", disabledText: "#7b8490", pressedBackground: "#e5e9ef",
  placeholder: "#7b8490",
  searchInputSurface: "#ffffff", searchInputBorder: "#dfe3e8",
  navigationSurface: "#f2f4f7", navigationBorder: "#dfe3e8", controlSecondaryForeground: "#5f6875",
  listDivider: "#dfe3e8",
  primaryActionBackground: "#1f6fb2", primaryActionForeground: "#ffffff", primaryActionBorder: "#1f6fb2",
  selectedNavigationBackground: "#dbeafe", selectedNavigationForeground: "#1f6fb2",
};

const darkColors: AppTheme["colors"] = {
  background: "#171d24", surface: "#1b2129", secondarySurface: "#242b35", input: "#202731",
  text: "#f1f4f7", secondaryText: "#b2bbc6", mutedText: "#8f9aa7", border: "#38414d",
  accent: "#65aef2", accentForeground: "#07121d", activeBackground: "#173d5d",
  inactiveForeground: "#c0c9d4", successBackground: "#173d2a", successBorder: "#3e9b68",
  successText: "#9ce0b5", warningBackground: "#463813", warningText: "#f4cf71",
  errorText: "#ff9b94", destructive: "#ff766e", modalBackdrop: "rgba(0, 0, 0, 0.65)",
  disabledBackground: "#2a313b", disabledText: "#77818d", pressedBackground: "#303946",
  placeholder: "#b3bec9",
  searchInputSurface: "#38414d", searchInputBorder: "#4a6078",
  navigationSurface: "#38414d", navigationBorder: "#43576d", controlSecondaryForeground: "#b9c4d0",
  listDivider: "#465361",
  primaryActionBackground: "#194170", primaryActionForeground: "#ffffff", primaryActionBorder: "#4b84bf",
  selectedNavigationBackground: "#194170", selectedNavigationForeground: "#65aef2",
};

export const LIGHT_THEME: AppTheme = { mode: "light", colors: lightColors };
export const DARK_THEME: AppTheme = { mode: "dark", colors: darkColors };

export function themeForColorScheme(scheme: "light" | "dark" | null | undefined): AppTheme {
  return scheme === "dark" ? DARK_THEME : LIGHT_THEME;
}

export type AppThemeContextValue = AppTheme & {
  preference: ThemePreference;
  effectiveScheme: ColorScheme;
  setPreference: (preference: ThemePreference) => void;
};

const ThemeContext = createContext<AppThemeContextValue>({
  ...LIGHT_THEME,
  preference: "system",
  effectiveScheme: "light",
  setPreference: () => undefined,
});

export function AppThemeProvider({ children }: PropsWithChildren) {
  const systemScheme = useColorScheme();
  const [preference, setPreferenceState] = useState<ThemePreference>("system");
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    let active = true;
    void loadThemePreference(AsyncStorage).then((storedPreference) => {
      if (active) {
        setPreferenceState(storedPreference);
        setHydrated(true);
      }
    });
    return () => { active = false; };
  }, []);

  const effectiveScheme = resolveColorScheme(preference, systemScheme);
  const theme = themeForColorScheme(effectiveScheme);
  const value = useMemo<AppThemeContextValue>(() => ({
    ...theme,
    preference,
    effectiveScheme,
    setPreference: (nextPreference) => {
      setPreferenceState(nextPreference);
      void saveThemePreference(AsyncStorage, nextPreference);
    },
  }), [effectiveScheme, preference, theme]);

  if (!hydrated) {
    return null;
  }
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useAppTheme(): AppThemeContextValue {
  return useContext(ThemeContext);
}

export function statusBarStyle(theme: AppTheme): "light-content" | "dark-content" {
  return theme.mode === "dark" ? "light-content" : "dark-content";
}

export function navigationCapsuleBorder(theme: AppTheme): string {
  return theme.mode === "dark" ? theme.colors.primaryActionBorder : theme.colors.navigationBorder;
}
