import type { DailyTargetComparisonItem, TargetAuthority, TargetDirection } from "./api/types";

export const PRIMARY_PROGRESS_NUTRIENTS = [
  "calories", "protein", "total_carbohydrate", "total_fat",
  "saturated_fat", "sodium", "dietary_fiber", "added_sugars",
] as const;

export function targetAuthorityLabel(authority: TargetAuthority): string {
  if (authority === "manual_override") return "Personal target";
  if (authority === "calculated_estimate") return "Estimated personal target";
  if (authority === "daily_value") return "FDA Daily Value";
  return "No target";
}

export function targetDirectionLabel(direction: TargetDirection): string {
  if (direction === "limit") return "Limit reference";
  if (direction === "minimum") return "Minimum reference";
  if (direction === "reference") return "Neutral reference";
  if (direction === "target") return "Progress toward target";
  return "No comparison target";
}

function incrementDigits(value: string): string {
  const digits = value.split("");
  for (let index = digits.length - 1; index >= 0; index -= 1) {
    if (digits[index] !== "9") {
      digits[index] = String(Number(digits[index]) + 1);
      return digits.join("");
    }
    digits[index] = "0";
  }
  return `1${digits.join("")}`;
}

export function formatDecimalString(value: string, fractionDigits: number): string {
  const match = /^(\d+)(?:\.(\d+))?$/.exec(value);
  if (!match) return value;
  let whole = match[1].replace(/^0+(?=\d)/, "");
  let fraction = match[2] ?? "";
  const kept = fraction.padEnd(fractionDigits, "0").slice(0, fractionDigits);
  const roundsUp = (fraction[fractionDigits] ?? "0") >= "5";
  let combined = `${whole}${kept}`;
  if (roundsUp) combined = incrementDigits(combined);
  if (fractionDigits > 0) {
    whole = combined.slice(0, -fractionDigits) || "0";
    fraction = combined.slice(-fractionDigits).replace(/0+$/, "");
  } else {
    whole = combined;
    fraction = "";
  }
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return fraction ? `${grouped}.${fraction}` : grouped;
}

export function formatTargetAmount(value: string, unit: string): string {
  return formatDecimalString(value, unit === "kcal" ? 0 : 1);
}

export function formatTargetPercentage(value: string): string {
  const whole = value.split(".")[0].replace(/^0+(?=\d)/, "");
  return `${formatDecimalString(value, whole.length < 2 ? 1 : 0)}%`;
}

export function percentageAtOrAbove100(value: string | null): boolean {
  if (value === null || !/^\d+(?:\.\d+)?$/.test(value)) return false;
  const whole = value.split(".")[0].replace(/^0+(?=\d)/, "");
  return whole.length > 3 || (whole.length === 3 && whole >= "100");
}

export function boundedProgressValue(value: string | null): number {
  if (value === null) return 0;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 0;
  return Math.max(0, Math.min(100, numeric));
}

export function progressAccessibilityLabel(item: DailyTargetComparisonItem, name: string): string {
  const direction = item.direction === "unavailable" ? null : accessibleTargetDirectionLabel(item.direction);
  const unit = item.unit === "kcal" ? "kilocalories" : item.unit === "g" ? "grams" : item.unit === "mg" ? "milligrams" : item.unit === "mcg" ? "micrograms" : item.unit;
  const consumed = item.consumedAmount === null ? "no consumed amount" : `${formatTargetAmount(item.consumedAmount, item.unit)} ${unit} consumed`;
  const target = item.targetAmount === null ? null : `${formatTargetAmount(item.targetAmount, item.unit)} ${unit} target`;
  const percentage = item.percentage === null ? null : formatTargetPercentage(item.percentage);
  const numericState = item.direction === "limit" && percentageAtOrAbove100(item.percentage) ? ", limit reached or exceeded" : "";
  const state = [direction ? `${direction}${numericState}` : null, item.hasUnknownContributors ? "incomplete data" : null].filter(Boolean);
  return [name, consumed, target, percentage, ...state].filter(Boolean).join(", ");
}

function accessibleTargetDirectionLabel(direction: TargetDirection): string {
  if (direction === "limit") return "limit";
  if (direction === "minimum") return "minimum target";
  if (direction === "reference") return "reference target";
  if (direction === "target") return "progress toward target";
  return "no comparison target";
}
