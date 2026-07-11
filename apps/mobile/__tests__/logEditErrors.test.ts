import { logEditErrorMessage } from "../src/features/logging/utils/logEditErrors";
import { ApiError } from "../src/shared/api/client";

test("structured deleted-source conflict returns the backend message", () => {
  const error = new ApiError({
    status: 409,
    body: {
      detail: {
        code: "source_food_deleted",
        message: "This historical entry cannot be edited because its source food was deleted.",
      },
    },
    message: "Request failed with status 409",
  });

  expect(logEditErrorMessage(error)).toBe(
    "This historical entry cannot be edited because its source food was deleted.",
  );
});

test("log edit errors use useful API messages and safe fallbacks", () => {
  expect(logEditErrorMessage(new ApiError({ status: 500, body: null, message: "Server unavailable" }))).toBe(
    "Server unavailable",
  );
  expect(logEditErrorMessage(new Error("network"))).toBe("Could not save changes.");
});
