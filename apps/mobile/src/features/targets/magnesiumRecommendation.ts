export function generalAdultMagnesiumTarget(
  age: number | null,
  sexForEquation: "female" | "male" | null,
): string | null {
  if (age === null || age < 19 || sexForEquation === null) return null;

  if (age <= 30) {
    return sexForEquation === "male"
      ? "400.000000"
      : "310.000000";
  }

  return sexForEquation === "male"
    ? "420.000000"
    : "320.000000";
}
