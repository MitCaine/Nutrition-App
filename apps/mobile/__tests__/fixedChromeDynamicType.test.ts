import React from "react";
import {
  Pressable,
  StyleSheet,
  Text,
} from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import { BottomNavigation } from "../src/app/navigation/BottomNavigation";
import { RootScreenHeader } from "../src/shared/components/RootScreenHeader";
import {
  RouteHeaderAction,
  RouteScreenHeader,
} from "../src/shared/components/RouteScreenHeader";

jest.mock("@expo/vector-icons", () => ({ Ionicons: "Ionicons" }));
jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ bottom: 34, left: 0, right: 0, top: 0 }),
}));
jest.mock("../src/app/theme/AppTheme", () => {
  const actual = jest.requireActual("../src/app/theme/AppTheme");
  return { ...actual, useAppTheme: () => ({ ...actual.LIGHT_THEME, preference: "system", effectiveScheme: "light", setPreference: jest.fn() }) };
});

function textContent(node: TestRenderer.ReactTestInstance | string): string {
  return typeof node === "string" ? node : node.children.map((child) => textContent(child as TestRenderer.ReactTestInstance | string)).join("");
}

test("fixed root chrome caps visual text growth while preserving accessible controls", async () => {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(React.Fragment, null,
      React.createElement(RootScreenHeader, { title: "Saved Foods", onOpenSettings: jest.fn() }),
      React.createElement(RouteScreenHeader, {
        title: "Nutrition targets",
        trailing: React.createElement(RouteHeaderAction, {
          accessibilityLabel: "Cancel nutrition targets",
          label: "Cancel",
          onPress: jest.fn(),
        }),
      }),
      React.createElement(BottomNavigation, { activeTab: "foods", onSelect: jest.fn() }),
    ));
  });
  const cappedLabels = renderer.root.findAllByType(Text)
    .filter((node) => node.props.maxFontSizeMultiplier === 1.5)
    .map(textContent);
  expect(cappedLabels).toEqual(expect.arrayContaining([
    "Saved Foods",
    "Nutrition targets",
    "Cancel",
    "Foods",
    "Daily Log",
    "Recipes",
  ]));
  await act(async () => renderer.unmount());
});

test("#108 route chrome supports long titles and preserves busy presentation", async () => {
  let renderer!: TestRenderer.ReactTestRenderer;

  await act(async () => {
    renderer = TestRenderer.create(
      React.createElement(
        RouteScreenHeader,
        {
          title:
            "A deliberately long route title that must remain readable on a narrow screen",
          trailing: React.createElement(
            RouteHeaderAction,
            {
              accessibilityLabel:
                "Cancel pending mutation",
              busy: true,
              disabled: true,
              label: "Cancel",
              onPress: jest.fn(),
            },
          ),
        },
      ),
    );
  });

  const title = renderer.root
    .findAllByType(Text)
    .find((node) =>
      textContent(node).startsWith(
        "A deliberately long route title",
      ),
    )!;

  expect(
    StyleSheet.flatten(title.props.style),
  ).toMatchObject({
    flex: 1,
    flexShrink: 1,
    minWidth: 0,
  });

  expect(
    title.props.maxFontSizeMultiplier,
  ).toBe(1.5);

  expect(
    title.props.numberOfLines,
  ).toBeUndefined();

  const action = renderer.root
    .findAllByType(Pressable)
    .find(
      (node) =>
        node.props.accessibilityLabel
        === "Cancel pending mutation",
    )!;

  expect(
    action.props.accessibilityState,
  ).toMatchObject({
    busy: true,
    disabled: true,
  });

  expect(
    StyleSheet.flatten(
      typeof action.props.style === "function"
        ? action.props.style({
            pressed: false,
          })
        : action.props.style,
    ),
  ).toMatchObject({
    minHeight: 44,
    opacity: 0.55,
  });

  expect(action.props.onPress).toBeUndefined();

  await act(async () =>
    renderer.unmount(),
  );
});
