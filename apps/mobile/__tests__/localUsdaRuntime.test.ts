import {
  createLocalUsdaRuntime,
  mapLocalUsdaFoodPreview,
} from "../src/runtime/local";
import type { Food } from "../src/features/foods/api/types";

const FOOD: Food = {
  id: "00000000-0000-4000-8000-000000000901",
  name: "Bananas, raw",
  brand: null,
  source_type: "usda",
  source_id: "1105314",
  is_recipe: false,
  source_kind: "usda",
  source_label: "USDA",
  is_favorite: false,
  can_favorite: true,
  serving_definitions: [],
  nutrients: [],
};

const USDA_PAYLOAD = {
  fdcId: 1105314,
  description: "Bananas, raw",
  dataType: "Foundation",
  brandOwner: null,
  foodNutrients: [
    { nutrientId: 1008, nutrientName: "Energy", amount: 89, unitName: "KCAL" },
    { nutrientId: 1003, nutrientName: "Protein", amount: 1.09, unitName: "G" },
    { nutrientId: 1087, nutrientName: "Calcium, Ca", amount: 5, unitName: "MG" },
  ],
  foodPortions: [{ id: 1, gramWeight: 118, amount: 1, measureUnit: { abbreviation: "medium" }, portionDescription: "1 medium" }],
};

function response(payload: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => payload } as Response;
}

function foodsDouble(): {
  findActiveSource: jest.Mock;
  importExternal: jest.Mock;
} {
  return {
    findActiveSource: jest.fn().mockResolvedValue(null),
    importExternal: jest.fn().mockResolvedValue(FOOD),
  };
}

