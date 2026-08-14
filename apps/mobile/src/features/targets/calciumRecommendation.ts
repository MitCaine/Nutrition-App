export function generalAdultCalciumTarget(
  age: number | null,
  sexForEquation: "female" | "male" | null,
): string | null {
  if (age === null || age < 19) return null;

  if (age <= 50) return "1000.000000";
  if (age >= 71) return "1200.000000";

  if (sexForEquation === null) return null;
  return sexForEquation === "female" ? "1200.000000" : "1000.000000";
}
