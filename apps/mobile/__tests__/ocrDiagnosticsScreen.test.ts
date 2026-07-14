import React from "react";
import { Image, Pressable, StyleSheet, Switch, Text, View } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

const mockRequestPhotoPermission = jest.fn();
const mockRequestCameraPermission = jest.fn();
const mockLaunchPicker = jest.fn();
const mockLaunchCamera = jest.fn();
const mockDeleteAsync = jest.fn();
const mockRecognizeTextFromImage = jest.fn();

jest.mock("@expo/vector-icons", () => ({ Ionicons: "Ionicons" }));
jest.mock("expo-file-system", () => ({
  deleteAsync: (...args: unknown[]) => mockDeleteAsync(...args),
}));
jest.mock("expo-image-picker", () => ({
  requestMediaLibraryPermissionsAsync: (...args: unknown[]) => mockRequestPhotoPermission(...args),
  requestCameraPermissionsAsync: (...args: unknown[]) => mockRequestCameraPermission(...args),
  launchImageLibraryAsync: (...args: unknown[]) => mockLaunchPicker(...args),
  launchCameraAsync: (...args: unknown[]) => mockLaunchCamera(...args),
}));
jest.mock("../src/native/ocr/NutritionOcr", () => ({
  DEFAULT_OCR_OPTIONS: { recognitionLevel: "accurate", languages: ["en-US"], usesLanguageCorrection: false },
  isOcrSupported: () => true,
  recognizeTextFromImage: (...args: unknown[]) => mockRecognizeTextFromImage(...args),
  normalizeOcrError: (error: { code?: string; message?: string }) => ({
    code: error.code ?? "ocr_recognition_failed",
    message: error.message ?? "Apple Vision OCR could not complete the request.",
  }),
}));

import { OcrDiagnosticsScreen } from "../src/features/ocr/diagnostics/OcrDiagnosticsScreen";

const photoAsset = { uri: "file:///photo-label.jpg", width: 1200, height: 1600, fileName: "photo.jpg" };
const cameraAsset = { uri: "file:///camera-label.jpg", width: 3024, height: 4032, fileName: null };
const result = {
  observations: [{
    id: "observation-0001",
    text: "Calories 120",
    confidence: 0.98,
    boundingBox: { x: 0.1, y: 0.2, width: 0.5, height: 0.1 },
  }],
  fullText: "Calories 120",
  image: { width: 1200, height: 1600, orientationApplied: false },
  recognition: { platform: "ios", recognitionLevel: "accurate", languages: ["en-US"], durationMs: 42 },
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function textContent(node: TestRenderer.ReactTestInstance): string {
  return node.children.map((child) => typeof child === "string" ? child : textContent(child)).join("");
}

function buttonWithLabel(root: TestRenderer.ReactTestInstance, label: string) {
  return root.findAllByType(Pressable).find((button) => textContent(button) === label)!;
}

function hasText(root: TestRenderer.ReactTestInstance, value: string) {
  return root.findAllByType(Text).some((node) => textContent(node).includes(value));
}

async function renderScreen() {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(OcrDiagnosticsScreen, { onBack: jest.fn() }));
  });
  return renderer;
}

async function press(renderer: TestRenderer.ReactTestRenderer, label: string, waitForCompletion = true) {
  if (waitForCompletion) {
    await act(async () => buttonWithLabel(renderer.root, label).props.onPress());
  } else {
    await act(async () => {
      void buttonWithLabel(renderer.root, label).props.onPress();
      await Promise.resolve();
    });
  }
}

beforeEach(() => {
  jest.clearAllMocks();
  mockRequestPhotoPermission.mockResolvedValue({ granted: true });
  mockRequestCameraPermission.mockResolvedValue({ granted: true });
  mockLaunchPicker.mockResolvedValue({ canceled: false, assets: [photoAsset] });
  mockLaunchCamera.mockResolvedValue({ canceled: false, assets: [cameraAsset] });
  mockDeleteAsync.mockResolvedValue(undefined);
  mockRecognizeTextFromImage.mockResolvedValue(result);
});

test("choose photo and run OCR retains source, dimensions, and full text", async () => {
  const renderer = await renderScreen();
  await press(renderer, "Choose photo");
  expect(renderer.root.findByType(Image).props.source).toEqual({ uri: photoAsset.uri });
  expect(hasText(renderer.root, "Source: photo library")).toBe(true);
  expect(hasText(renderer.root, "Picker dimensions: 1200 × 1600px")).toBe(true);
  await press(renderer, "Run OCR");
  expect(mockRecognizeTextFromImage).toHaveBeenCalledWith(photoAsset.uri, {
    recognitionLevel: "accurate", languages: ["en-US"], usesLanguageCorrection: false,
  });
  expect(hasText(renderer.root, "Calories 120")).toBe(true);
  expect(hasText(renderer.root, "Native displayed dimensions: 1200 × 1600px")).toBe(true);
  await act(async () => renderer.unmount());
  expect(mockDeleteAsync).not.toHaveBeenCalled();
});

test("take photo uses still-image camera options, runs OCR, and cleans its cache file", async () => {
  const renderer = await renderScreen();
  await press(renderer, "Take photo");
  expect(mockLaunchCamera).toHaveBeenCalledWith({ mediaTypes: ["images"], allowsEditing: false, quality: 1 });
  expect(hasText(renderer.root, "Source: camera")).toBe(true);
  await press(renderer, "Run OCR");
  expect(mockRecognizeTextFromImage).toHaveBeenCalledWith(cameraAsset.uri, expect.any(Object));
  await act(async () => renderer.unmount());
  expect(mockDeleteAsync).toHaveBeenCalledWith(cameraAsset.uri, { idempotent: true });
});

