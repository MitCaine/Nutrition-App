import type {
  NutrientSection,
} from "../../shared/nutrition/nutrientSections";
import type {
  NutrientUnit,
} from "../../shared/nutrition/types";

export type HistoryProjectionMode =
  | "complete_days"
  | "logged_days";

export type HistoryCoverage = Readonly<{
  requestedDayCount: number;
  loggedDayCount: number;
  completeDayCount: number;
}>;

export type HistoryDailyValueState =
  | "numeric"
  | "unavailable"
  | "gap";

export type HistoryProjectedDailyValue = Readonly<{
  date: string;
  state: HistoryDailyValueState;
  hasLogs: boolean;
  isComplete: boolean;
  hasNutrientEvidence: boolean;
  amountKnown: string | null;
  amountEstimated: string | null;
  numericAmount: string | null;
  isExplicitZeroTotal: boolean;
  hasUnknownContributors: boolean;
  unknownContributorCount: number;
}>;

export type HistoryProjectedNutrient = Readonly<{
  nutrientId: string;
  unit: NutrientUnit;
  usableDayCount: number;
  average: string | null;
  days: readonly HistoryProjectedDailyValue[];
}>;

export type HistoryProjection = Readonly<{
  mode: HistoryProjectionMode;
  startDate: string;
  endDate: string;
  firstLoggedDate: string | null;
  coverage: HistoryCoverage;
  nutrients: readonly HistoryProjectedNutrient[];
  groupedRows: readonly NutrientSection<HistoryProjectedNutrient>[];
}>;
