import {
  useEffect,
  useMemo,
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
  historySelectedChartDate,
  historySurface,
  withHistoryDenominatorPreference,
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

  const surface =
    historySurface(
      session,
    );

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

  return (
    <View style={styles.screen}>
      <RouteScreenHeader
        title="History"
        leading={(
          <BackButton
            accessibilityLabel="Back to Daily Log from History"
            onPress={onBack}
          />
        )}
      />

      <ScrollView
        contentContainerStyle={
          styles.content
        }
      >
        <View
          accessibilityRole="radiogroup"
          style={styles.controlGroup}
        >
          <Text style={styles.label}>
            Range
          </Text>

          <View style={styles.controlRow}>
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
                    onPress={() =>
                      chooseRangeLength(
                        rangeLength,
                      )
                    }
                    style={[
                      styles.choice,
                      selected
                        && styles.choiceSelected,
                    ]}
                  >
                    <Text
                      style={[
                        styles.choiceText,
                        selected
                          && styles
                            .choiceTextSelected,
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

        <View style={styles.rangeCard}>
          <Text style={styles.label}>
            Selected range
          </Text>

          <Text
            accessibilityLabel={
              `Selected History range ${rangeLabel}`
            }
            style={styles.rangeText}
          >
            {rangeLabel}
          </Text>

          <View style={styles.pagingRow}>
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
                styles.pageButton,
                !canPrevious
                  && styles.disabled,
              ]}
            >
              <Text
                style={[
                  styles.pageButtonText,
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
                styles.pageButton,
                !canNext
                  && styles.disabled,
              ]}
            >
              <Text
                style={[
                  styles.pageButtonText,
                  !canNext
                    && styles.disabledText,
                ]}
              >
                Next
              </Text>
            </AccessiblePressable>
          </View>
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
          === "refreshing" ? (
          <AccessibilityStatus
            kind="refreshing"
            message="Refreshing History…"
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
                <View style={styles.summaryCard}>
                  {projection.coverage
                    .completeDayCount > 0 ? (
                    <View
                      accessibilityRole="radiogroup"
                      style={styles.controlGroup}
                    >
                      <Text style={styles.label}>
                        Coverage
                      </Text>

                      <View
                        style={
                          styles.controlRow
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
                                styles.choice,
                                selected
                                  && styles
                                    .choiceSelected,
                              ]}
                            >
                              <Text
                                style={[
                                  styles.choiceText,
                                  selected
                                    && styles
                                      .choiceTextSelected,
                                ]}
                              >
                                {modeLabel(
                                  mode,
                                )}
                              </Text>
                            </AccessiblePressable>
                          );
                        })}
                      </View>
                    </View>
                  ) : null}

                  <Text style={styles.summaryTitle}>
                    Coverage mode:{" "}
                    {modeLabel(
                      effectiveMode,
                    )}
                  </Text>

                  <Text style={styles.summaryText}>
                    {
                      projection.coverage
                        .completeDayCount
                    }{" "}
                    Complete days ·{" "}
                    {
                      projection.coverage
                        .loggedDayCount
                    }{" "}
                    logged days
                  </Text>
                </View>

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
                ) : (
                  <View
                    style={
                      styles.summaryCard
                    }
                  >
                    <Text
                      style={
                        styles.summaryTitle
                      }
                    >
                      Nutrition Details
                    </Text>

                    <AccessiblePressable
                      accessibilityLabel={
                        "Back to History overview"
                      }
                      onPress={() =>
                        onSessionChange(
                          withHistorySurface(
                            session,
                            "overview",
                          ),
                        )
                      }
                      style={styles.choice}
                    >
                      <Text style={styles.choiceText}>
                        Back to overview
                      </Text>
                    </AccessiblePressable>
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
