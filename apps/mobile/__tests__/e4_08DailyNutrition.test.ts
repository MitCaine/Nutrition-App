import React, {
  useState,
} from "react";
import {
  Pressable,
  Text,
} from "react-native";
import TestRenderer, {
  act,
} from "react-test-renderer";

import type {
  DailyTargetComparison,
  DailyTargetComparisonItem,
} from "../src/features/targets/api/types";
import type {
  NutrientSectionId,
} from "../src/shared/nutrition/nutrientSections";
import {
  buildDailyNutritionSections,
} from "../src/features/logging/utils/dailyNutritionPresentation";

let mockComparison:
  DailyTargetComparison;

jest.mock(
  "../src/features/targets/hooks/useDailyTargetComparison",
  () => {
    const actual =
      jest.requireActual(
        "../src/features/targets/hooks/useDailyTargetComparison",
      );

    return {
      ...actual,
      useDailyTargetComparison:
        () => ({
          data: mockComparison,
          isLoading: false,
          isError: false,
          isFetching: false,
          isRefetchError: false,
          error: null,
          refetch: jest.fn(),
        }),
    };
  },
);

jest.mock(
  "../src/app/theme/AppTheme",
  () => {
    const actual =
      jest.requireActual(
        "../src/app/theme/AppTheme",
      );

    return {
      ...actual,
      useAppTheme: () => ({
        ...actual.LIGHT_THEME,
        preference: "system",
        effectiveScheme: "light",
        setPreference: jest.fn(),
      }),
    };
  },
);

import {
  DailyNutritionScreen,
} from "../src/features/logging/screens/DailyNutritionScreen";

function comparisonItem(
  nutrientId: string,
  overrides:
    Partial<DailyTargetComparisonItem>
    = {},
): DailyTargetComparisonItem {
  return {
    nutrientId,
    consumedAmount: "10",
    targetAmount: "20",
    unit: "g",
    percentage: "50",
    authority: "dri",
    direction: "target",
    trackingMode: "recommended",
    status: "available",
    reasonCode: null,
    noteCode: null,
    hasUnknownContributors: false,
    referenceType: null,
    sourceVersion: null,
    sourceId: null,
    calculationBasis: null,
    ...overrides,
  };
}

function textContent(
  node:
    TestRenderer.ReactTestInstance
    | string,
): string {
  if (typeof node === "string") {
    return node;
  }

  return node.children
    .map((child) =>
      textContent(
        child as
          TestRenderer.ReactTestInstance
          | string,
      ),
    )
    .join("");
}

function screenText(
  root:
    TestRenderer.ReactTestInstance,
): string {
  return root
    .findAllByType(Text)
    .map(textContent)
    .join(" ");
}

beforeEach(() => {
  mockComparison = {
    date: "2026-08-18",
    dailyValueCatalogVersion: "dv",
    driDatasetVersion: "dri",
    targetDirectionSemanticsVersion:
      "direction",
    comparisons: [
      comparisonItem(
        "calories",
        {
          consumedAmount: "500",
          targetAmount: "2000",
          unit: "kcal",
          percentage: "25",
          authority:
            "calculated_estimate",
        },
      ),
      comparisonItem(
        "sodium",
        {
          consumedAmount: "2400",
          targetAmount: "2300",
          unit: "mg",
          percentage: "104.3",
          authority: "daily_value",
          direction: "limit",
        },
      ),
      comparisonItem(
        "total_sugars",
        {
          consumedAmount: "30",
          targetAmount: null,
          percentage: null,
          authority: "unavailable",
          direction: "unavailable",
          status:
            "target_unavailable",
        },
      ),
      comparisonItem(
        "added_sugars",
        {
          consumedAmount: "12",
          targetAmount: "50",
          percentage: "24",
          authority: "daily_value",
          direction: "limit",
          hasUnknownContributors: true,
        },
      ),
      comparisonItem(
        "protein",
        {
          consumedAmount: "65",
          targetAmount: "100",
          percentage: "65",
          trackingMode: "custom",
          authority:
            "manual_override",
          hasUnknownContributors: true,
        },
      ),
      comparisonItem(
        "total_carbohydrate",
        {
          consumedAmount: "45",
          targetAmount: null,
          percentage: null,
          authority: "unavailable",
          direction: "unavailable",
          trackingMode: "amount_only",
          status: "amount_only",
        },
      ),
      comparisonItem(
        "vitamin_c",
        {
          consumedAmount: null,
          targetAmount: null,
          unit: "mg",
          percentage: null,
          authority: "unavailable",
          direction: "unavailable",
          status:
            "consumed_unavailable",
        },
      ),
      comparisonItem(
        "vitamin_b12",
        {
          trackingMode: "ignored",
        },
      ),
    ],
  };
});

