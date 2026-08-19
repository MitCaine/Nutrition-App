import {
  useEffect,
  useMemo,
  useRef,
} from "react";
import {
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import {
  useAppTheme,
} from "../../../app/theme/AppTheme";
import {
  useTargetConfiguration,
} from "../../targets/hooks/useDailyTargetComparison";
import {
  AccessibilityStatus,
} from "../../../shared/accessibility/AccessibilityStatus";
import {
  AccessiblePressable,
} from "../../../shared/accessibility/AccessiblePressable";
import {
  BackButton,
} from "../../../shared/components/BackButton";
import {
  RouteScreenHeader,
} from "../../../shared/components/RouteScreenHeader";
import {
  formatReadableDate,
} from "../../logging/utils/dailyLogDisplay";
import {
  historyRangeReadState,
  useHistoryRange,
} from "../historyQuery";
import {
  projectHistoryRange,
} from "../historyProjection";
import {
  buildHistoryOverviewCards,
  selectedHistoryValueLabel,
} from "../historyOverview";
import {
  buildHistoryNutritionDetailSections,
} from "../historyNutritionDetails";
import {
  HistoryDailyBarChart,
} from "../components/HistoryDailyBarChart";
import {
  canPageHistoryNext,
  canPageHistoryPrevious,
  effectiveHistoryProjectionMode,
  HISTORY_RANGE_LENGTHS,
  historyRange,
  nextHistorySession,
  previousHistorySession,
  historyDetailCollapsedSectionIds,
  historyDetailsScrollOffset,
  historyFocusedNutrientId,
  historySelectedChartDate,
  historySurface,
  withHistoryDenominatorPreference,
  withHistoryDetailSectionToggled,
  withHistoryDetailsScrollOffset,
  withHistoryFocusedNutrient,
  withHistoryRangeLength,
  withHistorySelectedChartDate,
  withHistorySurface,
  type HistoryRangeLength,
  type HistorySession,
} from "../historyRangeModel";
import type {
  HistoryProjectionMode,
} from "../types";

type Props = {
  session: HistorySession;
  onSessionChange: (
    session: HistorySession,
  ) => void;
  onFirstLoggedDateChange: (
    firstLoggedDate: string | null,
  ) => void;
  onBack: () => void;
};

function modeLabel(
  mode: HistoryProjectionMode,
): string {
  return mode === "complete_days"
    ? "Complete days"
    : "Logged days";
}

const HISTORY_MONTH_LABELS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
] as const;

function compactHistoryRangeLabel(
  startDate: string,
  endDate: string,
): string {
  const [
    startYear,
    startMonth,
    startDay,
  ] = startDate
    .split("-")
    .map(Number);

  const [
    endYear,
    endMonth,
    endDay,
  ] = endDate
    .split("-")
    .map(Number);

  const startMonthLabel =
    HISTORY_MONTH_LABELS[
      startMonth - 1
    ];

  const endMonthLabel =
    HISTORY_MONTH_LABELS[
      endMonth - 1
    ];

  if (
    !startMonthLabel
    || !endMonthLabel
    || !Number.isInteger(startYear)
    || !Number.isInteger(endYear)
    || !Number.isInteger(startDay)
    || !Number.isInteger(endDay)
  ) {
    return `${startDate} – ${endDate}`;
  }

  if (
    startYear === endYear
    && startMonth === endMonth
  ) {
    return (
      `${startMonthLabel} `
      + `${startDay}–${endDay}, `
      + `${startYear}`
    );
  }

  if (
    startYear === endYear
  ) {
    return (
      `${startMonthLabel} ${startDay}`
      + `–${endMonthLabel} ${endDay}, `
      + `${startYear}`
    );
  }

  return (
    `${startMonthLabel} ${startDay}, `
    + `${startYear}`
    + `–${endMonthLabel} ${endDay}, `
    + `${endYear}`
  );
}

function compactHistoryCoverageLabel(
  loggedDayCount: number,
  completeDayCount: number,
): string {
  const loggedDayLabel =
    loggedDayCount === 1
      ? "day"
      : "days";

  return (
    `${loggedDayCount} ${loggedDayLabel} logged`
    + ` · ${completeDayCount} complete`
  );
}

