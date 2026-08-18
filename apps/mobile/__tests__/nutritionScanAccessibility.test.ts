import React from "react";
import { Linking, Pressable, View } from "react-native";
import * as ImagePicker from "expo-image-picker";
import * as FileSystem from "expo-file-system";
import TestRenderer, { act } from "react-test-renderer";

const mockRequestCameraPermission = jest.fn();
const mockTakePictureAsync = jest.fn();

jest.mock("expo-file-system", () => ({
  deleteAsync: jest.fn(),
}));

jest.mock("expo-camera", () => {
  const mockReact = require("react");
  const mockReactNative = require("react-native");

  const CameraView = mockReact.forwardRef(
    (props: Record<string, unknown>, ref: unknown) => {
      mockReact.useImperativeHandle(ref, () => ({
        takePictureAsync: (...args: unknown[]) =>
          mockTakePictureAsync(...args),
      }));

      mockReact.useEffect(() => {
        if (typeof props.onCameraReady === "function") {
          props.onCameraReady();
        }
      }, []);

      return mockReact.createElement(mockReactNative.View, {
        testID: "mock-nutrition-camera-view",
      });
    },
  );

  return {
    Camera: {
      requestCameraPermissionsAsync: (...args: unknown[]) =>
        mockRequestCameraPermission(...args),
    },
    CameraView,
  };
});

jest.mock("expo-image-picker", () => ({
  requestMediaLibraryPermissionsAsync: jest.fn(),
  launchImageLibraryAsync: jest.fn(),
}));

jest.mock("../src/native/ocr/NutritionOcr", () => ({
  recognizeTextFromImage: jest.fn(),
}));

jest.mock("../src/features/ocr/api/ocrApi", () => ({
  parseNutritionLabel: jest.fn(),
}));

jest.mock("../src/app/theme/AppTheme", () => {
  const actual = jest.requireActual("../src/app/theme/AppTheme");

  return {
    ...actual,
    useAppTheme: () => ({
      ...actual.LIGHT_THEME,
      preference: "system",
      effectiveScheme: "light",
      setPreference: jest.fn(),
    }),
  };
});

import { recognizeTextFromImage } from "../src/native/ocr/NutritionOcr";
import type { ParsedField, ParsedNutritionLabel } from "../src/features/ocr/api/types";
import { NutritionCameraCapture } from "../src/features/ocr/components/NutritionCameraCapture";
import { NutritionScanScreen } from "../src/features/ocr/screens/NutritionScanScreen";
import {
  createNutritionTestRuntime,
  withNutritionRuntime,
} from "./nutritionRuntimeTestSupport";

function parsedField(value: string): ParsedField {
  return {
    value,
    comparison: null,
    source_text: value,
    source_observation_ids: ["observation-1"],
    confidence: 0.99,
    status: "parsed",
    warning_codes: [],
  };
}

const PARSED_LABEL: ParsedNutritionLabel = {
  serving: null,
  calories: parsedField("120"),
  nutrients: [],
  unparsed_lines: [],
  warnings: [],
  parser_version: "nutrition_label_v2",
};

async function flushAsyncWork() {
  for (let index = 0; index < 8; index += 1) {
    await Promise.resolve();
  }
}

function runtimeForScan(parseNutritionLabel: jest.Mock) {
  const baseline = createNutritionTestRuntime();

  return createNutritionTestRuntime({
    ocr: {
      ...baseline.ocr,
      parseNutritionLabel,
    },
  });
}

