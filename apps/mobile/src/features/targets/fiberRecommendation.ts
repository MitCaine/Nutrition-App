export function generalAdultFiberTarget(
  age: number | null,
  sexForEquation: "female" | "male" | null,
): string | null {
  if (age === null || age < 19 || sexForEquation === null) return null;

  if (sexForEquation === "male") {
    return age <= 50 ? "38.000000" : "30.000000";
  }

  return age <= 50 ? "25.000000" : "21.000000";
}
