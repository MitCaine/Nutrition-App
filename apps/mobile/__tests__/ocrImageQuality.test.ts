import {
  imageQualityWarnings,
  OCR_IMAGE_QUALITY_THRESHOLDS,
  type OcrImageQualityMetrics,
} from "../src/features/ocr/quality/imageQuality";

const GOOD_METRICS: OcrImageQualityMetrics = {
  width: 3024,
  height: 4032,
  meanLuminance: 0.55,
  darkPixelFraction: 0.08,
  brightPixelFraction: 0.05,
  focusVariance: 0.06,
  textRegionCount: 12,
  textRegionAreaFraction: 0.045,
};

function warningCodes(
  overrides: Partial<OcrImageQualityMetrics>,
): string[] {
  return imageQualityWarnings({
    ...GOOD_METRICS,
    ...overrides,
  }).map(({ code }) => code);
}

test("a well-qualified camera image produces no quality warning", () => {
  expect(imageQualityWarnings(GOOD_METRICS)).toEqual([]);
});

test("low-resolution threshold is strict at the short edge boundary", () => {
  const threshold = OCR_IMAGE_QUALITY_THRESHOLDS.minimumShortEdgePx;

  expect(
    warningCodes({ width: threshold - 1, height: 1600 }),
  ).toContain("low_resolution");

  expect(
    warningCodes({ width: threshold, height: 1600 }),
  ).not.toContain("low_resolution");
});

test("extreme darkness requires both low average luminance and a large dark-pixel fraction", () => {
  const {
    maximumMeanLuminanceForDark,
    minimumDarkPixelFractionForDark,
  } = OCR_IMAGE_QUALITY_THRESHOLDS;

  expect(
    warningCodes({
      meanLuminance: maximumMeanLuminanceForDark,
      darkPixelFraction: minimumDarkPixelFractionForDark,
    }),
  ).toContain("too_dark");

  expect(
    warningCodes({
      meanLuminance: maximumMeanLuminanceForDark + 0.001,
      darkPixelFraction: minimumDarkPixelFractionForDark,
    }),
  ).not.toContain("too_dark");

  expect(
    warningCodes({
      meanLuminance: maximumMeanLuminanceForDark,
      darkPixelFraction: minimumDarkPixelFractionForDark - 0.001,
    }),
  ).not.toContain("too_dark");
});

test("extreme brightness requires both high average luminance and a large clipped-highlight fraction", () => {
  const {
    minimumMeanLuminanceForBright,
    minimumBrightPixelFractionForBright,
  } = OCR_IMAGE_QUALITY_THRESHOLDS;

  expect(
    warningCodes({
      meanLuminance: minimumMeanLuminanceForBright,
      brightPixelFraction: minimumBrightPixelFractionForBright,
    }),
  ).toContain("too_bright");

  expect(
    warningCodes({
      meanLuminance: minimumMeanLuminanceForBright - 0.001,
      brightPixelFraction: minimumBrightPixelFractionForBright,
    }),
  ).not.toContain("too_bright");

  expect(
    warningCodes({
      meanLuminance: minimumMeanLuminanceForBright,
      brightPixelFraction: minimumBrightPixelFractionForBright - 0.001,
    }),
  ).not.toContain("too_bright");
});

test("severe blur uses an inclusive focus-variance boundary under otherwise usable exposure", () => {
  const threshold =
    OCR_IMAGE_QUALITY_THRESHOLDS.minimumFocusVarianceForUsable;

  expect(
    warningCodes({ focusVariance: threshold }),
  ).toContain("severe_blur");

  expect(
    warningCodes({ focusVariance: threshold + 0.001 }),
  ).not.toContain("severe_blur");
});

test("exposure warnings suppress a redundant blur warning", () => {
  const warnings = warningCodes({
    meanLuminance:
      OCR_IMAGE_QUALITY_THRESHOLDS.maximumMeanLuminanceForDark,
    darkPixelFraction:
      OCR_IMAGE_QUALITY_THRESHOLDS.minimumDarkPixelFractionForDark,
    focusVariance: 0,
  });

  expect(warnings).toContain("too_dark");
  expect(warnings).not.toContain("severe_blur");
});

test("text-area coverage warns only when enough detected regions make the proxy meaningful", () => {
  const {
    minimumTextRegionsForCoverage,
    minimumTextRegionAreaFraction,
  } = OCR_IMAGE_QUALITY_THRESHOLDS;

  expect(
    warningCodes({
      textRegionCount: minimumTextRegionsForCoverage,
      textRegionAreaFraction:
        minimumTextRegionAreaFraction - 0.001,
    }),
  ).toContain("too_far");

  expect(
    warningCodes({
      textRegionCount: minimumTextRegionsForCoverage,
      textRegionAreaFraction:
        minimumTextRegionAreaFraction,
    }),
  ).not.toContain("too_far");

  expect(
    warningCodes({
      textRegionCount: minimumTextRegionsForCoverage - 1,
      textRegionAreaFraction: 0.001,
    }),
  ).not.toContain("too_far");
});

test("missing text-area evidence is treated as uncertainty rather than rejection", () => {
  expect(
    warningCodes({
      textRegionCount: 0,
      textRegionAreaFraction: null,
    }),
  ).toEqual([]);
});

test("reliable too-far evidence suppresses an ambiguous blur diagnosis", () => {
  const warnings = warningCodes({
    focusVariance: 0,
    textRegionCount:
      OCR_IMAGE_QUALITY_THRESHOLDS.minimumTextRegionsForCoverage,
    textRegionAreaFraction:
      OCR_IMAGE_QUALITY_THRESHOLDS.minimumTextRegionAreaFraction - 0.001,
  });

  expect(warnings).toContain("too_far");
  expect(warnings).not.toContain("severe_blur");
});
