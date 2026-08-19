import type {
  CalendarState,
} from "../calendar/types";
import {
  addCalendarDays,
} from "../logging/utils/dailyLogDisplay";
import type {
  NutrientSectionId,
} from "../../shared/nutrition/nutrientSections";
import type {
  HistoryProjectionMode,
} from "./types";

export const HISTORY_RANGE_LENGTHS =
  [7, 30] as const;

export type HistoryRangeLength =
  typeof HISTORY_RANGE_LENGTHS[number];

export type HistorySurface =
  | "overview"
  | "nutrition_details"
  | "focused_nutrient";

export const HISTORY_DETAIL_SECTION_ORDER:
readonly NutrientSectionId[] = [
  "nutrition_facts",
  "vitamins",
  "minerals",
  "fatty_acids",
  "other",
];

export const
DEFAULT_HISTORY_DETAIL_COLLAPSED_SECTION_IDS:
readonly NutrientSectionId[] = [
  "vitamins",
  "minerals",
  "fatty_acids",
  "other",
];

export type HistorySession = Readonly<{
  rangeLength: HistoryRangeLength;
  endDate: string;
  latestEndDate: string;
  firstLoggedDate?: string | null;
  denominatorPreference:
    HistoryProjectionMode | null;
  surface?: HistorySurface;
  selectedChartDate?: string | null;
  detailCollapsedSectionIds?:
    readonly NutrientSectionId[];
  detailScrollOffset?: number;
  focusedNutrientId?: string | null;
}>;

export type HistoryRange = Readonly<{
  startDate: string;
  endDate: string;
}>;

export function authoritativeHistoryToday(
  state: CalendarState | undefined,
): string | null {
  if (
    state?.is_established !== true
    || !state.authoritative_time_zone
    || !state.today
  ) {
    return null;
  }

  return state.today;
}

export function latestHistoryEndDate(
  today: string,
): string {
  return addCalendarDays(today, -1);
}

export function freshHistorySession(
  today: string,
  rangeLength: HistoryRangeLength = 7,
): HistorySession {
  const latestEndDate =
    latestHistoryEndDate(today);

  return {
    rangeLength,
    endDate: latestEndDate,
    latestEndDate,
    denominatorPreference: null,
  };
}

export function historyRange(
  session: HistorySession,
): HistoryRange {
  return {
    startDate: addCalendarDays(
      session.endDate,
      -(session.rangeLength - 1),
    ),
    endDate: session.endDate,
  };
}

export function withHistoryRangeLength(
  session: HistorySession,
  rangeLength: HistoryRangeLength,
): HistorySession {
  return {
    ...session,
    rangeLength,
    endDate: session.latestEndDate,
    ...(
      session.selectedChartDate
        === undefined
        ? {}
        : {
            selectedChartDate:
              null,
          }
    ),
  };
}

export function withHistoryFirstLoggedDate(
  session: HistorySession,
  firstLoggedDate: string | null,
): HistorySession {
  return {
    ...session,
    firstLoggedDate,
  };
}

export function historySurface(
  session: HistorySession,
): HistorySurface {
  return session.surface
    ?? "overview";
}

export function historySelectedChartDate(
  session: HistorySession,
): string | null {
  return session.selectedChartDate
    ?? null;
}

export function
historyDetailCollapsedSectionIds(
  session: HistorySession,
): readonly NutrientSectionId[] {
  return (
    session.detailCollapsedSectionIds
    ?? DEFAULT_HISTORY_DETAIL_COLLAPSED_SECTION_IDS
  );
}

export function historyDetailsScrollOffset(
  session: HistorySession,
): number {
  return session.detailScrollOffset
    ?? 0;
}

export function historyFocusedNutrientId(
  session: HistorySession,
): string | null {
  return session.focusedNutrientId
    ?? null;
}

export function withHistorySurface(
  session: HistorySession,
  surface: HistorySurface,
): HistorySession {
  return {
    ...session,
    surface,
  };
}

export function withHistorySelectedChartDate(
  session: HistorySession,
  selectedChartDate: string | null,
): HistorySession {
  return {
    ...session,
    selectedChartDate,
  };
}

export function
withHistoryDetailSectionToggled(
  session: HistorySession,
  sectionId: NutrientSectionId,
): HistorySession {
  const current =
    historyDetailCollapsedSectionIds(
      session,
    );

  const collapsed =
    current.includes(sectionId)
      ? current.filter(
          (candidate) =>
            candidate !== sectionId,
        )
      : [
          ...current,
          sectionId,
        ];

  const normalized =
    HISTORY_DETAIL_SECTION_ORDER
      .filter(
        (candidate) =>
          collapsed.includes(
            candidate,
          ),
      );

  return {
    ...session,
    detailCollapsedSectionIds:
      normalized,
  };
}

export function withHistoryDetailsScrollOffset(
  session: HistorySession,
  detailScrollOffset: number,
): HistorySession {
  const normalized =
    Number.isFinite(
      detailScrollOffset,
    )
      ? Math.max(
          0,
          Math.round(
            detailScrollOffset,
          ),
        )
      : 0;

  return {
    ...session,
    detailScrollOffset:
      normalized,
  };
}

export function withHistoryFocusedNutrient(
  session: HistorySession,
  focusedNutrientId: string,
): HistorySession {
  return {
    ...session,
    surface:
      "focused_nutrient",
    focusedNutrientId,
  };
}

export function withHistoryDenominatorPreference(
  session: HistorySession,
  denominatorPreference:
    HistoryProjectionMode,
): HistorySession {
  return {
    ...session,
    denominatorPreference,
  };
}

export function previousHistorySession(
  session: HistorySession,
): HistorySession {
  return {
    ...session,
    endDate: addCalendarDays(
      session.endDate,
      -session.rangeLength,
    ),
    ...(
      session.selectedChartDate
        === undefined
        ? {}
        : {
            selectedChartDate:
              null,
          }
    ),
  };
}

export function canPageHistoryNext(
  session: HistorySession,
): boolean {
  const candidate =
    addCalendarDays(
      session.endDate,
      session.rangeLength,
    );

  return (
    candidate
    <= session.latestEndDate
  );
}

export function nextHistorySession(
  session: HistorySession,
): HistorySession {
  if (
    !canPageHistoryNext(session)
  ) {
    return session;
  }

  return {
    ...session,
    endDate: addCalendarDays(
      session.endDate,
      session.rangeLength,
    ),
    ...(
      session.selectedChartDate
        === undefined
        ? {}
        : {
            selectedChartDate:
              null,
          }
    ),
  };
}

export function canPageHistoryPrevious(
  session: HistorySession,
  firstLoggedDate: string | null,
): boolean {
  if (firstLoggedDate === null) {
    return false;
  }

  const candidatePreviousEnd =
    addCalendarDays(
      session.endDate,
      -session.rangeLength,
    );

  return (
    candidatePreviousEnd
    >= firstLoggedDate
  );
}

export function effectiveHistoryProjectionMode(
  completeDayCount: number,
  preference: HistoryProjectionMode | null,
): HistoryProjectionMode {
  if (completeDayCount === 0) {
    return "logged_days";
  }

  return preference ?? "complete_days";
}
