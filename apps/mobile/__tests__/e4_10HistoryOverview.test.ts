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
    Line: "Line",
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
  LIGHT_THEME,
} from "../src/app/theme/AppTheme";
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
  HistoryDailyBarChart,
  historyDailyBarGeometry,
  historySelectedDateScrollTarget,
} from "../src/features/history/components/HistoryDailyBarChart";
import {
  freshHistorySession,
  historySelectedChartDate,
  historySurface,
  nextHistorySession,
  previousHistorySession,
  withHistoryDenominatorPreference,
  withHistoryFocusedNutrient,
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

    const selectedScreenText =
      screenText(
        renderer,
      );

    expect(
      selectedScreenText,
    ).toContain(
      "Average · 400 kcal",
    );

    expect(
      selectedScreenText,
    ).toContain(
      "Selected day · Tue, Aug 18, 2026 · 700 kcal",
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
                "selected day 2026-08-18",
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

test(
  "30-day selected date scroll target centers an offscreen slot",
  () => {
    const days =
      projectedDays(
        30,
      );

    const geometry =
      historyDailyBarGeometry(
        days,
      );

    const selectedDate =
      days[15].date;

    expect(
      historySelectedDateScrollTarget(
        geometry,
        selectedDate,
        0,
      ),
    ).toBe(532);
  },
);

test(
  "30-day selected date scroll target clamps first and last slots to chart bounds",
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
      historySelectedDateScrollTarget(
        geometry,
        days[0].date,
        500,
      ),
    ).toBe(0);

    expect(
      historySelectedDateScrollTarget(
        geometry,
        days[29].date,
        0,
      ),
    ).toBe(1020);
  },
);

test(
  "30-day selected date aligns to one deterministic target even when merely visible",
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
      historySelectedDateScrollTarget(
        geometry,
        days[15].date,
        0,
        300,
      ),
    ).toBe(532);

    expect(
      historySelectedDateScrollTarget(
        geometry,
        days[15].date,
        532,
        300,
      ),
    ).toBeNull();

    expect(
      historySelectedDateScrollTarget(
        geometry,
        days[5].date,
        0,
        300,
      ),
    ).toBe(92);

    expect(
      historySelectedDateScrollTarget(
        geometry,
        days[5].date,
        92,
        300,
      ),
    ).toBeNull();
  },
);

test(
  "30-day selected date target uses the measured chart viewport",
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
      historySelectedDateScrollTarget(
        geometry,
        days[15].date,
        0,
        360,
      ),
    ).toBe(502);

    expect(
      historySelectedDateScrollTarget(
        geometry,
        days[15].date,
        502,
        360,
      ),
    ).toBeNull();
  },
);

test(
  "selected-date visibility ignores null absent and non-scrollable selections",
  () => {
    const thirtyDay =
      historyDailyBarGeometry(
        projectedDays(
          30,
        ),
      );

    expect(
      historySelectedDateScrollTarget(
        thirtyDay,
        null,
        0,
      ),
    ).toBeNull();

    expect(
      historySelectedDateScrollTarget(
        thirtyDay,
        "1999-01-01",
        0,
      ),
    ).toBeNull();

    const sevenDays =
      projectedDays(
        7,
      );

    const sevenDay =
      historyDailyBarGeometry(
        sevenDays,
      );

    expect(
      sevenDay.isScrollable,
    ).toBe(false);

    expect(
      historySelectedDateScrollTarget(
        sevenDay,
        sevenDays[6].date,
        0,
      ),
    ).toBeNull();
  },
);

test(
  "History overview renders the four canonical series with their semantic nutrition colors",
  () => {
    mockUseHistoryRange
      .mockReturnValue(
        successfulQuery(
          evidence(),
        ),
      );

    mockUseTargetConfiguration
      .mockReturnValue({
        data:
          undefined,
      });

    let renderer:
      TestRenderer.ReactTestRenderer;

    act(() => {
      renderer =
        TestRenderer.create(
          React.createElement(
            HistoryScreen,
            {
              session:
                freshHistorySession(
                  "2026-08-19",
                ),
              onSessionChange:
                jest.fn(),
              onFirstLoggedDateChange:
                jest.fn(),
              onBack:
                jest.fn(),
            },
          ),
        );
    });

    const rects =
      renderer!.root.findAll(
        (node) =>
          String(node.type)
            === "Rect",
      );

    const fills =
      rects.map(
        (node) =>
          node.props.fill,
      );

    expect(
      fills,
    ).toHaveLength(
      28,
    );

    expect(
      fills.slice(
        0,
        7,
      ),
    ).toEqual(
      Array(7).fill(
        LIGHT_THEME.colors
          .nutritionCaloriesSeries,
      ),
    );

    expect(
      fills.slice(
        7,
        14,
      ),
    ).toEqual(
      Array(7).fill(
        LIGHT_THEME.colors
          .nutritionProteinSeries,
      ),
    );

    expect(
      fills.slice(
        14,
        21,
      ),
    ).toEqual(
      Array(7).fill(
        LIGHT_THEME.colors
          .nutritionCarbohydrateSeries,
      ),
    );

    expect(
      fills.slice(
        21,
        28,
      ),
    ).toEqual(
      Array(7).fill(
        LIGHT_THEME.colors
          .nutritionFatSeries,
      ),
    );
  },
);

