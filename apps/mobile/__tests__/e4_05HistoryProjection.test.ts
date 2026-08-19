import type {
  HistoryRangeEvidence,
} from "../src/features/logging/api/types";
import {
  HistoryProjectionError,
  historyValueForDate,
  projectHistoryRange,
} from "../src/features/history/historyProjection";
import type {
  HistoryProjection,
} from "../src/features/history/types";
import {
  NUTRIENT_CATALOG,
} from "../src/shared/nutrition/catalog";

const fixture = require(
  "../../../packages/shared-contracts/e4-05/history-projection-fixtures.json",
) as {
  evidence: HistoryRangeEvidence;
  expected: {
    coverage: {
      requestedDayCount: number;
      loggedDayCount: number;
      completeDayCount: number;
    };
    groupedSectionIds: string[];
    complete_days: Array<{
      nutrientId: string;
      usableDayCount: number;
      average: string | null;
    }>;
    logged_days: Array<{
      nutrientId: string;
      usableDayCount: number;
      average: string | null;
    }>;
  };
};

function cloneEvidence(): HistoryRangeEvidence {
  return JSON.parse(
    JSON.stringify(fixture.evidence),
  ) as HistoryRangeEvidence;
}

function metrics(
  projection: HistoryProjection,
  nutrientIds: readonly string[],
) {
  return nutrientIds.map(
    (nutrientId) => {
      const row = projection.nutrients.find(
        (candidate) =>
          candidate.nutrientId
          === nutrientId,
      );
      expect(row).toBeDefined();

      return {
        nutrientId,
        usableDayCount:
          row!.usableDayCount,
        average: row!.average,
      };
    },
  );
}

function nutrient(
  projection: HistoryProjection,
  nutrientId: string,
) {
  const row = projection.nutrients.find(
    (candidate) =>
      candidate.nutrientId === nutrientId,
  );
  expect(row).toBeDefined();
  return row!;
}

function proteinRange(
  amounts: readonly string[],
): HistoryRangeEvidence {
  return {
    startDate: "2026-08-01",
    endDate: `2026-08-0${amounts.length}`,
    firstLoggedDate: "2026-08-01",
    days: amounts.map(
      (amount, index) => ({
        date: `2026-08-0${index + 1}`,
        hasLogs: true,
        isComplete: true,
        nutrients: [
          {
            nutrientId: "protein",
            amountKnown: amount,
            amountEstimated: "0",
            unit: "g",
            hasNumericEvidence: true,
            isExplicitZeroTotal: false,
            hasUnknownContributors: false,
            unknownContributorCount: 0,
          },
        ],
      }),
    ),
  };
}

