import { useEffect, useRef, type RefObject } from "react";
import { AccessibilityInfo, findNodeHandle } from "react-native";

export type AccessibilityFocusTarget = object | number;
export type CancelAccessibilityFocus = () => void;

type ScheduledHandle = ReturnType<typeof setTimeout> | number;

export type AccessibilityFocusDriver = {
  resolveHandle: (target: AccessibilityFocusTarget) => number | null;
  focusNativeHandle: (handle: number) => void;
  schedule: (callback: () => void, delayMs: number) => ScheduledHandle;
  cancelScheduled: (handle: ScheduledHandle) => void;
};

export type AccessibilityFocusOptions = {
  delayMs?: number;
  focusKeyboardTarget?: boolean;
};

export type AccessibilityFocusRequester = (
  target: AccessibilityFocusTarget | null | undefined,
  options?: AccessibilityFocusOptions,
) => CancelAccessibilityFocus;

const nativeDriver: AccessibilityFocusDriver = {
  resolveHandle: (target) => typeof target === "number"
    ? target
    : typeof findNodeHandle === "function"
    ? findNodeHandle(target as never)
    : null,
  focusNativeHandle: (handle) => AccessibilityInfo.setAccessibilityFocus(handle),
  schedule: (callback, delayMs) => setTimeout(callback, delayMs),
  cancelScheduled: (handle) => clearTimeout(handle),
};

/** Creates a cancellable focus requester. Driver injection is the deterministic test seam. */
export function createAccessibilityFocusRequester(
  driver: AccessibilityFocusDriver = nativeDriver,
): AccessibilityFocusRequester {
  return (target, options = {}) => {
    if (target == null) return () => undefined;
    let cancelled = false;
    const performFocus = () => {
      if (cancelled) return;
      if (options.focusKeyboardTarget !== false && typeof target === "object" && "focus" in target) {
        const focus = (target as { focus?: unknown }).focus;
        if (typeof focus === "function") focus.call(target);
      }
      const handle = driver.resolveHandle(target);
      if (handle !== null) driver.focusNativeHandle(handle);
    };
    const delayMs = options.delayMs ?? 60;
    if (delayMs <= 0) {
      performFocus();
      return () => { cancelled = true; };
    }
    const scheduled = driver.schedule(performFocus, delayMs);
    return () => {
      cancelled = true;
      driver.cancelScheduled(scheduled);
    };
  };
}

export const focusAccessibilityElement = createAccessibilityFocusRequester();

type ScreenFocusOptions = {
  active: boolean;
  routeKey: string;
  targetRef: RefObject<AccessibilityFocusTarget | null>;
  delayMs?: number;
  requestFocus?: AccessibilityFocusRequester;
};

/** Focuses once for each activation, never for ordinary rerenders or refreshes. */
export function useAccessibilityScreenFocus({
  active,
  routeKey,
  targetRef,
  delayMs,
  requestFocus = focusAccessibilityElement,
}: ScreenFocusOptions) {
  const focusedActivation = useRef<string | null>(null);
  useEffect(() => {
    if (!active) {
      focusedActivation.current = null;
      return;
    }
    if (focusedActivation.current === routeKey) return;
    focusedActivation.current = routeKey;
    return requestFocus(targetRef.current, { delayMs, focusKeyboardTarget: false });
  }, [active, delayMs, requestFocus, routeKey, targetRef]);
}

export function firstAvailableAccessibilityTarget(
  preferred: AccessibilityFocusTarget | null | undefined,
  fallback: AccessibilityFocusTarget | null | undefined,
): AccessibilityFocusTarget | null {
  return preferred ?? fallback ?? null;
}