describe("E2-06 local USDA gateway", () => {
  test("does not call the network without an injected personal credential", async () => {
    const fetchImpl = jest.fn();
    const runtime = createLocalUsdaRuntime(foodsDouble(), { fetchImpl });

    await expect(runtime.search("banana")).rejects.toMatchObject({
      kind: "unavailable",
      code: "usda_credentials_unconfigured",
      mutationOutcome: "not_applicable",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  test("keeps a legitimate empty result distinct from malformed or offline responses", async () => {
    const emptyFetch = jest.fn().mockResolvedValue(response({ foods: [], totalHits: 0 }));
    const emptyRuntime = createLocalUsdaRuntime(foodsDouble(), {
      credentialProvider: () => "personal-test-key",
      fetchImpl: emptyFetch,
    });
    await expect(emptyRuntime.search("not found")).resolves.toMatchObject({ foods: [], total_hits: 0 });

    const malformedRuntime = createLocalUsdaRuntime(foodsDouble(), {
      credentialProvider: () => "personal-test-key",
      fetchImpl: jest.fn().mockResolvedValue(response({ foods: "not-an-array" })),
    });
    await expect(malformedRuntime.search("banana")).rejects.toMatchObject({
      kind: "invalid_response",
      code: "usda_invalid_response",
      retryable: false,
    });

    const malformedPreviewRuntime = createLocalUsdaRuntime(foodsDouble(), {
      credentialProvider: () => "personal-test-key",
      fetchImpl: jest.fn().mockResolvedValue(response({ fdcId: 1105314, foodNutrients: "invalid" })),
    });
    await expect(malformedPreviewRuntime.getPreview(1105314)).rejects.toMatchObject({
      kind: "invalid_response",
      code: "usda_invalid_response",
      retryable: false,
    });

    const offlineRuntime = createLocalUsdaRuntime(foodsDouble(), {
      credentialProvider: () => "personal-test-key",
      fetchImpl: jest.fn().mockRejectedValue(new TypeError("network offline")),
    });
    await expect(offlineRuntime.search("banana")).rejects.toMatchObject({
      kind: "unavailable",
      code: "usda_offline",
      retryable: true,
      mutationOutcome: "not_applicable",
    });

    const offlineImportRuntime = createLocalUsdaRuntime(foodsDouble(), {
      credentialProvider: () => "personal-test-key",
      fetchImpl: jest.fn().mockRejectedValue(new TypeError("network offline")),
    });
    await expect(offlineImportRuntime.importFood(1105314)).rejects.toMatchObject({
      kind: "unavailable",
      code: "usda_offline",
      retryable: true,
      mutationOutcome: "confirmed_non_commit",
    });
  });

  test("matches route-specific upstream HTTP behavior and returns the outbound query", async () => {
    const searchBadRequest = jest.fn().mockResolvedValue(response({ detail: "invalid query" }, 400));
    const searchRuntime = createLocalUsdaRuntime(foodsDouble(), {
      credentialProvider: () => "personal-test-key",
      fetchImpl: searchBadRequest,
    });
    await expect(searchRuntime.search("ground beef 80/20")).resolves.toEqual({
      query: "ground beef 80% lean 20% fat",
      page_number: 1,
      page_size: 20,
      total_hits: 0,
      foods: [],
    });
    expect(searchBadRequest).toHaveBeenCalledWith(
      expect.stringContaining("query=ground%20beef%2080%25%20lean%2020%25%20fat"),
      expect.anything(),
    );

    const searchNotFoundRuntime = createLocalUsdaRuntime(foodsDouble(), {
      credentialProvider: () => "personal-test-key",
      fetchImpl: jest.fn().mockResolvedValue(response({ detail: "missing" }, 404)),
    });
    await expect(searchNotFoundRuntime.search("banana")).rejects.toMatchObject({
      kind: "unavailable",
      code: "usda_unavailable",
      retryable: true,
      mutationOutcome: "not_applicable",
    });

    const previewBadRequestRuntime = createLocalUsdaRuntime(foodsDouble(), {
      credentialProvider: () => "personal-test-key",
      fetchImpl: jest.fn().mockResolvedValue(response({ detail: "invalid" }, 400)),
    });
    await expect(previewBadRequestRuntime.getPreview(1105314)).rejects.toMatchObject({
      kind: "unavailable",
      code: "usda_unavailable",
      retryable: true,
      mutationOutcome: "not_applicable",
    });
  });

  test("maps the USDA preview with exact fixed-scale nutrient values and serving identity", () => {
    const preview = mapLocalUsdaFoodPreview(USDA_PAYLOAD);
    expect(preview).toMatchObject({ fdc_id: 1105314, external_id: "1105314", source_type: "usda" });
    expect(preview.serving_definitions).toEqual(expect.arrayContaining([
      expect.objectContaining({ label: "100 g", gram_weight: "100.000000", is_default: true }),
      expect.objectContaining({ label: "1 medium", gram_weight: "118.000000", is_default: false }),
    ]));
    expect(preview.nutrients).toEqual(expect.arrayContaining([
      expect.objectContaining({ nutrient_id: "calories", amount: "89.000000", data_status: "known" }),
      expect.objectContaining({ nutrient_id: "protein", amount: "1.090000", data_status: "known" }),
      expect.objectContaining({ nutrient_id: "calcium", amount: "5.000000", data_status: "known" }),
      expect.objectContaining({ nutrient_id: "vitamin_d", amount: null, data_status: "unknown" }),
    ]));
  });

  test("uses amount when present, even when null, and only falls back to value when absent", () => {
    const preview = mapLocalUsdaFoodPreview({
      ...USDA_PAYLOAD,
      foodNutrients: [
        { nutrientId: 1003, nutrientName: "Protein", amount: null, value: 99, unitName: "G" },
        { nutrientId: 1004, nutrientName: "Total lipid (fat)", value: 99, unitName: "G" },
      ],
    });
    expect(preview.nutrients).toEqual(expect.arrayContaining([
      expect.objectContaining({ nutrient_id: "protein", amount: null, data_status: "unknown" }),
      expect.objectContaining({ nutrient_id: "total_fat", amount: "99.000000", data_status: "known" }),
    ]));
  });

  test("normalizes generated USDA serving labels and candidate identities without Number conversion", () => {
    const preview = mapLocalUsdaFoodPreview({
      fdcId: 1105315,
      description: "Portion spelling fixture",
      servingSize: 32.5,
      servingSizeUnit: "g",
      foodNutrients: [],
      foodPortions: [
        { gramWeight: 32.5, amount: 2, measureUnit: { abbreviation: "tbsp" } },
        { gramWeight: 32, amount: 1, measureUnit: { abbreviation: "cup" } },
      ],
    });
    expect(preview.serving_definitions).toEqual(expect.arrayContaining([
      expect.objectContaining({
        candidate_id: "branded:serving-size",
        label: "32.5 g",
        quantity: "32.500000",
        gram_weight: "32.500000",
      }),
      expect.objectContaining({
        candidate_id: "portion:2 tbsp:2:tbsp:32.5",
        label: "2 tbsp",
        quantity: "2.000000",
        gram_weight: "32.500000",
      }),
      expect.objectContaining({
        candidate_id: "portion:1 cup:1:cup:32",
        label: "1 cup",
        quantity: "1.000000",
        gram_weight: "32.000000",
      }),
    ]));

    const integerPreview = mapLocalUsdaFoodPreview({
      fdcId: 1105316,
      description: "Integer serving spelling fixture",
      servingSize: 32,
      servingSizeUnit: "g",
      foodNutrients: [],
    });
    expect(integerPreview.serving_definitions).toEqual(expect.arrayContaining([
      expect.objectContaining({ candidate_id: "branded:serving-size", label: "32 g" }),
    ]));
  });

  test("imports atomically through the local Food authority and reconciles an existing source offline", async () => {
    const foods = foodsDouble();
    const fetchImpl = jest.fn().mockResolvedValue(response(USDA_PAYLOAD));
    const runtime = createLocalUsdaRuntime(foods, {
      credentialProvider: () => "personal-test-key",
      fetchImpl,
    });

    await expect(runtime.importFood(1105314)).resolves.toBe(FOOD);
    expect(foods.importExternal).toHaveBeenCalledWith(expect.objectContaining({
      source_type: "usda",
      source_id: "1105314",
      source_record_type: "usda_fdc",
      source_external_id: "1105314",
      source_metadata: expect.stringContaining("diagnostics"),
      food: expect.objectContaining({ name: "Bananas, raw" }),
    }));
    expect(fetchImpl).toHaveBeenCalledTimes(1);

    foods.findActiveSource.mockResolvedValue(FOOD);
    fetchImpl.mockRejectedValue(new TypeError("offline after import"));
    await expect(runtime.importFood(1105314)).resolves.toBe(FOOD);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  test("classifies timeout and route-specific missing responses without false empty results", async () => {
    const timeoutFetch = jest.fn((_url: string, _options: RequestInit) => new Promise<Response>((_resolve, reject) => {
      setTimeout(() => reject(Object.assign(new Error("aborted"), { name: "AbortError" })), 10);
    }));
    const timeoutRuntime = createLocalUsdaRuntime(foodsDouble(), {
      credentialProvider: () => "personal-test-key",
      fetchImpl: timeoutFetch as typeof fetch,
      timeoutMs: 1,
    });
    await expect(timeoutRuntime.getPreview(1105314)).rejects.toMatchObject({
      kind: "unavailable",
      code: "usda_timeout",
      retryable: true,
    });

    const missingRuntime = createLocalUsdaRuntime(foodsDouble(), {
      credentialProvider: () => "personal-test-key",
      fetchImpl: jest.fn().mockResolvedValue(response({ detail: "missing" }, 404)),
    });
    await expect(missingRuntime.getPreview(1105314)).rejects.toMatchObject({
      kind: "not_found",
      code: "usda_food_not_found",
    });

    const missingImportFoods = foodsDouble();
    const missingImportRuntime = createLocalUsdaRuntime(missingImportFoods, {
      credentialProvider: () => "personal-test-key",
      fetchImpl: jest.fn().mockResolvedValue(response({ detail: "missing" }, 404)),
    });
    await expect(missingImportRuntime.importFood(1105314)).rejects.toMatchObject({
      kind: "not_found",
      code: "usda_food_not_found",
      mutationOutcome: "confirmed_non_commit",
    });
    expect(missingImportFoods.importExternal).not.toHaveBeenCalled();

    const invalidImportFoods = foodsDouble();
    const invalidImportRuntime = createLocalUsdaRuntime(invalidImportFoods, {
      credentialProvider: () => "personal-test-key",
      fetchImpl: jest.fn().mockResolvedValue(response({ detail: "invalid" }, 400)),
    });
    await expect(invalidImportRuntime.importFood(1105314)).rejects.toMatchObject({
      kind: "unavailable",
      code: "usda_unavailable",
      retryable: true,
      mutationOutcome: "confirmed_non_commit",
    });
    expect(invalidImportFoods.importExternal).not.toHaveBeenCalled();
  });
});
