export function generalAdultPotassiumTarget(
  age: number | null,
  sexForEquation: "female" | "male" | null,
): string | null {
  if (age === null || age < 19 || sexForEquation === null) return null;

  return sexForEquation === "male"
    ? "3400.000000"
    : "2600.000000";
}