describe("E4-05 shared History projection", () => {
  test("equivalent local and remote evidence yields identical fixture projections in both modes", () => {
    for (
      const mode of [
        "complete_days",
        "logged_days",
      ] as const
    ) {
      const localEvidence = cloneEvidence();
      const remoteEvidence = cloneEvidence();

      const local = projectHistoryRange(
        localEvidence,
        mode,
      );
      const remote = projectHistoryRange(
        remoteEvidence,
        mode,
      );

      expect(JSON.stringify(local))
        .toBe(JSON.stringify(remote));

      expect(local.coverage)
        .toEqual(fixture.expected.coverage);

      expect(
        local.groupedRows.map(
          (section) => section.id,
        ),
      ).toEqual(
        fixture.expected.groupedSectionIds,
      );

      expect(
        metrics(
          local,
          fixture.expected[mode].map(
            (item) => item.nutrientId,
          ),
        ),
      ).toEqual(
        fixture.expected[mode],
      );
    }
  });

  test("daily states preserve gap, absent, unknown-only, explicit zero, known zero, estimated, and mixed unknown evidence", () => {
    const projection = projectHistoryRange(
      cloneEvidence(),
      "logged_days",
    );

    const protein = nutrient(
      projection,
      "protein",
    );

    expect(protein.days[0]).toMatchObject({
      state: "gap",
      hasLogs: false,
      hasNutrientEvidence: false,
      numericAmount: null,
    });

    expect(protein.days[1]).toMatchObject({
      state: "numeric",
      amountKnown: "1.000000",
      amountEstimated: "0",
      numericAmount: "1.000000",
      hasUnknownContributors: false,
    });

    expect(protein.days[2]).toMatchObject({
      state: "numeric",
      amountKnown: "0.250000",
      amountEstimated: "0.500000",
      numericAmount: "0.750000",
      hasUnknownContributors: true,
      unknownContributorCount: 1,
    });

    const vitaminC = nutrient(
      projection,
      "vitamin_c",
    );

    expect(vitaminC.days[1]).toMatchObject({
      state: "unavailable",
      hasNutrientEvidence: true,
      numericAmount: null,
      hasUnknownContributors: true,
      unknownContributorCount: 1,
    });

    expect(vitaminC.days[2]).toMatchObject({
      state: "unavailable",
      hasNutrientEvidence: false,
      amountKnown: null,
      amountEstimated: null,
      numericAmount: null,
    });

    expect(vitaminC.days[3]).toMatchObject({
      state: "numeric",
      amountKnown: "0",
      amountEstimated: "5.000000",
      numericAmount: "5.000000",
    });

    const sodium = nutrient(
      projection,
      "sodium",
    );

    expect(sodium.days[1]).toMatchObject({
      state: "numeric",
      numericAmount: "0",
      isExplicitZeroTotal: true,
    });

    expect(sodium.days[2]).toMatchObject({
      state: "numeric",
      numericAmount: "0.000000",
      isExplicitZeroTotal: false,
    });
  });

  test("Complete and Logged modes use nutrient-specific usable denominators over unchanged evidence", () => {
    const evidence = cloneEvidence();
    const complete = projectHistoryRange(
      evidence,
      "complete_days",
    );
    const logged = projectHistoryRange(
      evidence,
      "logged_days",
    );

    expect(complete.coverage)
      .toEqual(logged.coverage);

    expect(
      nutrient(complete, "protein"),
    ).toMatchObject({
      usableDayCount: 2,
      average: "0.875",
    });

    expect(
      nutrient(logged, "protein"),
    ).toMatchObject({
      usableDayCount: 3,
      average: "1",
    });

    expect(
      nutrient(complete, "vitamin_c"),
    ).toMatchObject({
      usableDayCount: 0,
      average: null,
    });

    expect(
      nutrient(logged, "vitamin_c"),
    ).toMatchObject({
      usableDayCount: 1,
      average: "5",
    });
  });

  test("one-day explicit zero is a real zero denominator value while unknown-only has no average", () => {
    const explicitZero: HistoryRangeEvidence = {
      startDate: "2026-08-01",
      endDate: "2026-08-01",
      firstLoggedDate: "2026-08-01",
      days: [
        {
          date: "2026-08-01",
          hasLogs: true,
          isComplete: true,
          nutrients: [
            {
              nutrientId: "protein",
              amountKnown: "0",
              amountEstimated: "0",
              unit: "g",
              hasNumericEvidence: true,
              isExplicitZeroTotal: true,
              hasUnknownContributors: false,
              unknownContributorCount: 0,
            },
          ],
        },
      ],
    };

    const zeroProjection =
      projectHistoryRange(
        explicitZero,
        "complete_days",
      );

    expect(
      nutrient(
        zeroProjection,
        "protein",
      ),
    ).toMatchObject({
      usableDayCount: 1,
      average: "0",
    });

    const unknownOnly: HistoryRangeEvidence = {
      ...explicitZero,
      days: [
        {
          ...explicitZero.days[0],
          nutrients: [
            {
              ...explicitZero.days[0]!
                .nutrients[0]!,
              hasNumericEvidence: false,
              isExplicitZeroTotal: false,
              hasUnknownContributors: true,
              unknownContributorCount: 1,
            },
          ],
        },
      ],
    };

    const unknownProjection =
      projectHistoryRange(
        unknownOnly,
        "complete_days",
      );

    expect(
      nutrient(
        unknownProjection,
        "protein",
      ),
    ).toMatchObject({
      usableDayCount: 0,
      average: null,
    });
  });

  test("exact values are summed first and divided once with 28-digit response-decimal semantics", () => {
    const repeating =
      projectHistoryRange(
        proteinRange(["1", "0", "0"]),
        "complete_days",
      );

    expect(
      nutrient(repeating, "protein")
        .average,
    ).toBe(
      "0.3333333333333333333333333333",
    );

    const subDisplayPrecision =
      projectHistoryRange(
        proteinRange([
          "0.0000004",
          "0.0000004",
        ]),
        "complete_days",
      );

    expect(
      nutrient(
        subDisplayPrecision,
        "protein",
      ).average,
    ).toBe("0.0000004");
  });

  test("contradictory canonical units fail explicitly instead of being combined", () => {
    const evidence =
      proteinRange(["1"]);

    evidence.days[0]!.nutrients[0] = {
      ...evidence.days[0]!.nutrients[0]!,
      unit: "mg",
    };

    expect(() =>
      projectHistoryRange(
        evidence,
        "complete_days",
      ),
    ).toThrow(HistoryProjectionError);

    try {
      projectHistoryRange(
        evidence,
        "complete_days",
      );
      throw new Error(
        "Expected unit mismatch.",
      );
    } catch (error) {
      expect(error).toMatchObject({
        code:
          "history_projection_unit_mismatch",
        nutrientId: "protein",
      });
    }
  });

  test("canonical structural rows remain available without manufacturing parent evidence, and selected-date values come from the same projection", () => {
    const projection = projectHistoryRange(
      cloneEvidence(),
      "logged_days",
    );

    expect(projection.nutrients)
      .toHaveLength(
        NUTRIENT_CATALOG.length,
      );

    expect(
      new Set(
        projection.nutrients.map(
          (row) => row.nutrientId,
        ),
      ),
    ).toEqual(
      new Set(
        NUTRIENT_CATALOG.map(
          (definition) =>
            definition.id,
        ),
      ),
    );

    expect(
      projection.groupedRows.map(
        (section) => section.id,
      ),
    ).toEqual([
      "nutrition_facts",
      "vitamins",
      "minerals",
      "fatty_acids",
      "other",
    ]);

    const nutritionFacts =
      projection.groupedRows.find(
        (section) =>
          section.id
          === "nutrition_facts",
      );

    expect(
      nutritionFacts?.items.map(
        (row) => row.nutrientId,
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
      nutrient(
        projection,
        "total_fat",
      ),
    ).toMatchObject({
      unit: "g",
      usableDayCount: 0,
      average: null,
    });

    // Saturated-fat evidence must not manufacture Total Fat.
    expect(
      nutrient(
        projection,
        "saturated_fat",
      ),
    ).toMatchObject({
      usableDayCount: 1,
      average: "2",
    });

    expect(
      historyValueForDate(
        projection,
        "total_fat",
        "2026-08-13",
      ),
    ).toMatchObject({
      state: "unavailable",
      hasLogs: true,
      hasNutrientEvidence: false,
      numericAmount: null,
    });

    expect(
      historyValueForDate(
        projection,
        "protein",
        "2026-08-12",
      ),
    ).toMatchObject({
      state: "numeric",
      amountKnown: "0.250000",
      amountEstimated: "0.500000",
      numericAmount: "0.750000",
      hasUnknownContributors: true,
    });

    expect(
      historyValueForDate(
        projection,
        "not_a_canonical_nutrient",
        "2026-08-13",
      ),
    ).toBeNull();
  });
});
