import type { OcrError, OcrRecognitionOptions, OcrRecognitionResult } from "../../../native/ocr/NutritionOcr";

export type OcrImageSelection = {
  uri: string;
  width: number;
  height: number;
  fileName?: string | null;
};

export type OcrDiagnosticsState = {
  selection: OcrImageSelection | null;
  status: "idle" | "recognizing" | "success" | "failure";
  result: OcrRecognitionResult | null;
  error: OcrError | null;
};

export type OcrDiagnosticsAction =
  | { type: "selected"; selection: OcrImageSelection }
  | { type: "recognitionStarted" }
  | { type: "recognitionSucceeded"; result: OcrRecognitionResult }
  | { type: "recognitionFailed"; error: OcrError }
  | { type: "cleared" };

export const INITIAL_OCR_DIAGNOSTICS_STATE: OcrDiagnosticsState = {
  selection: null,
  status: "idle",
  result: null,
  error: null,
};

export function ocrDiagnosticsReducer(
  state: OcrDiagnosticsState,
  action: OcrDiagnosticsAction,
): OcrDiagnosticsState {
  switch (action.type) {
  case "selected":
    return { selection: action.selection, status: "idle", result: null, error: null };
  case "recognitionStarted":
    return { ...state, status: "recognizing", result: null, error: null };
  case "recognitionSucceeded":
    return { ...state, status: "success", result: action.result, error: null };
  case "recognitionFailed":
    return { ...state, status: "failure", result: null, error: action.error };
  case "cleared":
    return INITIAL_OCR_DIAGNOSTICS_STATE;
  }
}

export type ImagePickerGateway = {
  requestPermission(): Promise<{ granted: boolean }>;
  launch(): Promise<{
    canceled: boolean;
    assets?: Array<{ uri: string; width: number; height: number; fileName?: string | null }> | null;
  }>;
};

export type ImageSelectionOutcome =
  | { kind: "selected"; selection: OcrImageSelection }
  | { kind: "cancelled" }
  | { kind: "permissionDenied" };

export async function chooseOcrImage(gateway: ImagePickerGateway): Promise<ImageSelectionOutcome> {
  const permission = await gateway.requestPermission();
  if (!permission.granted) {
    return { kind: "permissionDenied" };
  }
  const result = await gateway.launch();
  const asset = result.assets?.[0];
  if (result.canceled || !asset) {
    return { kind: "cancelled" };
  }
  return { kind: "selected", selection: asset };
}

export async function recognizeSelection(
  state: OcrDiagnosticsState,
  recognize: (uri: string, options: OcrRecognitionOptions) => Promise<OcrRecognitionResult>,
  options: OcrRecognitionOptions,
): Promise<OcrRecognitionResult> {
  if (!state.selection) {
    throw new Error("An image selection is required before OCR.");
  }
  return recognize(state.selection.uri, options);
}

export function isOcrDiagnosticsEnabled(developmentMode: boolean): boolean {
  return developmentMode;
}
