import { useMemo } from "react";
import { StyleSheet, Text, View } from "react-native";

import { useAppTheme } from "../../app/theme/AppTheme";
import { AccessiblePressable } from "../../shared/accessibility/AccessiblePressable";
import { AccessibilityStatus } from "../../shared/accessibility/AccessibilityStatus";
import { userFacingEpicOneError } from "../../shared/errors/userFacingError";
import { formatNutrientLabel } from "../../shared/nutrition/display";
import type { DailyTargetComparison, DailyTargetComparisonItem } from "./api/types";
import { targetProgressReadState, useDailyTargetComparison, type TargetProgressReadState } from "./hooks/useDailyTargetComparison";
import {
  boundedProgressValue, formatTargetAmount, formatTargetPercentage,
  percentageAtOrAbove100, PRIMARY_PROGRESS_NUTRIENTS, progressAccessibilityLabel,
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

export function TargetProgressSection({ date, entriesKnown = true, hasLoggedNutrition, onOpenTargets }: { date: string; entriesKnown?: boolean; hasLoggedNutrition?: boolean; onOpenTargets: () => void }) {
  const query = useDailyTargetComparison(date);
  const readState = targetProgressReadState(query, entriesKnown);
  return <TargetProgressContent readState={readState} data={query.data} isLoading={query.isLoading} isError={query.isError} isFetching={query.isFetching} isRefetchError={query.isRefetchError} error={query.error} onRetry={readState.retry} hasLoggedNutrition={hasLoggedNutrition} onOpenTargets={onOpenTargets} />;
}

export function TargetProgressContent({ data, isLoading, isError, isFetching = false, isRefetchError = false, error, readState, entriesKnown = true, hasLoggedNutrition, onRetry, onOpenTargets }: ContentProps) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const state = readState ?? targetProgressReadState({ data, isLoading, isError, isFetching, isRefetchError, error, refetch: onRetry }, entriesKnown);
  const byId = new Map((state.data?.comparisons ?? []).map((item) => [item.nutrientId, item]));
  const rows = PRIMARY_PROGRESS_NUTRIENTS.map((id) => byId.get(id)).filter((item): item is DailyTargetComparisonItem => Boolean(item));
  const inferredHasLoggedNutrition = state.data
    ? rows.some((item) => item.consumedAmount !== null || item.hasUnknownContributors)
    : undefined;
  const showOnboarding = (hasLoggedNutrition ?? inferredHasLoggedNutrition) === false;
  const targetsActionLabel = showOnboarding ? "Set up nutrition targets" : "Nutrition targets";
  const initialFailure = state.kind === "initial-failure"
    ? userFacingEpicOneError(state.error, { fallbackSummary: "Target comparisons are unavailable." })
    : null;
  return <View style={styles.section}>
    <View style={styles.headingRow}>
      <Text accessibilityRole="header" style={styles.heading}>Target Progress</Text>
      <AccessiblePressable accessibilityLabel={targetsActionLabel} onPress={onOpenTargets}><Text style={styles.link}>{targetsActionLabel}</Text></AccessiblePressable>
    </View>
    {showOnboarding ? <View style={styles.onboardingCopy}>
      <Text style={styles.sectionNote}>Log a food to start tracking your nutrition.</Text>
      <Text accessibilityLabel="FDA Daily Values provide general reference targets where available." style={styles.sectionNote}>FDA Daily Values provide general reference targets where available.</Text>
      <Text style={styles.sectionNote}>Add your information in Nutrition Targets for personalized calorie and macro targets.</Text>
    </View> : <Text accessibilityLabel="Reference targets use FDA Daily Values where available until you set personal targets." style={styles.sectionNote}>Reference targets use FDA Daily Values where available until you set personal targets.</Text>}
    {state.kind === "initial-loading" ? <AccessibilityStatus kind="loading" message="Loading target comparisons…" messageStyle={styles.secondary} /> : null}
    {state.kind === "initial-failure" ? <AccessibilityStatus kind="initial-failure" message={initialFailure!.summary} onRetry={state.retry} retryContext="target progress" messageStyle={styles.secondary} actionStyle={styles.statusAction} /> : null}
    {state.kind === "unavailable" ? <AccessibilityStatus kind="unavailable" message="Target progress is unavailable until Daily Log entries are available." onRetry={state.retry} retryContext="target progress" messageStyle={styles.secondary} actionStyle={styles.statusAction} /> : null}
    {state.kind === "empty" ? <AccessibilityStatus kind="empty" message="No target comparisons are available for this date." messageStyle={styles.secondary} /> : null}
    {state.kind === "refreshing" ? <AccessibilityStatus kind="refreshing" message="Refreshing target comparisons…" messageStyle={styles.secondary} /> : null}
    {state.kind === "refresh-failure" ? <AccessibilityStatus kind="stale" message="Target comparisons could not be refreshed; showing the last confirmed progress." onRetry={state.retry} retryContext="target progress" messageStyle={styles.secondary} actionStyle={styles.statusAction} /> : null}
    {state.data ? rows.map((item) => <ProgressRow key={item.nutrientId} item={item} />) : null}
  </View>;
}

