import React from "react";
import { Image, Pressable, Text } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

const mockRequestPermission = jest.fn();
const mockLaunchPicker = jest.fn();
const mockRecognizeTextFromImage = jest.fn();

jest.mock("@expo/vector-icons", () => ({ Ionicons: "Ionicons" }));

jest.mock("expo-image-picker", () => ({
  requestMediaLibraryPermissionsAsync: (...args: unknown[]) => mockRequestPermission(...args),
  launchImageLibraryAsync: (...args: unknown[]) => mockLaunchPicker(...args),
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

function textContent(node: TestRenderer.ReactTestInstance): string {
  return node.children
    .map((child) => typeof child === "string" ? child : textContent(child))
    .join("");
}

function buttonWithLabel(root: TestRenderer.ReactTestInstance, label: string) {
  return root.findAllByType(Pressable).find((button) => textContent(button) === label)!;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockRequestPermission.mockResolvedValue({ granted: true });
  mockLaunchPicker.mockResolvedValue({
    canceled: false,
    assets: [{ uri: "file:///label.jpg", width: 1200, height: 1600, fileName: "label.jpg" }],
  });
  mockRecognizeTextFromImage.mockResolvedValue(result);
});

test("mounted diagnostics screen selects an image, recognizes text, and clears", async () => {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(OcrDiagnosticsScreen, { onBack: jest.fn() }));
  });

  await act(async () => buttonWithLabel(renderer.root, "Choose image").props.onPress());
  expect(renderer.root.findByType(Image).props.source).toEqual({ uri: "file:///label.jpg" });

  await act(async () => buttonWithLabel(renderer.root, "Run OCR").props.onPress());
  expect(mockRecognizeTextFromImage).toHaveBeenCalledWith("file:///label.jpg", {
    recognitionLevel: "accurate",
    languages: ["en-US"],
    usesLanguageCorrection: false,
  });
  expect(renderer.root.findAllByType(Text).some((node) => textContent(node) === "Calories 120")).toBe(true);

  await act(async () => buttonWithLabel(renderer.root, "Clear").props.onPress());
  expect(renderer.root.findAllByType(Image)).toHaveLength(0);
  await act(async () => renderer.unmount());
});

test("mounted diagnostics screen presents actionable photo permission denial", async () => {
  mockRequestPermission.mockResolvedValue({ granted: false });
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(OcrDiagnosticsScreen, { onBack: jest.fn() }));
  });
  await act(async () => buttonWithLabel(renderer.root, "Choose image").props.onPress());
  expect(renderer.root.findAllByType(Text).some((node) => textContent(node).includes("Allow Photos access in iOS Settings"))).toBe(true);
  expect(mockLaunchPicker).not.toHaveBeenCalled();
  await act(async () => renderer.unmount());
});
