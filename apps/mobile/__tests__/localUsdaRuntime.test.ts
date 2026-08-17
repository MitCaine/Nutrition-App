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

  test("maps extended FDC identities with semantic units without guessing equivalence", () => {
    const preview = mapLocalUsdaFoodPreview({
      fdcId: 990101,
      description: "Extended nutrient fixture",
      dataType: "Foundation",
      foodNutrients: [
        { nutrientId: 1091, nutrientNumber: "305", nutrientName: "Phosphorus, P", amount: 125, unitName: "MG" },
        { nutrientId: 1095, nutrientNumber: "309", nutrientName: "Zinc, Zn", amount: 0, unitName: "MG" },
        { nutrientId: 1096, nutrientNumber: "310", nutrientName: "Chromium, Cr", amount: 3, unitName: "UG" },
        { nutrientId: 1098, nutrientNumber: "312", nutrientName: "Copper, Cu", amount: 0.4, unitName: "MG" },
        { nutrientId: 1100, nutrientNumber: "314", nutrientName: "Iodine, I", amount: 20, unitName: "UG" },
        { nutrientId: 1101, nutrientNumber: "315", nutrientName: "Manganese, Mn", amount: 0.7, unitName: "MG" },
        { nutrientId: 1102, nutrientNumber: "316", nutrientName: "Molybdenum, Mo", amount: 6, unitName: "UG" },
        { nutrientId: 1103, nutrientNumber: "317", nutrientName: "Selenium, Se", amount: null, unitName: "UG" },
        { nutrientId: 1106, nutrientNumber: "320", nutrientName: "Vitamin A, RAE", amount: 90, unitName: "UG" },
        { nutrientId: 1109, nutrientNumber: "323", nutrientName: "Vitamin E (alpha-tocopherol)", amount: 1.5, unitName: "MG" },
        { nutrientId: 1162, nutrientNumber: "401", nutrientName: "Vitamin C, total ascorbic acid", amount: 12, unitName: "MG" },
        { nutrientId: 1165, nutrientNumber: "404", nutrientName: "Thiamin", amount: 0.2, unitName: "MG" },
        { nutrientId: 1166, nutrientNumber: "405", nutrientName: "Riboflavin", amount: 0.3, unitName: "MG" },
        { nutrientId: 1169, nutrientNumber: "409", nutrientName: "Niacin equivalent N406 +N407", amount: 2.5, unitName: "MG" },
        { nutrientId: 1170, nutrientNumber: "410", nutrientName: "Pantothenic acid", amount: 0.8, unitName: "MG" },
        { nutrientId: 1175, nutrientNumber: "415", nutrientName: "Vitamin B-6", amount: 0.4, unitName: "MG" },
        { nutrientId: 1176, nutrientNumber: "416", nutrientName: "Biotin", amount: 4, unitName: "UG" },
        { nutrientId: 1178, nutrientNumber: "418", nutrientName: "Vitamin B-12", amount: 1.2, unitName: "UG" },
        { nutrientId: 1180, nutrientNumber: "421", nutrientName: "Choline, total", amount: 25, unitName: "MG" },
        { nutrientId: 1190, nutrientNumber: "435", nutrientName: "Folate, DFE", amount: 80, unitName: "UG" },
        { nutrientId: 1272, nutrientNumber: "621", nutrientName: "PUFA 22:6 n-3 (DHA)", amount: 0.03, unitName: "G" },
        { nutrientId: 1278, nutrientNumber: "629", nutrientName: "PUFA 20:5 n-3 (EPA)", amount: 0.02, unitName: "G" },
        { nutrientId: 1316, nutrientNumber: "675", nutrientName: "PUFA 18:2 n-6 c,c", amount: 2.1, unitName: "G" },
        { nutrientId: 1404, nutrientNumber: "851", nutrientName: "PUFA 18:3 n-3 c,c,c (ALA)", amount: 0.15, unitName: "G" },
        { nutrientId: 1104, nutrientNumber: "318", nutrientName: "Vitamin A, IU", amount: 5000, unitName: "IU" },
        { nutrientId: 1167, nutrientNumber: "406", nutrientName: "Niacin", amount: 99, unitName: "MG" },
        { nutrientId: 1177, nutrientNumber: "417", nutrientName: "Folate, total", amount: 999, unitName: "UG" },
        { nutrientId: 1185, nutrientNumber: "430", nutrientName: "Vitamin K (phylloquinone)", amount: 40, unitName: "UG" },
      ],
    });

    const nutrients = new Map(
      preview.nutrients.map((nutrient) => [nutrient.nutrient_id, nutrient]),
    );

    expect(preview.nutrients).toHaveLength(42);

    expect(nutrients.get("phosphorus")).toMatchObject({ amount: "125.000000", unit: "mg" });
    expect(nutrients.get("zinc")).toMatchObject({ amount: "0.000000", data_status: "zero" });
    expect(nutrients.get("selenium")).toMatchObject({ amount: null, data_status: "unknown" });

    expect(nutrients.get("vitamin_a")).toMatchObject({
      amount: "90.000000",
      unit: "mcg RAE",
      original_unit: "UG",
    });
    expect(nutrients.get("vitamin_e")).toMatchObject({
      amount: "1.500000",
      unit: "mg alpha-tocopherol",
    });
    expect(nutrients.get("niacin")).toMatchObject({
      amount: "2.500000",
      unit: "mg NE",
    });
    expect(nutrients.get("folate")).toMatchObject({
      amount: "80.000000",
      unit: "mcg DFE",
    });

    expect(nutrients.get("dha")).toMatchObject({ amount: "30.000000", unit: "mg" });
    expect(nutrients.get("epa")).toMatchObject({ amount: "20.000000", unit: "mg" });
    expect(nutrients.get("linoleic_acid")).toMatchObject({ amount: "2.100000", unit: "g" });
    expect(nutrients.get("alpha_linolenic_acid")).toMatchObject({ amount: "0.150000", unit: "g" });

    expect(nutrients.get("vitamin_k")).toMatchObject({
      amount: null,
      data_status: "unknown",
    });
    expect(nutrients.get("chloride")).toMatchObject({
      amount: null,
      data_status: "unknown",
    });
  });

  test("does not infer RAE, DFE, NE, or total Vitamin K from incompatible USDA identities", () => {
    const preview = mapLocalUsdaFoodPreview({
      fdcId: 990102,
      description: "Equivalence guard fixture",
      dataType: "Foundation",
      foodNutrients: [
        { nutrientId: 1104, nutrientNumber: "318", nutrientName: "Vitamin A, IU", amount: 5000, unitName: "IU" },
        { nutrientId: 1167, nutrientNumber: "406", nutrientName: "Niacin", amount: 16, unitName: "MG" },
        { nutrientId: 1177, nutrientNumber: "417", nutrientName: "Folate, total", amount: 400, unitName: "UG" },
        { nutrientId: 1185, nutrientNumber: "430", nutrientName: "Vitamin K (phylloquinone)", amount: 120, unitName: "UG" },
      ],
    });

    const nutrients = new Map(
      preview.nutrients.map((nutrient) => [nutrient.nutrient_id, nutrient]),
    );

    for (const id of ["vitamin_a", "niacin", "folate", "vitamin_k"]) {
      expect(nutrients.get(id)).toMatchObject({
        amount: null,
        data_status: "unknown",
      });
    }
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
