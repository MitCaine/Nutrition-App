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
  ScrollView,
  Text,
} from "react-native";
import TestRenderer, {
  act,
} from "react-test-renderer";

import {
  NUTRIENT_CATALOG,
} from "../src/shared/nutrition/catalog";
import type {
  HistoryNutrientEvidence,
  HistoryRangeEvidence,
} from "../src/features/logging/api/types";
import {
  projectHistoryRange,
} from "../src/features/history/historyProjection";
import {
  useHistoryRange,
} from "../src/features/history/historyQuery";
import {
  buildHistoryNutritionDetailSections,
} from "../src/features/history/historyNutritionDetails";
import {
  DEFAULT_HISTORY_DETAIL_COLLAPSED_SECTION_IDS,
  freshHistorySession,
  historyDetailCollapsedSectionIds,
  historyDetailsScrollOffset,
  historyFocusedNutrientId,
  historySurface,
  previousHistorySession,
  withHistoryDenominatorPreference,
  withHistoryDetailSectionToggled,
  withHistoryDetailsScrollOffset,
  withHistoryFocusedNutrient,
  withHistoryRangeLength,
  withHistorySurface,
  type HistorySession,
} from "../src/features/history/historyRangeModel";
import {
  HistoryScreen,
} from "../src/features/history/screens/HistoryScreen";
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

function nutrientEvidence(
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
  return {
    startDate:
      "2026-08-12",
    endDate:
      "2026-08-18",
    firstLoggedDate:
      "2026-08-12",
    days: [
      {
        date:
          "2026-08-12",
        hasLogs:
          true,
        isComplete:
          true,
        nutrients: [
          nutrientEvidence(
            "calories",
            "1200",
            "kcal",
          ),
          nutrientEvidence(
            "protein",
            "80",
            "g",
          ),
          nutrientEvidence(
            "total_carbohydrate",
            "140",
            "g",
          ),
          nutrientEvidence(
            "total_fat",
            "50",
            "g",
          ),
        ],
      },
      ...Array.from(
        {
          length: 6,
        },
        (_, index) => ({
          date:
            `2026-08-${String(
              13 + index,
            ).padStart(2, "0")}`,
          hasLogs:
            false,
          isComplete:
            false,
          nutrients:
            [],
        }),
      ),
    ],
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
          "275",
        unit:
          "g",
        authority:
          "daily_value",
        direction:
          "reference",
        trackingMode:
          "ignored",
      },
    ],
  } as unknown as TargetConfiguration;
}

function successfulQuery(
  data: HistoryRangeEvidence,
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
    typeof value === "string"
    || typeof value === "number"
  ) {
    return String(value);
  }

  if (
    Array.isArray(value)
  ) {
    return value
      .map(textValue)
      .join(" ");
  }

  return "";
}

function screenText(
  renderer:
    TestRenderer.ReactTestRenderer,
): string {
  return renderer.root
    .findAllByType(Text)
    .map(
      (node) =>
        textValue(
          node.props.children,
        ),
    )
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
}

function findPressable(
  renderer:
    TestRenderer.ReactTestRenderer,
  accessibilityLabel: string,
) {
  return renderer.root
    .findAllByType(
      Pressable,
    )
    .find(
      (node) =>
        node.props
          .accessibilityLabel
        === accessibilityLabel,
    );
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
  "detail model exposes every projected canonical nutrient exactly once in canonical sections",
  () => {
    const projection =
      projectHistoryRange(
        evidence(),
        "logged_days",
      );

    const sections =
      buildHistoryNutritionDetailSections(
        projection,
      );

    expect(
      sections.map(
        (section) =>
          section.label,
      ),
    ).toEqual([
      "Nutrition Facts",
      "Vitamins",
      "Minerals",
      "Fatty Acids",
      "Other",
    ]);

    const rows =
      sections.flatMap(
        (section) =>
          section.rows,
      );

    expect(
      rows,
    ).toHaveLength(
      NUTRIENT_CATALOG.length,
    );

    expect(
      new Set(
        rows.map(
          (row) =>
            row.nutrientId,
        ),
      ).size,
    ).toBe(
      NUTRIENT_CATALOG.length,
    );

    const nutritionFacts =
      sections.find(
        (section) =>
          section.id
          === "nutrition_facts",
      );

    expect(
      nutritionFacts
        ?.rows
        .slice(0, 15)
        .map(
          (row) =>
            row.nutrientId,
        ),
    ).toEqual([
      "calories",
      "total_fat",
      "saturated_fat",
      "trans_fat",
      "cholesterol",
      "sodium",
      "total_carbohydrate",
      "dietary_fiber",
      "total_sugars",
      "added_sugars",
      "protein",
      "vitamin_d",
      "calcium",
      "iron",
      "potassium",
    ]);

    expect(
      nutritionFacts
        ?.rows
        .find(
          (row) =>
            row.nutrientId
            === "saturated_fat",
        )
        ?.hierarchyDepth,
    ).toBe(1);

    expect(
      nutritionFacts
        ?.rows
        .find(
          (row) =>
            row.nutrientId
            === "added_sugars",
        )
        ?.hierarchyDepth,
    ).toBe(2);

    expect(
      sections
        .find(
          (section) =>
            section.id
            === "other",
        )
        ?.rows
        .some(
          (row) =>
            row.nutrientId
            === "choline",
        ),
    ).toBe(true);
  },
);

