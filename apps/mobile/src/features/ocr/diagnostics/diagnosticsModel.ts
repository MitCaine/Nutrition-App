import type { OcrError, OcrRecognitionOptions, OcrRecognitionResult } from "../../../native/ocr/NutritionOcr";

export type OcrImageSource = "photo_library" | "camera";

export type OcrImageSelection = {
  uri: string;
  width: number;
  height: number;
  fileName?: string | null;
  source: OcrImageSource;
};

export type RecognitionRequest = {
  id: number;
  selectionGeneration: number;
};

export type OcrDiagnosticsState = {
  selection: OcrImageSelection | null;
  selectionGeneration: number;
  acquisitionSource: OcrImageSource | null;
  recognitionRequest: RecognitionRequest | null;
  status: "idle" | "recognizing" | "success" | "failure";
  result: OcrRecognitionResult | null;
  error: OcrError | null;
  overlayEnabled: boolean;
};

export type OcrDiagnosticsAction =
  | { type: "acquisitionStarted"; source: OcrImageSource }
  | { type: "acquisitionFinished"; source: OcrImageSource }
  | { type: "selected"; selection: OcrImageSelection }
  | { type: "recognitionStarted"; request: RecognitionRequest }
  | { type: "recognitionSucceeded"; request: RecognitionRequest; result: OcrRecognitionResult }
  | { type: "recognitionFailed"; request: RecognitionRequest; error: OcrError }
  | { type: "overlayChanged"; enabled: boolean }
  | { type: "cleared" };

export const INITIAL_OCR_DIAGNOSTICS_STATE: OcrDiagnosticsState = {
  selection: null,
  selectionGeneration: 0,
  acquisitionSource: null,
  recognitionRequest: null,
  status: "idle",
  result: null,
  error: null,
  overlayEnabled: true,
};

export function ocrDiagnosticsReducer(
  state: OcrDiagnosticsState,
  action: OcrDiagnosticsAction,
): OcrDiagnosticsState {
  switch (action.type) {
  case "acquisitionStarted":
    return state.acquisitionSource ? state : { ...state, acquisitionSource: action.source };
  case "acquisitionFinished":
    return state.acquisitionSource === action.source ? { ...state, acquisitionSource: null } : state;
  case "selected":
    return {
      ...state,
      selection: action.selection,
      selectionGeneration: state.selectionGeneration + 1,
      acquisitionSource: null,
      status: "idle",
      result: null,
      error: null,
    };
  case "recognitionStarted":
    return state.recognitionRequest
      ? state
      : { ...state, recognitionRequest: action.request, status: "recognizing", result: null, error: null };
  case "recognitionSucceeded":
    if (state.recognitionRequest?.id !== action.request.id) {
      return state;
    }
    if (!state.selection || action.request.selectionGeneration !== state.selectionGeneration) {
      return { ...state, recognitionRequest: null, status: "idle", result: null, error: null };
    }
    return { ...state, recognitionRequest: null, status: "success", result: action.result, error: null };
  case "recognitionFailed":
    if (state.recognitionRequest?.id !== action.request.id) {
      return state;
    }
    if (!state.selection || action.request.selectionGeneration !== state.selectionGeneration) {
      return { ...state, recognitionRequest: null, status: "idle", result: null, error: null };
    }
    return { ...state, recognitionRequest: null, status: "failure", result: null, error: action.error };
  case "overlayChanged":
    return { ...state, overlayEnabled: action.enabled };
  case "cleared":
    return {
      ...INITIAL_OCR_DIAGNOSTICS_STATE,
      selectionGeneration: state.selectionGeneration + 1,
      recognitionRequest: state.recognitionRequest,
      overlayEnabled: state.overlayEnabled,
    };
  }
}

export type ImagePickerGateway = {
  requestPermission(): Promise<{ granted: boolean }>;
  launch(): Promise<{
    canceled: boolean;
    assets?: Array<{ uri: string; width: number; height: number; fileName?: string | null }> | null;
  }>;
};

export type ImageAcquisitionOutcome =
  | { kind: "selected"; selection: OcrImageSelection }
  | { kind: "cancelled"; source: OcrImageSource }
  | { kind: "permissionDenied"; source: OcrImageSource }
  | { kind: "failed"; source: OcrImageSource };

export async function acquireOcrImage(
  source: OcrImageSource,
  gateway: ImagePickerGateway,
): Promise<ImageAcquisitionOutcome> {
  try {
    const permission = await gateway.requestPermission();
    if (!permission.granted) {
      return { kind: "permissionDenied", source };
    }
    const result = await gateway.launch();
    const asset = result.assets?.[0];
    if (result.canceled || !asset) {
      return { kind: "cancelled", source };
    }
    return { kind: "selected", selection: { ...asset, source } };
  } catch {
    return { kind: "failed", source };
  }
}

export function canStartAcquisition(state: OcrDiagnosticsState): boolean {
  return state.acquisitionSource === null;
}

export function canStartRecognition(state: OcrDiagnosticsState): boolean {
  return Boolean(state.selection) && state.acquisitionSource === null && state.recognitionRequest === null;
}

export async function recognizeSelection(
  selection: OcrImageSelection,
  recognize: (uri: string, options: OcrRecognitionOptions) => Promise<OcrRecognitionResult>,
  options: OcrRecognitionOptions,
): Promise<OcrRecognitionResult> {
  return recognize(selection.uri, options);
}

export async function deleteCameraCapture(
  selection: OcrImageSelection | null,
  deleteFile: (uri: string) => Promise<void>,
): Promise<boolean> {
  if (!selection || selection.source !== "camera") {
    return false;
  }
  try {
    await deleteFile(selection.uri);
    return true;
  } catch {
    // Cache cleanup is best-effort and must tolerate already-missing files.
    return false;
  }
}

export function isOcrDiagnosticsEnabled(developmentMode: boolean): boolean {
  return developmentMode;
}
