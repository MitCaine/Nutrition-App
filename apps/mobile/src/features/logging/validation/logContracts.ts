/** Canonical meal and note rules shared by Daily Log clients. */

export const SUPPORTED_MEALS = ["breakfast", "lunch", "dinner", "snack"] as const;
export type MealType = (typeof SUPPORTED_MEALS)[number];
export const MAX_NOTE_CODE_POINTS = 1000;

export const MEAL_INVALID_MESSAGE = "Meal must be breakfast, lunch, dinner, snack, or absent.";
export const NOTE_INVALID_MESSAGE = "Note must be plain text.";
export const NOTE_TOO_LONG_MESSAGE = "Note must be 1,000 Unicode code points or fewer.";

export function isSupportedMeal(value: unknown): value is MealType {
  return typeof value === "string" && (SUPPORTED_MEALS as readonly string[]).includes(value);
}

/** Normalize an explicit meal while retaining undefined for omitted updates. */
export function normalizeLogMeal(value: string | null | undefined): MealType | null | undefined {
  if (value === undefined || value === null) {
    return value;
  }
  if (!isSupportedMeal(value)) {
    throw new LogContractError("meal_invalid", MEAL_INVALID_MESSAGE, "meal_type");
  }
  return value;
}

/** Trim one note without changing internal whitespace or line breaks. */
export function normalizeLogNote(value: string | null | undefined): string | null | undefined {
  if (value === undefined || value === null) {
    return value;
  }
  if (typeof value !== "string") {
    throw new LogContractError("note_invalid", NOTE_INVALID_MESSAGE, "notes");
  }
  const normalized = value.trim();
  if (codePointLength(normalized) > MAX_NOTE_CODE_POINTS) {
    throw new LogContractError("note_too_long", NOTE_TOO_LONG_MESSAGE, "notes");
  }
  return normalized || null;
}

export function codePointLength(value: string): number {
  return Array.from(value).length;
}

export class LogContractError extends Error {
  readonly code: "meal_invalid" | "note_too_long" | "note_invalid";
  readonly field: "meal_type" | "notes";

  constructor(
    code: "meal_invalid" | "note_too_long" | "note_invalid",
    message: string,
    field: "meal_type" | "notes",
  ) {
    super(message);
    this.name = "LogContractError";
    this.code = code;
    this.field = field;
  }
}
