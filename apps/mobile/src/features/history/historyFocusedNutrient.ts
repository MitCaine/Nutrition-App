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
    amount: string;
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
    numericAmount: string | null;
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
    amount:
      target.amount,
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
    numericAmount:
      day.state === "numeric"
        ? day.numericAmount
        : null,
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

type HistoryDecimalDigits =
  Readonly<{
    digits: string;
    scale: number;
  }>;

function historyDecimalDigits(
  value: string,
): HistoryDecimalDigits | null {
  const match =
    /^(\d+)(?:\.(\d+))?$/
      .exec(
        value,
      );

  if (!match) {
    return null;
  }

  const whole =
    match[1].replace(
      /^0+(?=\d)/,
      "",
    );

  const fraction =
    match[2] ?? "";

  const digits =
    `${whole}${fraction}`
      .replace(
        /^0+(?=\d)/,
        "",
      );

  return {
    digits,
    scale:
      fraction.length,
  };
}

function historyScaledDecimalDigits(
  value: HistoryDecimalDigits,
  scale: number,
): string {
  return (
    value.digits
    + "0".repeat(
      scale
      - value.scale,
    )
  ).replace(
    /^0+(?=\d)/,
    "",
  );
}

function compareHistoryDigitStrings(
  left: string,
  right: string,
): number {
  const width =
    Math.max(
      left.length,
      right.length,
    );

  const normalizedLeft =
    left.padStart(
      width,
      "0",
    );

  const normalizedRight =
    right.padStart(
      width,
      "0",
    );

  if (
    normalizedLeft
      === normalizedRight
  ) {
    return 0;
  }

  return normalizedLeft
    > normalizedRight
      ? 1
      : -1;
}

function subtractHistoryDigitStrings(
  left: string,
  right: string,
): string {
  const width =
    Math.max(
      left.length,
      right.length,
    );

  const normalizedLeft =
    left.padStart(
      width,
      "0",
    );

  const normalizedRight =
    right.padStart(
      width,
      "0",
    );

  let borrow = 0;
  let result = "";

  for (
    let index = width - 1;
    index >= 0;
    index -= 1
  ) {
    let difference =
      Number(
        normalizedLeft[index],
      )
      - borrow
      - Number(
        normalizedRight[index],
      );

    if (difference < 0) {
      difference += 10;
      borrow = 1;
    } else {
      borrow = 0;
    }

    result =
      String(
        difference,
      )
      + result;
  }

  return result.replace(
    /^0+(?=\d)/,
    "",
  );
}

function formatHistoryExactDecimal(
  digits: string,
  scale: number,
): string {
  const padded =
    digits.padStart(
      scale + 1,
      "0",
    );

  let whole =
    scale === 0
      ? padded
      : padded.slice(
          0,
          -scale,
        );

  const fraction =
    scale === 0
      ? ""
      : padded
          .slice(
            -scale,
          )
          .replace(
            /0+$/,
            "",
          );

  whole =
    whole.replace(
      /^0+(?=\d)/,
      "",
    );

  const grouped =
    whole.replace(
      /\B(?=(\d{3})+(?!\d))/g,
      ",",
    );

  return fraction
    ? `${grouped}.${fraction}`
    : grouped;
}

function exactPositiveHistoryDifference(
  left: string,
  right: string,
): string | null {
  const parsedLeft =
    historyDecimalDigits(
      left,
    );

  const parsedRight =
    historyDecimalDigits(
      right,
    );

  if (
    parsedLeft === null
    || parsedRight === null
  ) {
    return null;
  }

  const scale =
    Math.max(
      parsedLeft.scale,
      parsedRight.scale,
    );

  const leftDigits =
    historyScaledDecimalDigits(
      parsedLeft,
      scale,
    );

  const rightDigits =
    historyScaledDecimalDigits(
      parsedRight,
      scale,
    );

  if (
    compareHistoryDigitStrings(
      leftDigits,
      rightDigits,
    ) <= 0
  ) {
    return null;
  }

  return formatHistoryExactDecimal(
    subtractHistoryDigitStrings(
      leftDigits,
      rightDigits,
    ),
    scale,
  );
}

export function
focusedHistoryAboveReferenceLabel(
  model:
    HistoryFocusedNutrient,
  day:
    HistoryFocusedDailyRow,
): string | null {
  if (
    model.currentReference
      === null
    || day.state
      !== "numeric"
    || day.numericAmount
      === null
  ) {
    return null;
  }

  const difference =
    exactPositiveHistoryDifference(
      day.numericAmount,
      model.currentReference
        .amount,
    );

  if (difference === null) {
    return null;
  }

  return (
    `${difference} ${model.unit} `
    + "above reference"
  );
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