test.each([
  [
    "numeric",
    projectedDay(
      "2026-08-12",
      "numeric",
      "10",
    ),
    true,
  ],
  [
    "explicit zero",
    projectedDay(
      "2026-08-12",
      "numeric",
      "0",
      true,
    ),
    true,
  ],
  [
    "gap",
    projectedDay(
      "2026-08-12",
      "gap",
    ),
    false,
  ],
  [
    "unavailable",
    projectedDay(
      "2026-08-12",
      "unavailable",
    ),
    false,
  ],
])(
  "selected %s date uses the stronger phone-scale selection affordance",
  (
    _name,
    day,
    hasNumericBar,
  ) => {
    let renderer:
      TestRenderer.ReactTestRenderer;

    act(() => {
      renderer =
        TestRenderer.create(
          React.createElement(
            HistoryDailyBarChart,
            {
              days: [
                day,
              ],
              seriesLabel:
                "Test series",
              selectedDate:
                day.date,
              onSelectDate:
                jest.fn(),
              barColor:
                "series-color",
              selectionColor:
                "selection-color",
            },
          ),
        );
    });

    const rects =
      renderer!.root.findAll(
        (node) =>
          String(node.type)
            === "Rect",
      );

    const lines =
      renderer!.root.findAll(
        (node) =>
          String(node.type)
            === "Line",
      );

    if (hasNumericBar) {
      expect(
        rects,
      ).toHaveLength(1);

      expect(
        rects[0].props.fill,
      ).toBe(
        "selection-color",
      );

      expect(
        rects[0].props.stroke,
      ).toBe(
        "series-color",
      );

      expect(
        rects[0].props.strokeWidth,
      ).toBe(2);

      expect(
        lines,
      ).toHaveLength(0);
    } else {
      expect(
        rects,
      ).toHaveLength(0);

      expect(
        lines,
      ).toHaveLength(1);

      expect(
        lines[0].props.stroke,
      ).toBe(
        "selection-color",
      );

      expect(
        lines[0].props.strokeWidth,
      ).toBe(3);

      expect(
        lines[0].props.strokeLinecap,
      ).toBe(
        "round",
      );

      expect(
        lines[0].props.x2
          - lines[0].props.x1,
      ).toBe(16);

      expect(
        lines[0].props.y1,
      ).toBe(
        lines[0].props.y2,
      );
    }
  },
);
test.each([
  [
    "above",
    projectedDay(
      "2026-08-12",
      "numeric",
      "2301",
    ),
    2300,
    true,
    true,
  ],
  [
    "equal",
    projectedDay(
      "2026-08-12",
      "numeric",
      "2300",
    ),
    2300,
    false,
    true,
  ],
  [
    "below",
    projectedDay(
      "2026-08-12",
      "numeric",
      "2299",
    ),
    2300,
    false,
    true,
  ],
  [
    "gap",
    projectedDay(
      "2026-08-12",
      "gap",
    ),
    2300,
    false,
    true,
  ],
  [
    "unavailable",
    projectedDay(
      "2026-08-12",
      "unavailable",
    ),
    2300,
    false,
    true,
  ],
  [
    "no reference",
    projectedDay(
      "2026-08-12",
      "numeric",
      "2301",
    ),
    null,
    false,
    false,
  ],
])(
  "focused chart reference-crossing cue handles %s",
  (
    _name,
    day,
    referenceValue,
    expectedCrossing,
    expectedReferenceLine,
  ) => {
    let renderer:
      TestRenderer.ReactTestRenderer;

    act(() => {
      renderer =
        TestRenderer.create(
          React.createElement(
            HistoryDailyBarChart,
            {
              days: [
                day,
              ],
              seriesLabel:
                "Sodium",
              selectedDate:
                null,
              onSelectDate:
                jest.fn(),
              barColor:
                "series-color",
              selectionColor:
                "selection-color",
              referenceValue,
              referenceLineColor:
                "reference-color",
            },
          ),
        );
    });

    const lines =
      renderer!.root.findAll(
        (node) =>
          String(node.type)
            === "Line",
      );

    const caretLines =
      lines.filter(
        (node) =>
          node.props.stroke
            === "reference-color"
          && node.props.strokeWidth
            === 2
          && node.props.strokeLinecap
            === "round",
      );

    expect(
      caretLines,
    ).toHaveLength(
      expectedCrossing
        ? 2
        : 0,
    );

    const referenceLines =
      lines.filter(
        (node) =>
          node.props.strokeWidth
            === 1.5,
      );

    expect(
      referenceLines,
    ).toHaveLength(
      expectedReferenceLine
        ? 1
        : 0,
    );

    const dateControl =
      renderer!.root
        .findAllByType(
          Pressable,
        )[0];

    expect(
      String(
        dateControl.props
          .accessibilityLabel,
      ).includes(
        "above reference",
      ),
    ).toBe(
      expectedCrossing,
    );

    if (expectedCrossing) {
      const rects =
        renderer!.root.findAll(
          (node) =>
            String(node.type)
              === "Rect",
        );

      expect(
        rects,
      ).toHaveLength(1);

      const barTopY =
        rects[0].props.y;

      const xCoordinates =
        caretLines.flatMap(
          (node) => [
            node.props.x1,
            node.props.x2,
          ],
        );

      const yCoordinates =
        caretLines.flatMap(
          (node) => [
            node.props.y1,
            node.props.y2,
          ],
        );

      expect(
        Math.max(
          ...xCoordinates,
        )
        - Math.min(
          ...xCoordinates,
        ),
      ).toBeCloseTo(12);

      expect(
        Math.max(
          ...yCoordinates,
        )
        - Math.min(
          ...yCoordinates,
        ),
      ).toBeCloseTo(7);

      expect(
        Math.min(
          ...yCoordinates,
        ),
      ).toBeCloseTo(
        barTopY,
      );

      expect(
        Math.max(
          ...yCoordinates,
        ),
      ).toBeCloseTo(
        barTopY + 7,
      );
    }

    act(() => {
      renderer!.unmount();
    });
  },
);


