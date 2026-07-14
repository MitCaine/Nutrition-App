import { useMemo, useRef, useState } from "react";
import { PanResponder, StyleSheet, Text, View } from "react-native";

import type { Food } from "../../features/foods/api/types";
import { FoodDetailsScreen } from "../../features/foods/screens/FoodDetailsScreen";
import { FoodFormScreen } from "../../features/foods/screens/FoodFormScreen";
import { SavedFoodsScreen } from "../../features/foods/screens/SavedFoodsScreen";
import { restoredSearchOffset } from "../../features/foods/utils/unifiedFoodSearch";
import { useQueries } from "@tanstack/react-query";

import { getFood } from "../../features/foods/api/foodApi";
import { useFood } from "../../features/foods/hooks/useFoods";
import { useDailyLogs } from "../../features/logging/hooks/useLogs";
import { DailyLogScreen } from "../../features/logging/screens/DailyLogScreen";
import { LogFoodScreen } from "../../features/logging/screens/LogFoodScreen";
import { todayLocalDateString } from "../../features/logging/utils/dailyLogDisplay";
import type { LogFoodInitialAmount } from "../../features/logging/utils/logFoodForm";
import { IngredientPickerScreen } from "../../features/recipes/screens/IngredientPickerScreen";
import { RecipeDetailScreen } from "../../features/recipes/screens/RecipeDetailScreen";
import { RecipeFormScreen } from "../../features/recipes/screens/RecipeFormScreen";
import { RecipeListScreen } from "../../features/recipes/screens/RecipeListScreen";
import { useRecipe } from "../../features/recipes/hooks/useRecipes";
import {
  applyImportedIngredient,
  emptyRecipeDraft,
  ingredientForFood,
  recipeToDraft,
} from "../../features/recipes/utils/recipeDraft";
import type { RecipeDraft } from "../../features/recipes/utils/recipeDraft";
import { UsdaPreviewScreen } from "../../features/usda/screens/UsdaPreviewScreen";
import { UsdaSearchScreen } from "../../features/usda/screens/UsdaSearchScreen";
import { BottomNavigation } from "./BottomNavigation";
import { useAppTheme } from "../theme/AppTheme";
import { SettingsScreen } from "../settings/SettingsScreen";
import { isMainTabRoot, mainTabForRoute, settingsOriginForRoute, swipeDestination, tabSelectionDestination, type MainTab } from "./mainTabs";

type Route =
  | { name: "foods" }
  | { name: "new-food" }
  | { name: "food-detail"; foodId: string }
  | { name: "edit-food"; foodId: string }
  | { name: "log-food"; foodId: string; initialAmount?: LogFoodInitialAmount }
  | { name: "edit-log"; logId: string }
  | { name: "usda-preview"; fdcId: number }
  | { name: "recipes" }
  | { name: "new-recipe" }
  | { name: "recipe-detail"; recipeId: string }
  | { name: "edit-recipe"; recipeId: string }
  | { name: "ingredient-picker" }
  | { name: "recipe-usda-search" }
  | { name: "recipe-usda-preview"; fdcId: number }
  | { name: "daily-log" }
  | { name: "settings"; origin: MainTab };

function routeForMainTab(tab: MainTab): Route {
  if (tab === "foods") {
    return { name: "foods" };
  }
  if (tab === "daily-log") {
    return { name: "daily-log" };
  }
  return { name: "recipes" };
}

