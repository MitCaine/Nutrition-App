import React from "react";
import { Linking, Pressable } from "react-native";
import * as ImagePicker from "expo-image-picker";
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
import { withNutritionRuntime } from "./nutritionRuntimeTestSupport";

test("iOS label acquisition exposes a focused heading and contextual camera actions", async () => {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(withNutritionRuntime(React.createElement(NutritionScanScreen, {
      onCancel: jest.fn(),
      onReady: jest.fn(),
    })));
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

test("permission denial offers a direct route to app settings", async () => {
  const openSettings = jest.spyOn(Linking, "openSettings").mockResolvedValue();
  (ImagePicker.requestCameraPermissionsAsync as jest.Mock).mockResolvedValue({ granted: false });

  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(withNutritionRuntime(React.createElement(NutritionScanScreen, {
      onCancel: jest.fn(),
      onReady: jest.fn(),
    })));
  });

  const camera = renderer.root.findAllByType(Pressable)
    .find((node) => node.props.accessibilityLabel === "Take nutrition label photo")!;

  await act(async () => {
    await camera.props.onPress();
  });

  const settings = renderer.root.findAllByType(Pressable)
    .find((node) => node.props.accessibilityLabel === "Open app settings")!;
  expect(settings).toBeDefined();
  expect(settings.props.accessibilityHint).toContain("camera or photo access");

  await act(async () => {
    settings.props.onPress();
  });
  expect(openSettings).toHaveBeenCalledTimes(1);

  await act(async () => renderer.unmount());
  openSettings.mockRestore();
});

test("retake mode opens the camera once and camera cancellation leaves scan controls recoverable", async () => {
  jest.clearAllMocks();
  (ImagePicker.requestCameraPermissionsAsync as jest.Mock).mockResolvedValue({ granted: true });
  (ImagePicker.launchCameraAsync as jest.Mock).mockResolvedValue({ canceled: true, assets: null });

  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(withNutritionRuntime(React.createElement(NutritionScanScreen, {
      autoAcquireCamera: true,
      onCancel: jest.fn(),
      onReady: jest.fn(),
    })));
    await Promise.resolve();
    await Promise.resolve();
  });

  expect(ImagePicker.requestCameraPermissionsAsync).toHaveBeenCalledTimes(1);
  expect(ImagePicker.launchCameraAsync).toHaveBeenCalledTimes(1);

  const actions = renderer.root.findAllByType(Pressable);
  expect(actions.find((node) => node.props.accessibilityLabel === "Choose nutrition label photo")?.props.disabled).toBe(false);
  expect(actions.find((node) => node.props.accessibilityLabel === "Take nutrition label photo")?.props.disabled).toBe(false);
  expect(actions.find((node) => node.props.accessibilityLabel === "Cancel label scan")?.props.disabled).toBe(false);

  await act(async () => {
    renderer.update(withNutritionRuntime(React.createElement(NutritionScanScreen, {
      autoAcquireCamera: true,
      onCancel: jest.fn(),
      onReady: jest.fn(),
    })));
    await Promise.resolve();
  });
  expect(ImagePicker.launchCameraAsync).toHaveBeenCalledTimes(1);

  await act(async () => renderer.unmount());
});
