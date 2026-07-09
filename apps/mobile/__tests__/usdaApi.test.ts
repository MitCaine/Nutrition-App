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
