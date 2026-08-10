import * as Crypto from "expo-crypto";

import { validateMobileConfig } from "../config/runtimeConfig";
import type { OcrConfirmationInput } from "../src/features/ocr/api/types";
import {
  bootstrapApplicationRuntime,
} from "../src/runtime/applicationRuntimeBootstrap";
import { bootstrapLocalRuntimeFoundation } from "../src/runtime/local/localRuntimeFoundation";
import { LocalSQLiteTestDatabase } from "./localSQLiteTestSupport";

const NOW = () => new Date("2026-08-09T12:00:00.000Z");

function targetInput() {
  return {
    profile: {
      birth_date: "1996-01-15",
      sex_for_equation: "male" as const,
      height_cm: "175",
      height_unit: "cm" as const,
      weight_kg: "70",
      weight_unit: "kg" as const,
      activity_level: "sedentary" as const,
      energy_estimation_context: "general_adult" as const,
    },
    manual_overrides: {
      calories: null,
      protein: "90",
      total_carbohydrate: null,
      total_fat: null,
    },
  };
}

function decision(
  fieldKey: string,
  confirmedValue: string | null,
  unit: string | null = null,
): OcrConfirmationInput["field_decisions"][number] {
  return {
    field_key: fieldKey,
    nutrient_id: fieldKey.startsWith("nutrient.") ? fieldKey.slice("nutrient.".length) : null,
    suggested_value: confirmedValue,
    confirmed_value: confirmedValue,
    unit,
    decision: confirmedValue === null ? "omitted" : "accepted",
    parse_status: confirmedValue === null ? "missing" : "parsed",
    comparison: null,
    confidence: confirmedValue === null ? "0" : "0.99",
    source_text: confirmedValue ?? "",
    source_observation_ids: confirmedValue === null ? [] : [`obs-${fieldKey}`],
    warning_codes: [],
    resolution: null,
  };
}

function ocrConfirmation(): OcrConfirmationInput {
  return {
    parser_version: "nutrition_label_v1",
    image_source_type: "camera",
    client_request_id: "00000000-0000-4000-8000-000000000801",
    food: {
      name: "Scanned cereal",
      brand: null,
      notes: null,
      serving_definitions: [{
        label: "1 cup (30g)",
        quantity: "1",
        unit: "cup",
        gram_weight: "30",
        is_default: true,
      }],
      nutrients: [
        { nutrient_id: "calories", amount: "120", unit: "kcal", basis: "per_serving", data_status: "known" },
        { nutrient_id: "sodium", amount: "0", unit: "mg", basis: "per_serving", data_status: "zero" },
      ],
    },
    field_decisions: [
      decision("food.name", "Scanned cereal"),
      decision("food.brand", null),
      decision("food.notes", null),
      decision("serving.display", "1 cup (30g)"),
      decision("serving.quantity", "1"),
      decision("serving.unit", "cup"),
      decision("serving.gram_weight", "30", "g"),
      decision("nutrient.calories", "120", "kcal"),
      decision("nutrient.sodium", "0", "mg"),
    ],
    unknown_nutrients: [],
    parser_warning_codes: [],
  };
}