export function HistoryScreen({
  session,
  onSessionChange,
  onFirstLoggedDateChange,
  onBack,
}: Props) {
  const theme = useAppTheme();
  const styles = useMemo(
    () => createStyles(theme),
    [theme],
  );

  const scrollViewRef =
    useRef<ScrollView>(null);

  const range =
    historyRange(session);

  const query = useHistoryRange(
    range.startDate,
    range.endDate,
  );

  const readState =
    historyRangeReadState(query);

  const targetConfiguration =
    useTargetConfiguration();

  const evidence = readState.data;
  const evidenceFirstLoggedDate =
    evidence?.firstLoggedDate;

  useEffect(() => {
    if (
      evidenceFirstLoggedDate === undefined
      || evidenceFirstLoggedDate
        === session.firstLoggedDate
    ) {
      return;
    }

    onFirstLoggedDateChange(
      evidenceFirstLoggedDate,
    );
  }, [
    evidenceFirstLoggedDate,
    onFirstLoggedDateChange,
    session.firstLoggedDate,
  ]);

  const completeDayCount =
    evidence?.days.filter(
      (day) => day.isComplete,
    ).length ?? 0;

  const effectiveMode =
    effectiveHistoryProjectionMode(
      completeDayCount,
      session.denominatorPreference,
    );

  const projection = useMemo(
    () =>
      evidence
        ? projectHistoryRange(
            evidence,
            effectiveMode,
          )
        : null,
    [
      effectiveMode,
      evidence,
    ],
  );

  const overviewCards = useMemo(
    () =>
      projection
      && projection.coverage
        .loggedDayCount > 0
        ? buildHistoryOverviewCards(
            projection,
            targetConfiguration.data,
          )
        : [],
    [
      projection,
      targetConfiguration.data,
    ],
  );

  const detailSections = useMemo(
    () =>
      projection
      && projection.coverage
        .loggedDayCount > 0
        ? buildHistoryNutritionDetailSections(
            projection,
            targetConfiguration.data,
          )
        : [],
    [
      projection,
      targetConfiguration.data,
    ],
  );

  const surface =
    historySurface(
      session,
    );

  const collapsedDetailSectionIds =
    historyDetailCollapsedSectionIds(
      session,
    );

  const detailScrollOffset =
    historyDetailsScrollOffset(
      session,
    );

  const focusedNutrientId =
    historyFocusedNutrientId(
      session,
    );

  const focusedDetailRow = useMemo(
    () =>
      focusedNutrientId
        ? (
            detailSections
              .flatMap(
                (section) =>
                  section.rows,
              )
              .find(
                (row) =>
                  row.nutrientId
                  === focusedNutrientId,
              )
            ?? null
          )
        : null,
    [
      detailSections,
      focusedNutrientId,
    ],
  );

  useEffect(() => {
    if (
      surface
      !== "nutrition_details"
    ) {
      return;
    }

    scrollViewRef.current
      ?.scrollTo({
        animated: false,
        y: detailScrollOffset,
      });
  }, [
    detailScrollOffset,
    surface,
  ]);

  const selectedChartDate =
    historySelectedChartDate(
      session,
    );

  const knownFirstLoggedDate =
    session.firstLoggedDate
      !== undefined
      ? session.firstLoggedDate
      : evidenceFirstLoggedDate;

  const canPrevious =
    knownFirstLoggedDate
      !== undefined
      && canPageHistoryPrevious(
        session,
        knownFirstLoggedDate,
      );

  const canNext =
    canPageHistoryNext(
      session,
    );

  const rangeLabel =
    `${formatReadableDate(
      range.startDate,
    )} – ${formatReadableDate(
      range.endDate,
    )}`;

  const compactRangeLabel =
    compactHistoryRangeLabel(
      range.startDate,
      range.endDate,
    );

  const chooseRangeLength = (
    rangeLength: HistoryRangeLength,
  ) => {
    if (
      rangeLength
      === session.rangeLength
    ) {
      return;
    }

    onSessionChange(
      withHistoryRangeLength(
        session,
        rangeLength,
      ),
    );
  };

  const chooseMode = (
    mode: HistoryProjectionMode,
  ) => {
    if (
      mode
      === session.denominatorPreference
    ) {
      return;
    }

    onSessionChange(
      withHistoryDenominatorPreference(
        session,
        mode,
      ),
    );
  };

  const rememberDetailScrollOffset = (
    offset: number,
  ) => {
    if (
      surface
      !== "nutrition_details"
    ) {
      return;
    }

    const normalized =
      Math.max(
        0,
        Math.round(offset),
      );

    if (
      normalized
      === detailScrollOffset
    ) {
      return;
    }

    onSessionChange(
      withHistoryDetailsScrollOffset(
        session,
        normalized,
      ),
    );
  };

  const handleHeaderBack = () => {
    if (
      surface
      === "focused_nutrient"
    ) {
      onSessionChange(
        withHistorySurface(
          session,
          "nutrition_details",
        ),
      );

      return;
    }

    onBack();
  };

  return (
    <View style={styles.screen}>
      <RouteScreenHeader
        title="History"
        leading={(
          <BackButton
            accessibilityLabel={
              surface
                === "focused_nutrient"
                ? "Back to Nutrition Details from focused History"
                : "Back to Daily Log from History"
            }
            onPress={
              handleHeaderBack
            }
          />
        )}
      />

      <ScrollView
        ref={scrollViewRef}
        contentContainerStyle={
          styles.content
        }
        onMomentumScrollEnd={(
          event,
        ) =>
          rememberDetailScrollOffset(
            event.nativeEvent
              .contentOffset.y,
          )
        }
        onScrollEndDrag={(
          event,
        ) =>
          rememberDetailScrollOffset(
            event.nativeEvent
              .contentOffset.y,
          )
        }
        scrollEventThrottle={16}
      >
        <View
          style={
            styles.compactPeriodCard
          }
        >
          <View
            style={
              styles.compactPeriodTopRow
            }
          >
            <Text
              accessibilityLabel={
                `Selected History range ${rangeLabel}`
              }
              style={
                styles.compactRangeText
              }
            >
              {compactRangeLabel}
            </Text>

            <View
              accessibilityRole="radiogroup"
              style={
                styles.compactControlRow
              }
            >
              {HISTORY_RANGE_LENGTHS.map(
                (rangeLength) => {
                  const selected =
                    session.rangeLength
                    === rangeLength;

                  return (
                    <AccessiblePressable
                      key={rangeLength}
                      accessibilityLabel={
                        `Use ${rangeLength} Days`
                      }
                      accessibilityRole="radio"
                      accessibilityState={{
                        checked: selected,
                      }}
                      hitSlop={{
                        top: 3,
                        bottom: 3,
                      }}
                      onPress={() =>
                        chooseRangeLength(
                          rangeLength,
                        )
                      }
                      style={[
                        styles.compactChoice,
                        styles.compactRangeChoice,
                        selected
                          && styles
                            .compactChoiceSelected,
                      ]}
                    >
                      <Text
                        style={[
                          styles.compactChoiceText,
                          selected
                            && styles
                              .compactChoiceTextSelected,
                        ]}
                      >
                        {rangeLength} Days
                      </Text>
                    </AccessiblePressable>
                  );
                },
              )}
            </View>
          </View>

          <View
            style={
              styles.compactPagingRow
            }
          >
            <AccessiblePressable
              accessibilityLabel="Previous History period"
              accessibilityState={{
                disabled: !canPrevious,
              }}
              disabled={!canPrevious}
              onPress={() =>
                onSessionChange(
                  previousHistorySession(
                    session,
                  ),
                )
              }
              style={[
                styles.compactPageButton,
                !canPrevious
                  && styles.disabled,
              ]}
            >
              <Text
                style={[
                  styles.compactPageButtonText,
                  !canPrevious
                    && styles.disabledText,
                ]}
              >
                Previous
              </Text>
            </AccessiblePressable>

            <AccessiblePressable
              accessibilityLabel="Next History period"
              accessibilityState={{
                disabled: !canNext,
              }}
              disabled={!canNext}
              onPress={() =>
                onSessionChange(
                  nextHistorySession(
                    session,
                  ),
                )
              }
              style={[
                styles.compactPageButton,
                !canNext
                  && styles.disabled,
              ]}
            >
              <Text
                style={[
                  styles.compactPageButtonText,
                  !canNext
                    && styles.disabledText,
                ]}
              >
                Next
              </Text>
            </AccessiblePressable>
          </View>

          {projection
            && projection.coverage
              .loggedDayCount > 0 ? (
            <View
              style={
                styles.compactCoverageRow
              }
            >
              {projection.coverage
                .completeDayCount > 0 ? (
                <View
                  accessibilityRole="radiogroup"
                  style={
                    styles.compactControlRow
                  }
                >
                  {(
                    [
                      "complete_days",
                      "logged_days",
                    ] as const
                  ).map((mode) => {
                    const selected =
                      effectiveMode
                      === mode;

                    return (
                      <AccessiblePressable
                        key={mode}
                        accessibilityLabel={
                          `Use ${modeLabel(
                            mode,
                          )}`
                        }
                        accessibilityRole="radio"
                        accessibilityState={{
                          checked:
                            selected,
                        }}
                        onPress={() =>
                          chooseMode(
                            mode,
                          )
                        }
                        style={[
                          styles.compactChoice,
                          selected
                            && styles
                              .compactChoiceSelected,
                        ]}
                      >
                        <Text
                          style={[
                            styles.compactChoiceText,
                            selected
                              && styles
                                .compactChoiceTextSelected,
                          ]}
                        >
                          {mode
                            === "complete_days"
                            ? "Complete"
                            : "Logged"}
                        </Text>
                      </AccessiblePressable>
                    );
                  })}
                </View>
              ) : null}

              <Text
                style={
                  styles.compactCountText
                }
              >
                {compactHistoryCoverageLabel(
                  projection.coverage
                    .loggedDayCount,
                  projection.coverage
                    .completeDayCount,
                )}
              </Text>
            </View>
          ) : null}
        </View>

        {readState.kind
          === "initial-loading" ? (
          <AccessibilityStatus
            kind="loading"
            message="Loading History…"
          />
        ) : null}

        {readState.kind
          === "initial-failure" ? (
          <AccessibilityStatus
            kind="initial-failure"
            message={
              "History could not load for this range."
            }
            onRetry={
              readState.retry
            }
            retryContext="History"
          />
        ) : null}

        {readState.kind
          === "refresh-failure" ? (
          <AccessibilityStatus
            kind="retryable-failure"
            message={
              "History could not refresh. Showing the last result for this range."
            }
            onRetry={
              readState.retry
            }
            retryContext="History"
          />
        ) : null}

        {projection ? (
          <>
            {projection.firstLoggedDate
              === null ? (
              <AccessibilityStatus
                kind="empty"
                title="No History yet"
                message={
                  "No logged days are available yet."
                }
              />
            ) : projection.coverage
                .loggedDayCount === 0 ? (
              <AccessibilityStatus
                kind="empty"
                title="No logged days in this range"
                message={
                  "No food was logged during this period."
                }
              />
            ) : (
              <>

                {surface
                  === "overview" ? (
                  <>
                    <AccessiblePressable
                      accessibilityHint={
                        "Opens the distinct Nutrition Details History surface"
                      }
                      accessibilityLabel={
                        "Show more nutrition"
                      }
                      onPress={() =>
                        onSessionChange(
                          withHistorySurface(
                            session,
                            "nutrition_details",
                          ),
                        )
                      }
                      style={styles.choice}
                    >
                      <Text style={styles.choiceText}>
                        Show more nutrition
                      </Text>
                    </AccessiblePressable>

                    {overviewCards.map(
                      (card) => {
                        const selectedValue =
                          selectedChartDate
                            ? selectedHistoryValueLabel(
                                card,
                                selectedChartDate,
                              )
                            : null;

                        return (
                          <View
                            key={
                              card.nutrientId
                            }
                            style={
                              styles.summaryCard
                            }
                          >
                            <Text
                              style={
                                styles.summaryTitle
                              }
                            >
                              {card.label}
                            </Text>

                            <Text
                              style={
                                styles.rangeText
                              }
                            >
                              {card.statistic}
                            </Text>

                            <Text
                              style={
                                styles.summaryText
                              }
                            >
                              {
                                card.denominatorContext
                              }
                            </Text>

                            {card.targetContext
                              ? (
                              <Text
                                style={
                                  styles.summaryText
                                }
                              >
                                {
                                  card.targetContext
                                }
                              </Text>
                            ) : null}

                            <HistoryDailyBarChart
                              barColor={
                                theme.colors
                                  .accent
                              }
                              days={
                                card.days
                              }
                              onSelectDate={(
                                date,
                              ) =>
                                onSessionChange(
                                  withHistorySelectedChartDate(
                                    session,
                                    date,
                                  ),
                                )
                              }
                              selectedBarColor={
                                theme.colors
                                  .text
                              }
                              selectedDate={
                                selectedChartDate
                              }
                              seriesLabel={
                                card.label
                              }
                            />

                            {selectedChartDate
                              ? (
                              <Text
                                accessibilityLabel={
                                  `${
                                    card.label
                                  } selected ${
                                    selectedChartDate
                                  } ${
                                    selectedValue
                                      ?? "—"
                                  }`
                                }
                                style={
                                  styles.summaryText
                                }
                              >
                                {
                                  formatReadableDate(
                                    selectedChartDate,
                                  )
                                }{" "}
                                ·{" "}
                                {
                                  selectedValue
                                  ?? "—"
                                }
                              </Text>
                            ) : null}
                          </View>
                        );
                      },
                    )}
                  </>
                ) : surface
                    === "nutrition_details" ? (
                  <View
                    style={
                      styles.detailsSurface
                    }
                  >
                    <View
                      style={
                        styles.detailsHeader
                      }
                    >
                      <Text
                        accessibilityRole="header"
                        style={
                          styles.detailsTitle
                        }
                      >
                        Nutrition Details
                      </Text>

                      <AccessiblePressable
                        accessibilityHint={
                          "Closes Nutrition Details and returns to the History overview"
                        }
                        accessibilityLabel={
                          "Back to History overview"
                        }
                        hitSlop={{
                          top: 3,
                          bottom: 3,
                        }}
                        onPress={() =>
                          onSessionChange(
                            withHistorySurface(
                              session,
                              "overview",
                            ),
                          )
                        }
                        style={
                          styles.closeButton
                        }
                      >
                        <Text
                          style={
                            styles.closeButtonText
                          }
                        >
                          Close
                        </Text>
                      </AccessiblePressable>
                    </View>

                    {detailSections.map(
                      (section) => {
                        const expanded =
                          !collapsedDetailSectionIds
                            .includes(
                              section.id,
                            );

                        return (
                          <View
                            key={
                              section.id
                            }
                            style={
                              styles.detailSection
                            }
                          >
                            <AccessiblePressable
                              accessibilityLabel={
                                `${section.label} History section`
                              }
                              accessibilityState={{
                                expanded,
                              }}
                              onPress={() =>
                                onSessionChange(
                                  withHistoryDetailSectionToggled(
                                    session,
                                    section.id,
                                  ),
                                )
                              }
                              style={
                                styles.detailSectionHeader
                              }
                            >
                              <Text
                                accessibilityRole="header"
                                style={
                                  styles.detailSectionTitle
                                }
                              >
                                {
                                  section.label
                                }
                              </Text>

                              <Text
                                accessible={false}
                                style={
                                  styles.detailToggle
                                }
                              >
                                {expanded
                                  ? "−"
                                  : "+"}
                              </Text>
                            </AccessiblePressable>

                            {expanded
                              ? section.rows.map(
                                  (row) => (
                                    <AccessiblePressable
                                      key={
                                        row.nutrientId
                                      }
                                      accessibilityHint={
                                        "Opens focused nutrient History"
                                      }
                                      accessibilityLabel={
                                        `Open ${row.label} focused History`
                                      }
                                      onPress={() =>
                                        onSessionChange(
                                          withHistoryFocusedNutrient(
                                            session,
                                            row.nutrientId,
                                          ),
                                        )
                                      }
                                      style={[
                                        styles.detailRow,
                                        row.hierarchyDepth
                                          > 0
                                          ? {
                                              marginLeft:
                                                row.hierarchyDepth
                                                * 16,
                                            }
                                          : undefined,
                                      ]}
                                    >
                                      <View
                                        style={
                                          styles.detailRowTop
                                        }
                                      >
                                        <Text
                                          style={
                                            styles.detailRowName
                                          }
                                        >
                                          {
                                            row.label
                                          }
                                        </Text>

                                        <Text
                                          style={
                                            styles.detailRowValue
                                          }
                                        >
                                          {
                                            row.value
                                          }
                                        </Text>
                                      </View>

                                      <Text
                                        style={
                                          styles.detailSecondary
                                        }
                                      >
                                        {
                                          row.denominatorContext
                                        }
                                      </Text>

                                      {row.targetContext
                                        ? (
                                        <Text
                                          style={
                                            styles.detailSecondary
                                          }
                                        >
                                          {
                                            row.targetContext
                                          }
                                        </Text>
                                      ) : null}
                                    </AccessiblePressable>
                                  ),
                                )
                              : null}
                          </View>
                        );
                      },
                    )}
                  </View>
                ) : (
                  <View
                    style={
                      styles.summaryCard
                    }
                  >
                    <Text
                      accessibilityRole="header"
                      style={
                        styles.detailsTitle
                      }
                    >
                      Focused nutrient History
                    </Text>

                    <Text
                      style={
                        styles.focusedNutrientName
                      }
                    >
                      {
                        focusedDetailRow
                          ?.label
                        ?? focusedNutrientId
                        ?? "Nutrient"
                      }
                    </Text>

                    {focusedDetailRow
                      ? (
                      <Text
                        style={
                          styles.detailSecondary
                        }
                      >
                        Canonical unit:{" "}
                        {
                          focusedDetailRow
                            .unit
                        }
                      </Text>
                    ) : null}

                    <Text
                      style={
                        styles.detailSecondary
                      }
                    >
                      Focused chart and exact daily values are implemented in E4-12.
                    </Text>
                  </View>
                )}
              </>
            )}
          </>
        ) : null}
      </ScrollView>
    </View>
  );
}