test("iOS label acquisition exposes a focused heading and contextual acquisition actions", async () => {
  let renderer!: TestRenderer.ReactTestRenderer;

  await act(async () => {
    renderer = TestRenderer.create(
      withNutritionRuntime(
        React.createElement(NutritionScanScreen, {
          onCancel: jest.fn(),
          onReady: jest.fn(),
        }),
      ),
    );
  });

  expect(
    renderer.root.findByProps({
      accessibilityRole: "header",
      children: "Scan nutrition label",
    }),
  ).toBeDefined();

  const actions = renderer.root.findAllByType(Pressable);
  const choose = actions.find(
    (node) =>
      node.props.accessibilityLabel === "Choose nutrition label photo",
  )!;
  const camera = actions.find(
    (node) =>
      node.props.accessibilityLabel === "Take nutrition label photo",
  )!;

  expect(choose.props.accessibilityHint).toContain("iOS photo library");
  expect(camera.props.accessibilityHint).toContain("framing guidance");
  expect(
    actions.find(
      (node) => node.props.accessibilityLabel === "Cancel label scan",
    ),
  ).toBeDefined();

  await act(async () => renderer.unmount());
});

test("camera permission denial offers a direct route to app settings", async () => {
  const openSettings = jest
    .spyOn(Linking, "openSettings")
    .mockResolvedValue();

  mockRequestCameraPermission.mockResolvedValue({ granted: false });

  let renderer!: TestRenderer.ReactTestRenderer;

  await act(async () => {
    renderer = TestRenderer.create(
      withNutritionRuntime(
        React.createElement(NutritionScanScreen, {
          onCancel: jest.fn(),
          onReady: jest.fn(),
        }),
      ),
    );
  });

  const camera = renderer.root
    .findAllByType(Pressable)
    .find(
      (node) =>
        node.props.accessibilityLabel === "Take nutrition label photo",
    )!;

  await act(async () => {
    await camera.props.onPress();
  });

  expect(mockRequestCameraPermission).toHaveBeenCalledTimes(1);

  const settings = renderer.root
    .findAllByType(Pressable)
    .find(
      (node) => node.props.accessibilityLabel === "Open app settings",
    )!;

  expect(settings).toBeDefined();
  expect(settings.props.accessibilityHint).toContain(
    "camera or photo access",
  );

  await act(async () => {
    settings.props.onPress();
  });

  expect(openSettings).toHaveBeenCalledTimes(1);

  await act(async () => renderer.unmount());
  openSettings.mockRestore();
});

test("retake mode opens the app-owned camera once and cancellation leaves scan controls recoverable", async () => {
  jest.clearAllMocks();
  mockRequestCameraPermission.mockResolvedValue({ granted: true });

  let renderer!: TestRenderer.ReactTestRenderer;

  await act(async () => {
    renderer = TestRenderer.create(
      withNutritionRuntime(
        React.createElement(NutritionScanScreen, {
          autoAcquireCamera: true,
          onCancel: jest.fn(),
          onReady: jest.fn(),
        }),
      ),
    );

    await Promise.resolve();
    await Promise.resolve();
  });

  expect(mockRequestCameraPermission).toHaveBeenCalledTimes(1);
  expect(
    renderer.root.findByProps({
      accessibilityRole: "header",
      children: "Photograph Nutrition Facts",
    }),
  ).toBeDefined();
  expect(
    renderer.root.findByProps({
      testID: "mock-nutrition-camera-view",
    }),
  ).toBeDefined();

  const cameraActions = renderer.root.findAllByType(Pressable);
  const capture = cameraActions.find(
    (node) =>
      node.props.accessibilityLabel === "Capture nutrition label photo",
  )!;
  const cancelCamera = cameraActions.find(
    (node) =>
      node.props.accessibilityLabel === "Cancel camera capture",
  )!;

  expect(capture).toBeDefined();
  expect(capture.props.disabled).toBe(false);
  expect(cancelCamera).toBeDefined();

  await act(async () => {
    cancelCamera.props.onPress();
    await Promise.resolve();
  });

  const scanActions = renderer.root.findAllByType(Pressable);

  expect(
    scanActions.find(
      (node) =>
        node.props.accessibilityLabel === "Choose nutrition label photo",
    )?.props.disabled,
  ).toBe(false);

  expect(
    scanActions.find(
      (node) =>
        node.props.accessibilityLabel === "Take nutrition label photo",
    )?.props.disabled,
  ).toBe(false);

  expect(
    scanActions.find(
      (node) => node.props.accessibilityLabel === "Cancel label scan",
    )?.props.disabled,
  ).toBe(false);

  await act(async () => {
    renderer.update(
      withNutritionRuntime(
        React.createElement(NutritionScanScreen, {
          autoAcquireCamera: true,
          onCancel: jest.fn(),
          onReady: jest.fn(),
        }),
      ),
    );
    await Promise.resolve();
  });

  expect(mockRequestCameraPermission).toHaveBeenCalledTimes(1);

  await act(async () => renderer.unmount());
});

