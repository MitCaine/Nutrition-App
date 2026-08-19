import type {
  TargetConfiguration,
  TargetValue,
} from "../targets/api/types";
import {
  formatTargetAmount,
  targetAuthorityLabel,
  targetDirectionLabel,
} from "../targets/targetProgress";
import type {
  HistoryProjectedDailyValue,
  HistoryProjection,
  HistoryProjectionMode,
} from "./types";

export const HISTORY_OVERVIEW_NUTRIENTS = [
  {
    nutrientId: "calories",
    label: "Calories",
  },
  {
    nutrientId: "protein",
    label: "Protein",
  },
  {
    nutrientId: "total_carbohydrate",
    label: "Carbohydrate",
  },
  {
    nutrientId: "total_fat",
    label: "Fat",
  },
] as const;

export type HistoryOverviewCard =
  Readonly<{
    nutrientId:
      typeof HISTORY_OVERVIEW_NUTRIENTS[number]["nutrientId"];
    label: string;
    unit: string;
    statistic: string;
    denominatorContext: string;
    usableDayCount: number;
    days:
      readonly HistoryProjectedDailyValue[];
    targetContext: string | null;
  }>;

function formattedHistoryAmount(
  value: string,
  unit: string,
): string {
  return `${
    formatTargetAmount(
      value,
      unit,
    )
  } ${unit}`;
}

function denominatorContext(
  mode: HistoryProjectionMode,
  usableDayCount: number,
): string {
  const modeLabel =
    mode === "complete_days"
      ? "Complete-day average"
      : "Logged-day average";

  const dayLabel =
    usableDayCount === 1
      ? "day"
      : "days";

  return (
    `${modeLabel} · ` +
    `${usableDayCount} ${dayLabel} used`
  );
}

function meaningfulCurrentTarget(
  target:
    TargetValue | undefined,
): target is TargetValue & Readonly<{
  amount: string;
}> {
  return (
    target !== undefined
    && target.amount !== null
    && (
      target.trackingMode
        === "recommended"
      || target.trackingMode
        === "custom"
    )
    && target.authority
      !== "unavailable"
    && target.direction
      !== "unavailable"
  );
}

function currentTargetContext(
  configuration:
    TargetConfiguration | undefined,
  nutrientId: string,
): string | null {
  const target =
    configuration
      ?.effectiveTargets
      .find(
        (candidate) =>
          candidate.nutrientId
          === nutrientId,
      );

  if (
    !meaningfulCurrentTarget(
      target,
    )
  ) {
    return null;
  }

  return [
    `Current ${
      targetAuthorityLabel(
        target.authority,
      )
    }`,
    formattedHistoryAmount(
      target.amount,
      target.unit,
    ),
    targetDirectionLabel(
      target.direction,
    ),
  ].join(" · ");
}

export function
buildHistoryOverviewCards(
  projection: HistoryProjection,
  configuration?:
    TargetConfiguration,
): readonly HistoryOverviewCard[] {
  return HISTORY_OVERVIEW_NUTRIENTS
    .map((definition) => {
      const nutrient =
        projection.nutrients.find(
          (candidate) =>
            candidate.nutrientId
            === definition.nutrientId,
        );

      if (nutrient === undefined) {
        throw new Error(
          `History projection is missing canonical overview nutrient ${definition.nutrientId}.`,
        );
      }

      return {
        nutrientId:
          definition.nutrientId,
        label:
          definition.label,
        unit:
          nutrient.unit,
        statistic:
          nutrient.average === null
            ? "—"
            : formattedHistoryAmount(
                nutrient.average,
                nutrient.unit,
              ),
        denominatorContext:
          denominatorContext(
            projection.mode,
            nutrient.usableDayCount,
          ),
        usableDayCount:
          nutrient.usableDayCount,
        days:
          nutrient.days,
        targetContext:
          currentTargetContext(
            configuration,
            definition.nutrientId,
          ),
      };
    });
}

export function
selectedHistoryValueLabel(
  card: HistoryOverviewCard,
  date: string,
): string | null {
  const value =
    card.days.find(
      (candidate) =>
        candidate.date === date,
    );

  if (value === undefined) {
    return null;
  }

  if (value.state === "gap") {
    return "No logs";
  }

  if (
    value.state === "unavailable"
    || value.numericAmount === null
  ) {
    return "—";
  }

  return formattedHistoryAmount(
    value.numericAmount,
    card.unit,
  );
}
