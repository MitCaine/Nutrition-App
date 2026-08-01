import { useEffect, useMemo, useRef, type ReactNode } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { useAppTheme } from "../../../app/theme/AppTheme";
import { RootScreenHeader } from "../../../shared/components/RootScreenHeader";
import type { Food, RecentFood } from "../../foods/api/types";
import { useFavoriteFoods, useRecentFoods, useSavedFoods } from "../../foods/hooks/useFoods";
import { foodAccessibilityLabel, formatRecentUse } from "../../foods/utils/foodDiscovery";
import { useDailyLogs, dailyLogReadState } from "../hooks/useLogs";
import type { AddFoodFlowState } from "../utils/addFoodFlow";

type Props = {
  flow: AddFoodFlowState;
  mutationEnabled: boolean;
  onCancel: () => void;
  onOpenSettings: () => void;
  onSelectFood: (foodId: string) => void;
  onScrollSessionChange: (query: string, offset: number) => void;
};

export type DiscoveryReadState<T> =
  | { kind: "initial-loading"; data: null; retry: () => void }
  | { kind: "initial-failure"; data: null; error: unknown; retry: () => void }
  | { kind: "empty"; data: T[]; retry: () => void }
  | { kind: "success"; data: T[]; retry: () => void }
  | { kind: "refreshing"; data: T[]; retry: () => void }
  | { kind: "refresh-failure"; data: T[]; error: unknown; retry: () => void };

/** Translate one discovery query without coupling it to the other sections. */
export function discoveryReadState<T>(query: {
  data?: T[];
  error?: unknown;
  isError: boolean;
  isFetching: boolean;
  isLoading: boolean;
  isRefetchError?: boolean;
  refetch: () => unknown;
}): DiscoveryReadState<T> {
  const retry = () => { void query.refetch(); };
  if (!query.data && query.isError) {
    return { kind: "initial-failure", data: null, error: query.error, retry };
  }
  if (!query.data) {
    return { kind: "initial-loading", data: null, retry };
  }
  if (query.isRefetchError || (query.isError && !query.isLoading)) {
    return { kind: "refresh-failure", data: query.data, error: query.error, retry };
  }
  if (query.isFetching) {
    return { kind: "refreshing", data: query.data, retry };
  }
  if (query.data.length === 0) {
    return { kind: "empty", data: [], retry };
  }
  return { kind: "success", data: query.data, retry };
}

export function AddFoodScreen({ flow, mutationEnabled, onCancel, onOpenSettings, onSelectFood, onScrollSessionChange }: Props) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const resultsRef = useRef<ScrollView>(null);
  const restoredRef = useRef(false);
  const entries = dailyLogReadState(useDailyLogs(flow.originatingDate));
  const favorites = discoveryReadState(useFavoriteFoods());
  const recent = discoveryReadState(useRecentFoods());
  const saved = discoveryReadState(useSavedFoods(""));

  useEffect(() => {
    restoredRef.current = false;
  }, [flow.query]);

  const entriesUnavailable = entries.kind === "initial-failure" || entries.kind === "refresh-failure";
  return (
    <View style={styles.screen}>
      <RootScreenHeader title="Add Food" onOpenSettings={onOpenSettings} />
      <View style={styles.headerRow}>
        <Text style={styles.origin}>Logging for {flow.originatingDate}</Text>
        <Pressable accessibilityRole="button" accessibilityLabel="Cancel Add Food" onPress={onCancel}>
          <Text style={styles.link}>Cancel</Text>
        </Pressable>
      </View>
      <Text style={styles.secondary}>{flow.initialMeal ? `Initial meal: ${flow.initialMeal}` : "No meal selected"}</Text>
      {!mutationEnabled ? (
        <Text accessibilityRole="alert" style={styles.warning}>
          Add Food is unavailable because this date is not mutation-eligible.
        </Text>
      ) : null}
      {entriesUnavailable ? (
        <Text accessibilityRole="alert" style={styles.warning}>
          Existing entries could not be reviewed. Duplicate logging is possible.
        </Text>
      ) : null}
      <ScrollView
        ref={resultsRef}
        contentContainerStyle={styles.results}
        onScroll={(event) => onScrollSessionChange(flow.query, event.nativeEvent.contentOffset.y)}
        onContentSizeChange={() => {
          if (!restoredRef.current) {
            resultsRef.current?.scrollTo({ y: flow.scrollOffset, animated: false });
            restoredRef.current = true;
          }
        }}
        scrollEventThrottle={100}
      >
        <View style={styles.section}>
          <Text accessibilityRole="header" style={styles.sectionTitle}>Recent Entries</Text>
          <Text style={styles.secondary}>Recent Entries are unavailable until recent-entry history is available.</Text>
        </View>
        <FoodSection
          title="Favorites"
          state={favorites}
          mutationEnabled={mutationEnabled}
          onSelectFood={onSelectFood}
          emptyMessage="No favorite foods yet."
          retryLabel="Retry favorites"
          renderItem={(food) => (
            <Text style={styles.foodMeta}>{food.source_label} · Favorite</Text>
          )}
        />
        <FoodSection
          title="Recent Foods"
          state={recent}
          mutationEnabled={mutationEnabled}
          onSelectFood={onSelectFood}
          emptyMessage="No recently used foods."
          retryLabel="Retry recent foods"
          renderItem={(item) => (
            <Text style={styles.foodMeta}>{item.food.source_label} · {formatRecentUse(item.last_used_at)}</Text>
          )}
          getFood={(item) => item.food}
        />
        <FoodSection
          title="Saved Foods"
          state={saved}
          mutationEnabled={mutationEnabled}
          onSelectFood={onSelectFood}
          emptyMessage="No saved foods yet."
          retryLabel="Retry saved foods"
          renderItem={(food) => (
            <Text style={styles.foodMeta}>{food.brand ? `${food.brand} · ${food.source_label}` : food.source_label}</Text>
          )}
        />
      </ScrollView>
    </View>
  );
}

