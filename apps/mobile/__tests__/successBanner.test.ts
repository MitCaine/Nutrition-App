import React from "react";
import TestRenderer, { act } from "react-test-renderer";

import { scheduleBannerExpiration, SUCCESS_BANNER_DURATION_MS, TransientSuccessBanner } from "../src/shared/components/TransientSuccessBanner";

afterEach(() => jest.useRealTimers());

test("success banner expires after approximately five seconds", () => {
  jest.useFakeTimers();
  const expired = jest.fn();
  scheduleBannerExpiration(expired);
  jest.advanceTimersByTime(SUCCESS_BANNER_DURATION_MS - 1);
  expect(expired).not.toHaveBeenCalled();
  jest.advanceTimersByTime(1);
  expect(expired).toHaveBeenCalledTimes(1);
});

test("replacing a banner can cancel the old expiration", () => {
  jest.useFakeTimers();
  const oldExpired = jest.fn();
  const cancel = scheduleBannerExpiration(oldExpired);
  cancel();
  jest.advanceTimersByTime(SUCCESS_BANNER_DURATION_MS);
  expect(oldExpired).not.toHaveBeenCalled();
});

test("success banner announces changed outcomes and cleans up obsolete requests", async () => {
  const firstCancel = jest.fn();
  const secondCancel = jest.fn();
  const announcer = jest.fn()
    .mockReturnValueOnce(firstCancel)
    .mockReturnValueOnce(secondCancel);
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(TransientSuccessBanner, {
      message: "Food saved",
      announcer,
    }));
  });
  expect(announcer).toHaveBeenCalledWith("Food saved", expect.objectContaining({ kind: "success" }));
  await act(async () => {
    renderer.update(React.createElement(TransientSuccessBanner, {
      message: "Entry moved",
      announcer,
    }));
  });
  expect(firstCancel).toHaveBeenCalledTimes(1);
  expect(announcer).toHaveBeenCalledTimes(2);
  await act(async () => renderer.unmount());
  expect(secondCancel).toHaveBeenCalledTimes(1);
});

test("success banner can be dismissed immediately", async () => {
  const expired = jest.fn();
  let renderer!: TestRenderer.ReactTestRenderer;

  await act(async () => {
    renderer = TestRenderer.create(React.createElement(TransientSuccessBanner, {
      message: "Food saved",
      onExpired: expired,
    }));
  });

  const dismissButton = renderer.root.findAll(
      (node) =>
          node.props.accessibilityLabel === "Dismiss confirmation"
          && typeof node.props.onPress === "function",
  )[0];

  expect(dismissButton).toBeDefined();

  await act(async () => {
    dismissButton.props.onPress();
  });

  expect(expired).toHaveBeenCalledTimes(1);

  await act(async () => renderer.unmount());
});

test("success banner expiration is not extended by callback rerenders", async () => {
  jest.useFakeTimers();

  const firstExpired = jest.fn();
  const latestExpired = jest.fn();
  let renderer!: TestRenderer.ReactTestRenderer;

  await act(async () => {
    renderer = TestRenderer.create(React.createElement(TransientSuccessBanner, {
      message: "Food saved",
      onExpired: firstExpired,
    }));
  });

  await act(async () => {
    jest.advanceTimersByTime(SUCCESS_BANNER_DURATION_MS - 1);
  });

  await act(async () => {
    renderer.update(React.createElement(TransientSuccessBanner, {
      message: "Food saved",
      onExpired: latestExpired,
    }));
  });

  await act(async () => {
    jest.advanceTimersByTime(1);
  });

  expect(firstExpired).not.toHaveBeenCalled();
  expect(latestExpired).toHaveBeenCalledTimes(1);

  await act(async () => renderer.unmount());
});
