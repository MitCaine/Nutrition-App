import { useMemo } from "react";
import { StyleSheet, Text, View } from "react-native";

import { useAppTheme } from "../../app/theme/AppTheme";
import { AccessiblePressable } from "../../shared/accessibility/AccessiblePressable";
import { AccessibilityStatus } from "../../shared/accessibility/AccessibilityStatus";
import { userFacingEpicOneError } from "../../shared/errors/userFacingError";
import { NUTRIENT_CATALOG_BY_ID } from "../../shared/nutrition/catalog";
import { formatNutrientLabel } from "../../shared/nutrition/display";
import {
  canonicalNutrientParentId,
  groupCanonicalNutrientsBySection,
  nutrientVisibleDepth,
} from "../../shared/nutrition/nutrientSections";
import type {
  DailyTargetComparison,
  DailyTargetComparisonItem,
} from "./api/types";
import {
  targetProgressReadState,
  useDailyTargetComparison,
  type TargetProgressReadState,
} from "./hooks/useDailyTargetComparison";
import {
  boundedProgressValue,
  formatTargetAmount,
  formatTargetPercentage,
  percentageAtOrAbove100,
  progressAccessibilityLabel,
} from "./targetProgress";

type ContentProps = {
  data?: DailyTargetComparison;
  isLoading: boolean;
  isError: boolean;
  isFetching?: boolean;
  isRefetchError?: boolean;
  error?: unknown;
  /** A pre-translated state is used by the screen; legacy flags remain supported for focused callers. */
  readState?: TargetProgressReadState;
  entriesKnown?: boolean;
  hasLoggedNutrition?: boolean;
  onRetry: () => void;
  onOpenTargets: () => void;
};

export function TargetProgressSection({
  date,
  entriesKnown = true,
  hasLoggedNutrition,
  onOpenTargets,
}: {
  date: string;
  entriesKnown?: boolean;
  hasLoggedNutrition?: boolean;
  onOpenTargets: () => void;
}) {
  const query =
    useDailyTargetComparison(date);

  const readState =
    targetProgressReadState(
      query,
      entriesKnown,
    );

  return (
    <TargetProgressContent
      readState={readState}
      data={query.data}
      isLoading={query.isLoading}
      isError={query.isError}
      isFetching={query.isFetching}
      isRefetchError={
        query.isRefetchError
      }
      error={query.error}
      onRetry={readState.retry}
      hasLoggedNutrition={
        hasLoggedNutrition
      }
      onOpenTargets={
        onOpenTargets
      }
    />
  );
}

