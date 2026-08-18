import React from "react";
import { Linking, Pressable, Text, View } from "react-native";
import * as ImagePicker from "expo-image-picker";
import * as FileSystem from "expo-file-system";
import TestRenderer, { act } from "react-test-renderer";

const mockRequestCameraPermission = jest.fn();
const mockTakePictureAsync = jest.fn();
const mockPreferredBackCameraLensName = jest.fn();
const mockAccessibilityAnnounce = jest.fn(() => jest.fn());
const mockFocusAccessibilityElement = jest.fn(
  (_target: unknown, _options?: unknown) => jest.fn(),
);

jest.mock("../src/shared/accessibility/announcements", () => {
  const actual = jest.requireActual(
    "../src/shared/accessibility/announcements",
  );

  return {
    ...actual,
    useAccessibilityAnnouncement: () =>
      mockAccessibilityAnnounce,
  };
});

jest.mock("../src/shared/accessibility/focus", () => {
  const actual = jest.requireActual(
    "../src/shared/accessibility/focus",
  );

  return {
    ...actual,
    focusAccessibilityElement: (
      target: unknown,
      options?: unknown,
    ) => mockFocusAccessibilityElement(target, options),
  };
});

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
        autofocus: props.autofocus,
        selectedLens: props.selectedLens,
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

jest.mock("../src/native/camera/NutritionCamera", () => ({
  getPreferredBackCameraLensName: () =>
    mockPreferredBackCameraLensName(),
}));

