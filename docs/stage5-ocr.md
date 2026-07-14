# Stage 5A: Apple Vision OCR bridge

Stage 5A recognizes text in a selected still image. It deliberately does not parse nutrition values, create Foods, persist scans, or upload images.

## Integration and builds

The checked-in local Expo module is at `apps/mobile/modules/nutrition-ocr`. Expo Modules autolinking discovers `expo-module.config.json`; Expo prebuild generates the Xcode/Pods integration. This repository does not commit generated `apps/mobile/ios` or `apps/mobile/android` directories or generated Pod changes.

The deployment target is iOS 15.1, matching Expo SDK 53 and the generated mobile project. Apple Vision is part of the iOS SDK, so the module adds no third-party OCR Pod.

Expo Go cannot load a project-specific Swift module. Use a custom development build:

```bash
cd apps/mobile
npm install
npx expo prebuild --platform ios
npx expo run:ios
```

Run prebuild again after changing local module metadata, native dependencies, or app permission configuration. `npx expo prebuild --platform ios --clean` is useful as a consistency check, but it replaces the generated `ios/` directory.

The only new acquisition dependency is `expo-image-picker`. The app configuration supplies `NSPhotoLibraryUsageDescription` and explicitly disables camera and microphone permissions. Stage 5A supports choosing a photo; still-camera capture is deferred to a bounded follow-up.

## TypeScript contract

Callers import `isOcrSupported` and `recognizeTextFromImage` from `apps/mobile/src/native/ocr/NutritionOcr.ts`. They do not import Swift implementation types.

```ts
recognizeTextFromImage(
  imageUri: string,
  options?: {
    recognitionLevel?: "accurate" | "fast";
    languages?: string[];
    usesLanguageCorrection?: boolean;
    minimumTextHeight?: number;
  },
): Promise<OcrRecognitionResult>
```

Defaults are accurate recognition, `en-US`, language correction off, and no minimum text-height filter. Correction is off to reduce changes to nutrient abbreviations and decimal values. The native module accepts local `file:` URIs only and does not move base64 image data through the bridge.

The result contains ordered observations, exact candidate text, confidence in `0...1`, normalized boxes, joined `fullText`, displayed image dimensions, orientation status, configured level/languages, and recognition duration. IDs such as `observation-0001` are deterministic within one result.

Bounding boxes use the displayed, orientation-corrected image. The origin is the upper-left; `x` increases rightward and `y` increases downward. All four values are normalized relative to displayed image width and height. Native Vision lower-left coordinates are converted before crossing the bridge. Observations use conservative top-to-bottom row grouping and left-to-right ordering; this is not a nutrition-label parser.

Stable error codes are:

- `ocr_not_supported`
- `ocr_invalid_image_uri`
- `ocr_image_not_found`
- `ocr_image_decode_failed`
- `ocr_recognition_failed`

Android, web, Expo Go, and an unlinked iOS build report unsupported through the same TypeScript contract. Raw native errors and file paths are not surfaced to users.

## Diagnostics and privacy

In a development build, open Settings → Development → Apple Vision OCR diagnostics. The entry and route are both guarded by `__DEV__` and are unavailable in production mode.

The screen can choose an image, show its preview and picker dimensions, select recognition level and language-correction behavior, run/retry/clear OCR, and inspect status, recognized dimensions, duration, observation count, full text, confidence, and normalized boxes. Permission denial gives actionable iOS Settings guidance. There is no copy action because the repository has no clipboard dependency, and no overlay is included in this foundation.

OCR runs locally through Apple Vision on a user-initiated background queue. The selected image remains at its picker-provided local URI. Stage 5A does not upload it, retain a copy, write OCR results to app/backend persistence, or emit image paths/recognized text to analytics. Development-only native failure logs omit image paths and recognized text.

## Validation

```bash
cd apps/mobile
npm test -- --runInBand __tests__/nutritionOcr.test.ts __tests__/ocrDiagnostics.test.ts
npm test -- --runInBand
npm run typecheck
npx expo prebuild --platform ios --clean
npx expo run:ios
```

The TypeScript tests cover defaults and option mapping, native result validation, unsupported platforms, input validation, structured error normalization, permission denial, picker cancellation/success, recognition invocation, failure/retry/success/clear state, and development gating.

There is no checked-in native XCTest target in the generated-project workflow. Coordinate conversion, orientation dimension handling, option mapping, error mapping, and deterministic ordering are isolated as pure Swift helpers in the local module so native test coverage can be added when a durable module test host is introduced.
