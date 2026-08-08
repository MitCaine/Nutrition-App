import { ApiError } from "../src/shared/api/client";
import { z } from "zod";
import { RuntimeError } from "../src/runtime/RuntimeError";
import { mapRemoteError } from "../src/runtime/remote/mapRemoteError";

const responseValidationErrors = [
  ["Invalid Food response", new Error("Invalid Food response")],
  ["Invalid Food source contract", new Error("Invalid Food source contract")],
  ["Invalid recent Food timestamp", new Error("Invalid recent Food timestamp")],
  ["ZodError", new z.ZodError([{ code: "custom", path: ["food"], message: "Internal response contract detail" }])],
] as const;

test("application code takes precedence over HTTP conflict status", () => {
  const error = mapRemoteError(new ApiError({
    status: 409,
    body: {
      detail: {
        code: "invalid_target_request",
        message: "Review targets",
        field_errors: [{ field: "calories", message: "Out of range", code: "range" }],
      },
    },
    message: "Review targets",
  }), "mutation");

  expect(error).toBeInstanceOf(RuntimeError);
  expect(error).toEqual(expect.objectContaining({
    kind: "validation",
    code: "invalid_target_request",
    message: "Review targets",
    retryable: false,
    mutationOutcome: "confirmed_non_commit",
  }));
  expect(error.fieldErrors).toEqual([
    { field: "calories", message: "Out of range", code: "range" },
  ]);
});

test("unresolved mutation outcomes cannot be mistaken for safe replay", () => {
  const coded = mapRemoteError(new ApiError({
    status: 409,
    body: { detail: { code: "log_mutation_unresolved", message: "Pending" } },
    message: "Pending",
  }), "mutation");
  const transient = mapRemoteError(new ApiError({
    status: 503,
    body: null,
    message: "Unavailable",
  }), "mutation");

  expect(coded.mutationOutcome).toBe("unresolved");
  expect(coded.retryable).toBe(false);
  expect(transient.mutationOutcome).toBe("unresolved");
  expect(transient.retryable).toBe(true);
});

test("read failures retain semantic fallback classification without mutation certainty", () => {
  const notFound = mapRemoteError(new ApiError({
    status: 404,
    body: { detail: "Food not found" },
    message: "Food not found",
  }), "read");
  const invalid = mapRemoteError(new Error("Invalid Food response"), "read");

  expect(notFound).toEqual(expect.objectContaining({
    kind: "not_found",
    mutationOutcome: "not_applicable",
  }));
  expect(invalid).toEqual(expect.objectContaining({
    kind: "invalid_response",
    message: "The remote runtime returned an invalid response.",
    mutationOutcome: "not_applicable",
  }));
});

test.each(responseValidationErrors)("%s is a safe invalid response for reads", (_label, cause) => {
  const error = mapRemoteError(cause, "read");

  expect(error).toEqual(expect.objectContaining({
    kind: "invalid_response",
    message: "The remote runtime returned an invalid response.",
    retryable: false,
    mutationOutcome: "not_applicable",
  }));
  expect(error.message).not.toContain("Internal response contract detail");
});

test.each(responseValidationErrors)("%s remains unresolved for mutations", (_label, cause) => {
  expect(mapRemoteError(cause, "mutation")).toEqual(expect.objectContaining({
    kind: "invalid_response",
    message: "The remote runtime returned an invalid response.",
    retryable: false,
    mutationOutcome: "unresolved",
  }));
});

test("transport fallback text never exposes HTTP status or raw response JSON", () => {
  const unavailable = mapRemoteError(new ApiError({
    status: 503,
    body: null,
    message: "Request failed with status 503",
  }), "read");
  const opaque = mapRemoteError(new ApiError({
    status: 409,
    body: { detail: { code: "unknown_conflict", private: true } },
    message: '{"detail":{"private":true}}',
  }), "mutation");

  expect(unavailable.message).toBe("The remote service is unavailable.");
  expect(unavailable.message).not.toContain("503");
  expect(opaque.message).toBe("The request conflicts with current data.");
  expect(opaque.message).not.toContain("private");
});