test(
  "E4-08 projects one canonical row per visible nutrient with target-direction semantics",
  () => {
    const sections =
      buildDailyNutritionSections(
        mockComparison.comparisons,
      );

    expect(
      sections.map(
        (section) => [
          section.id,
          section.label,
        ],
      ),
    ).toEqual([
      [
        "nutrition_facts",
        "Nutrition Facts",
      ],
      [
        "vitamins",
        "Vitamins",
      ],
    ]);

    const rows =
      sections.flatMap(
        (section) =>
          section.rows,
      );

    expect(
      rows.some(
        (row) =>
          row.nutrientId
          === "vitamin_b12",
      ),
    ).toBe(false);

    expect(
      rows.find(
        (row) =>
          row.nutrientId
          === "calories",
      ),
    ).toEqual(
      expect.objectContaining({
        value:
          "500 kcal / 2,000 kcal",
        percentage: "25%",
        context:
          "Estimated personal target · Progress toward target",
      }),
    );

    expect(
      rows.find(
        (row) =>
          row.nutrientId
          === "sodium",
      ),
    ).toEqual(
      expect.objectContaining({
        value:
          "2,400 mg / 2,300 mg",
        percentage: "104%",
        context:
          "FDA Daily Value · Limit reference",
      }),
    );

    expect(
      rows.find(
        (row) =>
          row.nutrientId
          === "total_carbohydrate",
      ),
    ).toEqual(
      expect.objectContaining({
        value: "45 g",
        percentage: null,
        context: null,
      }),
    );

    expect(
      rows.find(
        (row) =>
          row.nutrientId
          === "vitamin_c",
      ),
    ).toEqual(
      expect.objectContaining({
        value: "—",
        percentage: null,
        context: null,
      }),
    );

    expect(
      rows.find(
        (row) =>
          row.nutrientId
          === "added_sugars",
      )?.hierarchyDepth,
    ).toBe(2);

    const unknownRows =
      rows.filter(
        (row) =>
          row.nutrientId
            === "protein"
          || row.nutrientId
            === "added_sugars",
      );

    for (
      const row
      of unknownRows
    ) {
      expect(
        row.accessibilityLabel,
      ).not.toMatch(
        /incomplete|unknown/i,
      );
    }

    expect(
      rows.some(
        (row) =>
          /success|failure|safe|unsafe/i
            .test(
              [
                row.value,
                row.percentage,
                row.context,
              ]
                .filter(Boolean)
                .join(" "),
            ),
      ),
    ).toBe(false);
  },
);

function SessionHarness() {
  const [
    visible,
    setVisible,
  ] = useState(true);

  const [
    collapsed,
    setCollapsed,
  ] = useState<
    Set<NutrientSectionId>
  >(
    () => new Set(),
  );

  if (!visible) {
    return React.createElement(
      Pressable,
      {
        accessibilityLabel:
          "Reopen Daily Nutrition",
        onPress: () =>
          setVisible(true),
      },
      React.createElement(
        Text,
        null,
        "Reopen",
      ),
    );
  }

  return React.createElement(
    DailyNutritionScreen,
    {
      date: "2026-08-18",
      collapsedSectionIds:
        collapsed,
      onToggleSection: (
        sectionId,
      ) => {
        setCollapsed(
          (current) => {
            const next =
              new Set(current);

            if (
              next.has(sectionId)
            ) {
              next.delete(
                sectionId,
              );
            } else {
              next.add(
                sectionId,
              );
            }

            return next;
          },
        );
      },
      onBack: () =>
        setVisible(false),
      onOpenTargets:
        jest.fn(),
    },
  );
}

test(
  "E4-08 sections start expanded, collapse independently, persist during the session, and reset on a fresh mount",
  async () => {
    let renderer!:
      TestRenderer.ReactTestRenderer;

    await act(async () => {
      renderer =
        TestRenderer.create(
          React.createElement(
            SessionHarness,
          ),
        );
    });

    expect(
      screenText(
        renderer.root,
      ),
    ).toContain("Calories");

    const nutritionFacts =
      renderer.root.findByProps({
        accessibilityLabel:
          "Nutrition Facts section",
      });

    expect(
      nutritionFacts.props
        .accessibilityState,
    ).toEqual(
      expect.objectContaining({
        expanded: true,
      }),
    );

    await act(async () => {
      nutritionFacts.props
        .onPress();
    });

    expect(
      screenText(
        renderer.root,
      ),
    ).not.toContain(
      "Calories",
    );

    expect(
      screenText(
        renderer.root,
      ),
    ).toContain(
      "Vitamin C",
    );

    await act(async () => {
      renderer.root
        .findByProps({
          accessibilityLabel:
            "Back to Daily Log from Daily Nutrition",
        })
        .props.onPress();
    });

    await act(async () => {
      renderer.root
        .findByProps({
          accessibilityLabel:
            "Reopen Daily Nutrition",
        })
        .props.onPress();
    });

    expect(
      screenText(
        renderer.root,
      ),
    ).not.toContain(
      "Calories",
    );

    await act(async () => {
      renderer.unmount();
    });

    await act(async () => {
      renderer =
        TestRenderer.create(
          React.createElement(
            SessionHarness,
          ),
        );
    });

    expect(
      screenText(
        renderer.root,
      ),
    ).toContain("Calories");

    await act(async () => {
      renderer.unmount();
    });
  },
);

test(
  "E4-08 screen exposes selected date and secondary target action without independent date navigation",
  async () => {
    const onOpenTargets =
      jest.fn();

    let renderer!:
      TestRenderer.ReactTestRenderer;

    await act(async () => {
      renderer =
        TestRenderer.create(
          React.createElement(
            DailyNutritionScreen,
            {
              date: "2026-08-18",
              collapsedSectionIds:
                new Set<NutrientSectionId>(),
              onToggleSection:
                jest.fn(),
              onBack: jest.fn(),
              onOpenTargets,
            },
          ),
        );
    });

    const text =
      screenText(
        renderer.root,
      );

    expect(text).toContain(
      "Daily Nutrition",
    );
    expect(text).toContain(
      "Tue, Aug 18, 2026",
    );
    expect(text).not.toContain(
      "Previous Day",
    );
    expect(text).not.toContain(
      "Next Day",
    );

    await act(async () => {
      renderer.root
        .findByProps({
          accessibilityLabel:
            "Nutrition targets",
        })
        .props.onPress();
    });

    expect(
      onOpenTargets,
    ).toHaveBeenCalledTimes(1);

    await act(async () => {
      renderer.unmount();
    });
  },
);
