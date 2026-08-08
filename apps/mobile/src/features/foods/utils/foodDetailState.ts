import { RuntimeError } from "../../../runtime/RuntimeError";

export type FoodDetailLoadState =
  | { kind: "loading" }
  | { kind: "unavailable"; message: string }
  | { kind: "error"; message: string }
  | { kind: "ready" };

export function foodDetailLoadState({
  hasData,
  isLoading,
  isError,
  error,
}: {
  hasData: boolean;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
}): FoodDetailLoadState {
  if (hasData) {
    return { kind: "ready" };
  }
  if (isLoading) {
    return { kind: "loading" };
  }
  if (isError && error instanceof RuntimeError && error.kind === "not_found") {
    return { kind: "unavailable", message: "This food is unavailable or has been deleted." };
  }
  if (isError) {
    return {
      kind: "error",
      message: error instanceof RuntimeError && error.message ? error.message : "Could not load food.",
    };
  }
  return { kind: "loading" };
}