function FoodSection<T extends Food | RecentFood>({
  title,
  state,
  mutationEnabled,
  onSelectFood,
  emptyMessage,
  retryLabel,
  renderItem,
  getFood = (item) => item as Food,
}: {
  title: string;
  state: DiscoveryReadState<T>;
  mutationEnabled: boolean;
  onSelectFood: (foodId: string) => void;
  emptyMessage: string;
  retryLabel: string;
  renderItem: (item: T) => ReactNode;
  getFood?: (item: T) => Food;
}) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  return (
    <View style={styles.section}>
      <Text accessibilityRole="header" style={styles.sectionTitle}>{title}</Text>
      {state.kind === "initial-loading" ? <Text accessibilityLiveRegion="polite" style={styles.secondary}>Loading {title.toLowerCase()}…</Text> : null}
      {state.kind === "initial-failure" ? <ReadError message={`${title} are unavailable.`} retryLabel={retryLabel} onRetry={state.retry} styles={styles} /> : null}
      {state.kind === "refreshing" ? <Text accessibilityLiveRegion="polite" style={styles.secondary}>Refreshing {title.toLowerCase()}…</Text> : null}
      {state.kind === "refresh-failure" ? <ReadError message={`${title} could not be refreshed; showing the last confirmed results.`} retryLabel={retryLabel} onRetry={state.retry} styles={styles} /> : null}
      {state.kind === "empty" ? <Text style={styles.secondary}>{emptyMessage}</Text> : null}
      {state.data?.map((item) => {
        const food = getFood(item);
        return (
          <Pressable
            key={food.id}
            accessibilityRole="button"
            accessibilityLabel={foodAccessibilityLabel(food)}
            disabled={!mutationEnabled}
            onPress={() => {
              if (mutationEnabled) {
                onSelectFood(food.id);
              }
            }}
            style={[styles.foodRow, !mutationEnabled && styles.disabled]}
          >
            <Text style={styles.foodName}>{food.name}</Text>
            {renderItem(item)}
          </Pressable>
        );
      })}
    </View>
  );
}

function ReadError({ message, retryLabel, onRetry, styles }: { message: string; retryLabel: string; onRetry: () => void; styles: ReturnType<typeof createStyles> }) {
  return (
    <View style={styles.errorRow}>
      <Text accessibilityRole="alert" style={styles.error}>{message}</Text>
      <Pressable accessibilityRole="button" accessibilityLabel={retryLabel} onPress={onRetry}><Text style={styles.link}>Retry</Text></Pressable>
    </View>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) { return StyleSheet.create({
  disabled: { opacity: 0.5 },
  error: { color: theme.colors.errorText },
  errorRow: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" },
  foodMeta: { color: theme.colors.secondaryText },
  foodName: { color: theme.colors.text, fontSize: 16, fontWeight: "600" },
  foodRow: { borderBottomColor: theme.colors.listDivider, borderBottomWidth: 1, gap: 4, paddingVertical: 14 },
  headerRow: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" },
  link: { color: theme.colors.accent, fontWeight: "700", padding: 8 },
  origin: { color: theme.colors.secondaryText },
  results: { gap: 18, paddingBottom: 32 },
  screen: { backgroundColor: theme.colors.background, flex: 1, gap: 12, padding: 16 },
  secondary: { color: theme.colors.secondaryText },
  section: { gap: 6 },
  sectionTitle: { color: theme.colors.text, fontSize: 18, fontWeight: "700" },
  warning: { backgroundColor: theme.colors.warningBackground, color: theme.colors.warningText, padding: 10 },
}); }
