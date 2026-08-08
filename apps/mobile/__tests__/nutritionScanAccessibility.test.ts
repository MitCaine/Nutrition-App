import React from "react";
import { Pressable } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

jest.mock("expo-file-system", () => ({ deleteAsync: jest.fn() }));
jest.mock("expo-image-picker", () => ({
  requestCameraPermissionsAsync: jest.fn(),
  requestMediaLibraryPermissionsAsync: jest.fn(),
  launchCameraAsync: jest.fn(),
  launchImageLibraryAsync: jest.fn(),
}));
jest.mock("../src/native/ocr/NutritionOcr", () => ({ recognizeTextFromImage: jest.fn() }));
jest.mock("../src/features/ocr/api/ocrApi", () => ({ parseNutritionLabel: jest.fn() }));
jest.mock("../src/app/theme/AppTheme", () => {
  const actual = jest.requireActual("../src/app/theme/AppTheme");
  return { ...actual, useAppTheme: () => ({ ...actual.LIGHT_THEME, preference: "system", effectiveScheme: "light", setPreference: jest.fn() }) };
});

import { NutritionScanScreen } from "../src/features/ocr/screens/NutritionScanScreen";

test("iOS label acquisition exposes a focused heading and contextual camera actions", async () => {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(NutritionScanScreen, {
      onCancel: jest.fn(),
      onReady: jest.fn(),
    }));
  });
  expect(renderer.root.findByProps({ accessibilityRole: "header", children: "Scan nutrition label" })).toBeDefined();
  const actions = renderer.root.findAllByType(Pressable);
  const choose = actions.find((node) => node.props.accessibilityLabel === "Choose nutrition label photo")!;
  const camera = actions.find((node) => node.props.accessibilityLabel === "Take nutrition label photo")!;
  expect(choose.props.accessibilityHint).toContain("iOS photo library");
  expect(camera.props.accessibilityHint).toContain("iOS camera");
  expect(actions.find((node) => node.props.accessibilityLabel === "Cancel label scan")).toBeDefined();
  await act(async () => renderer.unmount());
});
