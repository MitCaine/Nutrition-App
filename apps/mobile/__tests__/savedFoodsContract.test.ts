import { listFoods } from "../src/features/foods/api/foodApi";

const manual = {
  id: "manual-food",
  name: "Manual Food",
  source_type: "manual",
  is_recipe: false,
  serving_definitions: [],
  nutrients: [],
};

const usda = {
  id: "usda-food",
  name: "USDA Food",
  source_type: "usda",
  is_recipe: false,
  serving_definitions: [],
  nutrients: [],
};

beforeEach(() => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ foods: [manual, usda] }),
  });
});

test("Saved Foods list and search request the explicit ownership-aware view", async () => {
  await expect(listFoods("", "saved")).resolves.toEqual([manual, usda]);
  await expect(listFoods("green chili", "saved")).resolves.toEqual([manual, usda]);

  expect(global.fetch).toHaveBeenNthCalledWith(
    1,
    "http://localhost:8000/api/v1/foods?view=saved",
    expect.any(Object),
  );
  expect(global.fetch).toHaveBeenNthCalledWith(
    2,
    "http://localhost:8000/api/v1/foods?q=green%20chili&view=saved",
    expect.any(Object),
  );
});

test("generic selectors keep the projection-compatible Food-list contract", async () => {
  await listFoods("recipe");

  expect(global.fetch).toHaveBeenCalledWith(
    "http://localhost:8000/api/v1/foods?q=recipe",
    expect.any(Object),
  );
});
