import { listFavoriteFoods, listFoods, listRecentFoods, setFoodFavorite } from "../src/features/foods/api/foodApi";

const manual = {
  id: "manual-food",
  name: "Manual Food",
  source_type: "manual",
  is_recipe: false,
  source_kind: "manual", source_label: "Manual", is_favorite: false, can_favorite: true,
  serving_definitions: [],
  nutrients: [],
};

const usda = {
  id: "usda-food",
  name: "USDA Food",
  source_type: "usda",
  is_recipe: false,
  source_kind: "usda", source_label: "USDA", is_favorite: false, can_favorite: true,
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

test("favorite and recent contracts map source metadata and timestamps", async () => {
  global.fetch = jest.fn()
    .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ foods: [{ ...manual, is_favorite: true }] }) })
    .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ foods: [{ food: usda, last_used_at: "2026-07-14T12:00:00Z" }] }) })
    .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ ...manual, is_favorite: true }) })
    .mockResolvedValueOnce({ ok: true, status: 200, json: async () => manual });
  await expect(listFavoriteFoods()).resolves.toMatchObject([{ source_kind: "manual", is_favorite: true }]);
  await expect(listRecentFoods()).resolves.toMatchObject([{ food: { source_label: "USDA" }, last_used_at: "2026-07-14T12:00:00Z" }]);
  await setFoodFavorite("manual-food", true); await setFoodFavorite("manual-food", false);
  expect(global.fetch).toHaveBeenNthCalledWith(3, expect.stringContaining("/foods/manual-food/favorite"), expect.objectContaining({ method: "PUT" }));
  expect(global.fetch).toHaveBeenNthCalledWith(4, expect.stringContaining("/foods/manual-food/favorite"), expect.objectContaining({ method: "DELETE" }));
});

test("malformed source kinds and recent timestamps fail safely", async () => {
  global.fetch = jest.fn().mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ foods: [{ ...manual, source_kind: "recommended" }] }) });
  await expect(listFavoriteFoods()).rejects.toThrow("source contract");
  global.fetch = jest.fn().mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ foods: [{ food: manual, last_used_at: "not-a-time" }] }) });
  await expect(listRecentFoods()).rejects.toThrow("timestamp");
});

test("source labels must exactly match the backend-owned source kind", async () => {
  global.fetch = jest.fn().mockResolvedValueOnce({
    ok: true,
    status: 200,
    json: async () => ({ foods: [{ ...manual, source_kind: "legacy", source_label: "Legacy import" }] }),
  });
  await expect(listFavoriteFoods()).rejects.toThrow("source contract");

  global.fetch = jest.fn().mockResolvedValueOnce({
    ok: true,
    status: 200,
    json: async () => ({ foods: [{ ...manual, source_kind: "legacy", source_label: "Other source" }] }),
  });
  await expect(listFavoriteFoods()).resolves.toMatchObject([
    { source_kind: "legacy", source_label: "Other source" },
  ]);
});

test("a converged favorite response cannot render duplicate Food identities", async () => {
  global.fetch = jest.fn().mockResolvedValueOnce({
    ok: true,
    status: 200,
    json: async () => ({ foods: [manual, { ...manual }] }),
  });
  await expect(listFavoriteFoods()).resolves.toEqual([manual]);
});
