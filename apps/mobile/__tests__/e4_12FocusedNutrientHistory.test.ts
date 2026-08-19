import type {
  TargetConfiguration,
  TargetValue,
} from "../src/features/targets/api/types";
import {
  historyDailyBarGeometry,
} from "../src/features/history/components/HistoryDailyBarChart";
import {
  buildHistoryFocusedNutrient,
  focusedHistoryDayForDate,
} from "../src/features/history/historyFocusedNutrient";
import {
  freshHistorySession,
  historyFocusedDailyValuesExpanded,
  historySessionForOpen,
  nextHistorySession,
  previousHistorySession,
  withHistoryDenominatorPreference,
  withHistoryFocusedDailyValuesExpanded,
  withHistoryFocusedNutrient,
  withHistoryRangeLength,
  withHistorySelectedChartDate,
  type HistorySession,
} from "../src/features/history/historyRangeModel";
import type {
  HistoryProjectedDailyValue,
  HistoryProjectedNutrient,
} from "../src/features/history/types";

function projectedDay(
  overrides:
    Partial<HistoryProjectedDailyValue>
    & Pick<
      HistoryProjectedDailyValue,
      "date"
    >,
): HistoryProjectedDailyValue {
  return {
    date:
      overrides.date,
    state:
      overrides.state
      ?? "numeric",
    hasLogs:
      overrides.hasLogs
      ?? true,
    isComplete:
      overrides.isComplete
      ?? false,
    hasNutrientEvidence:
      overrides.hasNutrientEvidence
      ?? true,
    amountKnown:
      overrides.amountKnown
      ?? "10",
    amountEstimated:
      overrides.amountEstimated
      ?? "0",
    numericAmount:
      overrides.numericAmount
      ?? "10",
    isExplicitZeroTotal:
      overrides.isExplicitZeroTotal
      ?? false,
    hasUnknownContributors:
      overrides.hasUnknownContributors
      ?? false,
    unknownContributorCount:
      overrides.unknownContributorCount
      ?? 0,
  };
}

function numericDay(
  date: string,
  numericAmount: string,
  overrides:
    Partial<HistoryProjectedDailyValue>
      = {},
): HistoryProjectedDailyValue {
  return projectedDay({
    date,
    numericAmount,
    amountKnown:
      overrides.amountKnown
      ?? numericAmount,
    amountEstimated:
      overrides.amountEstimated
      ?? "0",
    ...overrides,
  });
}

function gapDay(
  date: string,
): HistoryProjectedDailyValue {
  return projectedDay({
    date,
    state:
      "gap",
    hasLogs:
      false,
    isComplete:
      false,
    hasNutrientEvidence:
      false,
    amountKnown:
      null,
    amountEstimated:
      null,
    numericAmount:
      null,
    isExplicitZeroTotal:
      false,
    hasUnknownContributors:
      false,
    unknownContributorCount:
      0,
  });
}

function unavailableDay(
  date: string,
  isComplete = false,
): HistoryProjectedDailyValue {
  return projectedDay({
    date,
    state:
      "unavailable",
    hasLogs:
      true,
    isComplete,
    hasNutrientEvidence:
      true,
    amountKnown:
      null,
    amountEstimated:
      null,
    numericAmount:
      null,
    isExplicitZeroTotal:
      false,
    hasUnknownContributors:
      true,
    unknownContributorCount:
      1,
  });
}

function focusedNutrient(
  days:
    readonly HistoryProjectedDailyValue[],
  overrides:
    Partial<HistoryProjectedNutrient>
      = {},
): HistoryProjectedNutrient {
  return {
    nutrientId:
      overrides.nutrientId
      ?? "vitamin_c",
    unit:
      overrides.unit
      ?? "mg",
    usableDayCount:
      overrides.usableDayCount
      ?? days.filter(
        (day) =>
          day.state
          === "numeric"
          && day.numericAmount
            !== null,
      ).length,
    average:
      overrides.average
      ?? "10",
    days,
  };
}

