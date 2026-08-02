import React from "react";
import { Pressable, StyleSheet, Text } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import { AccessiblePressable } from "../src/shared/accessibility/AccessiblePressable";
import { AccessibilityStatus } from "../src/shared/accessibility/AccessibilityStatus";

test("semantic failure state exposes an alert and contextual retry action", async () => {
  const retry = jest.fn();
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(AccessibilityStatus, {
      kind: "initial-failure",
      message: "Target comparisons are unavailable.",
      retryContext: "target comparisons",
      onRetry: retry,
    }));
  });
  const message = renderer.root.findAllByType(Text).find((node) => node.props.accessibilityRole === "alert");
  expect(message?.props.accessibilityLabel).toBe("Target comparisons are unavailable.");
  expect(message?.props.accessibilityLiveRegion).toBe("assertive");
  const action = renderer.root.findByType(Pressable);
  expect(action.props.accessibilityLabel).toBe("Retry target comparisons");
  await act(async () => action.props.onPress());
  expect(retry).toHaveBeenCalledTimes(1);
  await act(async () => renderer.unmount());
});

test("stale and busy states expose distinct semantics without announcing routine refresh", async () => {
  const announce = jest.fn(() => jest.fn());
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(React.Fragment, null,
      React.createElement(AccessibilityStatus, {
        kind: "stale",
        message: "Showing the last confirmed totals.",
        announce,
        announcementKey: "totals",
      }),
      React.createElement(AccessibilityStatus, {
        kind: "refreshing",
        message: "Refreshing totals.",
        announce,
        announcementKey: "refresh",
      }),
      React.createElement(AccessibilityStatus, {
        kind: "busy",
        message: "Saving entry.",
      }),
    ));
  });
  expect(announce).toHaveBeenCalledTimes(1);
  expect(announce).toHaveBeenCalledWith("Showing the last confirmed totals.", expect.objectContaining({ kind: "stale" }));
  const stale = renderer.root.findAllByType(Text).find((node) => node.props.accessibilityLabel === "Showing the last confirmed totals.");
  const refreshing = renderer.root.findAllByType(Text).find((node) => node.props.accessibilityLabel === "Refreshing totals.");
  expect(stale?.props.accessibilityLiveRegion).toBe("none");
  expect(refreshing?.props.accessibilityLiveRegion).toBe("none");
  const busy = renderer.root.findAllByType(Text).find((node) => node.props.accessibilityLabel === "Saving entry.");
  expect(busy?.props.accessibilityState).toEqual({ busy: true, disabled: true });
  expect(busy?.props.accessibilityLiveRegion).toBe("polite");
  await act(async () => renderer.unmount());
});

test("explicit failure announcements retain alert role but disable native live announcement", async () => {
  const announce = jest.fn(() => jest.fn());
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(AccessibilityStatus, {
      kind: "initial-failure",
      message: "Entries are unavailable.",
      announce,
      announcementKey: "entries",
    }));
  });
  const message = renderer.root.findByType(Text);
  expect(message.props.accessibilityRole).toBe("alert");
  expect(message.props.accessibilityLiveRegion).toBe("none");
  expect(announce).toHaveBeenCalledTimes(1);
  await act(async () => renderer.unmount());
});

test("native stale and unavailable states retain polite semantics without an explicit service", async () => {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(React.Fragment, null,
      React.createElement(AccessibilityStatus, {
        kind: "stale",
        message: "Showing confirmed entries.",
      }),
      React.createElement(AccessibilityStatus, {
        kind: "unavailable",
        message: "Totals are unavailable.",
      }),
    ));
  });
  const statuses = renderer.root.findAllByType(Text);
  expect(statuses.find((node) => node.props.accessibilityLabel === "Showing confirmed entries.")?.props.accessibilityLiveRegion).toBe("polite");
  expect(statuses.find((node) => node.props.accessibilityLabel === "Totals are unavailable.")?.props.accessibilityLiveRegion).toBe("polite");
  await act(async () => renderer.unmount());
});

test("accessible pressable enforces the target contract and blocks disabled activation", async () => {
  const onPress = jest.fn();
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(AccessiblePressable, {
      accessibilityLabel: "Retry totals",
      disabled: true,
      onPress,
    }, React.createElement(Text, null, "Retry")));
  });
  const pressable = renderer.root.findByType(Pressable);
  const flattened = StyleSheet.flatten(pressable.props.style);
  expect(flattened.minHeight).toBe(44);
  expect(flattened.minWidth).toBe(44);
  expect(pressable.props.accessibilityRole).toBe("button");
  expect(pressable.props.accessibilityState).toEqual(expect.objectContaining({ disabled: true }));
  expect(pressable.props.onPress).toBeUndefined();
  expect(onPress).not.toHaveBeenCalled();
  await act(async () => renderer.unmount());
});
