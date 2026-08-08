import { ApiError } from "./runtimeErrorTestSupport";
import { userFacingEpicOneError } from "../src/shared/errors/userFacingError";

test("known domain failures become bounded guidance with a validation target", () => {
  const error = new ApiError({
    status: 409,
    body: { detail: { code: "calendar_context_changed", message: "RAW_SERVER_DETAIL" } },
    message: "RAW_TRANSPORT_DETAIL",
  });
  const result = userFacingEpicOneError(error, { fallbackSummary: "Could not save changes." });

  expect(result).toEqual(expect.objectContaining({
    code: "calendar_context_changed",
    summary: "Your calendar settings changed while this screen was open.",
    recoveryInstruction: "Review the current date and try again.",
    severity: "warning",
    target: "date",
  }));
  expect(JSON.stringify(result)).not.toContain("RAW_SERVER_DETAIL");
  expect(JSON.stringify(result)).not.toContain("RAW_TRANSPORT_DETAIL");
});

test("unknown failures use the supplied safe fallback instead of exception text", () => {
  const result = userFacingEpicOneError(new Error("token=secret"), {
    fallbackSummary: "Target comparisons are unavailable.",
    recoveryInstruction: "Try loading target comparisons again.",
  });
  expect(result.summary).toBe("Target comparisons are unavailable.");
  expect(result.recoveryInstruction).toBe("Try loading target comparisons again.");
  expect(JSON.stringify(result)).not.toContain("token=secret");
});