test.each([
  ["Choose photo", mockRequestPhotoPermission, "Allow Photos access in iOS Settings"],
  ["Take photo", mockRequestCameraPermission, "Allow Camera access in iOS Settings"],
] as const)("%s permission denial is source-specific and assertive", async (label, permission, message) => {
  permission.mockResolvedValue({ granted: false });
  const renderer = await renderScreen();
  await press(renderer, label);
  expect(hasText(renderer.root, message)).toBe(true);
  const alert = renderer.root.findAllByType(Text).find((node) => textContent(node).includes(message))!;
  expect(alert.props.accessibilityRole).toBe("alert");
  await act(async () => renderer.unmount());
});

test("replacing an image discards an unresolved earlier OCR result", async () => {
  const pending = deferred<typeof result>();
  mockRecognizeTextFromImage.mockReturnValueOnce(pending.promise);
  const renderer = await renderScreen();
  await press(renderer, "Choose photo");
  await press(renderer, "Run OCR", false);
  expect(buttonWithLabel(renderer.root, "Run OCR").props.accessibilityState).toMatchObject({ disabled: true, busy: true });
  await press(renderer, "Take photo");
  expect(hasText(renderer.root, "Source: camera")).toBe(true);
  await act(async () => pending.resolve(result));
  expect(hasText(renderer.root, "Calories 120")).toBe(false);
  expect(buttonWithLabel(renderer.root, "Run OCR").props.accessibilityState.disabled).toBe(false);
  await act(async () => renderer.unmount());
});

test("clear while OCR is unresolved prevents repopulation and defers camera deletion", async () => {
  const pending = deferred<typeof result>();
  mockRecognizeTextFromImage.mockReturnValueOnce(pending.promise);
  const renderer = await renderScreen();
  await press(renderer, "Take photo");
  await press(renderer, "Run OCR", false);
  await press(renderer, "Clear");
  expect(renderer.root.findAllByType(Image)).toHaveLength(0);
  expect(mockDeleteAsync).not.toHaveBeenCalled();
  await act(async () => pending.resolve(result));
  expect(hasText(renderer.root, "Calories 120")).toBe(false);
  expect(mockDeleteAsync).toHaveBeenCalledWith(cameraAsset.uri, { idempotent: true });
  await act(async () => renderer.unmount());
});

test("overlay uses the measured aspect-fit rectangle and can be toggled", async () => {
  const renderer = await renderScreen();
  await press(renderer, "Choose photo");
  await press(renderer, "Run OCR");
  const preview = renderer.root.findAllByType(View).find((node) => node.props.accessibilityLabel === "Selected nutrition label image preview")!;
  await act(async () => preview.props.onLayout({ nativeEvent: { layout: { x: 0, y: 0, width: 300, height: 300 } } }));
  const overlay = renderer.root.findByProps({ testID: "ocr-overlay-observation-0001" });
  expect(StyleSheet.flatten(overlay.props.style)).toMatchObject({ x: 60, y: 60, width: 112.5, height: 30 });
  const toggle = renderer.root.findAllByType(Switch).find((node) => node.props.accessibilityLabel === "Show OCR bounding boxes")!;
  expect(toggle.props.accessibilityRole).toBe("switch");
  await act(async () => toggle.props.onValueChange(false));
  expect(renderer.root.findAllByProps({ testID: "ocr-overlay-observation-0001" })).toHaveLength(0);
  await act(async () => renderer.unmount());
});

test("recognition failure is assertive and Retry OCR succeeds", async () => {
  mockRecognizeTextFromImage
    .mockRejectedValueOnce({ code: "ocr_recognition_failed", message: "Recognition failed safely." })
    .mockResolvedValueOnce(result);
  const renderer = await renderScreen();
  await press(renderer, "Choose photo");
  await press(renderer, "Run OCR");
  expect(buttonWithLabel(renderer.root, "Retry OCR").props.accessibilityLabel).toBe("Retry OCR");
  const failure = renderer.root.findAllByType(Text).find((node) => textContent(node).includes("Recognition failed safely"))!;
  expect(failure.props.accessibilityRole).toBe("alert");
  await press(renderer, "Retry OCR");
  expect(hasText(renderer.root, "Calories 120")).toBe(true);
  await act(async () => renderer.unmount());
});

test("repeated acquisition and recognition actions are blocked while busy", async () => {
  const permission = deferred<{ granted: boolean }>();
  mockRequestPhotoPermission.mockReturnValueOnce(permission.promise);
  const renderer = await renderScreen();
  await press(renderer, "Choose photo", false);
  expect(buttonWithLabel(renderer.root, "Choose photo").props.accessibilityState).toMatchObject({ disabled: true, busy: true });
  buttonWithLabel(renderer.root, "Choose photo").props.onPress();
  expect(mockRequestPhotoPermission).toHaveBeenCalledTimes(1);
  await act(async () => permission.resolve({ granted: true }));

  const recognition = deferred<typeof result>();
  mockRecognizeTextFromImage.mockReturnValueOnce(recognition.promise);
  await press(renderer, "Run OCR", false);
  buttonWithLabel(renderer.root, "Run OCR").props.onPress();
  expect(mockRecognizeTextFromImage).toHaveBeenCalledTimes(1);
  await act(async () => recognition.resolve(result));
  await act(async () => renderer.unmount());
});
