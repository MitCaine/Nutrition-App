import { ApiError } from "../src/shared/api/client";
import { confirmationErrorMessage } from "../src/features/ocr/confirmation/confirmationErrors";

test("structured idempotency conflict is actionable and never displays raw JSON", () => {
  const error = new ApiError({ status: 409, body: { detail: { code: "ocr_confirmation_idempotency_conflict", payload: { raw: true } } }, message: "raw backend text" });
  const message = confirmationErrorMessage(error);
  expect(message).toContain("form changed");
  expect(message).toContain("new confirmation attempt");
  expect(message).not.toContain("payload");
});

test("confirmation validation errors receive a review message", () => {
  const error = new ApiError({ status: 400, body: { detail: { code: "invalid_ocr_confirmation_request" } }, message: "raw" });
  expect(confirmationErrorMessage(error)).toContain("confirmed values are invalid");
});

test("parse request errors direct the user back to scanning", () => {
  const error = new ApiError({ status: 400, body: { detail: { code: "invalid_ocr_parse_request" } }, message: "raw" });
  expect(confirmationErrorMessage(error)).toContain("Return to scanning");
});
