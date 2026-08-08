import { ApiError as HttpApiError } from "../src/shared/api/client";
import { RuntimeError } from "../src/runtime/RuntimeError";
import { mapRemoteError } from "../src/runtime/remote/mapRemoteError";

/** Compatibility-shaped fixture that feeds HTTP failures through the remote boundary. */
export class ApiError extends RuntimeError {
  constructor(input: { status: number; body: unknown; message: string }) {
    const mapped = mapRemoteError(new HttpApiError(input), "mutation");
    super({
      kind: mapped.kind,
      code: mapped.code,
      message: mapped.message,
      fieldErrors: mapped.fieldErrors,
      retryable: mapped.retryable,
      mutationOutcome: mapped.mutationOutcome,
      details: mapped.details,
    });
  }
}