export function TargetProgressContent({
  data,
  isLoading,
  isError,
  isFetching = false,
  isRefetchError = false,
  error,
  readState,
  entriesKnown = true,
  hasLoggedNutrition,
  onRetry,
  onOpenTargets,
}: ContentProps) {
  const theme = useAppTheme();

  const styles = useMemo(
    () => createStyles(theme),
    [theme],
  );

  const state =
    readState
    ?? targetProgressReadState(
      {
        data,
        isLoading,
        isError,
        isFetching,
        isRefetchError,
        error,
        refetch: onRetry,
      },
      entriesKnown,
    );

  const comparisons =
    state.data?.comparisons ?? [];

  const rows =
    comparisons.filter(
      (item) =>
        item.trackingMode
        !== "ignored",
    );

  const rowSections =
    groupCanonicalNutrientsBySection(
      rows,
      (item) => item.nutrientId,
    );

  const visibleNutrientIds =
    new Set(
      rows.map(
        (item) => item.nutrientId,
      ),
    );

  const inferredHasLoggedNutrition =
    state.data
      ? rows.some(
          (item) =>
            item.consumedAmount
              !== null
            || item
              .hasUnknownContributors,
        )
      : undefined;

  const hasPersonalizedTargets =
    Boolean(
      state.data?.comparisons.some(
        (item) =>
          item.authority
            === "calculated_estimate"
          || item.authority
            === "manual_override"
          || item.authority
            === "dri",
      ),
    );

  const showOnboarding =
    (
      hasLoggedNutrition
      ?? inferredHasLoggedNutrition
    ) === false;

  const showTargetsAction =
    !showOnboarding
    || !hasPersonalizedTargets;

  const targetsActionLabel =
    showOnboarding
      ? "Set up nutrition targets"
      : "Nutrition targets";

  const initialFailure =
    state.kind
      === "initial-failure"
      ? userFacingEpicOneError(
          state.error,
          {
            fallbackSummary:
              "Target comparisons are unavailable.",
          },
        )
      : null;

  return (
    <View style={styles.section}>
      <View style={styles.headingRow}>
        <Text
          accessibilityRole="header"
          style={styles.heading}
        >
          Target Progress
        </Text>

        {showTargetsAction ? (
          <AccessiblePressable
            accessibilityLabel={
              targetsActionLabel
            }
            onPress={onOpenTargets}
          >
            <Text style={styles.link}>
              {targetsActionLabel}
            </Text>
          </AccessiblePressable>
        ) : null}
      </View>

      {showOnboarding ? (
        <View
          style={styles.onboardingCopy}
        >
          <Text
            style={styles.sectionNote}
          >
            Log a food to start tracking
            your nutrition.
          </Text>

          {!hasPersonalizedTargets ? (
            <Text
              style={
                styles.sectionNote
              }
            >
              Add your information in
              Nutrition Targets for
              personalized calorie and
              nutrient targets.
            </Text>
          ) : null}
        </View>
      ) : null}

      {state.kind
        === "initial-loading" ? (
        <AccessibilityStatus
          kind="loading"
          message="Loading target comparisons…"
          messageStyle={
            styles.secondary
          }
        />
      ) : null}

      {state.kind
        === "initial-failure" ? (
        <AccessibilityStatus
          kind="initial-failure"
          message={
            initialFailure!.summary
          }
          onRetry={state.retry}
          retryContext="target progress"
          messageStyle={
            styles.secondary
          }
          actionStyle={
            styles.statusAction
          }
        />
      ) : null}

      {state.kind
        === "unavailable" ? (
        <AccessibilityStatus
          kind="unavailable"
          message="Target progress is unavailable until Daily Log entries are available."
          onRetry={state.retry}
          retryContext="target progress"
          messageStyle={
            styles.secondary
          }
          actionStyle={
            styles.statusAction
          }
        />
      ) : null}

      {state.kind === "empty" ? (
        <AccessibilityStatus
          kind="empty"
          message="No target comparisons are available for this date."
          messageStyle={
            styles.secondary
          }
        />
      ) : null}

      {state.kind
        === "refreshing" ? (
        <AccessibilityStatus
          kind="refreshing"
          message="Refreshing target comparisons…"
          messageStyle={
            styles.secondary
          }
        />
      ) : null}

      {state.kind
        === "refresh-failure" ? (
        <AccessibilityStatus
          kind="stale"
          message="Target comparisons could not be refreshed; showing the last confirmed progress."
          onRetry={state.retry}
          retryContext="target progress"
          messageStyle={
            styles.secondary
          }
          actionStyle={
            styles.statusAction
          }
        />
      ) : null}

      {state.data
        ? rowSections.map((section) => (
            <View
              key={section.id}
              style={
                styles.nutrientSection
              }
            >
              {section.label ? (
                <Text
                  accessibilityRole="header"
                  style={
                    styles.groupHeading
                  }
                >
                  {section.label}
                </Text>
              ) : null}

              {section.items.map(
                (item) => (
                  <ProgressRow
                    key={
                      item.nutrientId
                    }
                    item={item}
                    hierarchyDepth={
                      nutrientVisibleDepth(
                        item.nutrientId,
                        visibleNutrientIds,
                        canonicalNutrientParentId,
                      )
                    }
                  />
                ),
              )}
            </View>
          ))
        : null}
    </View>
  );
}

