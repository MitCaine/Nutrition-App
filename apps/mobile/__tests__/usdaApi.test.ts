import { z } from "zod";

import {
  getUsdaFoodPreview,
  importUsdaFood,
  searchUsdaFoods,
} from "../src/features/usda/api/usdaApi";

const foodId =
  "11111111-1111-4111-8111-111111111111";

const timestamp =
  "2026-08-22T18:00:00Z";

const nutrientCandidate = {
  nutrient_id: "calories",
  amount: "89.000000",
  unit: "kcal" as const,
  basis: "per_100g" as const,
  data_status: "known" as const,
  source: "usda_fdc" as const,
  external_nutrient_id: "1008",
  external_nutrient_number: "208",
  original_amount: "89.000000",
  original_unit: "KCAL",
  display_name: "Energy",
};

const searchResult = {
  fdc_id: 1105314,
  description: "Bananas, raw",
  data_type: "Foundation",
  brand_owner: null,
  food_category: null,
  publication_date: null,
  importable: true,
  nutrient_preview: [
    nutrientCandidate,
  ],
};

const searchResponse = {
  query: "raw banana",
  page_number: 1,
  page_size: 20,
  total_hits: 1,
  foods: [
    searchResult,
  ],
};

const previewResponse = {
  source_type: "usda" as const,
  external_id: "1105314",
  fdc_id: 1105314,
  name: "Bananas, raw",
  brand: null,
  data_type: "Foundation",
  food_category: null,
  publication_date: null,
  nutrients: [
    nutrientCandidate,
  ],
  serving_definitions: [
    {
      candidate_id: "usda-100g",
      label: "100 g",
      quantity: "100.000000",
      unit: "g",
      gram_weight: "100.000000",
      is_default: true,
      source: "usda_fdc" as const,
    },
  ],
  diagnostics: [],
  source_metadata: {
    dataType: "Foundation",
    provider: {
      name: "FoodData Central",
    },
    flags: [
      true,
      null,
      1,
    ],
  },
};

const importedFood = {
  id: foodId,
  name: "Bananas, raw",
  brand: null,
  notes: null,
  source_type: "usda",
  source_id: "1105314",
  is_recipe: false,
  source_kind: "usda" as const,
  source_label: "USDA",
  is_favorite: false,
  can_favorite: true,
  created_at: timestamp,
  updated_at: timestamp,
  serving_definitions: [],
  nutrients: [],
};

function mockJson(
  value: unknown,
  responseStatus = 200,
): void {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: responseStatus,
    json: async () => value,
  });
}

test(
  "USDA search API encodes query and preserves complete canonical response",
  async () => {
    mockJson(searchResponse);

    const response =
      await searchUsdaFoods(
        "raw banana",
      );

    expect(global.fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/usda/foods/search?query=raw%20banana&page_size=20",
      expect.any(Object),
    );

    expect(response).toEqual(
      searchResponse,
    );

    expect(
      response.foods[0]
        .nutrient_preview[0]
        .amount,
    ).toBe("89.000000");
  },
);

test(
  "USDA search API normalizes only outbound lean fat ratio query",
  async () => {
    mockJson({
      query:
        "ground beef 80% lean 20% fat",
      page_number: 1,
      page_size: 20,
      total_hits: 0,
      foods: [],
    });

    const displayedQuery =
      "ground beef 80/20";

    await searchUsdaFoods(
      displayedQuery,
    );

    expect(displayedQuery).toBe(
      "ground beef 80/20",
    );

    expect(global.fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/usda/foods/search?query=ground%20beef%2080%25%20lean%2020%25%20fat&page_size=20",
      expect.any(Object),
    );
  },
);

