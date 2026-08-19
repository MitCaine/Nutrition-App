jest.mock(
  "@expo/vector-icons",
  () => ({
    Ionicons: () => null,
  }),
);

jest.mock(
  "react-native-svg",
  () => ({
    __esModule: true,
    default: "Svg",
    Svg: "Svg",
    Circle: "Circle",
    Rect: "Rect",
  }),
);

jest.mock(
  "../src/features/history/historyQuery",
  () => ({
    ...jest.requireActual(
      "../src/features/history/historyQuery",
    ),
    useHistoryRange:
      jest.fn(),
  }),
);

jest.mock(
  "../src/features/targets/hooks/useDailyTargetComparison",
  () => ({
    useTargetConfiguration:
      jest.fn(),
  }),
);

import React from "react";
import {
  Pressable,
  Text,
} from "react-native";
import TestRenderer, {
  act,
} from "react-test-renderer";

import {
  addCalendarDays,
} from "../src/features/logging/utils/dailyLogDisplay";
import type {
  HistoryNutrientEvidence,
  HistoryRangeEvidence,
} from "../src/features/logging/api/types";
import {
  useHistoryRange,
} from "../src/features/history/historyQuery";
import {
  buildHistoryOverviewCards,
} from "../src/features/history/historyOverview";
import {
  historyDailyBarGeometry,
} from "../src/features/history/components/HistoryDailyBarChart";
import {
  freshHistorySession,
  historySelectedChartDate,
  historySurface,
  nextHistorySession,
  previousHistorySession,
  withHistoryDenominatorPreference,
  withHistoryRangeLength,
  withHistorySelectedChartDate,
  withHistorySurface,
  type HistorySession,
} from "../src/features/history/historyRangeModel";
import {
  HistoryScreen,
} from "../src/features/history/screens/HistoryScreen";
import type {
  HistoryProjectedDailyValue,
  HistoryProjectedNutrient,
  HistoryProjection,
  HistoryProjectionMode,
} from "../src/features/history/types";
import type {
  TargetConfiguration,
} from "../src/features/targets/api/types";
import {
  useTargetConfiguration,
} from "../src/features/targets/hooks/useDailyTargetComparison";

const mockUseHistoryRange =
  useHistoryRange as unknown as jest.Mock;

const mockUseTargetConfiguration =
  useTargetConfiguration as unknown as jest.Mock;

function projectedDay(
  date: string,
  state:
    HistoryProjectedDailyValue["state"],
  numericAmount:
    string | null = null,
  explicitZero = false,
): HistoryProjectedDailyValue {
  const hasLogs =
    state !== "gap";

  return {
    date,
    state,
    hasLogs,
    isComplete:
      hasLogs,
    hasNutrientEvidence:
      state !== "gap",
    amountKnown:
      numericAmount,
    amountEstimated:
      state === "numeric"
        ? "0"
        : null,
    numericAmount,
    isExplicitZeroTotal:
      explicitZero,
    hasUnknownContributors:
      false,
    unknownContributorCount:
      0,
  };
}

function projectedDays(
  dayCount: number,
): readonly HistoryProjectedDailyValue[] {
  return Array.from(
    {
      length:
        dayCount,
    },
    (
      _,
      index,
    ) =>
      projectedDay(
        addCalendarDays(
          "2026-07-20",
          index,
        ),
        "numeric",
        String(
          index + 1,
        ),
      ),
  );
}

function projection(
  dayCount = 7,
  mode:
    HistoryProjectionMode =
      "logged_days",
): HistoryProjection {
  const days =
    projectedDays(
      dayCount,
    );

  const nutrientRows:
    readonly HistoryProjectedNutrient[] =
    [
      {
        nutrientId:
          "calories",
        unit:
          "kcal",
        usableDayCount:
          dayCount,
        average:
          "1000",
        days,
      },
      {
        nutrientId:
          "protein",
        unit:
          "g",
        usableDayCount:
          dayCount,
        average:
          "80",
        days,
      },
      {
        nutrientId:
          "total_carbohydrate",
        unit:
          "g",
        usableDayCount:
          dayCount,
        average:
          "120",
        days,
      },
      {
        nutrientId:
          "total_fat",
        unit:
          "g",
        usableDayCount:
          dayCount,
        average:
          null,
        days,
      },
    ];

  return {
    mode,
    startDate:
      days[0].date,
    endDate:
      days[
        days.length - 1
      ].date,
    firstLoggedDate:
      days[0].date,
    coverage: {
      requestedDayCount:
        dayCount,
      loggedDayCount:
        dayCount,
      completeDayCount:
        mode
        === "complete_days"
          ? dayCount
          : 0,
    },
    nutrients:
      nutrientRows,
    groupedRows:
      [],
  };
}

