import { requireOptionalNativeModule } from "expo-modules-core";
import { Platform } from "react-native";
import { z } from "zod";

import {
  OCR_ERROR_CODES,
  type OcrErrorCode,
  type OcrErrorContext,
  type OcrRecognitionOptions,
  type OcrRecognitionResult,
  type ResolvedOcrRecognitionOptions,
} from "./types";

type NativeNutritionOcrModule = {
  isSupported(): boolean;
  recognizeTextFromImage(
    imageUri: string,
    options: ResolvedOcrRecognitionOptions,
  ): Promise<unknown>;
};

type OcrClientDependencies = {
  platform: string;
  nativeModule: NativeNutritionOcrModule | null;
};

const observationSchema = z.object({
  id: z.string().min(1),
  text: z.string(),
  confidence: z.number().min(0).max(1),
  boundingBox: z.object({
    x: z.number().min(0).max(1),
    y: z.number().min(0).max(1),
    width: z.number().min(0).max(1),
    height: z.number().min(0).max(1),
  }),
});

const resultSchema = z.object({
  observations: z.array(observationSchema),
  fullText: z.string(),
  image: z.object({
    width: z.number().int().positive(),
    height: z.number().int().positive(),
    orientationApplied: z.boolean(),
  }),
  recognition: z.object({
    platform: z.literal("ios"),
    recognitionLevel: z.enum(["accurate", "fast"]),
    languages: z.array(z.string().min(1)),
    durationMs: z.number().nonnegative(),
  }),
});

export const DEFAULT_OCR_OPTIONS: ResolvedOcrRecognitionOptions = {
  recognitionLevel: "accurate",
  languages: ["en-US"],
  // Nutrition abbreviations and decimal values are safer without spell correction.
  usesLanguageCorrection: false,
};

export class OcrError extends Error {
  readonly code: OcrErrorCode;
  readonly context?: OcrErrorContext;

  constructor(code: OcrErrorCode, message: string, context?: OcrErrorContext) {
    super(message);
    this.name = "OcrError";
    this.code = code;
    this.context = context;
  }
}

function isOcrErrorCode(value: unknown): value is OcrErrorCode {
  return typeof value === "string" && (OCR_ERROR_CODES as readonly string[]).includes(value);
}

export function resolveOcrOptions(options: OcrRecognitionOptions = {}): ResolvedOcrRecognitionOptions {
  if (options.languages?.some((language) => language.trim().length === 0)) {
    throw new OcrError("ocr_recognition_failed", "OCR languages cannot contain an empty value.");
  }
  if (options.languages && options.languages.length === 0) {
    throw new OcrError("ocr_recognition_failed", "OCR languages cannot be empty.");
  }
  if (options.minimumTextHeight !== undefined &&
      (!Number.isFinite(options.minimumTextHeight) || options.minimumTextHeight <= 0 || options.minimumTextHeight > 1)) {
    throw new OcrError("ocr_recognition_failed", "minimumTextHeight must be greater than 0 and at most 1.");
  }

  return {
    recognitionLevel: options.recognitionLevel ?? DEFAULT_OCR_OPTIONS.recognitionLevel,
    languages: options.languages?.map((language) => language.trim()) ?? [...DEFAULT_OCR_OPTIONS.languages],
    usesLanguageCorrection: options.usesLanguageCorrection ?? DEFAULT_OCR_OPTIONS.usesLanguageCorrection,
    ...(options.minimumTextHeight === undefined ? {} : { minimumTextHeight: options.minimumTextHeight }),
  };
}

export function normalizeOcrError(error: unknown): OcrError {
  if (error instanceof OcrError) {
    return error;
  }
  if (typeof error === "object" && error !== null && "code" in error && isOcrErrorCode(error.code)) {
    const message = "message" in error && typeof error.message === "string"
      ? error.message
      : "Apple Vision OCR could not complete the request.";
    return new OcrError(error.code, message);
  }
  return new OcrError("ocr_recognition_failed", "Apple Vision OCR could not complete the request.");
}

export function createOcrClient(dependencies: OcrClientDependencies) {
  const isOcrSupported = (): boolean =>
    dependencies.platform === "ios" && dependencies.nativeModule?.isSupported() === true;

  const recognizeTextFromImage = async (
    imageUri: string,
    options?: OcrRecognitionOptions,
  ): Promise<OcrRecognitionResult> => {
    if (dependencies.platform !== "ios" || !dependencies.nativeModule?.isSupported()) {
      throw new OcrError("ocr_not_supported", "On-device Apple Vision OCR is available only in an iOS development build.");
    }
    if (typeof imageUri !== "string" || imageUri.trim().length === 0) {
      throw new OcrError("ocr_invalid_image_uri", "Choose a local image before starting OCR.");
    }

    try {
      const rawResult = await dependencies.nativeModule.recognizeTextFromImage(
        imageUri.trim(),
        resolveOcrOptions(options),
      );
      const parsed = resultSchema.safeParse(rawResult);
      if (!parsed.success) {
        throw new OcrError("ocr_recognition_failed", "The native OCR module returned an invalid result.");
      }
      return parsed.data;
    } catch (error) {
      throw normalizeOcrError(error);
    }
  };

  return { isOcrSupported, recognizeTextFromImage };
}

const nativeModule = requireOptionalNativeModule<NativeNutritionOcrModule>("NutritionOcr");
const client = createOcrClient({ platform: Platform.OS, nativeModule });

export const isOcrSupported = client.isOcrSupported;
export const recognizeTextFromImage = client.recognizeTextFromImage;

export type {
  OcrBoundingBox,
  OcrErrorCode,
  OcrImageMetadata,
  OcrRecognitionMetadata,
  OcrRecognitionLevel,
  OcrRecognitionOptions,
  OcrRecognitionResult,
  OcrTextObservation,
  ResolvedOcrRecognitionOptions,
} from "./types";