function createStyles(
  theme: ReturnType<
    typeof useAppTheme
  >,
) {
  return StyleSheet.create({
    choice: {
      borderColor:
        theme.colors.border,
      borderRadius: 10,
      borderWidth: 1,
      paddingHorizontal: 14,
      paddingVertical: 10,
    },
    choiceSelected: {
      backgroundColor:
        theme.colors
          .selectedNavigationBackground,
      borderColor:
        theme.colors.accent,
    },
    choiceText: {
      color:
        theme.colors.secondaryText,
      fontSize: 16,
      fontWeight: "600",
    },
    choiceTextSelected: {
      color:
        theme.colors
          .selectedNavigationForeground,
    },
    compactChoice: {
      alignItems:
        "center",
      borderColor:
        theme.colors.border,
      borderRadius: 9,
      borderWidth: 1,
      justifyContent:
        "center",
      minHeight: 44,
      paddingHorizontal: 10,
      paddingVertical: 6,
    },
    compactChoiceSelected: {
      backgroundColor:
        theme.colors
          .selectedNavigationBackground,
      borderColor:
        theme.colors.accent,
    },
    compactChoiceText: {
      color:
        theme.colors.secondaryText,
      fontSize: 14,
      fontWeight: "700",
    },
    compactChoiceTextSelected: {
      color:
        theme.colors
          .selectedNavigationForeground,
    },
    compactControlRow: {
      flexDirection: "row",
      flexWrap: "wrap",
      gap: 6,
    },
    compactCountText: {
      color:
        theme.colors.secondaryText,
      flexGrow: 1,
      flexShrink: 1,
      fontSize: 13,
      fontWeight: "600",
      textAlign: "left",
    },
    compactCoverageRow: {
      alignItems: "center",
      flexDirection: "row",
      flexWrap: "wrap",
      gap: 8,
      justifyContent:
        "space-between",
    },
    compactPageButton: {
      alignItems:
        "center",
      borderColor:
        theme.colors.border,
      borderRadius: 9,
      borderWidth: 1,
      flex: 1,
      justifyContent:
        "center",
      minHeight: 44,
      paddingHorizontal: 10,
      paddingVertical: 6,
    },
    compactPageButtonText: {
      color:
        theme.colors.accent,
      fontSize: 15,
      fontWeight: "700",
    },
    compactPagingRow: {
      flexDirection: "row",
      gap: 8,
      marginTop: 4,
    },
    compactPeriodCard: {
      backgroundColor:
        theme.colors.surface,
      borderColor:
        theme.colors.border,
      borderRadius: 12,
      borderWidth: 1,
      gap: 8,
      padding: 10,
    },
    compactPeriodTopRow: {
      alignItems: "center",
      flexDirection: "row",
      flexWrap: "wrap",
      gap: 10,
      justifyContent:
        "space-between",
    },
    compactRangeChoice: {
      minHeight: 38,
      paddingVertical: 3,
    },
    compactRangeText: {
      color:
        theme.colors.text,
      flexGrow: 1,
      flexShrink: 1,
      fontSize: 16,
      fontWeight: "800",
      lineHeight: 20,
      minWidth: 140,
      textAlign: "left",
    },
    content: {
      gap: 16,
      padding: 16,
      paddingBottom: 32,
    },
    controlGroup: {
      gap: 8,
    },
    controlRow: {
      flexDirection: "row",
      flexWrap: "wrap",
      gap: 8,
    },
    disabled: {
      backgroundColor:
        theme.colors.disabledBackground,
      borderColor:
        theme.colors.border,
    },
    disabledText: {
      color:
        theme.colors.disabledText,
    },
    closeButton: {
      alignItems:
        "center",
      borderColor:
        theme.colors.border,
      borderRadius: 10,
      borderWidth: 1,
      justifyContent:
        "center",
      minHeight: 38,
      paddingHorizontal: 14,
      paddingVertical: 3,
    },
    closeButtonText: {
      color:
        theme.colors.accent,
      fontSize: 15,
      fontWeight: "700",
    },
    detailRow: {
      borderBottomColor:
        theme.colors.border,
      borderBottomWidth: 1,
      gap: 4,
      paddingHorizontal: 2,
      paddingVertical: 10,
    },
    detailRowName: {
      color:
        theme.colors.text,
      flex: 1,
      fontSize: 15,
      fontWeight: "700",
      paddingRight: 10,
    },
    detailRowTop: {
      alignItems: "flex-start",
      flexDirection: "row",
      justifyContent:
        "space-between",
    },
    detailRowValue: {
      color:
        theme.colors.text,
      fontSize: 15,
      fontWeight: "600",
      textAlign: "right",
    },
    detailSecondary: {
      color:
        theme.colors.secondaryText,
      fontSize: 13,
    },
    detailsHeader: {
      alignItems: "center",
      flexDirection: "row",
      justifyContent:
        "space-between",
    },
    detailsSurface: {
      backgroundColor:
        theme.colors.surface,
      borderColor:
        theme.colors.border,
      borderRadius: 12,
      borderWidth: 1,
      gap: 12,
      padding: 14,
    },
    detailsTitle: {
      color:
        theme.colors.text,
      fontSize: 22,
      fontWeight: "800",
    },
    detailSection: {
      gap: 2,
    },
    detailSectionHeader: {
      alignItems: "center",
      borderBottomColor:
        theme.colors.border,
      borderBottomWidth: 2,
      flexDirection: "row",
      justifyContent:
        "space-between",
      paddingVertical: 8,
    },
    detailSectionTitle: {
      color:
        theme.colors.text,
      fontSize: 17,
      fontWeight: "800",
    },
    detailToggle: {
      color:
        theme.colors.text,
      fontSize: 24,
      fontWeight: "600",
    },
    focusedNutrientName: {
      color:
        theme.colors.text,
      fontSize: 20,
      fontWeight: "800",
    },
    label: {
      color:
        theme.colors.secondaryText,
      fontSize: 14,
      fontWeight: "700",
    },
    pageButton: {
      borderColor:
        theme.colors.border,
      borderRadius: 10,
      borderWidth: 1,
      flex: 1,
      paddingHorizontal: 14,
      paddingVertical: 10,
    },
    pageButtonText: {
      color:
        theme.colors.accent,
      fontSize: 16,
      fontWeight: "700",
    },
    pagingRow: {
      flexDirection: "row",
      gap: 8,
    },
    rangeCard: {
      backgroundColor:
        theme.colors.surface,
      borderColor:
        theme.colors.border,
      borderRadius: 12,
      borderWidth: 1,
      gap: 10,
      padding: 14,
    },
    rangeText: {
      color:
        theme.colors.text,
      fontSize: 16,
      fontWeight: "700",
    },
    screen: {
      backgroundColor:
        theme.colors.background,
      flex: 1,
    },
    summaryCard: {
      backgroundColor:
        theme.colors.surface,
      borderColor:
        theme.colors.border,
      borderRadius: 12,
      borderWidth: 1,
      gap: 10,
      padding: 14,
    },
    summaryText: {
      color:
        theme.colors.secondaryText,
      fontSize: 15,
    },
    summaryTitle: {
      color:
        theme.colors.text,
      fontSize: 17,
      fontWeight: "700",
    },
  });
}