function target(
  overrides:
    Partial<TargetValue>
      = {},
): TargetValue {
  return {
    nutrientId:
      overrides.nutrientId
      ?? "vitamin_c",
    amount:
      overrides.amount
        === undefined
        ? "15"
        : overrides.amount,
    unit:
      overrides.unit
      ?? "mg",
    authority:
      overrides.authority
      ?? "daily_value",
    direction:
      overrides.direction
      ?? "reference",
    trackingMode:
      overrides.trackingMode
      ?? "recommended",
    reasonCode:
      overrides.reasonCode
      ?? null,
    noteCode:
      overrides.noteCode
      ?? null,
    referenceType:
      overrides.referenceType
      ?? null,
    sourceVersion:
      overrides.sourceVersion
      ?? null,
    sourceId:
      overrides.sourceId
      ?? null,
    calculationBasis:
      overrides.calculationBasis
      ?? null,
  };
}

function targetConfiguration(
  value:
    TargetValue,
): TargetConfiguration {
  return {
    effectiveTargets: [
      value,
    ],
  } as unknown as TargetConfiguration;
}

describe(
  "E4-12 focused nutrient History",
  () => {
    test(
      "uses projected identity, stable unit, average, denominator, and meaningful current reference",
      () => {
        const days = [
          numericDay(
            "2026-08-12",
            "8",
          ),
          numericDay(
            "2026-08-13",
            "12",
          ),
        ];

        const model =
          buildHistoryFocusedNutrient(
            focusedNutrient(
              days,
              {
                average:
                  "10",
                usableDayCount:
                  2,
              },
            ),
            "logged_days",
            targetConfiguration(
              target(),
            ),
          );

        expect(
          model.nutrientId,
        ).toBe(
          "vitamin_c",
        );

        expect(
          model.label,
        ).toBe(
          "Vitamin C",
        );

        expect(
          model.unit,
        ).toBe(
          "mg",
        );

        expect(
          model.statistic,
        ).toBe(
          "10 mg",
        );

        expect(
          model.denominatorContext,
        ).toBe(
          "Logged-day average · 2 days used",
        );

        expect(
          model.currentReference,
        ).toEqual({
          numericValue:
            15,
          amountLabel:
            "15 mg",
          context:
            "Current FDA Daily Value · 15 mg · Neutral reference",
          lineLabel:
            "Current FDA Daily Value · 15 mg",
        });
      },
    );

    test.each([
      [
        "amount-only",
        target({
          trackingMode:
            "amount_only",
        }),
      ],
      [
        "ignored",
        target({
          trackingMode:
            "ignored",
        }),
      ],
      [
        "unavailable authority",
        target({
          authority:
            "unavailable",
        }),
      ],
      [
        "unavailable direction",
        target({
          direction:
            "unavailable",
        }),
      ],
      [
        "missing amount",
        target({
          amount:
            null,
        }),
      ],
      [
        "incompatible unit",
        target({
          unit:
            "mcg",
        }),
      ],
    ])(
      "does not manufacture a current reference for %s target state",
      (
        _name,
        value,
      ) => {
        const model =
          buildHistoryFocusedNutrient(
            focusedNutrient([
              numericDay(
                "2026-08-12",
                "10",
              ),
            ]),
            "logged_days",
            targetConfiguration(
              value,
            ),
          );

        expect(
          model.currentReference,
        ).toBeNull();
      },
    );

    test(
      "preserves numeric, estimated, explicit-zero, unavailable, no-log, and Complete states",
      () => {
        const model =
          buildHistoryFocusedNutrient(
            focusedNutrient([
              numericDay(
                "2026-08-12",
                "10",
              ),
              numericDay(
                "2026-08-13",
                "12",
                {
                  amountKnown:
                    "7",
                  amountEstimated:
                    "5",
                },
              ),
              numericDay(
                "2026-08-14",
                "0",
                {
                  amountKnown:
                    "0",
                  amountEstimated:
                    "0",
                  isExplicitZeroTotal:
                    true,
                },
              ),
              unavailableDay(
                "2026-08-15",
                true,
              ),
              gapDay(
                "2026-08-16",
              ),
            ]),
            "logged_days",
          );

        expect(
          model.days.map(
            (day) => ({
              date:
                day.date,
              value:
                day.value,
              state:
                day.state,
              complete:
                day.isComplete,
              estimated:
                day.includesEstimated,
              explicitZero:
                day.explicitZero,
            }),
          ),
        ).toEqual([
          {
            date:
              "2026-08-12",
            value:
              "10 mg",
            state:
              "numeric",
            complete:
              false,
            estimated:
              false,
            explicitZero:
              false,
          },
          {
            date:
              "2026-08-13",
            value:
              "12 mg",
            state:
              "numeric",
            complete:
              false,
            estimated:
              true,
            explicitZero:
              false,
          },
          {
            date:
              "2026-08-14",
            value:
              "0 mg",
            state:
              "numeric",
            complete:
              false,
            estimated:
              false,
            explicitZero:
              true,
          },
          {
            date:
              "2026-08-15",
            value:
              "—",
            state:
              "unavailable",
            complete:
              true,
            estimated:
              false,
            explicitZero:
              false,
          },
          {
            date:
              "2026-08-16",
            value:
              "No logs",
            state:
              "gap",
            complete:
              false,
            estimated:
              false,
            explicitZero:
              false,
          },
        ]);

        expect(
          focusedHistoryDayForDate(
            model,
            "2026-08-15",
          )?.value,
        ).toBe(
          "—",
        );

        expect(
          focusedHistoryDayForDate(
            model,
            "2026-08-20",
          ),
        ).toBeNull();
      },
    );

    test(
      "chart geometry keeps a true zero baseline with daily maximum scaling when no reference exists",
      () => {
        const geometry =
          historyDailyBarGeometry([
            numericDay(
              "2026-08-12",
              "0",
              {
                isExplicitZeroTotal:
                  true,
              },
            ),
            numericDay(
              "2026-08-13",
              "10",
            ),
            gapDay(
              "2026-08-14",
            ),
          ]);

        expect(
          geometry.baseline,
        ).toBe(
          86,
        );

        expect(
          geometry.maxNumericValue,
        ).toBe(
          10,
        );

        expect(
          geometry.scaleMaximum,
        ).toBe(
          10,
        );

        expect(
          geometry.referenceValue,
        ).toBeNull();

        expect(
          geometry.referenceY,
        ).toBeNull();

        expect(
          geometry.points[0]
            .barHeight,
        ).toBe(
          0,
        );

        expect(
          geometry.points[1]
            .barY,
        ).toBe(
          8,
        );

        expect(
          geometry.points[2]
            .numericValue,
        ).toBeNull();
      },
    );

    test(
      "reference above daily maximum expands scale from zero through the reference",
      () => {
        const geometry =
          historyDailyBarGeometry(
            [
              numericDay(
                "2026-08-12",
                "10",
              ),
            ],
            20,
          );

        expect(
          geometry.maxNumericValue,
        ).toBe(
          10,
        );

        expect(
          geometry.scaleMaximum,
        ).toBe(
          20,
        );

        expect(
          geometry.referenceValue,
        ).toBe(
          20,
        );

        expect(
          geometry.referenceY,
        ).toBe(
          8,
        );

        expect(
          geometry.points[0]
            .barHeight,
        ).toBe(
          39,
        );

        expect(
          geometry.points[0]
            .barY,
        ).toBe(
          47,
        );
      },
    );

    test(
      "daily maximum above reference retains the daily maximum scale and bounds the current line",
      () => {
        const geometry =
          historyDailyBarGeometry(
            [
              numericDay(
                "2026-08-12",
                "20",
              ),
            ],
            10,
          );

        expect(
          geometry.scaleMaximum,
        ).toBe(
          20,
        );

        expect(
          geometry.points[0]
            .barY,
        ).toBe(
          8,
        );

        expect(
          geometry.referenceY,
        ).toBe(
          47,
        );

        expect(
          geometry.referenceY,
        ).toBeGreaterThan(
          8,
        );

        expect(
          geometry.referenceY,
        ).toBeLessThanOrEqual(
          geometry.baseline,
        );
      },
    );

    test(
      "thirty-day geometry preserves all thirty calendar observations with qualified day slots",
      () => {
        const days =
          Array.from(
            {
              length: 30,
            },
            (
              _,
              index,
            ) =>
              numericDay(
                `2026-07-${
                  String(
                    index + 1,
                  ).padStart(
                    2,
                    "0",
                  )
                }`,
                String(
                  index + 1,
                ),
              ),
          );

        const geometry =
          historyDailyBarGeometry(
            days,
          );

        expect(
          geometry.points,
        ).toHaveLength(
          30,
        );

        expect(
          geometry.width,
        ).toBe(
          30 * 44,
        );

        expect(
          geometry.isScrollable,
        ).toBe(
          true,
        );

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
          geometry.points.every(
            (point) =>
              point.slotWidth
              === 44,
          ),
        ).toBe(
          true,
        );
      },
    );

    test(
      "Daily values defaults expanded for 7 days and collapsed for 30 days until explicitly set",
      () => {
        const seven =
          freshHistorySession(
            "2026-08-19",
            7,
          );

        const thirty =
          freshHistorySession(
            "2026-08-19",
            30,
          );

        expect(
          historyFocusedDailyValuesExpanded(
            seven,
          ),
        ).toBe(
          true,
        );

        expect(
          historyFocusedDailyValuesExpanded(
            thirty,
          ),
        ).toBe(
          false,
        );

        const explicitCollapsed =
          withHistoryFocusedDailyValuesExpanded(
            seven,
            false,
          );

        const changedToThirty =
          withHistoryRangeLength(
            explicitCollapsed,
            30,
          );

        expect(
          historyFocusedDailyValuesExpanded(
            changedToThirty,
          ),
        ).toBe(
          false,
        );

        const explicitExpanded =
          withHistoryFocusedDailyValuesExpanded(
            thirty,
            true,
          );

        const changedToSeven =
          withHistoryRangeLength(
            explicitExpanded,
            7,
          );

        expect(
          historyFocusedDailyValuesExpanded(
            changedToSeven,
          ),
        ).toBe(
          true,
        );
      },
    );

    test(
      "same focused nutrient and explicit disclosure survive paging and denominator changes while selected date clears on range movement",
      () => {
        let session:
          HistorySession =
          freshHistorySession(
            "2026-08-19",
            7,
          );

        session =
          withHistoryFocusedNutrient(
            session,
            "vitamin_c",
          );

        session =
          withHistoryFocusedDailyValuesExpanded(
            session,
            false,
          );

        session =
          withHistorySelectedChartDate(
            session,
            "2026-08-15",
          );

        const denominatorChanged =
          withHistoryDenominatorPreference(
            session,
            "logged_days",
          );

        expect(
          denominatorChanged
            .focusedNutrientId,
        ).toBe(
          "vitamin_c",
        );

        expect(
          historyFocusedDailyValuesExpanded(
            denominatorChanged,
          ),
        ).toBe(
          false,
        );

        expect(
          denominatorChanged
            .selectedChartDate,
        ).toBe(
          "2026-08-15",
        );

        const previous =
          previousHistorySession(
            denominatorChanged,
          );

        expect(
          previous
            .focusedNutrientId,
        ).toBe(
          "vitamin_c",
        );

        expect(
          historyFocusedDailyValuesExpanded(
            previous,
          ),
        ).toBe(
          false,
        );

        expect(
          previous
            .selectedChartDate,
        ).toBeNull();

        const next =
          nextHistorySession(
            previous,
          );

        expect(
          next
            .focusedNutrientId,
        ).toBe(
          "vitamin_c",
        );

        expect(
          historyFocusedDailyValuesExpanded(
            next,
          ),
        ).toBe(
          false,
        );
      },
    );

    test(
      "History open reuses retained session exactly and creates a fresh session only when no return context exists",
      () => {
        let retained:
          HistorySession =
          freshHistorySession(
            "2026-08-19",
            30,
          );

        retained = {
          ...retained,
          firstLoggedDate:
            "2026-01-01",
          detailCollapsedSectionIds:
            [
              "minerals",
            ],
          detailScrollOffset:
            480,
        };

        retained =
          withHistoryFocusedNutrient(
            retained,
            "vitamin_c",
          );

        retained =
          withHistoryFocusedDailyValuesExpanded(
            retained,
            true,
          );

        retained =
          withHistorySelectedChartDate(
            retained,
            "2026-08-10",
          );

        const reopened =
          historySessionForOpen(
            retained,
            "2026-08-20",
          );

        expect(
          reopened,
        ).toBe(
          retained,
        );

        expect(
          reopened,
        ).toMatchObject({
          rangeLength:
            30,
          focusedNutrientId:
            "vitamin_c",
          focusedDailyValuesExpanded:
            true,
          selectedChartDate:
            "2026-08-10",
          detailCollapsedSectionIds:
            [
              "minerals",
            ],
          detailScrollOffset:
            480,
        });

        const fresh =
          historySessionForOpen(
            null,
            "2026-08-20",
          );

        expect(
          fresh.endDate,
        ).toBe(
          "2026-08-19",
        );

        expect(
          fresh.rangeLength,
        ).toBe(
          7,
        );

        expect(
          fresh.focusedNutrientId,
        ).toBeUndefined();
      },
    );

  },
);