test("camera preview exposes framing guidance that does not require an exact crop", async () => {
  jest.clearAllMocks();
  mockRequestCameraPermission.mockResolvedValue({ granted: true });

  let renderer!: TestRenderer.ReactTestRenderer;

  await act(async () => {
    renderer = TestRenderer.create(
      withNutritionRuntime(
        React.createElement(NutritionScanScreen, {
          onCancel: jest.fn(),
          onReady: jest.fn(),
        }),
      ),
    );
  });

  const camera = renderer.root
    .findAllByType(Pressable)
    .find(
      (node) =>
        node.props.accessibilityLabel === "Take nutrition label photo",
    )!;

  await act(async () => {
    await camera.props.onPress();
    await Promise.resolve();
  });

  const instruction = renderer.root
    .findAllByType(View)
    .flatMap((node) => node.findAllByType(require("react-native").Text))
    .find(
      (node) =>
        typeof node.props.children === "string" &&
        node.props.children.includes("required crop"),
    );

  expect(instruction).toBeDefined();

  const preview = renderer.root.findByProps({
    accessibilityLabel: "Nutrition Facts camera preview",
  });

  expect(preview.props.accessibilityHint).toContain("corner guides");

  await act(async () => renderer.unmount());
});

test("successful app-owned camera capture continues through recognition and parsing and cleans up the temporary image", async () => {
  jest.clearAllMocks();

  mockRequestCameraPermission.mockResolvedValue({ granted: true });
  mockTakePictureAsync.mockResolvedValue({
    uri: "file:///tmp/nutrition-camera-success.jpg",
    width: 3024,
    height: 4032,
  });

  const recognized = {
    fullText: "Calories 120",
  };

  (recognizeTextFromImage as jest.Mock).mockResolvedValue(recognized);

  const parseNutritionLabel = jest.fn().mockResolvedValue(PARSED_LABEL);
  const runtime = runtimeForScan(parseNutritionLabel);
  const onReady = jest.fn();

  let renderer!: TestRenderer.ReactTestRenderer;

  await act(async () => {
    renderer = TestRenderer.create(
      withNutritionRuntime(
        React.createElement(NutritionScanScreen, {
          onCancel: jest.fn(),
          onReady,
        }),
        runtime,
      ),
    );
  });

  const takePhoto = renderer.root
    .findAllByType(Pressable)
    .find(
      (node) =>
        node.props.accessibilityLabel === "Take nutrition label photo",
    )!;

  await act(async () => {
    takePhoto.props.onPress();
    await flushAsyncWork();
  });

  const capture = renderer.root
    .findAllByType(Pressable)
    .find(
      (node) =>
        node.props.accessibilityLabel === "Capture nutrition label photo",
    )!;

  await act(async () => {
    capture.props.onPress();
    await flushAsyncWork();
  });

  expect(mockTakePictureAsync).toHaveBeenCalledTimes(1);

  expect(recognizeTextFromImage).toHaveBeenCalledWith(
    "file:///tmp/nutrition-camera-success.jpg",
  );

  expect(parseNutritionLabel).toHaveBeenCalledWith(recognized);

  expect(onReady).toHaveBeenCalledTimes(1);
  expect(onReady.mock.calls[0][0].imageSourceType).toBe("camera");
  expect(onReady.mock.calls[0][0].parserVersion).toBe(
    "nutrition_label_v2",
  );

  expect(FileSystem.deleteAsync).toHaveBeenCalledWith(
    "file:///tmp/nutrition-camera-success.jpg",
    { idempotent: true },
  );

  await act(async () => renderer.unmount());
});

