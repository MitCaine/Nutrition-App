import type { OcrImageQualityMetrics } from "../../../native/ocr/types";

export type OcrImageQualityWarningCode =
  | "low_resolution"
  | "too_dark"
  | "too_bright"
  | "severe_blur"
  | "too_far";

export type OcrImageQualityWarning = Readonly<{
  code: OcrImageQualityWarningCode;
  message: string;
}>;

/**
 * Conservative acquisition thresholds.
 *
 * These are intentionally warnings, not rejection criteria. A caller must
 * always retain a deterministic path to continue with the original image.
 */
export const OCR_IMAGE_QUALITY_THRESHOLDS = Object.freeze({
  minimumShortEdgePx: 900,

  maximumMeanLuminanceForDark: 0.16,
  minimumDarkPixelFractionForDark: 0.60,

  minimumMeanLuminanceForBright: 0.90,
  minimumBrightPixelFractionForBright: 0.45,

  minimumFocusVarianceForUsable: 0.025,

  minimumTextRegionsForCoverage: 3,
  minimumTextRegionAreaFraction: 0.012,
});

function isExtremeDark(metrics: OcrImageQualityMetrics): boolean {
  return (
    metrics.meanLuminance <=
      OCR_IMAGE_QUALITY_THRESHOLDS.maximumMeanLuminanceForDark &&
    metrics.darkPixelFraction >=
      OCR_IMAGE_QUALITY_THRESHOLDS.minimumDarkPixelFractionForDark
  );
}

function isExtremeBright(metrics: OcrImageQualityMetrics): boolean {
  return (
    metrics.meanLuminance >=
      OCR_IMAGE_QUALITY_THRESHOLDS.minimumMeanLuminanceForBright &&
    metrics.brightPixelFraction >=
      OCR_IMAGE_QUALITY_THRESHOLDS.minimumBrightPixelFractionForBright
  );
}

export function imageQualityWarnings(
  metrics: OcrImageQualityMetrics,
): OcrImageQualityWarning[] {
  const warnings: OcrImageQualityWarning[] = [];

  if (
    Math.min(metrics.width, metrics.height) <
    OCR_IMAGE_QUALITY_THRESHOLDS.minimumShortEdgePx
  ) {
    warnings.push({
      code: "low_resolution",
      message:
        "This photo is unusually low resolution. Move closer and retake if the Nutrition Facts text is difficult to read.",
    });
  }

  const tooDark = isExtremeDark(metrics);
  const tooBright = isExtremeBright(metrics);

  if (tooDark) {
    warnings.push({
      code: "too_dark",
      message:
        "The label is very dark. Add more light or move to a brighter area before retaking.",
    });
  }

  if (tooBright) {
    warnings.push({
      code: "too_bright",
      message:
        "The label has extensive blown-out highlights. Reduce glare or change the camera angle before retaking.",
    });
  }

  const tooFar =
    metrics.textRegionAreaFraction !== null &&
    metrics.textRegionCount >=
      OCR_IMAGE_QUALITY_THRESHOLDS.minimumTextRegionsForCoverage &&
    metrics.textRegionAreaFraction <
      OCR_IMAGE_QUALITY_THRESHOLDS.minimumTextRegionAreaFraction;

  if (tooFar) {
    warnings.push({
      code: "too_far",
      message:
        "The detected text occupies only a small part of the photo. Move closer while keeping the complete Nutrition Facts panel visible.",
    });
  }

  // Extreme exposure and very small text can both reduce fine-detail
  // measurements without proving camera-motion blur. Prefer the more
  // specific actionable warning instead of presenting a redundant or
  // misleading blur diagnosis.
  if (
    !tooDark &&
    !tooBright &&
    !tooFar &&
    metrics.focusVariance <=
      OCR_IMAGE_QUALITY_THRESHOLDS.minimumFocusVarianceForUsable
  ) {
    warnings.push({
      code: "severe_blur",
      message:
        "The photo looks severely blurred. Hold the phone steadier and retake the label.",
    });
  }

  return warnings;
}

export type { OcrImageQualityMetrics } from "../../../native/ocr/types";