function targetConfiguration():
  TargetConfiguration {
  return {
    effectiveTargets: [
      {
        nutrientId:
          "calories",
        amount:
          "2000",
        unit:
          "kcal",
        authority:
          "manual_override",
        direction:
          "target",
        trackingMode:
          "recommended",
      },
      {
        nutrientId:
          "protein",
        amount:
          "90",
        unit:
          "g",
        authority:
          "manual_override",
        direction:
          "target",
        trackingMode:
          "amount_only",
      },
      {
        nutrientId:
          "total_carbohydrate",
        amount:
          "200",
        unit:
          "g",
        authority:
          "daily_value",
        direction:
          "reference",
        trackingMode:
          "ignored",
      },
      {
        nutrientId:
          "total_fat",
        amount:
          null,
        unit:
          "g",
        authority:
          "unavailable",
        direction:
          "unavailable",
        trackingMode:
          "recommended",
      },
    ],
  } as unknown as TargetConfiguration;
}

function evidenceNutrient(
  nutrientId: string,
  amount: string,
  unit:
    HistoryNutrientEvidence["unit"],
): HistoryNutrientEvidence {
  return {
    nutrientId,
    amountKnown:
      amount,
    amountEstimated:
      "0",
    unit,
    hasNumericEvidence:
      true,
    isExplicitZeroTotal:
      amount === "0",
    hasUnknownContributors:
      false,
    unknownContributorCount:
      0,
  };
}

function evidence():
  HistoryRangeEvidence {
  const start =
    "2026-08-12";

  const days =
    Array.from(
      {
        length: 7,
      },
      (
        _,
        index,
      ) => {
        const amount =
          String(
            index + 1,
          );

        return {
          date:
            addCalendarDays(
              start,
              index,
            ),
          hasLogs:
            true,
          isComplete:
            true,
          nutrients: [
            evidenceNutrient(
              "calories",
              `${amount}00`,
              "kcal",
            ),
            evidenceNutrient(
              "protein",
              `${amount}0`,
              "g",
            ),
            evidenceNutrient(
              "total_carbohydrate",
              `${amount}5`,
              "g",
            ),
            evidenceNutrient(
              "total_fat",
              amount,
              "g",
            ),
          ],
        };
      },
    );

  return {
    startDate:
      start,
    endDate:
      "2026-08-18",
    firstLoggedDate:
      start,
    days,
  };
}

function successfulQuery(
  data:
    HistoryRangeEvidence,
) {
  return {
    data,
    error:
      null,
    isError:
      false,
    isFetching:
      false,
    isLoading:
      false,
    isRefetchError:
      false,
    refetch:
      jest.fn(),
  };
}

function textValue(
  value: unknown,
): string {
  if (
    typeof value
      === "string"
    || typeof value
      === "number"
  ) {
    return String(
      value,
    );
  }

  if (
    Array.isArray(
      value,
    )
  ) {
    return value
      .map(
        textValue,
      )
      .join(" ");
  }

  return "";
}

function screenText(
  renderer:
    TestRenderer.ReactTestRenderer,
): string {
  return renderer.root
    .findAllByType(
      Text,
    )
    .map(
      (node) =>
        textValue(
          node.props.children,
        ),
    )
    .join(" ")
    .replace(
      /\s+/g,
      " ",
    )
    .trim();
}

beforeEach(() => {
  mockUseHistoryRange
    .mockReset();

  mockUseTargetConfiguration
    .mockReset();

  mockUseTargetConfiguration
    .mockReturnValue({
      data:
        undefined,
    });
});