function ProgressRow({
  item,
  hierarchyDepth = 0,
}: {
  item: DailyTargetComparisonItem;
  hierarchyDepth?: number;
}) {
  const theme = useAppTheme();

  const styles = useMemo(
    () => createStyles(theme),
    [theme],
  );

  const name =
    formatNutrientLabel(
      item.nutrientId,
      NUTRIENT_CATALOG_BY_ID.get(
        item.nutrientId,
      )?.display_name,
    );

  const percentage =
    item.percentage === null
      ? null
      : formatTargetPercentage(
          item.percentage,
        );

  const consumed =
    item.consumedAmount === null
      ? "—"
      : `${
          formatTargetAmount(
            item.consumedAmount,
            item.unit,
          )
        } ${item.unit}`;

  const target =
    item.targetAmount === null
      ? null
      : `${
          formatTargetAmount(
            item.targetAmount,
            item.unit,
          )
        } ${item.unit}`;

  const over =
    percentageAtOrAbove100(
      item.percentage,
    );

  const limitAttention =
    item.direction === "limit"
    && boundedProgressValue(
      item.percentage,
    ) >= 80;

  const detail =
    target
      ? `${consumed} / ${target}`
      : consumed;

  const statusDetail =
    item.trackingMode
      === "amount_only"
      ? item.reasonCode
          === "target_reference_not_established"
        ? "No established daily goal"
        : "Total consumed only"
      : null;

  return (
    <View
      style={[
        styles.row,
        hierarchyDepth > 0
          ? {
              marginLeft:
                hierarchyDepth * 16,
            }
          : undefined,
        limitAttention
          && styles.limitAttention,
      ]}
    >
      <View
        style={styles.headingRow}
      >
        <Text
          accessible
          accessibilityLabel={
            progressAccessibilityLabel(
              item,
              name,
              statusDetail
                ?? undefined,
            )
          }
          style={styles.name}
        >
          {name}
        </Text>

        {item
          .hasUnknownContributors ? (
          <Text
            style={
              styles.incomplete
            }
          >
            Incomplete data
          </Text>
        ) : null}
      </View>

      <Text
        accessible={false}
        style={styles.value}
      >
        {detail}
      </Text>

      {percentage ? (
        <Text
          accessible={false}
          style={styles.secondary}
        >
          {percentage}
        </Text>
      ) : null}

      {statusDetail ? (
        <Text
          accessible={false}
          style={styles.secondary}
        >
          {statusDetail}
        </Text>
      ) : null}

      {item.percentage !== null ? (
        <View
          accessible={false}
          style={styles.track}
        >
          <View
            style={[
              styles.fill,
              limitAttention
                && styles.limitFill,
              {
                width: `${
                  boundedProgressValue(
                    item.percentage,
                  )
                }%`,
              },
            ]}
          />

          {over ? (
            <Text
              accessible={false}
              style={
                styles.overflow
              }
            >
              ›
            </Text>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

function createStyles(
  theme: ReturnType<
    typeof useAppTheme
  >,
) {
  return StyleSheet.create({
    fill: {
      backgroundColor:
        theme.colors.accent,
      borderRadius: 3,
      height: 6,
    },
    nutrientSection: {
      gap: 8,
    },
    groupHeading: {
      borderBottomColor:
        theme.colors.border,
      borderBottomWidth: 2,
      color: theme.colors.text,
      fontSize: 16,
      fontWeight: "800",
      letterSpacing: 0.8,
      marginTop: 14,
      paddingBottom: 6,
      textTransform: "uppercase",
    },
    heading: {
      color: theme.colors.text,
      fontSize: 18,
      fontWeight: "700",
    },
    headingRow: {
      alignItems: "center",
      flexDirection: "row",
      justifyContent:
        "space-between",
    },
    incomplete: {
      color:
        theme.colors.warningText,
      fontSize: 12,
      fontWeight: "700",
    },
    limitAttention: {
      backgroundColor:
        theme.colors
          .warningBackground,
    },
    limitFill: {
      backgroundColor:
        theme.colors.warningText,
    },
    link: {
      color: theme.colors.accent,
      fontWeight: "600",
      paddingVertical: 8,
    },
    name: {
      color: theme.colors.text,
      fontWeight: "700",
    },
    onboardingCopy: {
      gap: 3,
    },
    overflow: {
      color: theme.colors.text,
      fontSize: 16,
      fontWeight: "900",
      position: "absolute",
      right: -7,
      top: -7,
    },
    row: {
      backgroundColor:
        theme.colors.surface,
      borderColor:
        theme.colors.border,
      borderRadius: 8,
      borderWidth: 1,
      gap: 3,
      padding: 10,
    },
    secondary: {
      color:
        theme.colors.secondaryText,
      fontSize: 13,
    },
    sectionNote: {
      color:
        theme.colors.secondaryText,
      fontSize: 13,
    },
    section: {
      gap: 8,
    },
    statusAction: {
      alignSelf: "flex-start",
    },
    track: {
      backgroundColor:
        theme.colors
          .disabledBackground,
      borderRadius: 3,
      height: 6,
      marginRight: 5,
      marginTop: 3,
    },
    value: {
      color: theme.colors.text,
    },
  });
}
