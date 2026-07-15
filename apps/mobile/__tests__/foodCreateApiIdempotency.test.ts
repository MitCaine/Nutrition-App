import {
  createFood,
  createFoodServing,
  duplicateFood,
} from "../src/features/foods/api/foodApi";

const responseFood = {
  id: "food-1",
  name: "Food",
  source_type: "manual",
  is_recipe: false,
  source_kind: "manual",
  source_label: "Manual",
  is_favorite: false,
  can_favorite: true,
  serving_definitions: [],
  nutrients: [],
};

beforeEach(() => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 201,
    json: async () => responseFood,
  });
});

test("Food create APIs transmit client request IDs in their central request bodies", async () => {
  await createFood({
    client_request_id: "food-request",
    name: "Food",
    serving_definitions: [
      { label: "1 portion", quantity: "1", unit: "portion", is_default: true },
    ],
    nutrients: [],
  });
  await duplicateFood({ foodId: "food-1", clientRequestId: "duplicate-request" });
  await createFoodServing("food-1", {
    client_request_id: "serving-request",
    label: "1 slice",
    quantity: "1",
    unit: "slice",
    is_default: false,
  });

  const bodies = (global.fetch as jest.Mock).mock.calls.map((call) => JSON.parse(call[1].body));
  expect(bodies[0].client_request_id).toBe("food-request");
  expect(bodies[1]).toEqual({ client_request_id: "duplicate-request" });
  expect(bodies[2].client_request_id).toBe("serving-request");
});
