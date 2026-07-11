import { foodDetailLoadState } from "../src/features/foods/utils/foodDetailState";
import { ApiError } from "../src/shared/api/client";

test("food detail distinguishes loading, unavailable, error, and ready states", () => {
  expect(foodDetailLoadState({ hasData: false, isLoading: true, isError: false, error: null })).toEqual({ kind: "loading" });
  expect(foodDetailLoadState({
    hasData: false,
    isLoading: false,
    isError: true,
    error: new ApiError({ status: 404, body: { detail: "Food not found" }, message: "Food not found" }),
  })).toEqual({ kind: "unavailable", message: "This food is unavailable or has been deleted." });
  expect(foodDetailLoadState({
    hasData: false,
    isLoading: false,
    isError: true,
    error: new ApiError({ status: 503, body: null, message: "Service unavailable" }),
  })).toEqual({ kind: "error", message: "Service unavailable" });
  expect(foodDetailLoadState({ hasData: true, isLoading: false, isError: false, error: null })).toEqual({ kind: "ready" });
});
