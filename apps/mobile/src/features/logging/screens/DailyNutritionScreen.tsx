import {
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
  AccessiblePressable,
} from "../../../shared/accessibility/AccessiblePressable";
import {
  AccessibilityStatus,
} from "../../../shared/accessibility/AccessibilityStatus";
import type {
  NutrientSectionId,
} from "../../../shared/nutrition/nutrientSections";
import {
  targetProgressReadState,
  useDailyTargetComparison,
} from "../../targets/hooks/useDailyTargetComparison";
import {
  formatReadableDate,
} from "../utils/dailyLogDisplay";
import {
  buildDailyNutritionSections,
} from "../utils/dailyNutritionPresentation";

type Props = {
  date: string;
  collapsedSectionIds:
    ReadonlySet<NutrientSectionId>;
  onToggleSection:
    (sectionId: NutrientSectionId) => void;
  onBack: () => void;
  onOpenTargets: () => void;
};

export function DailyNutritionScreen({
  date,
  collapsedSectionIds,
  onToggleSection,
  onBack,
  onOpenTargets,
}: Props) {
  const theme = useAppTheme();

  const styles = useMemo(
    () => createStyles(theme),
    [theme],
  );

  const query =
    useDailyTargetComparison(date);

  const state =
    targetProgressReadState(
      query,
      true,
    );

  const sections =
    buildDailyNutritionSections(
      state.data?.comparisons
      ?? [],
    );

  return (
    <View
      style={[
        styles.screen,
        {
          backgroundColor:
            theme.colors.background,
        },
      ]}
    >
      <View style={styles.header}>
        <View
          style={styles.actionRow}
        >
          <AccessiblePressable
            accessibilityLabel="Back to Daily Log from Daily Nutrition"
            onPress={onBack}
            style={styles.headerAction}
          >
            <Text
              style={
                styles.headerActionText
              }
            >
              Back
            </Text>
          </AccessiblePressable>

          <AccessiblePressable
            accessibilityLabel="Nutrition targets"
            onPress={onOpenTargets}
            style={styles.headerAction}
          >
            <Text
              style={
                styles.headerActionText
              }
            >
              Nutrition targets
            </Text>
          </AccessiblePressable>
        </View>

        <Text
          accessibilityRole="header"
          style={styles.title}
        >
          Daily Nutrition
        </Text>

        <Text style={styles.date}>
          {formatReadableDate(date)}
        </Text>
      </View>

      <ScrollView
        contentContainerStyle={
          styles.content
        }
      >
        {state.kind
          === "initial-loading" ? (
          <AccessibilityStatus
            kind="loading"
            message="Loading Daily Nutrition…"
          />
        ) : null}

        {state.kind
          === "initial-failure" ? (
          <AccessibilityStatus
            kind="initial-failure"
            message="Daily Nutrition is unavailable."
            onRetry={state.retry}
            retryContext="Daily Nutrition"
          />
        ) : null}

        {state.kind
          === "empty" ? (
          <AccessibilityStatus
            kind="empty"
            message="No nutrition is available for this date."
          />
        ) : null}

        {state.kind
          === "refreshing" ? (
          <AccessibilityStatus
            kind="refreshing"
            message="Refreshing Daily Nutrition…"
          />
        ) : null}

        {state.kind
          === "refresh-failure" ? (
          <AccessibilityStatus
            kind="stale"
            message="Daily Nutrition could not be refreshed; showing the last confirmed values."
            onRetry={state.retry}
            retryContext="Daily Nutrition"
          />
        ) : null}

        {sections.map(
          (section) => {
            const expanded =
              !collapsedSectionIds.has(
                section.id,
              );

            return (
              <View
                key={section.id}
                style={
                  styles.section
                }
              >
                <AccessiblePressable
                  accessibilityLabel={`${section.label} section`}
                  accessibilityState={{
                    expanded,
                  }}
                  onPress={() =>
                    onToggleSection(
                      section.id,
                    )
                  }
                  style={
                    styles.sectionHeader
                  }
                >
                  <Text
                    accessibilityRole="header"
                    style={
                      styles.sectionTitle
                    }
                  >
                    {section.label}
                  </Text>

                  <Text
                    accessible={false}
                    style={
                      styles.sectionToggle
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
                        <View
                          key={
                            row.nutrientId
                          }
                          style={[
                            styles.row,
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
                          <Text
                            accessibilityLabel={
                              row.accessibilityLabel
                            }
                            style={
                              styles.rowName
                            }
                          >
                            {row.label}
                          </Text>

                          <Text
                            accessible={false}
                            style={
                              styles.rowValue
                            }
                          >
                            {row.value}
                          </Text>

                          {row.percentage
                            ? (
                              <Text
                                accessible={
                                  false
                                }
                                style={
                                  styles.secondary
                                }
                              >
                                {
                                  row.percentage
                                }
                              </Text>
                            )
                            : null}

                          {row.context
                            ? (
                              <Text
                                accessible={
                                  false
                                }
                                style={
                                  styles.secondary
                                }
                              >
                                {
                                  row.context
                                }
                              </Text>
                            )
                            : null}
                        </View>
                      ),
                    )
                  : null}
              </View>
            );
          },
        )}
      </ScrollView>
    </View>
  );
}

function createStyles(
  theme:
    ReturnType<typeof useAppTheme>,
) {
  return StyleSheet.create({
    actionRow: {
      alignItems: "center",
      flexDirection: "row",
      justifyContent:
        "space-between",
    },
    content: {
      gap: 12,
      padding: 16,
      paddingBottom: 32,
    },
    date: {
      color:
        theme.colors.secondaryText,
      fontSize: 15,
      marginTop: 4,
    },
    header: {
      borderBottomColor:
        theme.colors.border,
      borderBottomWidth: 1,
      paddingBottom: 12,
      paddingHorizontal: 16,
      paddingTop: 4,
    },
    headerAction: {
      alignItems: "flex-start",
      paddingHorizontal: 0,
    },
    headerActionText: {
      color: theme.colors.accent,
      fontWeight: "600",
    },
    row: {
      borderBottomColor:
        theme.colors.border,
      borderBottomWidth: 1,
      gap: 3,
      paddingVertical: 10,
    },
    rowName: {
      color: theme.colors.text,
      fontWeight: "700",
    },
    rowValue: {
      color: theme.colors.text,
      fontSize: 15,
    },
    screen: {
      flex: 1,
    },
    secondary: {
      color:
        theme.colors.secondaryText,
      fontSize: 13,
    },
    section: {
      gap: 2,
    },
    sectionHeader: {
      alignItems: "center",
      borderBottomColor:
        theme.colors.border,
      borderBottomWidth: 2,
      flexDirection: "row",
      justifyContent:
        "space-between",
      paddingHorizontal: 0,
    },
    sectionTitle: {
      color: theme.colors.text,
      fontSize: 17,
      fontWeight: "800",
    },
    sectionToggle: {
      color: theme.colors.text,
      fontSize: 24,
      fontWeight: "600",
    },
    title: {
      color: theme.colors.text,
      fontSize: 28,
      fontWeight: "800",
      marginTop: 4,
    },
  });
}