test(
  "period rows use E4-05 average and usable-day evidence with neutral unavailable values and optional current context",
  () => {
    const projection =
      projectHistoryRange(
        evidence(),
        "logged_days",
      );

    const sections =
      buildHistoryNutritionDetailSections(
        projection,
        targetConfiguration(),
      );

    const rows =
      sections.flatMap(
        (section) =>
          section.rows,
      );

    const calories =
      rows.find(
        (row) =>
          row.nutrientId
          === "calories",
      );

    const protein =
      rows.find(
        (row) =>
          row.nutrientId
          === "protein",
      );

    const vitaminC =
      rows.find(
        (row) =>
          row.nutrientId
          === "vitamin_c",
      );

    expect(
      calories?.value,
    ).toBe(
      "1,200 kcal",
    );

    expect(
      calories
        ?.denominatorContext,
    ).toBe(
      "Logged-day average · 1 day used",
    );

    expect(
      calories
        ?.targetContext,
    ).toContain(
      "2,000 kcal",
    );

    expect(
      protein
        ?.targetContext,
    ).toBeNull();

    expect(
      vitaminC?.value,
    ).toBe("—");

    expect(
      vitaminC
        ?.denominatorContext,
    ).toBe(
      "Logged-day average · 0 days used",
    );
  },
);

test(
  "HistorySession owns detail defaults accordion scroll and focused identity across navigation changes",
  () => {
    const fresh =
      freshHistorySession(
        "2026-08-19",
      );

    expect(
      historyDetailCollapsedSectionIds(
        fresh,
      ),
    ).toEqual(
      DEFAULT_HISTORY_DETAIL_COLLAPSED_SECTION_IDS,
    );

    expect(
      historyDetailsScrollOffset(
        fresh,
      ),
    ).toBe(0);

    const expandedVitamins =
      withHistoryDetailSectionToggled(
        fresh,
        "vitamins",
      );

    expect(
      historyDetailCollapsedSectionIds(
        expandedVitamins,
      ),
    ).not.toContain(
      "vitamins",
    );

    const scrolled =
      withHistoryDetailsScrollOffset(
        expandedVitamins,
        640.4,
      );

    expect(
      historyDetailsScrollOffset(
        scrolled,
      ),
    ).toBe(640);

    const focused =
      withHistoryFocusedNutrient(
        scrolled,
        "vitamin_c",
      );

    expect(
      historySurface(
        focused,
      ),
    ).toBe(
      "focused_nutrient",
    );

    expect(
      historyFocusedNutrientId(
        focused,
      ),
    ).toBe(
      "vitamin_c",
    );

    const back =
      withHistorySurface(
        focused,
        "nutrition_details",
      );

    expect(
      historyDetailCollapsedSectionIds(
        back,
      ),
    ).not.toContain(
      "vitamins",
    );

    expect(
      historyDetailsScrollOffset(
        back,
      ),
    ).toBe(640);

    const older =
      previousHistorySession(
        focused,
      );

    expect(
      historySurface(
        older,
      ),
    ).toBe(
      "focused_nutrient",
    );

    expect(
      historyFocusedNutrientId(
        older,
      ),
    ).toBe(
      "vitamin_c",
    );

    expect(
      historyDetailCollapsedSectionIds(
        older,
      ),
    ).not.toContain(
      "vitamins",
    );

    const thirty =
      withHistoryRangeLength(
        focused,
        30,
      );

    expect(
      historySurface(
        thirty,
      ),
    ).toBe(
      "focused_nutrient",
    );

    expect(
      historyFocusedNutrientId(
        thirty,
      ),
    ).toBe(
      "vitamin_c",
    );

    expect(
      historyDetailCollapsedSectionIds(
        withHistoryDenominatorPreference(
          focused,
          "logged_days",
        ),
      ),
    ).not.toContain(
      "vitamins",
    );
  },
);