jest.mock("../src/native/ocr/NutritionOcr", () => ({
  inspectImageQuality: jest.fn(),
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

import {
  inspectImageQuality,
  recognizeTextFromImage,
} from "../src/native/ocr/NutritionOcr";
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

const GOOD_IMAGE_QUALITY = {
  width: 3024,
  height: 4032,
  meanLuminance: 0.55,
  darkPixelFraction: 0.08,
  brightPixelFraction: 0.04,
  focusVariance: 0.06,
  textRegionCount: 12,
  textRegionAreaFraction: 0.042,
};

const BLURRED_IMAGE_QUALITY = {
  ...GOOD_IMAGE_QUALITY,
  focusVariance: 0,
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
  mockPreferredBackCameraLensName.mockReturnValue(
    "Back Triple Camera",
  );
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

  const nativeCamera = renderer.root.findByProps({
    testID: "mock-nutrition-camera-view",
  });

  expect(nativeCamera.props.selectedLens).toBe(
    "Back Triple Camera",
  );
  expect(nativeCamera.props.autofocus).toBe("off");

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
  (inspectImageQuality as jest.Mock).mockResolvedValue(
    GOOD_IMAGE_QUALITY,
  );

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
  expect(inspectImageQuality).not.toHaveBeenCalled();

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

test("warning-producing camera image pauses before recognition and offers deterministic recovery actions", async () => {
  jest.clearAllMocks();

  mockRequestCameraPermission.mockResolvedValue({ granted: true });
  mockTakePictureAsync.mockResolvedValue({
    uri: "file:///tmp/blurred-label.jpg",
    width: 3024,
    height: 4032,
  });
  (inspectImageQuality as jest.Mock).mockResolvedValue(
    BLURRED_IMAGE_QUALITY,
  );

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

  expect(inspectImageQuality).toHaveBeenCalledWith(
    "file:///tmp/blurred-label.jpg",
  );
  expect(recognizeTextFromImage).not.toHaveBeenCalled();

  expect(
    renderer.root.findByProps({
      accessibilityRole: "header",
      children: "Check photo quality",
    }),
  ).toBeDefined();

  const warningText = renderer.root
    .findAllByType(Text)
    .map((node) => {
      const children = node.props.children;
      return Array.isArray(children)
        ? children.join("")
        : String(children ?? "");
    })
    .join(" ");

  expect(warningText).toContain("severely blurred");

  expect(mockAccessibilityAnnounce).toHaveBeenCalledWith(
    expect.stringContaining("Photo quality warning."),
    expect.objectContaining({
      key: "nutrition-image-quality-warning",
      priority: "assertive",
    }),
  );

  expect(mockFocusAccessibilityElement).toHaveBeenCalled();

  const qualityFocusOptions =
    mockFocusAccessibilityElement.mock.calls[
      mockFocusAccessibilityElement.mock.calls.length - 1
    ]?.[1];

  expect(qualityFocusOptions).toEqual({
    delayMs: 60,
    focusKeyboardTarget: false,
  });

  expect(
    renderer.root
      .findAllByType(Pressable)
      .find(
        (node) => node.props.accessibilityLabel === "Retake photo",
      ),
  ).toBeDefined();

  expect(
    renderer.root
      .findAllByType(Pressable)
      .find(
        (node) => node.props.accessibilityLabel === "Use photo anyway",
      ),
  ).toBeDefined();

  await act(async () => renderer.unmount());

  expect(FileSystem.deleteAsync).toHaveBeenCalledWith(
    "file:///tmp/blurred-label.jpg",
    { idempotent: true },
  );
});

test("use photo anyway recognizes and parses the original warned camera image", async () => {
  jest.clearAllMocks();

  mockRequestCameraPermission.mockResolvedValue({ granted: true });
  mockTakePictureAsync.mockResolvedValue({
    uri: "file:///tmp/use-anyway-label.jpg",
    width: 3024,
    height: 4032,
  });
  (inspectImageQuality as jest.Mock).mockResolvedValue(
    BLURRED_IMAGE_QUALITY,
  );

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

  const useAnyway = renderer.root
    .findAllByType(Pressable)
    .find(
      (node) => node.props.accessibilityLabel === "Use photo anyway",
    )!;

  await act(async () => {
    useAnyway.props.onPress();
    useAnyway.props.onPress();
    await flushAsyncWork();
  });

  expect(recognizeTextFromImage).toHaveBeenCalledTimes(1);
  expect(recognizeTextFromImage).toHaveBeenCalledWith(
    "file:///tmp/use-anyway-label.jpg",
  );
  expect(parseNutritionLabel).toHaveBeenCalledWith(recognized);
  expect(onReady).toHaveBeenCalledTimes(1);
  expect(onReady.mock.calls[0][0].imageSourceType).toBe("camera");

  expect(FileSystem.deleteAsync).toHaveBeenCalledWith(
    "file:///tmp/use-anyway-label.jpg",
    { idempotent: true },
  );

  await act(async () => renderer.unmount());
});

test("retake deletes the warned temporary image before reopening the camera", async () => {
  jest.clearAllMocks();

  mockRequestCameraPermission.mockResolvedValue({ granted: true });
  mockTakePictureAsync.mockResolvedValue({
    uri: "file:///tmp/retake-quality-label.jpg",
    width: 3024,
    height: 4032,
  });
  (inspectImageQuality as jest.Mock).mockResolvedValue(
    BLURRED_IMAGE_QUALITY,
  );

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

  const retake = renderer.root
    .findAllByType(Pressable)
    .find(
      (node) => node.props.accessibilityLabel === "Retake photo",
    )!;

  await act(async () => {
    retake.props.onPress();
    retake.props.onPress();
    await flushAsyncWork();
  });

  expect(FileSystem.deleteAsync).toHaveBeenCalledWith(
    "file:///tmp/retake-quality-label.jpg",
    { idempotent: true },
  );

  expect(recognizeTextFromImage).not.toHaveBeenCalled();

  expect(
    renderer.root.findByProps({
      accessibilityRole: "header",
      children: "Photograph Nutrition Facts",
    }),
  ).toBeDefined();

  expect(mockRequestCameraPermission).toHaveBeenCalledTimes(2);

  await act(async () => renderer.unmount());
});

test("quality evaluator failure falls through to recognition with the original camera image", async () => {
  jest.clearAllMocks();

  mockRequestCameraPermission.mockResolvedValue({ granted: true });
  mockTakePictureAsync.mockResolvedValue({
    uri: "file:///tmp/quality-failure-label.jpg",
    width: 3024,
    height: 4032,
  });
  (inspectImageQuality as jest.Mock).mockRejectedValue(
    new Error("quality evaluator failed"),
  );

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

  expect(recognizeTextFromImage).toHaveBeenCalledWith(
    "file:///tmp/quality-failure-label.jpg",
  );
  expect(parseNutritionLabel).toHaveBeenCalledWith(recognized);
  expect(onReady).toHaveBeenCalledTimes(1);

  await act(async () => renderer.unmount());
});

test("camera quality inspection resolving after screen unmount cleans the temporary image without starting recognition", async () => {
  jest.clearAllMocks();

  mockRequestCameraPermission.mockResolvedValue({ granted: true });
  mockTakePictureAsync.mockResolvedValue({
    uri: "file:///tmp/unmounted-quality-label.jpg",
    width: 3024,
    height: 4032,
  });

  let resolveInspection!: (value: unknown) => void;

  (inspectImageQuality as jest.Mock).mockImplementation(
    () =>
      new Promise((resolve) => {
        resolveInspection = resolve;
      }),
  );

  const onReady = jest.fn();

  let renderer!: TestRenderer.ReactTestRenderer;

  await act(async () => {
    renderer = TestRenderer.create(
      withNutritionRuntime(
        React.createElement(NutritionScanScreen, {
          onCancel: jest.fn(),
          onReady,
        }),
      ),
    );
  });

  const takePhoto = renderer.root
    .findAllByType(Pressable)
    .find(
      (node) =>
        node.props.accessibilityLabel ===
        "Take nutrition label photo",
    )!;

  await act(async () => {
    takePhoto.props.onPress();
    await flushAsyncWork();
  });

  const capture = renderer.root
    .findAllByType(Pressable)
    .find(
      (node) =>
        node.props.accessibilityLabel ===
        "Capture nutrition label photo",
    )!;

  await act(async () => {
    capture.props.onPress();
    await flushAsyncWork();
  });

  expect(inspectImageQuality).toHaveBeenCalledWith(
    "file:///tmp/unmounted-quality-label.jpg",
  );
  expect(recognizeTextFromImage).not.toHaveBeenCalled();

  await act(async () => {
    renderer.unmount();
    await flushAsyncWork();
  });

  await act(async () => {
    resolveInspection(GOOD_IMAGE_QUALITY);
    await flushAsyncWork();
  });

  expect(recognizeTextFromImage).not.toHaveBeenCalled();
  expect(onReady).not.toHaveBeenCalled();

  expect(FileSystem.deleteAsync).toHaveBeenCalledWith(
    "file:///tmp/unmounted-quality-label.jpg",
    { idempotent: true },
  );
});
