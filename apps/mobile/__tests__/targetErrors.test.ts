import { ApiError } from "../src/shared/api/client";
import { targetErrorMessage } from "../src/features/targets/targetErrors";

test("structured target validation errors do not expose raw response JSON", () => {
  const error = new ApiError({ status: 400, body: { detail: { code: "invalid_target_request", field_errors: [{ input: { private: true } }] } }, message: '{"private":true}' });
  const message = targetErrorMessage(error);
  expect(message).toContain("Review");
  expect(message).not.toContain("private");
});