test(
  "HistoryScreen shows distinct grouped details and preserves context through focused shell without changing range identity",
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

    const showMore =
      findPressable(
        renderer,
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

    expect(
      screenText(
        renderer,
      ),
    ).toContain(
      "Nutrition Details",
    );

    expect(
      screenText(
        renderer,
      ),
    ).toContain(
      "Close",
    );

    expect(
      screenText(
        renderer,
      ),
    ).toContain(
      "Aug 12–18, 2026",
    );

    expect(
      screenText(
        renderer,
      ),
    ).toContain(
      "1 day logged · 1 complete",
    );

    expect(
      screenText(
        renderer,
      ),
    ).not.toContain(
      "Coverage ·",
    );

    expect(
      screenText(
        renderer,
      ),
    ).not.toContain(
      "Selected range",
    );

    expect(
      findPressable(
        renderer,
        "Previous History period",
      ),
    ).toBeDefined();

    expect(
      findPressable(
        renderer,
        "Next History period",
      ),
    ).toBeDefined();

    const chartDateControls =
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
      chartDateControls,
    ).toHaveLength(0);

    expect(
      findPressable(
        renderer,
        "Nutrition Facts History section",
      )?.props
        .accessibilityState
        .expanded,
    ).toBe(true);

    expect(
      findPressable(
        renderer,
        "Vitamins History section",
      )?.props
        .accessibilityState
        .expanded,
    ).toBe(false);

    const vitamins =
      findPressable(
        renderer,
        "Vitamins History section",
      );

    await act(
      async () => {
        vitamins
          ?.props
          .onPress();
      },
    );

    const outerScroll =
      renderer.root
        .findByType(
          ScrollView,
        );

    await act(
      async () => {
        outerScroll.props
          .onScrollEndDrag({
            nativeEvent: {
              contentOffset: {
                y: 480,
              },
            },
          });
      },
    );

    const vitaminC =
      findPressable(
        renderer,
        "Open Vitamin C focused History",
      );

    expect(
      vitaminC,
    ).toBeDefined();

    await act(
      async () => {
        vitaminC
          ?.props
          .onPress();
      },
    );

    const focusedText =
      screenText(
        renderer,
      );

    expect(
      focusedText,
    ).toContain(
      "Focused nutrient History",
    );

    expect(
      focusedText,
    ).toContain(
      "Vitamin C",
    );

    expect(
      focusedText,
    ).toContain(
      "E4-12",
    );

    expect(
      renderer.root
        .findAllByType(
          Pressable,
        )
        .some(
          (node) =>
            typeof node.props
              .accessibilityLabel
              === "string"
            && node.props
              .accessibilityLabel
              .startsWith(
                "Select Calories History date",
              ),
        ),
    ).toBe(false);

    expect(
      findPressable(
        renderer,
        "Back to Nutrition Details",
      ),
    ).toBeUndefined();

    const back =
      findPressable(
        renderer,
        "Back to Nutrition Details from focused History",
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
      findPressable(
        renderer,
        "Vitamins History section",
      )?.props
        .accessibilityState
        .expanded,
    ).toBe(true);

    expect(
      mockUseHistoryRange
        .mock.calls
        .every(
          ([startDate, endDate]) =>
            startDate
              === "2026-08-12"
            && endDate
              === "2026-08-18",
        ),
    ).toBe(true);

    const close =
      findPressable(
        renderer,
        "Back to History overview",
      );

    await act(
      async () => {
        close
          ?.props
          .onPress();
      },
    );

    expect(
      findPressable(
        renderer,
        "Show more nutrition",
      ),
    ).toBeDefined();

    expect(
      renderer.root
        .findAllByType(
          Pressable,
        )
        .some(
          (node) =>
            node.props
              .accessibilityLabel
            ===
              "Select Calories History date 2026-08-12",
        ),
    ).toBe(true);

    await act(
      async () => {
        renderer.unmount();
      },
    );
  },
);

test(
  "detail group and focus state remain session-only optional extensions",
  () => {
    const legacy:
      HistorySession = {
      rangeLength:
        7,
      endDate:
        "2026-08-18",
      latestEndDate:
        "2026-08-18",
      denominatorPreference:
        null,
    };

    expect(
      historySurface(
        legacy,
      ),
    ).toBe(
      "overview",
    );

    expect(
      historyFocusedNutrientId(
        legacy,
      ),
    ).toBeNull();

    expect(
      historyDetailCollapsedSectionIds(
        legacy,
      ),
    ).toEqual(
      DEFAULT_HISTORY_DETAIL_COLLAPSED_SECTION_IDS,
    );
  },
);
