export function generalAdultVitaminDTarget(
  age: number | null,
): string | null {
  if (age === null || age < 19) return null;

  return age >= 71 ? "20.000000" : "15.000000";
}