export function AppNavigator() {
  const theme = useAppTheme();
  const [route, setRoute] = useState<Route>({ name: "foods" });
  const [foodQuery, setFoodQuery] = useState("");
  const [recipeQuery, setRecipeQuery] = useState("");
  const [ingredientQuery, setIngredientQuery] = useState("");
  const [recipeUsdaQuery, setRecipeUsdaQuery] = useState("");
  const [recipeDraft, setRecipeDraft] = useState<RecipeDraft>(emptyRecipeDraft());
  const [foodMessage, setFoodMessage] = useState<string | null>(null);
  const [recipeMessage, setRecipeMessage] = useState<string | null>(null);
  const [date, setDate] = useState(todayLocalDateString());
  const foodSearchScroll = useRef({ query: "", offset: 0 });
  const recipeSearchScroll = useRef({ query: "", offset: 0 });
  const dailyLogScroll = useRef({ date, offset: 0 });
  const activeTab = route.name === "settings" ? route.origin : mainTabForRoute(route.name);
  const swipeEnabled = isMainTabRoot(route.name);

  const selectMainTab = (tab: MainTab) => {
    const destination = tabSelectionDestination(activeTab, tab);
    if (!destination) {
      return;
    }
    setFoodMessage(null);
    setRecipeMessage(null);
    setRoute(routeForMainTab(destination));
  };

  const mainSwipeResponder = useMemo(
    () => PanResponder.create({
      onMoveShouldSetPanResponder: (_event, gesture) =>
        isMainTabRoot(route.name) &&
        Math.abs(gesture.dx) > 12 &&
        Math.abs(gesture.dx) > Math.abs(gesture.dy) * 1.5,
      onPanResponderRelease: (_event, gesture) => {
        const destination = swipeDestination(activeTab, gesture.dx);
        if (destination !== activeTab) {
          setFoodMessage(null);
          setRecipeMessage(null);
          setRoute(routeForMainTab(destination));
        }
      },
    }),
    [activeTab, route.name],
  );

  let content;
  if (route.name === "settings") {
    content = <SettingsScreen onBack={() => setRoute(routeForMainTab(route.origin))} />;
  } else if (route.name === "new-food") {
    content = <FoodFormScreen onCancel={() => setRoute({ name: "foods" })} onSaved={(foodId) => setRoute({ name: "food-detail", foodId })} />;
  } else if (route.name === "food-detail") {
    content = (
      <FoodDetailsScreen
        foodId={route.foodId}
        onBack={() => setRoute({ name: "foods" })}
        onDeleted={(message) => {
          setFoodMessage(message);
          setRoute({ name: "foods" });
        }}
        onEdit={() => setRoute({ name: "edit-food", foodId: route.foodId })}
        onLog={(initialAmount) =>
          setRoute({ name: "log-food", foodId: route.foodId, initialAmount })
        }
      />
    );
  } else if (route.name === "edit-food") {
    content = <EditFoodRoute foodId={route.foodId} onCancel={() => setRoute({ name: "food-detail", foodId: route.foodId })} onSaved={(foodId) => setRoute({ name: "food-detail", foodId })} />;
  } else if (route.name === "log-food") {
    content = <LogFoodScreen foodId={route.foodId} date={date} initialAmount={route.initialAmount} onCancel={() => setRoute({ name: "food-detail", foodId: route.foodId })} onSaved={() => setRoute({ name: "daily-log" })} />;
  } else if (route.name === "edit-log") {
    content = <EditLogRoute logId={route.logId} date={date} onCancel={() => setRoute({ name: "daily-log" })} onSaved={() => setRoute({ name: "daily-log" })} />;
  } else if (route.name === "usda-preview") {
    content = (
      <UsdaPreviewScreen
        fdcId={route.fdcId}
        onBack={() => setRoute({ name: "foods" })}
        onImported={(food) => {
          setFoodQuery("");
          foodSearchScroll.current = { query: "", offset: 0 };
          setRoute({ name: "food-detail", foodId: food.id });
        }}
      />
    );
  } else if (route.name === "recipes") {
    content = (
      <RecipeListScreen
        query={recipeQuery}
        setQuery={setRecipeQuery}
        initialScrollOffset={restoredSearchOffset(recipeQuery, recipeSearchScroll.current)}
        onScrollSessionChange={(query, offset) => {
          recipeSearchScroll.current = { query, offset };
        }}
        onCreate={() => {
          setRecipeMessage(null);
          setRecipeDraft(emptyRecipeDraft());
          setRoute({ name: "new-recipe" });
        }}
        onOpenRecipe={(recipeId) => {
          setRecipeMessage(null);
          setRoute({ name: "recipe-detail", recipeId });
        }}
        message={recipeMessage}
        onMessageExpired={() => setRecipeMessage(null)}
        onOpenSettings={() => setRoute({ name: "settings", origin: settingsOriginForRoute(route.name) })}
      />
    );
  } else if (route.name === "new-recipe") {
    content = (
      <RecipeFormScreen
        draft={recipeDraft}
        setDraft={setRecipeDraft}
        onCancel={() => setRoute({ name: "recipes" })}
        onSaved={(recipeId) => setRoute({ name: "recipe-detail", recipeId })}
        onAddIngredient={() => setRoute({ name: "ingredient-picker" })}
      />
    );
  } else if (route.name === "recipe-detail") {
    content = (
      <RecipeDetailRoute
        recipeId={route.recipeId}
        onBack={() => setRoute({ name: "recipes" })}
        onEdit={(draft) => {
          setRecipeDraft(draft);
          setRoute({ name: "edit-recipe", recipeId: route.recipeId });
        }}
        onOpenFood={(foodId) => setRoute({ name: "food-detail", foodId })}
        onLogFood={(foodId) => setRoute({ name: "log-food", foodId })}
        onDeleted={() => {
          setRecipeMessage("Recipe deleted");
          setRoute({ name: "recipes" });
        }}
      />
    );
  } else if (route.name === "edit-recipe") {
    content = (
      <RecipeFormScreen
        draft={recipeDraft}
        setDraft={setRecipeDraft}
        onCancel={() => setRoute({ name: "recipe-detail", recipeId: route.recipeId })}
        onSaved={(recipeId) => setRoute({ name: "recipe-detail", recipeId })}
        onAddIngredient={() => setRoute({ name: "ingredient-picker" })}
      />
    );
  } else if (route.name === "ingredient-picker") {
    content = (
      <IngredientPickerScreen
        query={ingredientQuery}
        setQuery={setIngredientQuery}
        currentPublishedFoodItemId={recipeDraft.publishedFoodItemId}
        onBack={() => setRoute(recipeDraft.recipeId ? { name: "edit-recipe", recipeId: recipeDraft.recipeId } : { name: "new-recipe" })}
        onSelectFood={(food) => {
          setRecipeDraft({ ...recipeDraft, ingredients: [...recipeDraft.ingredients, ingredientForFood(food)] });
          setRoute(recipeDraft.recipeId ? { name: "edit-recipe", recipeId: recipeDraft.recipeId } : { name: "new-recipe" });
        }}
        onSearchUsda={() => setRoute({ name: "recipe-usda-search" })}
      />
    );
  } else if (route.name === "recipe-usda-search") {
    content = (
      <UsdaSearchScreen
        query={recipeUsdaQuery}
        setQuery={setRecipeUsdaQuery}
        onBack={() => setRoute({ name: "ingredient-picker" })}
        onOpenPreview={(fdcId) => setRoute({ name: "recipe-usda-preview", fdcId })}
      />
    );
  } else if (route.name === "recipe-usda-preview") {
    content = (
      <UsdaPreviewScreen
        fdcId={route.fdcId}
        onBack={() => setRoute({ name: "recipe-usda-search" })}
        onImported={(food: Food) => {
          setRecipeDraft(applyImportedIngredient(recipeDraft, food));
          setRoute(recipeDraft.recipeId ? { name: "edit-recipe", recipeId: recipeDraft.recipeId } : { name: "new-recipe" });
        }}
      />
    );
  } else if (route.name === "daily-log") {
    content = <DailyLogScreen
      date={date}
      setDate={(nextDate) => {
        dailyLogScroll.current = { date: nextDate, offset: 0 };
        setDate(nextDate);
      }}
      initialScrollOffset={dailyLogScroll.current.date === date ? dailyLogScroll.current.offset : 0}
      onScrollOffsetChange={(offset) => { dailyLogScroll.current = { date, offset }; }}
      onOpenFood={(foodId) => setRoute({ name: "food-detail", foodId })}
      onEditLog={(logId) => setRoute({ name: "edit-log", logId })}
      onOpenSettings={() => setRoute({ name: "settings", origin: "daily-log" })}
    />;
  } else {
    content = (
      <SavedFoodsScreen
        query={foodQuery}
        setQuery={setFoodQuery}
        initialScrollOffset={restoredSearchOffset(foodQuery, foodSearchScroll.current)}
        onScrollSessionChange={(query, offset) => {
          foodSearchScroll.current = { query, offset };
        }}
        onCreate={() => {
          setFoodMessage(null);
          setRoute({ name: "new-food" });
        }}
        onOpenUsdaPreview={(fdcId) => {
          setFoodMessage(null);
          setRoute({ name: "usda-preview", fdcId });
        }}
        onOpenFood={(foodId) => {
          setFoodMessage(null);
          setRoute({ name: "food-detail", foodId });
        }}
        message={foodMessage}
        onMessageExpired={() => setFoodMessage(null)}
        onOpenSettings={() => setRoute({ name: "settings", origin: settingsOriginForRoute(route.name) })}
      />
    );
  }

  return (
    <View style={[styles.shell, { backgroundColor: theme.colors.background }]}>
      <View style={styles.content} {...(swipeEnabled ? mainSwipeResponder.panHandlers : {})}>{content}</View>
      <BottomNavigation activeTab={activeTab} onSelect={selectMainTab} />
    </View>
  );
}