test("selected local authority completes core workflows with FastAPI and PostgreSQL absent", async () => {
  let nextId = 100;
  (Crypto.randomUUID as jest.Mock).mockImplementation(() =>
    `00000000-0000-4000-8000-${String(nextId++).padStart(12, "0")}`);
  const database = new LocalSQLiteTestDatabase();
  await database.initialize();

  const applicationFetch = jest.spyOn(global, "fetch").mockRejectedValue(
    new TypeError("FastAPI and PostgreSQL are unreachable"),
  );
  const usdaFetch = jest.fn(async (input: RequestInfo | URL) => ({
    ok: true,
    status: 200,
    json: async () => ({ foods: [], totalHits: 0 }),
    url: String(input),
  }) as Response);

  const localConfiguration = validateMobileConfig({
    dataAuthority: "local",
    deploymentMode: "production",
  });
  const handle = await bootstrapApplicationRuntime(localConfiguration, {
    openLocalRuntime: async () => {
      const foundation = await bootstrapLocalRuntimeFoundation(
        database.asExpoDatabase(),
        { now: NOW },
        { now: NOW },
        {
          credentialProvider: () => "personal-test-key",
          fetchImpl: usdaFetch as typeof fetch,
        },
        { now: NOW },
        { now: NOW },
        { now: NOW },
      );
      return Object.assign(foundation, {
        close: async () => { database.close(); },
      });
    },
    loadRemoteRuntime: async () => {
      throw new Error("remote adapter registry must remain unconstructed");
    },
  });
  const runtime = handle.runtime;

  try {
    await expect(runtime.calendar.establishTimeZone("UTC")).resolves.toMatchObject({
      calendar_revision: 1,
      today: "2026-08-09",
    });

    const foodInput = {
      name: "Offline oats",
      brand: "Kitchen",
      notes: "local",
      serving_definitions: [{
        label: "1 bowl",
        quantity: "1",
        unit: "bowl",
        gram_weight: "50",
        is_default: true,
      }],
      nutrients: [
        { nutrient_id: "protein", amount: "20", unit: "g" as const, basis: "per_100g" as const, data_status: "known" as const },
        { nutrient_id: "calories", amount: "200", unit: "kcal" as const, basis: "per_serving" as const, data_status: "known" as const },
      ],
    };
    const food = await runtime.foods.create({
      ...foodInput,
      client_request_id: "00000000-0000-4000-8000-000000000201",
    });
    await expect(runtime.foods.get(food.id)).resolves.toMatchObject({ name: "Offline oats" });
    const updatedFood = await runtime.foods.update(food.id, {
      ...foodInput,
      name: "Offline oats updated",
    });
    expect(updatedFood.name).toBe("Offline oats updated");

    const recipe = await runtime.recipes.create({
      name: "Offline oat bowl",
      notes: "composed locally",
      serving_count_yield: "2",
      final_cooked_weight_grams: "100",
      ingredients: [{
        food_item_id: food.id,
        position: 0,
        amount_quantity: "50",
        amount_unit: "g",
        serving_definition_id: null,
      }],
    });
    const published = await runtime.recipes.publish({
      recipeId: recipe.id,
      clientRequestId: "00000000-0000-4000-8000-000000000301",
    });
    const resolvedRecipe = await runtime.foods.getResolvedNutrition(published.food.id);
    expect(resolvedRecipe.nutrition_authority).toBe("recipe_publication_revision");

    const logRequestId = "00000000-0000-4000-8000-000000000401";
    const log = await runtime.dailyLogs.create({
      client_request_id: logRequestId,
      calendar_revision: 1,
      food_item_id: published.food.id,
      logged_date: "2026-08-09",
      amount_quantity: "1",
      amount_unit: "serving",
      serving_definition_id: published.food.serving_definitions.find((value) => value.is_default)?.id,
      source_food_updated_at: published.food.updated_at,
      source_recipe_publication_revision_id: resolvedRecipe.recipe_publication_revision_id,
      meal_type: "breakfast",
      notes: "offline log",
    });
    await expect(runtime.dailyLogs.list("2026-08-09")).resolves.toMatchObject([{ id: log.id }]);
    await expect(runtime.dailyLogs.getMutationStatus(logRequestId, "create")).resolves.toMatchObject({
      status: "confirmed_success",
      log_id: log.id,
    });

    const editContext = await runtime.dailyLogs.getEditContext(log.id);
    const edited = await runtime.dailyLogs.update(log.id, {
      client_request_id: "00000000-0000-4000-8000-000000000402",
      calendar_revision: 1,
      expected_updated_at: log.updated_at,
      source_food_updated_at: editContext.current_source_food_updated_at,
      source_recipe_publication_revision_id: editContext.current_recipe_publication_revision_id,
      notes: "edited offline",
    });
    expect(edited.notes).toBe("edited offline");

    await expect(runtime.targets.getConfiguration()).resolves.toMatchObject({ profile: null });
    const targets = await runtime.targets.updateConfiguration(targetInput());
    expect(targets.manualOverrides).toEqual(expect.arrayContaining([
      expect.objectContaining({ nutrientId: "protein", amount: "90.000000" }),
    ]));
    await expect(runtime.targets.getDailyComparison("2026-08-09")).resolves.toMatchObject({
      date: "2026-08-09",
      comparisons: expect.arrayContaining([
        expect.objectContaining({
          nutrientId: "protein",
          consumedAmount: "5.000000",
          status: "available",
        }),
      ]),
    });

    const parsed = await runtime.ocr.parseNutritionLabel({
      fullText: "Nutrition Facts\nServing size 1 cup (30g)\nCalories 120\nSodium 0mg",
      observations: [
        { id: "header", text: "Nutrition Facts", confidence: 0.99, boundingBox: { x: 0, y: 0, width: 0.5, height: 0.1 } },
        { id: "serving", text: "Serving size 1 cup (30g)", confidence: 0.98, boundingBox: { x: 0, y: 0.1, width: 0.8, height: 0.1 } },
        { id: "calories", text: "Calories 120", confidence: 0.99, boundingBox: { x: 0, y: 0.2, width: 0.5, height: 0.1 } },
        { id: "sodium", text: "Sodium 0mg", confidence: 0.97, boundingBox: { x: 0, y: 0.3, width: 0.5, height: 0.1 } },
      ],
      image: { width: 1000, height: 1500, orientationApplied: true },
      recognition: {
        platform: "ios",
        recognitionLevel: "accurate",
        languages: ["en-US"],
        durationMs: 20,
      },
    });
    expect(parsed.parser_version).toBe("nutrition_label_v1");
    await expect(runtime.ocr.confirmNutritionLabel(ocrConfirmation())).resolves.toMatchObject({
      food: { name: "Scanned cereal", source_kind: "ocr_confirmed" },
    });

    await runtime.dailyLogs.delete(log.id, {
      client_request_id: "00000000-0000-4000-8000-000000000403",
      calendar_revision: 1,
      expected_updated_at: edited.updated_at,
    });
    await expect(runtime.dailyLogs.list("2026-08-09")).resolves.toEqual([]);

    expect(applicationFetch).not.toHaveBeenCalled();
    expect(usdaFetch).not.toHaveBeenCalled();
    await expect(runtime.usda.search("oats")).resolves.toMatchObject({ foods: [] });
    expect(usdaFetch).toHaveBeenCalledTimes(1);
    expect(String(usdaFetch.mock.calls[0][0])).toMatch(/^https:\/\/api\.nal\.usda\.gov\/fdc\/v1\/foods\/search\?/);
    expect(applicationFetch).not.toHaveBeenCalled();
  } finally {
    applicationFetch.mockRestore();
    await handle.close();
  }
});
