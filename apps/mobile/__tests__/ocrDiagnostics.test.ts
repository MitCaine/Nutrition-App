import { OcrError } from "../src/native/ocr/NutritionOcr";
import {
  chooseOcrImage,
  INITIAL_OCR_DIAGNOSTICS_STATE,
  isOcrDiagnosticsEnabled,
  ocrDiagnosticsReducer,
  recognizeSelection,
} from "../src/features/ocr/diagnostics/diagnosticsModel";

const selection = { uri: "file:///label.jpg", width: 1200, height: 1600, fileName: "label.jpg" };
const result = {
  observations: [],
  fullText: "",
  image: { width: 1200, height: 1600, orientationApplied: false },
  recognition: { platform: "ios" as const, recognitionLevel: "accurate" as const, languages: ["en-US"], durationMs: 10 },
};

test("photo permission denial is actionable and does not launch the picker", async () => {
  const launch = jest.fn();
  await expect(chooseOcrImage({
    requestPermission: jest.fn().mockResolvedValue({ granted: false }),
    launch,
  })).resolves.toEqual({ kind: "permissionDenied" });
  expect(launch).not.toHaveBeenCalled();
});

test("successful image selection returns local image metadata", async () => {
  await expect(chooseOcrImage({
    requestPermission: jest.fn().mockResolvedValue({ granted: true }),
    launch: jest.fn().mockResolvedValue({ canceled: false, assets: [selection] }),
  })).resolves.toEqual({ kind: "selected", selection });
});

test("selection cancellation leaves diagnostics unchanged", async () => {
  await expect(chooseOcrImage({
    requestPermission: jest.fn().mockResolvedValue({ granted: true }),
    launch: jest.fn().mockResolvedValue({ canceled: true }),
  })).resolves.toEqual({ kind: "cancelled" });
});

test("diagnostics state supports recognition success, retry after failure, and clear", () => {
  const selected = ocrDiagnosticsReducer(INITIAL_OCR_DIAGNOSTICS_STATE, { type: "selected", selection });
  const recognizing = ocrDiagnosticsReducer(selected, { type: "recognitionStarted" });
  const failed = ocrDiagnosticsReducer(recognizing, {
    type: "recognitionFailed",
    error: new OcrError("ocr_recognition_failed", "Try again."),
  });
  expect(failed.status).toBe("failure");
  const retrying = ocrDiagnosticsReducer(failed, { type: "recognitionStarted" });
  const succeeded = ocrDiagnosticsReducer(retrying, { type: "recognitionSucceeded", result });
  expect(succeeded).toMatchObject({ status: "success", result, selection });
  expect(ocrDiagnosticsReducer(succeeded, { type: "cleared" })).toEqual(INITIAL_OCR_DIAGNOSTICS_STATE);
});

test("recognition invokes the bridge with the selected local URI", async () => {
  const state = ocrDiagnosticsReducer(INITIAL_OCR_DIAGNOSTICS_STATE, { type: "selected", selection });
  const recognize = jest.fn().mockResolvedValue(result);
  await expect(recognizeSelection(state, recognize, { recognitionLevel: "accurate" })).resolves.toEqual(result);
  expect(recognize).toHaveBeenCalledWith(selection.uri, { recognitionLevel: "accurate" });
});

test("the diagnostics route gate is development-only", () => {
  expect(isOcrDiagnosticsEnabled(true)).toBe(true);
  expect(isOcrDiagnosticsEnabled(false)).toBe(false);
});