test("photo-library acquisition remains on ImagePicker and does not request the app-owned camera", async () => {
  jest.clearAllMocks();

  (ImagePicker.requestMediaLibraryPermissionsAsync as jest.Mock)
    .mockResolvedValue({ granted: true });

  (ImagePicker.launchImageLibraryAsync as jest.Mock).mockResolvedValue({
    canceled: false,
    assets: [
      {
        uri: "file:///library/nutrition-label.jpg",
        width: 2000,
        height: 3000,
        fileName: "nutrition-label.jpg",
      },
    ],
  });

  const recognized = {
    fullText: "Calories 120",
  };

  (recognizeTextFromImage as jest.Mock).mockResolvedValue(recognized);

  const parseNutritionLabel = jest.fn().mockResolvedValue(PARSED_LABEL);
  const runtime = runtimeForScan(parseNutritionLabel);
  const onReady = jest.fn();

  let renderer!: TestRenderer.ReactTestRenderer;

  await act(async () => {
    renderer = TestRenderer.create(
      withNutritionRuntime(
        React.createElement(NutritionScanScreen, {
          onCancel: jest.fn(),
          onReady,
        }),
        runtime,
      ),
    );
  });

  const choosePhoto = renderer.root
    .findAllByType(Pressable)
    .find(
      (node) =>
        node.props.accessibilityLabel === "Choose nutrition label photo",
    )!;

  await act(async () => {
    choosePhoto.props.onPress();
    await flushAsyncWork();
  });

  expect(
    ImagePicker.requestMediaLibraryPermissionsAsync,
  ).toHaveBeenCalledTimes(1);

  expect(ImagePicker.launchImageLibraryAsync).toHaveBeenCalledTimes(1);

  expect(mockRequestCameraPermission).not.toHaveBeenCalled();
  expect(mockTakePictureAsync).not.toHaveBeenCalled();

  expect(recognizeTextFromImage).toHaveBeenCalledWith(
    "file:///library/nutrition-label.jpg",
  );

  expect(onReady).toHaveBeenCalledTimes(1);
  expect(onReady.mock.calls[0][0].imageSourceType).toBe(
    "photo_library",
  );

  // Photo-library assets are user-owned and must not be deleted.
  expect(FileSystem.deleteAsync).not.toHaveBeenCalled();

  await act(async () => renderer.unmount());
});

test("a camera photo that finishes after the camera component unmounts is deleted instead of leaking from cache", async () => {
  jest.clearAllMocks();

  let resolveCapture!: (capture: {
    uri: string;
    width: number;
    height: number;
  }) => void;

  mockTakePictureAsync.mockImplementation(
    () =>
      new Promise((resolve) => {
        resolveCapture = resolve;
      }),
  );

  const onCaptured = jest.fn();

  let renderer!: TestRenderer.ReactTestRenderer;

  await act(async () => {
    renderer = TestRenderer.create(
      React.createElement(NutritionCameraCapture, {
        onCancel: jest.fn(),
        onCaptured,
      }),
    );

    await flushAsyncWork();
  });

  const capture = renderer.root
    .findAllByType(Pressable)
    .find(
      (node) =>
        node.props.accessibilityLabel === "Capture nutrition label photo",
    )!;

  await act(async () => {
    capture.props.onPress();
    await Promise.resolve();
  });

  expect(mockTakePictureAsync).toHaveBeenCalledTimes(1);

  await act(async () => {
    renderer.unmount();
  });

  await act(async () => {
    resolveCapture({
      uri: "file:///tmp/unmounted-camera-capture.jpg",
      width: 3024,
      height: 4032,
    });

    await flushAsyncWork();
  });

  expect(onCaptured).not.toHaveBeenCalled();

  expect(FileSystem.deleteAsync).toHaveBeenCalledWith(
    "file:///tmp/unmounted-camera-capture.jpg",
    { idempotent: true },
  );
});