test(
  "overview is exactly Calories, Protein, Carbohydrate, and Fat with E4-05 statistics",
  () => {
    const cards =
      buildHistoryOverviewCards(
        projection(),
      );

    expect(
      cards.map(
        (card) =>
          card.label,
      ),
    ).toEqual([
      "Calories",
      "Protein",
      "Carbohydrate",
      "Fat",
    ]);

    expect(
      cards.map(
        (card) =>
          card.nutrientId,
      ),
    ).toEqual([
      "calories",
      "protein",
      "total_carbohydrate",
      "total_fat",
    ]);

    expect(
      cards[0]
        .statistic,
    ).toBe(
      "1,000 kcal",
    );

    expect(
      cards[0]
        .denominatorContext,
    ).toBe(
      "Logged-day average · 7 days used",
    );

    expect(
      cards[3]
        .statistic,
    ).toBe("—");
  },
);

test(
  "current target lens is numeric and nonblocking without amount-only ignored or unavailable manufacture",
  () => {
    const cards =
      buildHistoryOverviewCards(
        projection(),
        targetConfiguration(),
      );

    expect(
      cards[0]
        .targetContext,
    ).toContain(
      "2,000 kcal",
    );

    expect(
      cards[0]
        .targetContext,
    ).not.toContain(
      "%",
    );

    expect(
      cards[1]
        .targetContext,
    ).toBeNull();

    expect(
      cards[2]
        .targetContext,
    ).toBeNull();

    expect(
      cards[3]
        .targetContext,
    ).toBeNull();

    expect(
      buildHistoryOverviewCards(
        projection(),
        undefined,
      )[0]
        .statistic,
    ).toBe(
      "1,000 kcal",
    );
  },
);

test(
  "daily chart keeps exact slots and distinguishes gap unavailable numeric and explicit zero",
  () => {
    const days = [
      projectedDay(
        "2026-08-12",
        "numeric",
        "10",
      ),
      projectedDay(
        "2026-08-13",
        "gap",
      ),
      projectedDay(
        "2026-08-14",
        "unavailable",
      ),
      projectedDay(
        "2026-08-15",
        "numeric",
        "0",
        true,
      ),
      projectedDay(
        "2026-08-16",
        "numeric",
        "5",
      ),
      projectedDay(
        "2026-08-17",
        "numeric",
        "8",
      ),
      projectedDay(
        "2026-08-18",
        "numeric",
        "3",
      ),
    ] as const;

    const geometry =
      historyDailyBarGeometry(
        days,
      );

    expect(
      geometry.points,
    ).toHaveLength(7);

    expect(
      geometry.baseline,
    ).toBeGreaterThan(0);

    expect(
      geometry.points[1]
        .numericValue,
    ).toBeNull();

    expect(
      geometry.points[2]
        .numericValue,
    ).toBeNull();

    expect(
      geometry.points[3]
        .numericValue,
    ).toBe(0);

    expect(
      geometry.points[3]
        .explicitZero,
    ).toBe(true);

    expect(
      geometry.points[3]
        .barHeight,
    ).toBe(0);

    expect(
      geometry.maxNumericValue,
    ).toBe(10);
  },
);

test(
  "30-day chart retains all dates in physical-touch-sized horizontal slots",
  () => {
    const days =
      projectedDays(
        30,
      );

    const geometry =
      historyDailyBarGeometry(
        days,
      );

    expect(
      geometry.points,
    ).toHaveLength(30);

    expect(
      geometry.points.map(
        (point) =>
          point.date,
      ),
    ).toEqual(
      days.map(
        (day) =>
          day.date,
      ),
    );

    expect(
      geometry.isScrollable,
    ).toBe(true);

    expect(
      geometry.width,
    ).toBe(1320);

    expect(
      geometry.points.every(
        (point) =>
          point.slotWidth
          >= 44,
      ),
    ).toBe(true);

    const sevenDay =
      historyDailyBarGeometry(
        projectedDays(
          7,
        ),
      );

    expect(
      sevenDay.isScrollable,
    ).toBe(false);

    expect(
      sevenDay.width,
    ).toBe(300);
  },
);

