import type { ThemePreference } from "../theme/themePreference";

export const APPEARANCE_OPTIONS: ReadonlyArray<{ value: ThemePreference; label: string }> = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

export function appearanceOptionSelected(current: ThemePreference, option: ThemePreference): boolean {
  return current === option;
}
