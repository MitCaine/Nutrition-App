import { APPEARANCE_OPTIONS, appearanceOptionSelected } from "../src/app/settings/settingsModel";

test("Settings exposes System, Light, and Dark appearance rows", () => {
  expect(APPEARANCE_OPTIONS).toEqual([
    { value: "system", label: "System" },
    { value: "light", label: "Light" },
    { value: "dark", label: "Dark" },
  ]);
});

test("only the current appearance option is selected", () => {
  expect(appearanceOptionSelected("dark", "dark")).toBe(true);
  expect(appearanceOptionSelected("dark", "system")).toBe(false);
});
