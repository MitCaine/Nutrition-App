import type {
  TargetConfiguration,
  TargetValue,
} from "../targets/api/types";
import {
  formatTargetAmount,
  targetAuthorityLabel,
  targetDirectionLabel,
} from "../targets/targetProgress";
import {
  NUTRIENT_CATALOG_BY_ID,
} from "../../shared/nutrition/catalog";
import {
  formatNutrientLabel,
} from "../../shared/nutrition/display";
import type {
  HistoryProjectedDailyValue,
  HistoryProjectedNutrient,
  HistoryProjectionMode,
} from "./types";

export type HistoryFocusedReference =
  Readonly<{
    numericValue: number;
    amountLabel: string;
    context: string;
    lineLabel: string;
  }>;

export type HistoryFocusedDailyRow =
  Readonly<{
    date: string;
    state:
      HistoryProjectedDailyValue["state"];
    value: string;
    hasLogs: boolean;
    isComplete: boolean;
    includesEstimated: boolean;
    explicitZero: boolean;
  }>;

export type HistoryFocusedNutrient =
  Readonly<{
    nutrientId: string;
    label: string;
    unit: string;
    statistic: string;
    denominatorContext: string;
    usableDayCount: number;
    days:
      readonly HistoryFocusedDailyRow[];
    projectedDays:
      readonly HistoryProjectedDailyValue[];
    currentReference:
      HistoryFocusedReference | null;
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
    `${modeLabel} · `
    + `${usableDayCount} ${dayLabel} used`
  );
}

function positiveNumericString(
  value: string | null,
): boolean {
  if (value === null) {
    return false;
  }

  const numeric = Number(value);

  return (
    Number.isFinite(numeric)
    && numeric > 0
  );
}

function meaningfulCurrentReference(
  target:
    TargetValue | undefined,
  nutrient:
    HistoryProjectedNutrient,
): target is TargetValue & Readonly<{
  amount: string;
}> {
  if (
    target === undefined
    || target.amount === null
    || (
      target.trackingMode
        !== "recommended"
      && target.trackingMode
        !== "custom"
    )
    || target.authority
      === "unavailable"
    || target.direction
      === "unavailable"
    || target.unit
      !== nutrient.unit
  ) {
    return false;
  }

  const numeric =
    Number(target.amount);

  return (
    Number.isFinite(numeric)
    && numeric >= 0
  );
}

function currentReference(
  configuration:
    TargetConfiguration | undefined,
  nutrient:
    HistoryProjectedNutrient,
): HistoryFocusedReference | null {
  const target =
    configuration
      ?.effectiveTargets
      ?.find(
        (candidate) =>
          candidate.nutrientId
          === nutrient.nutrientId,
      );

  if (
    !meaningfulCurrentReference(
      target,
      nutrient,
    )
  ) {
    return null;
  }

  const amountLabel =
    formattedHistoryAmount(
      target.amount,
      target.unit,
    );

  const authorityLabel =
    targetAuthorityLabel(
      target.authority,
    );

  return {
    numericValue:
      Number(target.amount),
    amountLabel,
    context: [
      `Current ${authorityLabel}`,
      amountLabel,
      targetDirectionLabel(
        target.direction,
      ),
    ].join(" · "),
    lineLabel:
      `Current ${authorityLabel} · ${amountLabel}`,
  };
}

function focusedDailyRow(
  day:
    HistoryProjectedDailyValue,
  unit: string,
): HistoryFocusedDailyRow {
  const value =
    day.state === "gap"
      ? "No logs"
      : (
          day.state === "unavailable"
          || day.numericAmount === null
        )
        ? "—"
        : formattedHistoryAmount(
            day.numericAmount,
            unit,
          );

  return {
    date:
      day.date,
    state:
      day.state,
    value,
    hasLogs:
      day.hasLogs,
    isComplete:
      day.isComplete,
    includesEstimated:
      positiveNumericString(
        day.amountEstimated,
      ),
    explicitZero:
      day.isExplicitZeroTotal,
  };
}

export function
buildHistoryFocusedNutrient(
  nutrient:
    HistoryProjectedNutrient,
  mode:
    HistoryProjectionMode,
  configuration?:
    TargetConfiguration,
): HistoryFocusedNutrient {
  const catalog =
    NUTRIENT_CATALOG_BY_ID.get(
      nutrient.nutrientId,
    );

  const label =
    formatNutrientLabel(
      nutrient.nutrientId,
      catalog?.display_name,
    );

  return {
    nutrientId:
      nutrient.nutrientId,
    label,
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
        mode,
        nutrient.usableDayCount,
      ),
    usableDayCount:
      nutrient.usableDayCount,
    days:
      nutrient.days.map(
        (day) =>
          focusedDailyRow(
            day,
            nutrient.unit,
          ),
      ),
    projectedDays:
      nutrient.days,
    currentReference:
      currentReference(
        configuration,
        nutrient,
      ),
  };
}

export function focusedHistoryDayForDate(
  model:
    HistoryFocusedNutrient,
  date: string,
): HistoryFocusedDailyRow | null {
  return (
    model.days.find(
      (day) =>
        day.date === date,
    )
    ?? null
  );
}