test(
  "selected chart date survives denominator and surface changes but clears on period movement",
  () => {
    const fresh =
      freshHistorySession(
        "2026-08-19",
      );

    const selected =
      withHistorySelectedChartDate(
        fresh,
        "2026-08-18",
      );

    expect(
      historySelectedChartDate(
        selected,
      ),
    ).toBe(
      "2026-08-18",
    );

    expect(
      historySelectedChartDate(
        withHistoryDenominatorPreference(
          selected,
          "logged_days",
        ),
      ),
    ).toBe(
      "2026-08-18",
    );

    const details =
      withHistorySurface(
        selected,
        "nutrition_details",
      );

    expect(
      historySurface(
        details,
      ),
    ).toBe(
      "nutrition_details",
    );

    expect(
      historySelectedChartDate(
        details,
      ),
    ).toBe(
      "2026-08-18",
    );

    expect(
      historySelectedChartDate(
        previousHistorySession(
          selected,
        ),
      ),
    ).toBeNull();

    expect(
      historySelectedChartDate(
        withHistoryRangeLength(
          selected,
          30,
        ),
      ),
    ).toBeNull();

    const older:
      HistorySession = {
      ...selected,
      endDate:
        "2026-08-11",
    };

    expect(
      historySelectedChartDate(
        nextHistorySession(
          older,
        ),
      ),
    ).toBeNull();
  },
);

test(
  "HistoryScreen aligns chart selection across four cards and uses a distinct details shell",
  async () => {
    mockUseHistoryRange
      .mockReturnValue(
        successfulQuery(
          evidence(),
        ),
      );

    function Harness() {
      const [
        session,
        setSession,
      ] =
        React.useState(
          () =>
            freshHistorySession(
              "2026-08-19",
            ),
        );

      return React.createElement(
        HistoryScreen,
        {
          onBack:
            jest.fn(),
          onFirstLoggedDateChange:
            jest.fn(),
          onSessionChange:
            setSession,
          session,
        },
      );
    }

    let renderer!:
      TestRenderer.ReactTestRenderer;

    await act(
      async () => {
        renderer =
          TestRenderer.create(
            React.createElement(
              Harness,
            ),
          );
      },
    );

    const initial =
      screenText(
        renderer,
      );

    expect(
      initial,
    ).toContain(
      "Calories",
    );

    expect(
      initial,
    ).toContain(
      "Protein",
    );

    expect(
      initial,
    ).toContain(
      "Carbohydrate",
    );

    expect(
      initial,
    ).toContain(
      "Fat",
    );

    const datePress =
      renderer.root
        .findAllByType(
          Pressable,
        )
        .find(
          (node) =>
            node.props
              .accessibilityLabel
            ===
              "Select Calories History date 2026-08-18",
        );

    expect(
      datePress,
    ).toBeDefined();

    await act(
      async () => {
        datePress
          ?.props
          .onPress();
      },
    );

    const selectedLabels =
      renderer.root
        .findAllByType(
          Text,
        )
        .filter(
          (node) =>
            typeof node.props
              .accessibilityLabel
              === "string"
            && node.props
              .accessibilityLabel
              .includes(
                "selected 2026-08-18",
              ),
        );

    expect(
      selectedLabels,
    ).toHaveLength(4);

    const showMore =
      renderer.root
        .findAllByType(
          Pressable,
        )
        .find(
          (node) =>
            node.props
              .accessibilityLabel
            ===
              "Show more nutrition",
        );

    expect(
      showMore,
    ).toBeDefined();

    await act(
      async () => {
        showMore
          ?.props
          .onPress();
      },
    );

    const detailsText =
      screenText(
        renderer,
      );

    expect(
      detailsText,
    ).toContain(
      "Nutrition Details",
    );

    const detailsChartDateControls =
      renderer.root
        .findAllByType(
          Pressable,
        )
        .filter(
          (node) =>
            typeof node.props
              .accessibilityLabel
              === "string"
            && node.props
              .accessibilityLabel
              .startsWith(
                "Select Calories History date",
              ),
        );

    expect(
      detailsChartDateControls,
    ).toHaveLength(0);

    const back =
      renderer.root
        .findAllByType(
          Pressable,
        )
        .find(
          (node) =>
            node.props
              .accessibilityLabel
            ===
              "Back to History overview",
        );

    expect(
      back,
    ).toBeDefined();

    await act(
      async () => {
        back
          ?.props
          .onPress();
      },
    );

    expect(
      screenText(
        renderer,
      ),
    ).toContain(
      "Carbohydrate",
    );

    await act(
      async () => {
        renderer.unmount();
      },
    );
  },
);
