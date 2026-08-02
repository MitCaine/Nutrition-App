import { useEffect, useMemo } from "react";
import { AccessibilityInfo, Platform } from "react-native";

export type AccessibilityAnnouncementPriority = "polite" | "assertive";
export type AccessibilityAnnouncementKind =
  | "success"
  | "warning"
  | "error"
  | "stale"
  | "review-required"
  | "mutation-outcome";

type ScheduledHandle = ReturnType<typeof setTimeout> | number;

export type AccessibilityAnnouncementOptions = {
  key?: string;
  kind?: AccessibilityAnnouncementKind;
  priority?: AccessibilityAnnouncementPriority;
  dedupeMs?: number;
  delayMs?: number;
};

type AnnouncementDriver = {
  announceNative: (message: string, priority: AccessibilityAnnouncementPriority) => void;
  now: () => number;
  schedule: (callback: () => void, delayMs: number) => ScheduledHandle;
  cancelScheduled: (handle: ScheduledHandle) => void;
};

export type CancelAccessibilityAnnouncement = (() => void) & {
  isPending?: () => boolean;
  onSettled?: (listener: () => void) => () => void;
};
export type AccessibilityAnnouncer = (
  message: string,
  options?: AccessibilityAnnouncementOptions,
) => CancelAccessibilityAnnouncement;

const nativeDriver: AnnouncementDriver = {
  announceNative: (message, priority) => {
    const info = AccessibilityInfo as typeof AccessibilityInfo & {
      announceForAccessibilityWithOptions?: (value: string, options: { queue?: boolean }) => void;
    };
    if (Platform.OS === "ios" && info.announceForAccessibilityWithOptions) {
      info.announceForAccessibilityWithOptions(message, { queue: priority === "polite" });
      return;
    }
    AccessibilityInfo.announceForAccessibility(message);
  },
  now: () => Date.now(),
  schedule: (callback, delayMs) => setTimeout(callback, delayMs),
  cancelScheduled: (handle) => clearTimeout(handle),
};

const MAX_DEDUPE_ENTRIES = 100;

function createAnnouncementCancellation(cancelPendingWork: () => void) {
  let state: "pending" | "completed" | "cancelled" = "pending";
  const listeners = new Set<() => void>();
  const settle = (next: "completed" | "cancelled") => {
    if (state !== "pending") return;
    state = next;
    listeners.forEach((listener) => listener());
    listeners.clear();
  };
  const cancel = (() => {
    if (state !== "pending") return;
    cancelPendingWork();
    settle("cancelled");
  }) as CancelAccessibilityAnnouncement;
  cancel.isPending = () => state === "pending";
  cancel.onSettled = (listener) => {
    if (state !== "pending") {
      listener();
      return () => undefined;
    }
    listeners.add(listener);
    return () => listeners.delete(listener);
  };
  return { cancel, complete: () => settle("completed") };
}

/** Creates a bounded announcer. Driver injection keeps tests independent of native timing. */
export function createAccessibilityAnnouncer(
  driver: AnnouncementDriver = nativeDriver,
): AccessibilityAnnouncer {
  const recent = new Map<string, { message: string; announcedAt: number }>();
  return (rawMessage, options = {}) => {
    const message = rawMessage.trim();
    let scheduled: ScheduledHandle | null = null;
    const ownership = createAnnouncementCancellation(() => {
      if (scheduled !== null) driver.cancelScheduled(scheduled);
      scheduled = null;
    });
    if (!message) {
      ownership.complete();
      return ownership.cancel;
    }
    const dispatch = () => {
      if (!ownership.cancel.isPending?.()) return;
      const key = options.key ?? message;
      const previous = recent.get(key);
      const now = driver.now();
      if (
        previous?.message === message &&
        now - previous.announcedAt < (options.dedupeMs ?? 1500)
      ) {
        scheduled = null;
        ownership.complete();
        return;
      }
      if (!recent.has(key) && recent.size >= MAX_DEDUPE_ENTRIES) {
        const oldestKey = recent.keys().next().value as string | undefined;
        if (oldestKey !== undefined) recent.delete(oldestKey);
      }
      recent.delete(key);
      recent.set(key, { message, announcedAt: now });
      driver.announceNative(
        message,
        options.priority ?? (options.kind === "error" ? "assertive" : "polite"),
      );
      scheduled = null;
      ownership.complete();
    };
    if ((options.delayMs ?? 0) > 0) {
      scheduled = driver.schedule(dispatch, options.delayMs!);
    } else {
      dispatch();
    }
    return ownership.cancel;
  };
}

export const announceAccessibility = createAccessibilityAnnouncer();

/** Explicit owner used by hooks and deterministic lifecycle tests. */
export function createAccessibilityAnnouncementOwner(announcer: AccessibilityAnnouncer) {
  const pending = new Set<CancelAccessibilityAnnouncement>();
  const subscriptions = new Map<CancelAccessibilityAnnouncement, () => void>();
  const announce = (message: string, options?: AccessibilityAnnouncementOptions) => {
    const request = announcer(message, options);
    if (request.isPending?.()) {
      pending.add(request);
      const unsubscribe = request.onSettled?.(() => {
        pending.delete(request);
        subscriptions.delete(request);
      });
      if (unsubscribe) subscriptions.set(request, unsubscribe);
    }
    let released = false;
    return () => {
      if (released) return;
      released = true;
      subscriptions.get(request)?.();
      subscriptions.delete(request);
      request();
      pending.delete(request);
    };
  };
  return {
    announce,
    cancelAll() {
      [...pending].forEach((request) => request());
      pending.clear();
      subscriptions.forEach((unsubscribe) => unsubscribe());
      subscriptions.clear();
    },
    pendingCount: () => pending.size,
  };
}

/** Owns only genuinely pending announcements for the calling component. */
export function useAccessibilityAnnouncement(announcer = announceAccessibility) {
  const owner = useMemo(() => createAccessibilityAnnouncementOwner(announcer), [announcer]);
  useEffect(() => () => owner.cancelAll(), [owner]);
  return owner.announce;
}
