import { MutationObserver, QueryClient } from "@tanstack/react-query";

import type { DailyLog, DailyLogCreateInput } from "../src/features/logging/api/types";

test("an externally configured automatic mutation retry retains the same request ID", async () => {
  const input: DailyLogCreateInput = {
    client_request_id: "00000000-0000-4000-8000-000000000099",
    food_item_id: "food-1",
    logged_date: "2026-07-14",
    amount_quantity: "1",
    amount_unit: "serving",
    serving_definition_id: "serving-1",
  };
  const response: DailyLog = {
    id: "log-1",
    food_item_id: input.food_item_id,
    source_food_available: true,
    logged_date: input.logged_date,
    amount_quantity: input.amount_quantity,
    amount_unit: input.amount_unit,
    serving_definition_id: input.serving_definition_id,
  };
  const mutationFn = jest.fn()
    .mockRejectedValueOnce(new Error("ambiguous transport failure"))
    .mockResolvedValueOnce(response);
  const queryClient = new QueryClient({
    defaultOptions: {
      mutations: { retry: 1, retryDelay: 0 },
    },
  });
  const mutation = new MutationObserver<DailyLog, Error, DailyLogCreateInput>(
    queryClient,
    { mutationFn },
  );

  await expect(mutation.mutate(input)).resolves.toEqual(response);

  expect(mutationFn).toHaveBeenCalledTimes(2);
  expect(mutationFn.mock.calls[0][0]).toEqual(input);
  expect(mutationFn.mock.calls[1][0]).toEqual(input);
  expect(mutationFn.mock.calls[1][0].client_request_id).toBe(input.client_request_id);
  queryClient.clear();
});
