import type {
  HistoryDayEvidence,
  HistoryNutrientEvidence,
  HistoryRangeEvidence,
} from "../logging/api/types";
import {
  addResponseDecimals,
  divideResponseDecimals,
  parseResponseDecimal,
  type ResponseDecimal,
} from "../../shared/exact/decimal";
import {
  NUTRIENT_CATALOG,
} from "../../shared/nutrition/catalog";
import {
  groupCanonicalNutrientsBySection,
} from "../../shared/nutrition/nutrientSections";
import type {
  NutrientUnit,
} from "../../shared/nutrition/types";
import type {
  HistoryProjectedDailyValue,
  HistoryProjectedNutrient,
  HistoryProjection,
  HistoryProjectionMode,
} from "./types";

export type HistoryProjectionErrorCode =
  "history_projection_unit_mismatch";

export class HistoryProjectionError extends Error {
  readonly code: HistoryProjectionErrorCode;
  readonly nutrientId: string;

  constructor(
    code: HistoryProjectionErrorCode,
    nutrientId: string,
    message: string,
  ) {
    super(message);
    this.name = "HistoryProjectionError";
    this.code = code;
    this.nutrientId = nutrientId;
  }
}

function collectStableUnits(
  evidence: HistoryRangeEvidence,
): Map<string, NutrientUnit> {
  const units = new Map<string, NutrientUnit>(
    NUTRIENT_CATALOG.map(
      (nutrient) => [
        nutrient.id,
        nutrient.default_unit,
      ] as const,
    ),
  );

  for (const day of evidence.days) {
    for (const nutrient of day.nutrients) {
      const existing = units.get(nutrient.nutrientId);
      if (existing !== undefined && existing !== nutrient.unit) {
        throw new HistoryProjectionError(
          "history_projection_unit_mismatch",
          nutrient.nutrientId,
          `History nutrient ${nutrient.nutrientId} changed canonical unit within one range.`,
        );
      }
      units.set(nutrient.nutrientId, nutrient.unit);
    }
  }

  return units;
}

function nutrientEvidenceFor(
  day: HistoryDayEvidence,
  nutrientId: string,
): HistoryNutrientEvidence | undefined {
  return day.nutrients.find(
    (nutrient) => nutrient.nutrientId === nutrientId,
  );
}

function dailyValue(
  day: HistoryDayEvidence,
  nutrientId: string,
): HistoryProjectedDailyValue {
  if (!day.hasLogs) {
    return {
      date: day.date,
      state: "gap",
      hasLogs: false,
      isComplete: false,
      hasNutrientEvidence: false,
      amountKnown: null,
      amountEstimated: null,
      numericAmount: null,
      isExplicitZeroTotal: false,
      hasUnknownContributors: false,
      unknownContributorCount: 0,
    };
  }

  const nutrient = nutrientEvidenceFor(day, nutrientId);

  if (nutrient === undefined) {
    return {
      date: day.date,
      state: "unavailable",
      hasLogs: true,
      isComplete: day.isComplete,
      hasNutrientEvidence: false,
      amountKnown: null,
      amountEstimated: null,
      numericAmount: null,
      isExplicitZeroTotal: false,
      hasUnknownContributors: false,
      unknownContributorCount: 0,
    };
  }

  const common = {
    date: day.date,
    hasLogs: true,
    isComplete: day.isComplete,
    hasNutrientEvidence: true,
    amountKnown: nutrient.amountKnown,
    amountEstimated: nutrient.amountEstimated,
    isExplicitZeroTotal: nutrient.isExplicitZeroTotal,
    hasUnknownContributors: nutrient.hasUnknownContributors,
    unknownContributorCount: nutrient.unknownContributorCount,
  } as const;

  if (!nutrient.hasNumericEvidence) {
    return {
      ...common,
      state: "unavailable",
      numericAmount: null,
    };
  }

  return {
    ...common,
    state: "numeric",
    numericAmount: addResponseDecimals(
      nutrient.amountKnown,
      nutrient.amountEstimated,
    ),
  };
}

function isEligible(
  mode: HistoryProjectionMode,
  value: HistoryProjectedDailyValue,
): boolean {
  if (value.state !== "numeric") {
    return false;
  }

  return mode === "complete_days"
    ? value.isComplete
    : value.hasLogs;
}

function projectNutrient(
  evidence: HistoryRangeEvidence,
  mode: HistoryProjectionMode,
  nutrientId: string,
  unit: NutrientUnit,
): HistoryProjectedNutrient {
  const days = evidence.days.map(
    (day) => dailyValue(day, nutrientId),
  );

  let exactSum: ResponseDecimal =
    parseResponseDecimal("0");
  let usableDayCount = 0;

  for (const value of days) {
    if (!isEligible(mode, value)) {
      continue;
    }

    exactSum = addResponseDecimals(
      exactSum,
      value.numericAmount!,
    );
    usableDayCount += 1;
  }

  return {
    nutrientId,
    unit,
    usableDayCount,
    average: usableDayCount === 0
      ? null
      : divideResponseDecimals(
        exactSum,
        String(usableDayCount),
      ),
    days,
  };
}

export function projectHistoryRange(
  evidence: HistoryRangeEvidence,
  mode: HistoryProjectionMode,
): HistoryProjection {
  const units = collectStableUnits(evidence);

  const rows = [...units.entries()].map(
    ([nutrientId, unit]) =>
      projectNutrient(
        evidence,
        mode,
        nutrientId,
        unit,
      ),
  );

  const groupedRows =
    groupCanonicalNutrientsBySection(
      rows,
      (row) => row.nutrientId,
    );

  const nutrients =
    groupedRows.flatMap(
      (section) => section.items,
    );

  return {
    mode,
    startDate: evidence.startDate,
    endDate: evidence.endDate,
    firstLoggedDate: evidence.firstLoggedDate,
    coverage: {
      requestedDayCount: evidence.days.length,
      loggedDayCount: evidence.days.filter(
        (day) => day.hasLogs,
      ).length,
      completeDayCount: evidence.days.filter(
        (day) => day.isComplete,
      ).length,
    },
    nutrients,
    groupedRows,
  };
}

export function historyValueForDate(
  projection: HistoryProjection,
  nutrientId: string,
  date: string,
): HistoryProjectedDailyValue | null {
  const nutrient = projection.nutrients.find(
    (row) => row.nutrientId === nutrientId,
  );

  if (nutrient === undefined) {
    return null;
  }

  return (
    nutrient.days.find(
      (day) => day.date === date,
    )
    ?? null
  );
}