function RecipeDetailRoute({
  recipeId,
  onBack,
  onEdit,
  onOpenFood,
  onLogFood,
  onDeleted,
}: {
  recipeId: string;
  onBack: () => void;
  onEdit: (draft: RecipeDraft) => void;
  onOpenFood: (foodId: string) => void;
  onLogFood: (foodId: string) => void;
  onDeleted: () => void;
}) {
  const recipe = useRecipe(recipeId);
  const ingredientFoodIds = Array.from(
    new Set(recipe.data?.ingredients.map((ingredient) => ingredient.food_item_id) ?? []),
  );
  const ingredientFoods = useQueries({
    queries: ingredientFoodIds.map((foodId) => ({
      queryKey: ["foods", foodId],
      queryFn: () => getFood(foodId),
      enabled: Boolean(recipe.data),
    })),
  });
  const isLoadingFoods = ingredientFoods.some((query) => query.isLoading);
  const hasFoodError = ingredientFoods.some((query) => query.isError);

  if (!recipe.data || isLoadingFoods) {
    return <LoadingState />;
  }
  const loadedFoods = ingredientFoods.map((query) => query.data).filter((food): food is Food => Boolean(food));
  const draftResult = recipeToDraft(recipe.data, loadedFoods);
  const canEdit = !hasFoodError && draftResult.ok;
  return (
    <RecipeDetailScreen
      recipe={recipe.data}
      onBack={onBack}
      onEdit={() => {
        if (draftResult.ok) {
          onEdit(draftResult.draft);
        }
      }}
      onOpenFood={onOpenFood}
      onLogFood={onLogFood}
      onDeleted={onDeleted}
      ingredientFoods={loadedFoods}
      editBlockedMessage={
        canEdit
          ? null
          : "This recipe references an ingredient food that could not be loaded. Editing is blocked to avoid losing ingredients."
      }
    />
  );
}

function EditLogRoute({
  logId,
  date,
  onCancel,
  onSaved,
}: {
  logId: string;
  date: string;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const logs = useDailyLogs(date);
  const log = logs.data?.find((item) => item.id === logId);
  if (!log) {
    return <LoadingState />;
  }
  return <LogFoodScreen foodId={log.food_item_id} date={date} log={log} onCancel={onCancel} onSaved={onSaved} />;
}

function EditFoodRoute({
  foodId,
  onCancel,
  onSaved,
}: {
  foodId: string;
  onCancel: () => void;
  onSaved: (foodId: string) => void;
}) {
  const food = useFood(foodId);
  if (!food.data) {
    return <LoadingState />;
  }
  return <FoodFormScreen food={food.data} onCancel={onCancel} onSaved={onSaved} />;
}

function LoadingState() {
  const theme = useAppTheme();
  return (
    <View style={[styles.loading, { backgroundColor: theme.colors.background }]}>
      <Text style={{ color: theme.colors.text }}>Loading...</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  content: { flex: 1 },
  loading: { flex: 1, padding: 16 },
  shell: { flex: 1, paddingTop: 48 },
});