test(
  "selected crossing caret apex remains anchored to the selected numeric bar top",
  () => {
    const day =
      projectedDay(
        "2026-08-12",
        "numeric",
        "2301",
      );

    let renderer:
      TestRenderer.ReactTestRenderer;

    act(() => {
      renderer =
        TestRenderer.create(
          React.createElement(
            HistoryDailyBarChart,
            {
              days: [
                day,
              ],
              seriesLabel:
                "Sodium",
              selectedDate:
                day.date,
              onSelectDate:
                jest.fn(),
              barColor:
                "series-color",
              selectionColor:
                "selection-color",
              referenceValue:
                2300,
              referenceLineColor:
                "reference-color",
            },
          ),
        );
    });

    const rects =
      renderer!.root.findAll(
        (node) =>
          String(node.type)
            === "Rect",
      );

    expect(
      rects,
    ).toHaveLength(1);

    expect(
      rects[0].props.fill,
    ).toBe(
      "selection-color",
    );

    expect(
      rects[0].props.stroke,
    ).toBe(
      "series-color",
    );

    const caretLines =
      renderer!.root
        .findAll(
          (node) =>
            String(node.type)
              === "Line",
        )
        .filter(
          (node) =>
            node.props.stroke
              === "reference-color"
            && node.props.strokeWidth
              === 2
            && node.props.strokeLinecap
              === "round",
        );

    expect(
      caretLines,
    ).toHaveLength(2);

    const yCoordinates =
      caretLines.flatMap(
        (node) => [
          node.props.y1,
          node.props.y2,
        ],
      );

    expect(
      Math.min(
        ...yCoordinates,
      ),
    ).toBeCloseTo(
      rects[0].props.y,
    );

    expect(
      Math.max(
        ...yCoordinates,
      ),
    ).toBeCloseTo(
      rects[0].props.y + 7,
    );

    act(() => {
      renderer!.unmount();
    });
  },
);

test(
  "focused selected day exposes exact above-reference delta visibly and accessibly",
  () => {
    mockUseHistoryRange
      .mockReturnValue(
        successfulQuery(
          evidence(),
        ),
      );

    mockUseTargetConfiguration
      .mockReturnValue({
        data: {
          effectiveTargets: [
            {
              nutrientId:
                "calories",
              amount:
                "699",
              unit:
                "kcal",
              authority:
                "manual_override",
              direction:
                "target",
              trackingMode:
                "recommended",
            },
          ],
        } as unknown as
          TargetConfiguration,
      });

    const session =
      withHistorySelectedChartDate(
        withHistoryFocusedNutrient(
          freshHistorySession(
            "2026-08-19",
          ),
          "calories",
        ),
        "2026-08-18",
      );

    let renderer:
      TestRenderer.ReactTestRenderer;

    act(() => {
      renderer =
        TestRenderer.create(
          React.createElement(
            HistoryScreen,
            {
              session,
              onSessionChange:
                jest.fn(),
              onFirstLoggedDateChange:
                jest.fn(),
              onBack:
                jest.fn(),
            },
          ),
        );
    });

    expect(
      screenText(
        renderer!,
      ),
    ).toContain(
      "700 kcal · 1 kcal above reference",
    );

    const selectedLabel =
      renderer!.root
        .findAllByType(
          Text,
        )
        .map(
          (node) =>
            node.props
              .accessibilityLabel,
        )
        .find(
          (value) =>
            typeof value
              === "string"
            && value.includes(
              "Calories selected 2026-08-18",
            ),
        );

    expect(
      selectedLabel,
    ).toBe(
      "Calories selected 2026-08-18 700 kcal 1 kcal above reference",
    );

    act(() => {
      renderer!.unmount();
    });
  },
);
