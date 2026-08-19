import type { DailyTargetComparisonItem } from "../src/features/targets/api/types";
import {
  buildE407CompactNutritionRows,
  E4_07_COMPACT_NUTRIENTS,
} from "../src/features/logging/screens/DailyLogScreen";
import {
  MAIN_TABS,
  mainTabForRoute,
} from "../src/app/navigation/mainTabs";

jest.mock(
  "../src/shared/components/RootScreenHeader",
  () => ({
    RootScreenHeader: () => null,
  }),
);

jest.mock(
  "@react-native-community/datetimepicker",
  () => ({
    __esModule: true,
    default: () => null,
  }),
);

function item(
  nutrientId: string,
  consumedAmount: string | null,
  targetAmount: string | null,
  unit: string,
  trackingMode:
    | "recommended"
    | "custom"
    | "amount_only"
    | "ignored",
): DailyTargetComparisonItem {
  return {
    nutrientId,
    consumedAmount,
    targetAmount,
    unit,
    percentage: "99",
    authority:
      targetAmount === null
        ? "unavailable"
        : "manual_override",
    direction:
      targetAmount === null
        ? "unavailable"
        : "target",
    trackingMode,
    status:
      trackingMode === "amount_only"
        ? "amount_only"
        : targetAmount === null
          ? "target_unavailable"
          : "available",
    reasonCode: null,
    noteCode: null,
    hasUnknownContributors: false,
    referenceType: null,
    sourceVersion: null,
    sourceId: null,
    calculationBasis: null,
  };
}

test("E4-07 compact nutrition is fixed to four nutrients and never renders percentages", () => {
  expect(
    E4_07_COMPACT_NUTRIENTS.map(
      (row) => row.nutrientId,
    ),
  ).toEqual([
    "calories",
    "protein",
    "total_carbohydrate",
    "total_fat",
  ]);

  const rows =
    buildE407CompactNutritionRows(
      [
        item(
          "calories",
          "500",
          "2000",
          "kcal",
          "recommended",
        ),
        item(
          "protein",
          "30",
          "100",
          "g",
          "custom",
        ),
        item(
          "total_carbohydrate",
          "45",
          "250",
          "g",
          "amount_only",
        ),
        item(
          "total_fat",
          "20",
          "70",
          "g",
          "recommended",
        ),
        item(
          "sodium",
          "900",
          "2300",
          "mg",
          "recommended",
        ),
      ],
      true,
    );

  expect(rows).toEqual([
    {
      nutrientId: "calories",
      label: "Calories",
      value: "500 / 2,000 kcal",
    },
    {
      nutrientId: "protein",
      label: "Protein",
      value: "30 / 100 g",
    },
    {
      nutrientId:
        "total_carbohydrate",
      label: "Carbohydrate",
      value: "45 g",
    },
    {
      nutrientId: "total_fat",
      label: "Fat",
      value: "20 / 70 g",
    },
  ]);

  expect(
    rows.some(
      (row) => row.value.includes("%"),
    ),
  ).toBe(false);
});

test("E4-07 empty Daily Log keeps History semantics separate from neutral compact zeros", () => {
  expect(
    buildE407CompactNutritionRows(
      [],
      false,
    ).map((row) => row.value),
  ).toEqual([
    "0 logged",
    "0 logged",
    "0 logged",
    "0 logged",
  ]);
});

test("History and Daily Nutrition remain owned by the existing Daily Log tab", () => {
  expect(MAIN_TABS).toEqual([
    "foods",
    "daily-log",
    "recipes",
  ]);

  expect(
    mainTabForRoute(
      "daily-log-history",
    ),
  ).toBe("daily-log");

  expect(
    mainTabForRoute(
      "daily-log-nutrition",
    ),
  ).toBe("daily-log");
});
