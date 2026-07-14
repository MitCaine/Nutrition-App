import { importUsdaFood, searchUsdaFoods } from "../src/features/usda/api/usdaApi";

test("USDA search API encodes query and returns normalized response", async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({
      query: "raw banana",
      page_number: 1,
      page_size: 20,
      total_hits: 1,
      foods: [
        {
          fdc_id: 1105314,
          description: "Bananas, raw",
          data_type: "Foundation",
          importable: true,
          nutrient_preview: [],
        },
      ],
    }),
  });

  const response = await searchUsdaFoods("raw banana");

  expect(global.fetch).toHaveBeenCalledWith(
    "http://localhost:8000/api/v1/usda/foods/search?query=raw%20banana&page_size=20",
    expect.any(Object),
  );
  expect(response.foods[0].fdc_id).toBe(1105314);
  expect(response.foods[0].data_type).toBe("Foundation");
});

test("USDA search API normalizes only outbound lean fat ratio query", async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({
      query: "ground beef 80% lean 20% fat",
      page_number: 1,
      page_size: 20,
      total_hits: 0,
      foods: [],
    }),
  });
  const displayedQuery = "ground beef 80/20";

  await searchUsdaFoods(displayedQuery);

  expect(displayedQuery).toBe("ground beef 80/20");
  expect(global.fetch).toHaveBeenCalledWith(
    "http://localhost:8000/api/v1/usda/foods/search?query=ground%20beef%2080%25%20lean%2020%25%20fat&page_size=20",
    expect.any(Object),
  );
});

test("USDA search API sends unchanged queries without unnecessary rewriting", async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({
      query: "1/2 cup milk",
      page_number: 1,
      page_size: 20,
      total_hits: 0,
      foods: [],
    }),
  });

  await searchUsdaFoods("1/2 cup milk");

  expect(global.fetch).toHaveBeenCalledWith(
    "http://localhost:8000/api/v1/usda/foods/search?query=1%2F2%20cup%20milk&page_size=20",
    expect.any(Object),
  );
});

test("invalid lean fat ratio passes through unchanged and accepts empty results", async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({
      query: "ground beef 80/30",
      page_number: 1,
      page_size: 20,
      total_hits: 0,
      foods: [],
    }),
  });

  await expect(searchUsdaFoods("ground beef 80/30")).resolves.toMatchObject({ foods: [] });
  expect(global.fetch).toHaveBeenCalledWith(
    "http://localhost:8000/api/v1/usda/foods/search?query=ground%20beef%2080%2F30&page_size=20",
    expect.any(Object),
  );
});

test("USDA import API posts to import endpoint and returns local food", async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 201,
    json: async () => ({
      id: "food-1",
      name: "Bananas, raw",
      source_type: "usda",
      source_id: "1105314",
      is_recipe: false,
      source_kind: "usda",
      source_label: "USDA",
      is_favorite: false,
      can_favorite: true,
      serving_definitions: [],
      nutrients: [],
    }),
  });

  const food = await importUsdaFood(1105314);

  expect(global.fetch).toHaveBeenCalledWith(
    "http://localhost:8000/api/v1/usda/foods/1105314/import",
    expect.objectContaining({ method: "POST" }),
  );
  expect(food.source_type).toBe("usda");
  expect(food.source_id).toBe("1105314");
});
