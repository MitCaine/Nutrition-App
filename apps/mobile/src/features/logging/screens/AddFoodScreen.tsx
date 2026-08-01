import { useEffect, useMemo, useRef, type ReactNode } from "react";
import { Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import { useAppTheme } from "../../../app/theme/AppTheme";
import { RootScreenHeader } from "../../../shared/components/RootScreenHeader";
import type { Food, RecentFood } from "../../foods/api/types";
import { useFavoriteFoods, useRecentFoods, useSavedFoods } from "../../foods/hooks/useFoods";
import { useDebouncedSearchQuery } from "../../foods/hooks/useDebouncedSearchQuery";
import { foodAccessibilityLabel, formatRecentUse } from "../../foods/utils/foodDiscovery";
import { useUsdaSearch } from "../../usda/hooks/useUsda";
import { formatUsdaNutrientPreview, usdaResultMeta } from "../../usda/utils/usdaDisplay";
import type { UsdaSearchResponse } from "../../usda/api/types";
import { useDailyLogs, useRecentEntries, dailyLogReadState } from "../hooks/useLogs";
import type { RecentEntry } from "../api/types";
import type { AddFoodFlowState } from "../utils/addFoodFlow";

type Props = {
  flow: AddFoodFlowState;
  mutationEnabled: boolean;
  onCancel: () => void;
  onOpenSettings: () => void;
  onSelectFood: (foodId: string) => void;
  onRepeatRecentEntry?: (entry: RecentEntry) => void;
  onSelectUsdaFood?: (fdcId: number) => void;
  /** Opens the existing reusable custom-food creation flow. */
  onCreateCustomFood?: () => void;
  /** Opens the existing supported label-scanning flow. */
  onScanNutritionLabel?: () => void;
  onQueryChange?: (query: string) => void;
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
  if (!query.data && query.isError) return { kind: "initial-failure", data: null, error: query.error, retry };
  if (!query.data) return { kind: "initial-loading", data: null, retry };
  if (query.isRefetchError || (query.isError && !query.isLoading)) return { kind: "refresh-failure", data: query.data, error: query.error, retry };
  if (query.isFetching) return { kind: "refreshing", data: query.data, retry };
  if (query.data.length === 0) return { kind: "empty", data: [], retry };
  return { kind: "success", data: query.data, retry };
}

export type UsdaDiscoveryReadState =
  | { kind: "prompt"; retry: () => void }
  | { kind: "searching"; retry: () => void }
  | { kind: "initial-failure"; error: unknown; retry: () => void }
  | { kind: "empty"; data: UsdaSearchResponse; retry: () => void }
  | { kind: "success"; data: UsdaSearchResponse; retry: () => void }
  | { kind: "refreshing"; data: UsdaSearchResponse; retry: () => void }
  | { kind: "refresh-failure"; data: UsdaSearchResponse; error: unknown; retry: () => void };

/** Translate USDA query flags while keeping USDA independent from Saved Foods. */
export function usdaDiscoveryReadState(
  query: string,
  searchQuery: string,
  result: {
    data?: UsdaSearchResponse;
    error?: unknown;
    isError: boolean;
    isFetching: boolean;
    isLoading: boolean;
    isRefetchError?: boolean;
    refetch: () => unknown;
  },
): UsdaDiscoveryReadState {
  const retry = () => { void result.refetch(); };
  if (query.trim().length < 2) return { kind: "prompt", retry };
  if (query.trim() !== searchQuery) return { kind: "searching", retry };
  if (!result.data && result.isError) return { kind: "initial-failure", error: result.error, retry };
  if (!result.data || result.isLoading) return { kind: "searching", retry };
  if (result.isRefetchError || (result.isError && !result.isLoading)) return { kind: "refresh-failure", data: result.data, error: result.error, retry };
  if (result.isFetching) return { kind: "refreshing", data: result.data, retry };
  if (result.data.foods.length === 0) return { kind: "empty", data: result.data, retry };
  return { kind: "success", data: result.data, retry };
}

export function AddFoodScreen({ flow, mutationEnabled, onCancel, onOpenSettings, onSelectFood, onRepeatRecentEntry, onSelectUsdaFood, onCreateCustomFood, onScanNutritionLabel, onQueryChange, onScrollSessionChange }: Props) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const resultsRef = useRef<ScrollView>(null);
  const restoredRef = useRef(false);
  const entries = dailyLogReadState(useDailyLogs(flow.originatingDate));
  const recentEntries = discoveryReadState(useRecentEntries());
  const favorites = discoveryReadState(useFavoriteFoods());
  const recent = discoveryReadState(useRecentFoods());
  const searchQuery = useDebouncedSearchQuery(flow.query);
  const searchMode = flow.query.trim().length > 0;
  // Browse mode must not keep a live search request (especially USDA) mounted
  // while a prior debounced query is settling after the user clears input.
  const activeSearchQuery = searchMode ? searchQuery : "";
  const saved = discoveryReadState(useSavedFoods(activeSearchQuery));
  const usda = usdaDiscoveryReadState(flow.query, activeSearchQuery, useUsdaSearch(activeSearchQuery));
  const activeOffset = searchMode ? flow.searchScrollOffset : flow.browseScrollOffset;

  useEffect(() => {
    restoredRef.current = false;
  }, [flow.query, searchMode]);

  const entriesUnavailable = entries.kind === "initial-failure" || entries.kind === "refresh-failure";
  return (
    <View style={styles.screen}>
      <RootScreenHeader title="Add Food" onOpenSettings={onOpenSettings} />
      <View style={styles.headerRow}>
        <Text style={styles.origin}>Logging for {flow.originatingDate}</Text>
        <Pressable accessibilityRole="button" accessibilityLabel="Cancel Add Food" onPress={onCancel}><Text style={styles.link}>Cancel</Text></Pressable>
      </View>
      <Text style={styles.secondary}>{flow.initialMeal ? `Initial meal: ${flow.initialMeal}` : "No meal selected"}</Text>
      {!mutationEnabled ? <Text accessibilityRole="alert" style={styles.warning}>Add Food is unavailable because this date is not mutation-eligible.</Text> : null}
      {entriesUnavailable ? <Text accessibilityRole="alert" style={styles.warning}>Existing entries could not be reviewed. Duplicate logging is possible.</Text> : null}
      <TextInput
        accessibilityLabel="Search foods"
        autoCapitalize="none"
        onChangeText={(query) => onQueryChange?.(query)}
        placeholder="Search saved and USDA foods"
        placeholderTextColor={theme.colors.placeholder}
        returnKeyType="search"
        style={styles.search}
        value={flow.query}
      />
      {onCreateCustomFood || (Platform.OS === "ios" && onScanNutritionLabel) ? (
        <View accessibilityRole="toolbar" style={styles.acquisitionActions}>
          {onCreateCustomFood ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Add custom food"
              accessibilityHint="Opens the custom food form"
              accessibilityState={{ disabled: !mutationEnabled }}
              disabled={!mutationEnabled}
              onPress={() => { if (mutationEnabled) onCreateCustomFood(); }}
              style={[styles.actionButton, !mutationEnabled && styles.disabled]}
            >
              <Text style={styles.actionText}>Custom Food</Text>
            </Pressable>
          ) : null}
          {Platform.OS === "ios" && onScanNutritionLabel ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Scan nutrition label"
              accessibilityHint="Opens label scanning"
              accessibilityState={{ disabled: !mutationEnabled }}
              disabled={!mutationEnabled}
              onPress={() => { if (mutationEnabled) onScanNutritionLabel(); }}
              style={[styles.actionButton, !mutationEnabled && styles.disabled]}
            >
              <Text style={styles.actionText}>Scan label</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}
      <ScrollView
        key={searchMode ? "search" : "browse"}
        ref={resultsRef}
        contentContainerStyle={styles.results}
        onScroll={(event) => onScrollSessionChange(flow.query, event.nativeEvent.contentOffset.y)}
        onContentSizeChange={() => {
          if (!restoredRef.current) {
            resultsRef.current?.scrollTo({ y: activeOffset, animated: false });
            restoredRef.current = true;
          }
        }}
        scrollEventThrottle={100}
      >
        {searchMode ? (
          <SearchContent
            query={flow.query}
            searchQuery={searchQuery}
            saved={saved}
            usda={usda}
            mutationEnabled={mutationEnabled}
            onSelectFood={onSelectFood}
            onSelectUsdaFood={onSelectUsdaFood ?? (() => undefined)}
            styles={styles}
          />
        ) : (
          <BrowseContent
            recentEntries={recentEntries}
            favorites={favorites}
            recent={recent}
            saved={saved}
            mutationEnabled={mutationEnabled}
            onSelectFood={onSelectFood}
            onRepeatRecentEntry={onRepeatRecentEntry}
            styles={styles}
          />
        )}
      </ScrollView>
    </View>
  );
}

function BrowseContent({ recentEntries, favorites, recent, saved, mutationEnabled, onSelectFood, onRepeatRecentEntry, styles }: {
  recentEntries: DiscoveryReadState<RecentEntry>;
  favorites: DiscoveryReadState<Food>;
  recent: DiscoveryReadState<RecentFood>;
  saved: DiscoveryReadState<Food>;
  mutationEnabled: boolean;
  onSelectFood: (foodId: string) => void;
  onRepeatRecentEntry?: (entry: RecentEntry) => void;
  styles: ReturnType<typeof createStyles>;
}) {
  return (
    <>
      <RecentEntriesSection state={recentEntries} mutationEnabled={mutationEnabled} onRepeat={onRepeatRecentEntry} styles={styles} />
      <FoodSection title="Favorites" state={favorites} mutationEnabled={mutationEnabled} onSelectFood={onSelectFood} emptyMessage="No favorite foods yet." retryLabel="Retry favorites" renderItem={(food) => <Text style={styles.foodMeta}>{food.source_label} · Favorite</Text>} />
      <FoodSection title="Recent Foods" state={recent} mutationEnabled={mutationEnabled} onSelectFood={onSelectFood} emptyMessage="No recently used foods." retryLabel="Retry recent foods" renderItem={(item) => <Text style={styles.foodMeta}>{item.food.source_label} · {formatRecentUse(item.last_used_at)}</Text>} getFood={(item) => item.food} />
      <FoodSection title="Saved Foods" state={saved} mutationEnabled={mutationEnabled} onSelectFood={onSelectFood} emptyMessage="No saved foods yet." retryLabel="Retry saved foods" renderItem={(food) => <Text style={styles.foodMeta}>{food.brand ? `${food.brand} · ${food.source_label}` : food.source_label}</Text>} />
    </>
  );
}

function RecentEntriesSection({ state, mutationEnabled, onRepeat, styles }: {
  state: DiscoveryReadState<RecentEntry>;
  mutationEnabled: boolean;
  onRepeat?: (entry: RecentEntry) => void;
  styles: ReturnType<typeof createStyles>;
}) {
  return (
    <View style={styles.section}>
      <Text accessibilityRole="header" style={styles.sectionTitle}>Recent Entries</Text>
      {state.kind === "initial-loading" ? <Text accessibilityLiveRegion="polite" style={styles.secondary}>Loading recent entries…</Text> : null}
      {state.kind === "initial-failure" ? <ReadError message="Recent Entries are unavailable." retryLabel="Retry recent entries" onRetry={state.retry} styles={styles} /> : null}
      {state.kind === "refreshing" ? <Text accessibilityLiveRegion="polite" style={styles.secondary}>Refreshing recent entries…</Text> : null}
      {state.kind === "refresh-failure" ? <ReadError message="Recent Entries could not be refreshed; showing the last confirmed entries." retryLabel="Retry recent entries" onRetry={state.retry} styles={styles} /> : null}
      {state.kind === "empty" ? <Text style={styles.secondary}>No recent entries yet.</Text> : null}
      {state.data?.map((entry) => (
        <Pressable
          key={entry.id}
          accessibilityRole="button"
          accessibilityLabel={`Repeat ${entry.food_name_snapshot ?? "Food"}`}
          accessibilityState={{ disabled: !mutationEnabled || !onRepeat }}
          disabled={!mutationEnabled || !onRepeat}
          onPress={() => { if (mutationEnabled) onRepeat?.(entry); }}
          style={[styles.foodRow, (!mutationEnabled || !onRepeat) && styles.disabled]}
        >
          <Text style={styles.foodName}>{entry.food_name_snapshot ?? "Food"}</Text>
          <Text style={styles.foodMeta}>
            {entry.logged_date} · {entry.amount_quantity} {entry.amount_unit}
            {entry.meal_type ? ` · ${entry.meal_type}` : ""}
            {entry.note_present ? " · Note" : ""}
          </Text>
          <Text style={styles.link}>Repeat</Text>
        </Pressable>
      ))}
    </View>
  );
}

function SearchContent({ query, searchQuery, saved, usda, mutationEnabled, onSelectFood, onSelectUsdaFood, styles }: {
  query: string;
  searchQuery: string;
  saved: DiscoveryReadState<Food>;
  usda: UsdaDiscoveryReadState;
  mutationEnabled: boolean;
  onSelectFood: (foodId: string) => void;
  onSelectUsdaFood: (fdcId: number) => void;
  styles: ReturnType<typeof createStyles>;
}) {
  if (query.trim() !== searchQuery) return <Text style={styles.secondary}>Searching foods…</Text>;
  return (
    <>
      <FoodSection title="Saved Foods" state={saved} mutationEnabled={mutationEnabled} onSelectFood={onSelectFood} emptyMessage="No saved foods found." retryLabel="Retry saved foods" renderItem={(food) => <Text style={styles.foodMeta}>{food.brand ? `${food.brand} · ${food.source_label}` : food.source_label}</Text>} />
      <UsdaSearchSection state={usda} mutationEnabled={mutationEnabled} onSelectFood={onSelectUsdaFood} styles={styles} />
    </>
  );
}

function UsdaSearchSection({ state, mutationEnabled, onSelectFood, styles }: { state: UsdaDiscoveryReadState; mutationEnabled: boolean; onSelectFood: (fdcId: number) => void; styles: ReturnType<typeof createStyles> }) {
  return (
    <View style={styles.section}>
      <Text accessibilityRole="header" style={styles.sectionTitle}>USDA Results</Text>
      {state.kind === "prompt" ? <Text style={styles.secondary}>Search USDA foods by name, brand, or ingredient.</Text> : null}
      {state.kind === "searching" ? <Text style={styles.secondary}>Searching USDA foods…</Text> : null}
      {state.kind === "initial-failure" ? <ReadError message="USDA search is unavailable right now." retryLabel="Retry USDA search" onRetry={state.retry} styles={styles} /> : null}
      {state.kind === "empty" ? <Text style={styles.secondary}>No USDA foods found. Try a different search.</Text> : null}
      {state.kind === "refreshing" ? <Text style={styles.secondary}>Refreshing USDA foods…</Text> : null}
      {state.kind === "refresh-failure" ? <ReadError message="USDA search could not be refreshed; showing the last confirmed results." retryLabel="Retry USDA search" onRetry={state.retry} styles={styles} /> : null}
      {state.kind !== "prompt" && state.kind !== "searching" && state.kind !== "initial-failure" && state.kind !== "empty" ? state.data.foods.map((food) => (
        <Pressable key={food.fdc_id} accessibilityRole="button" accessibilityLabel={`USDA Food ${food.fdc_id}`} disabled={!mutationEnabled || !food.importable} onPress={() => { if (mutationEnabled && food.importable) onSelectFood(food.fdc_id); }} style={[styles.foodRow, (!mutationEnabled || !food.importable) && styles.disabled]}>
          <Text style={styles.foodName}>{food.description}</Text>
          <Text style={styles.foodMeta}>{usdaResultMeta(food)}</Text>
          {food.food_category ? <Text style={styles.foodMeta}>{food.food_category}</Text> : null}
          {formatUsdaNutrientPreview(food.nutrient_preview) ? <Text style={styles.foodMeta}>{formatUsdaNutrientPreview(food.nutrient_preview)}</Text> : null}
        </Pressable>
      )) : null}
    </View>
  );
}

function FoodSection<T extends Food | RecentFood>({ title, state, mutationEnabled, onSelectFood, emptyMessage, retryLabel, renderItem, getFood = (item) => item as Food }: {
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
        return <Pressable key={food.id} accessibilityRole="button" accessibilityLabel={foodAccessibilityLabel(food)} disabled={!mutationEnabled} onPress={() => { if (mutationEnabled) onSelectFood(food.id); }} style={[styles.foodRow, !mutationEnabled && styles.disabled]}><Text style={styles.foodName}>{food.name}</Text>{renderItem(item)}</Pressable>;
      })}
    </View>
  );
}

