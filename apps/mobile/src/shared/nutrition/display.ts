import type { AggregatedNutrientTotal } from "./types";

export function formatDisplayNumber(value: string | number | null | undefined, options?: { maxFractionDigits?: number }): string {
  if (value === null || value === undefined || value === "") {
    return "unknown";
  }

  const numericValue = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numericValue)) {
    return String(value);
  }

  const maxFractionDigits = options?.maxFractionDigits ?? 2;
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: maxFractionDigits,
    minimumFractionDigits: 0,
  }).format(numericValue);
}

export function formatAmountWithUnit(
  amount: string | number | null | undefined,
  unit: string,
  options?: { maxFractionDigits?: number },
): string {
  const formattedAmount = formatDisplayNumber(amount, options);
  return formattedAmount === "unknown" ? "unknown" : `${formattedAmount}${unit}`;
}

export function formatNutrientLabel(nutrientId: string, displayName?: string | null): string {
  if (displayName?.trim()) {
    return displayName.trim();
  }

  return nutrientId
    .split("_")
    .filter(Boolean)
    .map((word) => {
      const lower = word.toLowerCase();
      if (lower === "d" || lower === "iu") {
        return lower.toUpperCase();
      }
      return lower.charAt(0).toUpperCase() + lower.slice(1);
    })
    .join(" ");
}

export function isUnknownOnlyAggregatedTotal(total: AggregatedNutrientTotal): boolean {
  return (
    formatDisplayNumber(total.amountKnown) === "0" &&
    formatDisplayNumber(total.amountEstimated) === "0" &&
    total.hasUnknownContributors
  );
}

export function formatAggregatedTotal(total: AggregatedNutrientTotal): string {
  const known = formatAmountWithUnit(total.amountKnown, total.unit);
  const estimatedAmount = formatDisplayNumber(total.amountEstimated);
  const estimated = estimatedAmount === "0" ? "" : ` + ${estimatedAmount} estimated`;
  const unknown = total.hasUnknownContributors
    ? ` + unknown from ${total.unknownContributorCount} item${total.unknownContributorCount === 1 ? "" : "s"}`
    : "";

  if (isUnknownOnlyAggregatedTotal(total)) {
    return `Unknown from ${total.unknownContributorCount} item${total.unknownContributorCount === 1 ? "" : "s"}`;
  }

  return `${known}${estimated}${unknown}`;
}
