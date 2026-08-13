import React from "react";
import TestRenderer, { act } from "react-test-renderer";

const mockQueryClient = {
  invalidateQueries: jest.fn(),
  removeQueries: jest.fn(),
  setQueryData: jest.fn(),
};

jest.mock("@tanstack/react-query", () => ({
  useMutation: (options: unknown) => options,
  useQuery: (options: unknown) => options,
  useQueryClient: () => mockQueryClient,
}));

import {
  useCalendarState,
  useConfirmCalendarTimeZoneChange,
  useEstablishCalendarTimeZone,
  usePreviewCalendarTimeZoneChange,
} from "../src/features/calendar/hooks/useCalendar";
import {
  useFavoriteFoods,
  useFoodMutations,
} from "../src/features/foods/hooks/useFoods";
import {
  useLogMutations,
  useRecentEntries,
} from "../src/features/logging/hooks/useLogs";
import { useRecipeMutations } from "../src/features/recipes/hooks/useRecipes";
import { useUsdaImport } from "../src/features/usda/hooks/useUsda";
import type { NutritionRuntime } from "../src/runtime/NutritionRuntime";
import { createNutritionTestRuntime, withNutritionRuntime } from "./nutritionRuntimeTestSupport";

type QueryCallback = { queryFn: () => Promise<unknown> };
type MutationCallback = { mutationFn: (input: unknown) => Promise<unknown> };

class ReceiverSensitiveCalendar {
  private readonly owner = "calendar";
  async getState() { return `${this.owner}:get`; }
  async establishTimeZone() { return `${this.owner}:establish`; }
  async previewTimeZoneChange() { return `${this.owner}:preview`; }
  async confirmTimeZoneChange() { return `${this.owner}:confirm`; }
}

class ReceiverSensitiveFoods {
  private readonly owner = "foods";
  async listFavorites() { return `${this.owner}:favorites`; }
  async delete() { return `${this.owner}:delete`; }
  async duplicate() { return `${this.owner}:duplicate`; }
}

class ReceiverSensitiveRecipes {
  private readonly owner = "recipes";
  async create() { return `${this.owner}:create`; }
  async delete() { return `${this.owner}:delete`; }
  async publish() { return `${this.owner}:publish`; }
}

class ReceiverSensitiveDailyLogs {
  private readonly owner = "dailyLogs";
  async listRecentEntries() { return `${this.owner}:recent`; }
  async create() { return `${this.owner}:create`; }
}

class ReceiverSensitiveUsda {
  private readonly owner = "usda";
  async importFood() { return `${this.owner}:import`; }
}

test("receiver-sensitive class methods remain bound through every affected hook callback", async () => {
  const runtime = createNutritionTestRuntime({
    calendar: new ReceiverSensitiveCalendar() as unknown as NutritionRuntime["calendar"],
    foods: new ReceiverSensitiveFoods() as unknown as NutritionRuntime["foods"],
    recipes: new ReceiverSensitiveRecipes() as unknown as NutritionRuntime["recipes"],
    dailyLogs: new ReceiverSensitiveDailyLogs() as unknown as NutritionRuntime["dailyLogs"],
    usda: new ReceiverSensitiveUsda() as unknown as NutritionRuntime["usda"],
  });
  let callbacks!: {
    calendarState: QueryCallback;
    establishCalendar: MutationCallback;
    previewCalendar: MutationCallback;
    confirmCalendar: MutationCallback;
    favoriteFoods: QueryCallback;
    deleteFood: MutationCallback;
    duplicateFood: MutationCallback;
    createRecipe: MutationCallback;
    deleteRecipe: MutationCallback;
    publishRecipe: MutationCallback;
    recentEntries: QueryCallback;
    createLog: MutationCallback;
    importFood: MutationCallback;
  };

  function Probe() {
    const foodMutations = useFoodMutations();
    const recipeMutations = useRecipeMutations();
    const logMutations = useLogMutations("2026-08-12");
    callbacks = {
      calendarState: useCalendarState() as unknown as QueryCallback,
      establishCalendar: useEstablishCalendarTimeZone() as unknown as MutationCallback,
      previewCalendar: usePreviewCalendarTimeZoneChange() as unknown as MutationCallback,
      confirmCalendar: useConfirmCalendarTimeZoneChange() as unknown as MutationCallback,
      favoriteFoods: useFavoriteFoods() as unknown as QueryCallback,
      deleteFood: foodMutations.deleteFood as unknown as MutationCallback,
      duplicateFood: foodMutations.duplicateFood as unknown as MutationCallback,
      createRecipe: recipeMutations.createRecipe as unknown as MutationCallback,
      deleteRecipe: recipeMutations.deleteRecipe as unknown as MutationCallback,
      publishRecipe: recipeMutations.publishRecipe as unknown as MutationCallback,
      recentEntries: useRecentEntries() as unknown as QueryCallback,
      createLog: logMutations.createLog as unknown as MutationCallback,
      importFood: useUsdaImport() as unknown as MutationCallback,
    };
    return null;
  }

  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(withNutritionRuntime(React.createElement(Probe), runtime));
  });

  await expect(callbacks.calendarState.queryFn()).resolves.toBe("calendar:get");
  await expect(callbacks.establishCalendar.mutationFn("America/Los_Angeles")).resolves.toBe("calendar:establish");
  await expect(callbacks.previewCalendar.mutationFn("America/New_York")).resolves.toBe("calendar:preview");
  await expect(callbacks.confirmCalendar.mutationFn({})).resolves.toBe("calendar:confirm");
  await expect(callbacks.favoriteFoods.queryFn()).resolves.toBe("foods:favorites");
  await expect(callbacks.deleteFood.mutationFn({})).resolves.toBe("foods:delete");
  await expect(callbacks.duplicateFood.mutationFn({})).resolves.toBe("foods:duplicate");
  await expect(callbacks.createRecipe.mutationFn({})).resolves.toBe("recipes:create");
  await expect(callbacks.deleteRecipe.mutationFn({})).resolves.toBe("recipes:delete");
  await expect(callbacks.publishRecipe.mutationFn({})).resolves.toBe("recipes:publish");
  await expect(callbacks.recentEntries.queryFn()).resolves.toBe("dailyLogs:recent");
  await expect(callbacks.createLog.mutationFn({})).resolves.toBe("dailyLogs:create");
  await expect(callbacks.importFood.mutationFn(123)).resolves.toBe("usda:import");

  await act(async () => renderer.unmount());
});
