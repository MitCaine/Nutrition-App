export type OcrRecognitionLevel = "accurate" | "fast";

export type OcrRecognitionOptions = {
  recognitionLevel?: OcrRecognitionLevel;
  languages?: string[];
  usesLanguageCorrection?: boolean;
  minimumTextHeight?: number;
};

export type ResolvedOcrRecognitionOptions = {
  recognitionLevel: OcrRecognitionLevel;
  languages: string[];
  usesLanguageCorrection: boolean;
  minimumTextHeight?: number;
};

export type OcrBoundingBox = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type OcrTextObservation = {
  id: string;
  text: string;
  confidence: number;
  boundingBox: OcrBoundingBox;
};

export type OcrImageMetadata = {
  width: number;
  height: number;
  orientationApplied: boolean;
};

export type OcrRecognitionMetadata = {
  platform: "ios";
  recognitionLevel: OcrRecognitionLevel;
  languages: string[];
  durationMs: number;
};

export type OcrRecognitionResult = {
  observations: OcrTextObservation[];
  fullText: string;
  image: OcrImageMetadata;
  recognition: OcrRecognitionMetadata;
};

export const OCR_ERROR_CODES = [
  "ocr_not_supported",
  "ocr_invalid_image_uri",
  "ocr_image_not_found",
  "ocr_image_decode_failed",
  "ocr_recognition_failed",
] as const;

export type OcrErrorCode = (typeof OCR_ERROR_CODES)[number];

export type OcrErrorContext = Record<string, string | number | boolean>;
