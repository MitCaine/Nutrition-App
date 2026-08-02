import { ApiError } from "../src/shared/api/client";
import { isDeleteReconciliationRequired, isUncertainDeleteError } from "../src/features/logging/utils/logDeleteErrors";

test("delete treats transport and server failures as uncertain until reconciled", () => {
  expect(isUncertainDeleteError(new Error("connection lost"))).toBe(true);
  expect(isUncertainDeleteError(new ApiError({ status: 503, body: null, message: "unavailable" }))).toBe(true);
  expect(isDeleteReconciliationRequired(new ApiError({
    status: 409,
    body: { detail: { code: "log_mutation_unresolved", message: "pending" } },
    message: "pending",
  }))).toBe(true);
});

test("stable stale conflicts do not enter uncertain recovery", () => {
  expect(isUncertainDeleteError(new ApiError({
    status: 409,
    body: { detail: { code: "stale_log_entry", message: "changed" } },
    message: "changed",
  }))).toBe(false);
  expect(isDeleteReconciliationRequired(new ApiError({
    status: 409,
    body: { detail: { code: "stale_log_entry", message: "changed" } },
    message: "changed",
  }))).toBe(false);
});