function ReadError({ message, retryLabel, onRetry, styles }: { message: string; retryLabel: string; onRetry: () => void; styles: ReturnType<typeof createStyles> }) {
  return <View style={styles.errorRow}><Text accessibilityRole="alert" style={styles.error}>{message}</Text><Pressable accessibilityRole="button" accessibilityLabel={retryLabel} onPress={onRetry}><Text style={styles.link}>Retry</Text></Pressable></View>;
}

function createStyles(theme: ReturnType<typeof useAppTheme>) { return StyleSheet.create({
  actionButton: { alignItems: "center", backgroundColor: theme.colors.primaryActionBackground, borderRadius: 6, flex: 1, minHeight: 44, justifyContent: "center", padding: 10 },
  actionText: { color: theme.colors.primaryActionForeground, fontWeight: "700" },
  acquisitionActions: { flexDirection: "row", gap: 8 },
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
  search: { backgroundColor: theme.colors.input, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, color: theme.colors.text, padding: 12 },
  secondary: { color: theme.colors.secondaryText },
  section: { gap: 6 },
  sectionTitle: { color: theme.colors.text, fontSize: 18, fontWeight: "700" },
  warning: { backgroundColor: theme.colors.warningBackground, color: theme.colors.warningText, padding: 10 },
}); }
