import { useEffect } from "react";

export type DraftStatus = {
  dirty: boolean;
  busy: boolean;
};

export type DraftStatusReporter = (
  key: string,
  status: DraftStatus,
) => void;

export const CLEAN_DRAFT_STATUS: DraftStatus = {
  dirty: false,
  busy: false,
};

export type DraftExitDecision =
  | "allow"
  | "confirm-discard"
  | "blocked-busy";

export function draftExitDecision(
  statuses: ReadonlyArray<DraftStatus | null | undefined>,
): DraftExitDecision {
  if (statuses.some((status) => status?.busy)) {
    return "blocked-busy";
  }
  if (statuses.some((status) => status?.dirty)) {
    return "confirm-discard";
  }
  return "allow";
}

export function draftObjectsEqual<T>(left: T, right: T): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function useDraftStatusReporter({
  draftKey,
  dirty,
  busy,
  reporter,
}: {
  draftKey?: string;
  dirty: boolean;
  busy: boolean;
  reporter?: DraftStatusReporter;
}) {
  useEffect(() => {
    if (!draftKey || !reporter) return;
    reporter(draftKey, { dirty, busy });
  }, [busy, dirty, draftKey, reporter]);

  useEffect(() => {
    if (!draftKey || !reporter) return;
    return () => {
      reporter(draftKey, CLEAN_DRAFT_STATUS);
    };
  }, [draftKey, reporter]);
}
