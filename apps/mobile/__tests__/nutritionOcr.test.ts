import {
  createOcrClient,
  DEFAULT_OCR_OPTIONS,
  normalizeOcrError,
  OcrError,
  resolveOcrOptions,
} from "../src/native/ocr/NutritionOcr";

const validResult = {
  observations: [{
    id: "observation-0001",
    text: "Calories 120",
    confidence: 0.98,
    boundingBox: { x: 0.1, y: 0.2, width: 0.5, height: 0.1 },
  }],
  fullText: "Calories 120",
  image: { width: 1200, height: 1600, orientationApplied: false },
  recognition: { platform: "ios" as const, recognitionLevel: "accurate" as const, languages: ["en-US"], durationMs: 42 },
};

test("OCR defaults favor still-image accuracy without language correction or filtering", () => {
  expect(resolveOcrOptions()).toEqual(DEFAULT_OCR_OPTIONS);
  expect(DEFAULT_OCR_OPTIONS).toEqual({
    recognitionLevel: "accurate",
    languages: ["en-US"],
    usesLanguageCorrection: false,
  });
});

test("OCR options are resolved without mutating defaults", () => {
  expect(resolveOcrOptions({ recognitionLevel: "fast", minimumTextHeight: 0.02 })).toEqual({
    recognitionLevel: "fast",
    languages: ["en-US"],
    usesLanguageCorrection: false,
    minimumTextHeight: 0.02,
  });
});

test("unsupported platforms reject through the stable contract", async () => {
  const client = createOcrClient({ platform: "android", nativeModule: null });
  expect(client.isOcrSupported()).toBe(false);
  await expect(client.recognizeTextFromImage("file:///label.jpg")).rejects.toMatchObject({ code: "ocr_not_supported" });
});

test("the bridge passes normalized options and validates successful native results", async () => {
  const recognizeTextFromImage = jest.fn().mockResolvedValue(validResult);
  const client = createOcrClient({
    platform: "ios",
    nativeModule: { isSupported: () => true, recognizeTextFromImage },
  });
  await expect(client.recognizeTextFromImage(" file:///label.jpg ")).resolves.toEqual(validResult);
  expect(recognizeTextFromImage).toHaveBeenCalledWith("file:///label.jpg", DEFAULT_OCR_OPTIONS);
});

test("malformed native payloads become structured recognition failures", async () => {
  const client = createOcrClient({
    platform: "ios",
    nativeModule: { isSupported: () => true, recognizeTextFromImage: jest.fn().mockResolvedValue({ fullText: 7 }) },
  });
  await expect(client.recognizeTextFromImage("file:///label.jpg")).rejects.toMatchObject({
    code: "ocr_recognition_failed",
    message: "The native OCR module returned an invalid result.",
  });
});

test("native error codes are preserved but unknown details are not exposed", () => {
  expect(normalizeOcrError({ code: "ocr_image_not_found", message: "Choose the image again." })).toMatchObject({
    code: "ocr_image_not_found",
    message: "Choose the image again.",
  });
  expect(normalizeOcrError(new Error("/private/sensitive/path.jpg"))).toEqual(
    new OcrError("ocr_recognition_failed", "Apple Vision OCR could not complete the request."),
  );
});

test("obvious invalid input is rejected before native invocation", async () => {
  const recognizeTextFromImage = jest.fn();
  const client = createOcrClient({
    platform: "ios",
    nativeModule: { isSupported: () => true, recognizeTextFromImage },
  });
  await expect(client.recognizeTextFromImage(" ")).rejects.toMatchObject({ code: "ocr_invalid_image_uri" });
  expect(recognizeTextFromImage).not.toHaveBeenCalled();
});