function ProgressRow({ item }: { item: DailyTargetComparisonItem }) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const name = formatNutrientLabel(item.nutrientId);
  const percentage = item.percentage === null ? null : formatTargetPercentage(item.percentage);
  const consumed = item.consumedAmount === null ? "—" : `${formatTargetAmount(item.consumedAmount, item.unit)} ${item.unit}`;
  const target = item.targetAmount === null ? null : `${formatTargetAmount(item.targetAmount, item.unit)} ${item.unit}`;
  const over = percentageAtOrAbove100(item.percentage);
  const limitAttention = item.direction === "limit" && boundedProgressValue(item.percentage) >= 80;
  const detail = target ? `${consumed} / ${target}` : consumed;
  return <View style={[styles.row, limitAttention && styles.limitAttention]}>
    <View style={styles.headingRow}><Text accessible accessibilityLabel={progressAccessibilityLabel(item, name)} style={styles.name}>{name}</Text>{item.hasUnknownContributors ? <Text style={styles.incomplete}>Incomplete data</Text> : null}</View>
    <Text accessible={false} style={styles.value}>{detail}</Text>
    {percentage ? <Text accessible={false} style={styles.secondary}>{percentage}</Text> : null}
    {item.percentage !== null ? <View accessible={false} style={styles.track}><View style={[styles.fill, limitAttention && styles.limitFill, { width: `${boundedProgressValue(item.percentage)}%` }]} />{over ? <Text accessible={false} style={styles.overflow}>›</Text> : null}</View> : null}
  </View>;
}

function createStyles(theme: ReturnType<typeof useAppTheme>) { return StyleSheet.create({
  fill: { backgroundColor: theme.colors.accent, borderRadius: 3, height: 6 },
  heading: { color: theme.colors.text, fontSize: 18, fontWeight: "700" },
  headingRow: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" },
  incomplete: { color: theme.colors.warningText, fontSize: 12, fontWeight: "700" },
  limitAttention: { backgroundColor: theme.colors.warningBackground },
  limitFill: { backgroundColor: theme.colors.warningText },
  link: { color: theme.colors.accent, fontWeight: "600", paddingVertical: 8 },
  name: { color: theme.colors.text, fontWeight: "700" },
  onboardingCopy: { gap: 3 },
  overflow: { color: theme.colors.text, fontSize: 16, fontWeight: "900", position: "absolute", right: -7, top: -7 },
  row: { backgroundColor: theme.colors.surface, borderColor: theme.colors.border, borderRadius: 8, borderWidth: 1, gap: 3, padding: 10 },
  secondary: { color: theme.colors.secondaryText, fontSize: 13 },
  sectionNote: { color: theme.colors.secondaryText, fontSize: 13 },
  section: { gap: 8 },
  statusAction: { alignSelf: "flex-start" },
  track: { backgroundColor: theme.colors.disabledBackground, borderRadius: 3, height: 6, marginRight: 5, marginTop: 3 },
  value: { color: theme.colors.text },
}); }