test(
  "USDA search API sends unchanged queries without unnecessary rewriting",
  async () => {
    mockJson({
      query: "1/2 cup milk",
      page_number: 1,
      page_size: 20,
      total_hits: 0,
      foods: [],
    });

    await searchUsdaFoods(
      "1/2 cup milk",
    );

    expect(global.fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/usda/foods/search?query=1%2F2%20cup%20milk&page_size=20",
      expect.any(Object),
    );
  },
);

test(
  "invalid lean fat ratio passes through unchanged and accepts canonical empty results",
  async () => {
    mockJson({
      query: "ground beef 80/30",
      page_number: 1,
      page_size: 20,
      total_hits: 0,
      foods: [],
    });

    await expect(
      searchUsdaFoods(
        "ground beef 80/30",
      ),
    ).resolves.toMatchObject({
      foods: [],
    });

    expect(global.fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/usda/foods/search?query=ground%20beef%2080%2F30&page_size=20",
      expect.any(Object),
    );
  },
);

test(
  "USDA preview preserves backend source metadata and exact decimals",
  async () => {
    mockJson(previewResponse);

    const response =
      await getUsdaFoodPreview(
        1105314,
      );

    expect(response).toEqual(
      previewResponse,
    );

    const withMetadata =
      response as typeof response & {
        source_metadata:
          Record<string, unknown>;
      };

    expect(
      withMetadata.source_metadata,
    ).toEqual(
      previewResponse.source_metadata,
    );

    expect(
      response.serving_definitions[0]
        .quantity,
    ).toBe("100.000000");
  },
);

test.each([
  [
    "missing total_hits",
    (() => {
      const value = {
        ...searchResponse,
      } as Record<string, unknown>;

      delete value.total_hits;
      return value;
    })(),
  ],
  [
    "numeric nutrient decimal",
    {
      ...searchResponse,
      foods: [
        {
          ...searchResult,
          nutrient_preview: [
            {
              ...nutrientCandidate,
              amount: 89,
            },
          ],
        },
      ],
    },
  ],
  [
    "unexpected search field",
    {
      ...searchResponse,
      unexpected: true,
    },
  ],
])(
  "USDA search rejects malformed successful response: %s",
  async (_name, response) => {
    mockJson(response);

    await expect(
      searchUsdaFoods(
        "raw banana",
      ),
    ).rejects.toBeInstanceOf(
      z.ZodError,
    );
  },
);

test.each([
  [
    "missing source_metadata",
    (() => {
      const value = {
        ...previewResponse,
      } as Record<string, unknown>;

      delete value.source_metadata;
      return value;
    })(),
  ],
  [
    "invalid source type",
    {
      ...previewResponse,
      source_type: "manual",
    },
  ],
  [
    "non JSON metadata value",
    {
      ...previewResponse,
      source_metadata: {
        invalid: undefined,
      },
    },
  ],
  [
    "numeric serving decimal",
    {
      ...previewResponse,
      serving_definitions: [
        {
          ...previewResponse
            .serving_definitions[0],
          quantity: 100,
        },
      ],
    },
  ],
])(
  "USDA preview rejects malformed successful response: %s",
  async (_name, response) => {
    mockJson(response);

    await expect(
      getUsdaFoodPreview(
        1105314,
      ),
    ).rejects.toBeInstanceOf(
      z.ZodError,
    );
  },
);

test(
  "USDA import API posts to import endpoint and reuses canonical Food parser",
  async () => {
    mockJson(
      importedFood,
      201,
    );

    const food =
      await importUsdaFood(
        1105314,
      );

    expect(global.fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/usda/foods/1105314/import",
      expect.objectContaining({
        method: "POST",
      }),
    );

    expect(food).toEqual(
      importedFood,
    );
  },
);

test(
  "USDA import rejects malformed Food through canonical Food parser",
  async () => {
    mockJson(
      {
        ...importedFood,
        source_label: "Manual",
      },
      201,
    );

    await expect(
      importUsdaFood(
        1105314,
      ),
    ).rejects.toBeInstanceOf(
      z.ZodError,
    );
  },
);
