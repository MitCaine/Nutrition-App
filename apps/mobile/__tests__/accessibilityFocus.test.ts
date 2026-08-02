import React, { createRef } from "react";
import TestRenderer, { act } from "react-test-renderer";

import {
  createAccessibilityFocusRequester,
  useAccessibilityScreenFocus,
} from "../src/shared/accessibility/focus";

afterEach(() => jest.useRealTimers());

test("a screen focus request occurs once per active route and not on refresh rerenders", async () => {
  const requestFocus = jest.fn(() => jest.fn());
  const targetRef = createRef<object>();
  targetRef.current = {};

  function Harness({ active, routeKey, refresh }: { active: boolean; routeKey: string; refresh: number }) {
    useAccessibilityScreenFocus({ active, routeKey, targetRef, requestFocus });
    return React.createElement("harness", { refresh });
  }

  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(Harness, { active: true, routeKey: "foods", refresh: 0 }));
  });
  await act(async () => {
    renderer.update(React.createElement(Harness, { active: true, routeKey: "foods", refresh: 1 }));
  });
  expect(requestFocus).toHaveBeenCalledTimes(1);

  await act(async () => {
    renderer.update(React.createElement(Harness, { active: false, routeKey: "foods", refresh: 1 }));
    renderer.update(React.createElement(Harness, { active: true, routeKey: "daily-log", refresh: 1 }));
  });
  expect(requestFocus).toHaveBeenCalledTimes(2);
  await act(async () => renderer.unmount());
});

test("a delayed focus request is cancelled on unmount", () => {
  jest.useFakeTimers();
  const focusNativeHandle = jest.fn();
  const requester = createAccessibilityFocusRequester({
    resolveHandle: () => 42,
    focusNativeHandle,
    schedule: (callback, delayMs) => setTimeout(callback, delayMs),
    cancelScheduled: (timer) => clearTimeout(timer as ReturnType<typeof setTimeout>),
  });

  const cancel = requester({ focus: jest.fn() }, { delayMs: 50 });
  cancel();
  jest.advanceTimersByTime(50);

  expect(focusNativeHandle).not.toHaveBeenCalled();
});
