import { useMemo, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { useAppTheme } from "../../app/theme/AppTheme";
import { formatNutrientLabel } from "../../shared/nutrition/display";
import type { DailyTargetComparison, DailyTargetComparisonItem } from "./api/types";
import { useDailyTargetComparison } from "./hooks/useDailyTargetComparison";
import {
  boundedProgressValue, formatTargetAmount, formatTargetPercentage,
  percentageAtOrAbove100, PRIMARY_PROGRESS_NUTRIENTS, progressAccessibilityLabel,
  targetAuthorityLabel, targetDirectionLabel,
} from "./targetProgress";

type ContentProps = {
  data?: DailyTargetComparison;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  onOpenTargets: () => void;
};

export function TargetProgressSection({ date, onOpenTargets }: { date: string; onOpenTargets: () => void }) {
  const query = useDailyTargetComparison(date);
  return <TargetProgressContent data={query.data} isLoading={query.isLoading} isError={query.isError} onRetry={() => { void query.refetch(); }} onOpenTargets={onOpenTargets} />;
}

export function TargetProgressContent({ data, isLoading, isError, onRetry, onOpenTargets }: ContentProps) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const byId = new Map((data?.comparisons ?? []).map((item) => [item.nutrientId, item]));
  const rows = PRIMARY_PROGRESS_NUTRIENTS.map((id) => byId.get(id)).filter((item): item is DailyTargetComparisonItem => Boolean(item));
  return <View style={styles.section}>
    <View style={styles.headingRow}>
      <Text accessibilityRole="header" style={styles.heading}>Daily progress</Text>
      <Pressable accessibilityRole="button" accessibilityLabel="Open Nutrition targets settings" onPress={onOpenTargets}><Text style={styles.link}>Nutrition targets</Text></Pressable>
    </View>
    {isLoading && !data ? <Text accessibilityLiveRegion="polite" style={styles.secondary}>Loading target comparisons…</Text> : null}
    {isError ? <View style={styles.errorRow}><Text accessibilityRole="alert" style={styles.secondary}>Target comparisons are unavailable.</Text><Pressable accessibilityRole="button" accessibilityLabel="Retry target comparisons" onPress={onRetry}><Text style={styles.link}>Retry</Text></Pressable></View> : null}
    {rows.map((item) => <ProgressRow key={item.nutrientId} item={item} />)}
  </View>;
}

function ProgressRow({ item }: { item: DailyTargetComparisonItem }) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const [noteOpen, setNoteOpen] = useState(false);
  const name = formatNutrientLabel(item.nutrientId);
  const percentage = item.percentage === null ? null : formatTargetPercentage(item.percentage);
  const consumed = item.consumedAmount === null ? "Amount unavailable" : `${formatTargetAmount(item.consumedAmount, item.unit)} ${item.unit}`;
  const target = item.targetAmount === null ? null : `${formatTargetAmount(item.targetAmount, item.unit)} ${item.unit}`;
  const over = percentageAtOrAbove100(item.percentage);
  const limitAttention = item.direction === "limit" && boundedProgressValue(item.percentage) >= 80;
  const detail = target ? `${consumed} / ${target}` : consumed;
  const interpretation = item.direction === "unavailable" ? "No comparison target" : `${percentage ?? "Percentage unavailable"} · ${targetAuthorityLabel(item.authority)}`;
  return <View style={[styles.row, limitAttention && styles.limitAttention]}>
    <View style={styles.headingRow}><Text accessible accessibilityLabel={progressAccessibilityLabel(item, name)} style={styles.name}>{name}</Text>{item.hasUnknownContributors ? <Text style={styles.incomplete}>Incomplete data</Text> : null}</View>
    <Text accessible={false} style={styles.value}>{detail}</Text>
    <Text accessible={false} style={styles.secondary}>{interpretation}</Text>
    <Text accessible={false} style={styles.direction}>{targetDirectionLabel(item.direction)}{over && item.percentage !== null ? ` · ${percentage}` : ""}</Text>
    {item.percentage !== null ? <View accessibilityRole="progressbar" accessibilityValue={{ min: 0, max: 100, now: boundedProgressValue(item.percentage), text: `${percentage}, ${targetDirectionLabel(item.direction)}` }} style={styles.track}><View style={[styles.fill, limitAttention && styles.limitFill, { width: `${boundedProgressValue(item.percentage)}%` }]} />{over ? <Text accessible={false} style={styles.overflow}>›</Text> : null}</View> : null}
    {item.noteCode === "protein_percent_dv_labeling_caveat" ? <><Pressable accessibilityRole="button" accessibilityLabel={noteOpen ? "Hide protein Daily Value information" : "Explain protein Daily Value"} onPress={() => setNoteOpen((value) => !value)}><Text style={styles.noteLink}>{noteOpen ? "Hide info" : "Why this reference?"}</Text></Pressable>{noteOpen ? <Text style={styles.secondary}>Protein % Daily Value is generally not required on adult labels unless specific labeling conditions apply.</Text> : null}</> : null}
  </View>;
}

function createStyles(theme: ReturnType<typeof useAppTheme>) { return StyleSheet.create({
  direction: { color: theme.colors.mutedText, fontSize: 12 },
  errorRow: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" },
  fill: { backgroundColor: theme.colors.accent, borderRadius: 3, height: 6 },
  heading: { color: theme.colors.text, fontSize: 18, fontWeight: "700" },
  headingRow: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" },
  incomplete: { color: theme.colors.warningText, fontSize: 12, fontWeight: "700" },
  limitAttention: { backgroundColor: theme.colors.warningBackground },
  limitFill: { backgroundColor: theme.colors.warningText },
  link: { color: theme.colors.accent, fontWeight: "600", paddingVertical: 8 },
  name: { color: theme.colors.text, fontWeight: "700" },
  noteLink: { color: theme.colors.accent, fontSize: 13, fontWeight: "600", paddingVertical: 4 },
  overflow: { color: theme.colors.text, fontSize: 16, fontWeight: "900", position: "absolute", right: -7, top: -7 },
  row: { backgroundColor: theme.colors.surface, borderColor: theme.colors.border, borderRadius: 8, borderWidth: 1, gap: 3, padding: 10 },
  secondary: { color: theme.colors.secondaryText, fontSize: 13 },
  section: { gap: 8 },
  track: { backgroundColor: theme.colors.disabledBackground, borderRadius: 3, height: 6, marginRight: 5, marginTop: 3 },
  value: { color: theme.colors.text },
}); }
