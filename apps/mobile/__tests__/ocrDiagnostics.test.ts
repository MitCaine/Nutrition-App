import { OcrError } from "../src/native/ocr/NutritionOcr";
import {
  acquireOcrImage,
  canStartAcquisition,
  canStartRecognition,
  deleteCameraCapture,
  INITIAL_OCR_DIAGNOSTICS_STATE,
  isOcrDiagnosticsEnabled,
  ocrDiagnosticsReducer,
  recognizeSelection,
  type OcrImageSelection,
} from "../src/features/ocr/diagnostics/diagnosticsModel";

const photoSelection: OcrImageSelection = {
  uri: "file:///photo-label.jpg",
  width: 1200,
  height: 1600,
  fileName: "label.jpg",
  source: "photo_library",
};
const cameraSelection: OcrImageSelection = {
  uri: "file:///camera-label.jpg",
  width: 3024,
  height: 4032,
  fileName: null,
  source: "camera",
};
const result = {
  observations: [],
  fullText: "",
  image: { width: 1200, height: 1600, orientationApplied: false },
  recognition: { platform: "ios" as const, recognitionLevel: "accurate" as const, languages: ["en-US"], durationMs: 10 },
};

function gateway(asset: Omit<OcrImageSelection, "source">) {
  return {
    requestPermission: jest.fn().mockResolvedValue({ granted: true }),
    launch: jest.fn().mockResolvedValue({ canceled: false, assets: [asset] }),
  };
}

test.each([
  ["photo_library" as const, photoSelection],
  ["camera" as const, cameraSelection],
])("%s acquisition retains source and picker dimensions", async (source, selection) => {
  await expect(acquireOcrImage(source, gateway(selection))).resolves.toEqual({
    kind: "selected",
    selection,
  });
});

test.each(["photo_library", "camera"] as const)("%s permission denial is distinct and skips launch", async (source) => {
  const launch = jest.fn();
  await expect(acquireOcrImage(source, {
    requestPermission: jest.fn().mockResolvedValue({ granted: false }),
    launch,
  })).resolves.toEqual({ kind: "permissionDenied", source });
  expect(launch).not.toHaveBeenCalled();
});

test("cancellation remains distinct from permission denial", async () => {
  await expect(acquireOcrImage("camera", {
    requestPermission: jest.fn().mockResolvedValue({ granted: true }),
    launch: jest.fn().mockResolvedValue({ canceled: true }),
  })).resolves.toEqual({ kind: "cancelled", source: "camera" });
});

test("picker exceptions become source-specific acquisition failures without native details", async () => {
  await expect(acquireOcrImage("photo_library", {
    requestPermission: jest.fn().mockResolvedValue({ granted: true }),
    launch: jest.fn().mockRejectedValue(new Error("/private/cache/secret.jpg")),
  })).resolves.toEqual({ kind: "failed", source: "photo_library" });
});

test("repeated acquisition is blocked until the first action finishes", () => {
  const started = ocrDiagnosticsReducer(INITIAL_OCR_DIAGNOSTICS_STATE, { type: "acquisitionStarted", source: "camera" });
  const repeated = ocrDiagnosticsReducer(started, { type: "acquisitionStarted", source: "photo_library" });
  expect(canStartAcquisition(started)).toBe(false);
  expect(repeated).toBe(started);
  expect(ocrDiagnosticsReducer(started, { type: "acquisitionFinished", source: "camera" }).acquisitionSource).toBeNull();
});

test("repeated recognition is blocked and successful state can be cleared", () => {
  const selected = ocrDiagnosticsReducer(INITIAL_OCR_DIAGNOSTICS_STATE, { type: "selected", selection: photoSelection });
  const request = { id: 1, selectionGeneration: selected.selectionGeneration };
  const recognizing = ocrDiagnosticsReducer(selected, { type: "recognitionStarted", request });
  const repeated = ocrDiagnosticsReducer(recognizing, { type: "recognitionStarted", request: { ...request, id: 2 } });
  expect(canStartRecognition(recognizing)).toBe(false);
  expect(repeated).toBe(recognizing);
  const succeeded = ocrDiagnosticsReducer(recognizing, { type: "recognitionSucceeded", request, result });
  expect(succeeded).toMatchObject({ status: "success", result, selection: photoSelection, recognitionRequest: null });
  expect(ocrDiagnosticsReducer(succeeded, { type: "cleared" })).toMatchObject({ selection: null, result: null, status: "idle" });
});

test("a stale OCR result is discarded after image replacement", () => {
  const first = ocrDiagnosticsReducer(INITIAL_OCR_DIAGNOSTICS_STATE, { type: "selected", selection: photoSelection });
  const request = { id: 1, selectionGeneration: first.selectionGeneration };
  const recognizing = ocrDiagnosticsReducer(first, { type: "recognitionStarted", request });
  const replaced = ocrDiagnosticsReducer(recognizing, { type: "selected", selection: cameraSelection });
  const settled = ocrDiagnosticsReducer(replaced, { type: "recognitionSucceeded", request, result });
  expect(settled).toMatchObject({ selection: cameraSelection, result: null, status: "idle", recognitionRequest: null });
});

test("a stale OCR failure is discarded after clear", () => {
  const selected = ocrDiagnosticsReducer(INITIAL_OCR_DIAGNOSTICS_STATE, { type: "selected", selection: cameraSelection });
  const request = { id: 4, selectionGeneration: selected.selectionGeneration };
  const recognizing = ocrDiagnosticsReducer(selected, { type: "recognitionStarted", request });
  const cleared = ocrDiagnosticsReducer(recognizing, { type: "cleared" });
  const settled = ocrDiagnosticsReducer(cleared, {
    type: "recognitionFailed",
    request,
    error: new OcrError("ocr_recognition_failed", "old failure"),
  });
  expect(settled).toMatchObject({ selection: null, error: null, status: "idle", recognitionRequest: null });
});

test("overlay toggle is explicit and replacing an image resets old OCR output", () => {
  const toggled = ocrDiagnosticsReducer(INITIAL_OCR_DIAGNOSTICS_STATE, { type: "overlayChanged", enabled: false });
  expect(toggled.overlayEnabled).toBe(false);
  const selected = ocrDiagnosticsReducer(toggled, { type: "selected", selection: photoSelection });
  expect(selected).toMatchObject({ result: null, error: null, overlayEnabled: false });
});

test("only camera cache captures are explicitly deleted and missing files are tolerated", async () => {
  const deleteFile = jest.fn().mockResolvedValue(undefined);
  await expect(deleteCameraCapture(cameraSelection, deleteFile)).resolves.toBe(true);
  expect(deleteFile).toHaveBeenCalledWith(cameraSelection.uri);
  deleteFile.mockClear();
  await expect(deleteCameraCapture(photoSelection, deleteFile)).resolves.toBe(false);
  expect(deleteFile).not.toHaveBeenCalled();
  await expect(deleteCameraCapture(cameraSelection, jest.fn().mockRejectedValue(new Error("missing")))).resolves.toBe(false);
});

test("recognition invokes the bridge with the selected local URI", async () => {
  const recognize = jest.fn().mockResolvedValue(result);
  await expect(recognizeSelection(photoSelection, recognize, { recognitionLevel: "accurate" })).resolves.toEqual(result);
  expect(recognize).toHaveBeenCalledWith(photoSelection.uri, { recognitionLevel: "accurate" });
});

test("the diagnostics route gate remains development-only", () => {
  expect(isOcrDiagnosticsEnabled(true)).toBe(true);
  expect(isOcrDiagnosticsEnabled(false)).toBe(false);
});
