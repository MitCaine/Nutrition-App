import type { AggregatedNutrientTotal } from "./types";

export function formatAggregatedTotal(total: AggregatedNutrientTotal): string {
  const estimated = total.amountEstimated === "0" ? "" : ` + ${total.amountEstimated} estimated`;
  const unknown = total.hasUnknownContributors
    ? ` + unknown from ${total.unknownContributorCount} item${total.unknownContributorCount === 1 ? "" : "s"}`
    : "";

  return `${total.amountKnown}${total.unit}${estimated}${unknown}`;
}
