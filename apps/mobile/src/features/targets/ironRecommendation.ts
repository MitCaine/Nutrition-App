export function generalAdultIronTarget(
  age: number | null,
  sexForEquation: "female" | "male" | null,
): string | null {
  if (age === null || age < 19) return null;
  if (age >= 51) return "8.000000";
  if (sexForEquation === null) return null;

  return sexForEquation === "female" ? "18.000000" : "8.000000";
}
