# Stage 5: Apple Vision still-image OCR

Stage 5 recognizes text in a selected or newly captured still image. It does not parse nutrition values, create Foods, persist scans, or upload images. Stage 5A introduced the native bridge and photo-library diagnostics; Stage 5B adds still-camera capture, cache cleanup, race protection, an aspect-fit bounding-box overlay, and deterministic orientation validation.

## Integration and builds

The checked-in local Expo module is at `apps/mobile/modules/nutrition-ocr`. Expo Modules autolinking discovers `expo-module.config.json`; Expo prebuild generates the Xcode/Pods integration. Generated `apps/mobile/ios`, `apps/mobile/android`, and Pod changes are not committed.

The deployment target is iOS 15.1, matching Expo SDK 53. Apple Vision and ImageIO are system frameworks. Expo Go cannot load the project-specific Swift module, so use a custom development build:

```bash
cd apps/mobile
npm install
npx expo prebuild --platform ios
npx expo run:ios
```

The Image Picker plugin supplies distinct photo-library and camera purpose strings. Microphone permission is disabled. A clean prebuild is required after pulling the Stage 5B permission change into an existing generated project:

```bash
npx expo prebuild --platform ios --clean
```

## OCR contract

Callers import `isOcrSupported` and `recognizeTextFromImage` from `apps/mobile/src/native/ocr/NutritionOcr.ts`. The Stage 5A public contract remains unchanged.

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

Defaults are accurate recognition, `en-US`, language correction off, and no minimum text-height filter. The module accepts local `file:` URIs and does not move base64 image data through the bridge.

Stable native OCR errors remain:

- `ocr_not_supported`
- `ocr_invalid_image_uri`
- `ocr_image_not_found`
- `ocr_image_decode_failed`
- `ocr_recognition_failed`

Camera/photo permission denial, cancellation, and acquisition failure are local diagnostics outcomes; they are not mislabeled as OCR failures. Android, web, Expo Go, and unlinked iOS builds remain unsupported through the typed support check.

## Acquisition and temporary files

The diagnostics model records `source: "photo_library" | "camera"` alongside the picker URI, width, height, and optional filename. Photo and camera permissions are requested only by their corresponding actions. Both launch paths accept images only, disable editing/base64, request full quality, and return exactly one local file.

Expo Image Picker 16.1.4 writes both camera and library results into its app cache under `ImagePicker`. For camera capture, its iOS implementation fixes the `UIImage` orientation, encodes a JPEG, and returns the cache URI. Camera files are therefore app-owned temporary copies. Stage 5B deletes replaced, cleared, and unmounted camera captures using idempotent `expo-file-system` deletion. Deletion is deferred while the same URI is being recognized and missing-file cleanup is tolerated. Photo-library originals are never deleted; their picker-created cache copies are left to Expo/iOS cache lifecycle.

No selected or captured image is copied into application persistence.

## Orientation and coordinates

`VNImageRequestHandler` receives the EXIF `CGImagePropertyOrientation`, including all mirrored cases. Apple Vision defines observation boxes against the processed image with a normalized lower-left origin, and the orientation argument supersedes other image orientation information. The bridge therefore:

1. swaps displayed width/height for left, right, left-mirrored, and right-mirrored input;
2. reports `orientationApplied` for every orientation except up;
3. relies on Vision to orient and mirror the processed image;
4. converts only the origin from lower-left to upper-left with `y = 1 - maxY`.

No Stage 5A coordinate correction was required. The output remains normalized to the displayed, orientation-corrected image, with `x` increasing rightward and `y` downward.

Pure Swift validation covers dimensions, applied status, lower-left conversion, clamp behavior, and deterministic ordering for all eight EXIF orientations. A second runtime executable generates an upright synthetic `TOP` fixture, inverse-encodes it for each EXIF orientation, writes/decodes the JPEG metadata, runs real Apple Vision OCR, and verifies that the recognized boxes align in the same displayed coordinate space for all rotated and mirrored variants.

## Diagnostics overlay and concurrency

Open Settings → Development → Apple Vision OCR diagnostics in a development build. The entry and route remain guarded by `__DEV__`.

The screen provides Choose photo, Take photo, Run/Retry OCR, Clear, and an optional bounding-box overlay. It shows image source, picker dimensions, native displayed dimensions, orientation status, OCR options, observation count, duration, full text, confidence, and raw normalized boxes.

The overlay measures the preview container at runtime. It computes the contained image rectangle using `min(containerWidth/imageWidth, containerHeight/imageHeight)`, centers that rectangle inside any aspect-fit letterboxing, and maps each normalized box into it. Native recognized dimensions are authoritative for the result overlay; picker and native dimensions remain separately visible.

One acquisition and one recognition may be active at a time. Camera/photo replacement remains available while OCR is finishing, but Run is disabled until that native request settles. Recognition requests carry an image-generation token; replacement or Clear invalidates the token, so stale success and failure results cannot repopulate the screen. Replacing an image resets prior results and boxes.

Buttons expose disabled/busy state, the overlay uses switch semantics, failures use assertive alerts, progress/state uses polite live updates, and individual raw observations are hidden from accessibility traversal in favor of one coherent full-text result and observation summary.

## Privacy and limitations

OCR runs locally on a user-initiated background queue. Stage 5 does not upload images, persist images or OCR text, modify Foods, or emit paths/text to production analytics. Development native errors omit image paths and recognized text.

Apple Vision recognition and confidence can vary with blur, glare, low contrast, very small text, unusual fonts, and complex multi-column layouts. Reading order remains deliberately conservative and is not a nutrition-label parser. Apple notes that some Vision simulator results can differ from device rendering. The iOS simulator does not provide Image Picker camera capture, so physical-device camera QA is still required.

## Validation commands and status

```bash
cd apps/mobile
npm test -- --runInBand __tests__/nutritionOcr.test.ts __tests__/ocrDiagnostics.test.ts __tests__/ocrOverlayLayout.test.ts __tests__/ocrDiagnosticsScreen.test.ts
npm test -- --runInBand
npm run typecheck
npx expo export --platform ios --output-dir .expo/ocr-stage5b-export --clear

mkdir -p /tmp/nutrition-ocr-tests
xcrun swiftc modules/nutrition-ocr/ios/NutritionOcrGeometry.swift modules/nutrition-ocr/ios-tests/NutritionOcrGeometryTests.swift -framework ImageIO -o /tmp/nutrition-ocr-tests/NutritionOcrGeometryTests
/tmp/nutrition-ocr-tests/NutritionOcrGeometryTests

xcrun swiftc modules/nutrition-ocr/ios/NutritionOcrGeometry.swift modules/nutrition-ocr/ios-tests/NutritionOcrVisionRuntimeTests.swift -framework AppKit -framework CoreImage -framework ImageIO -framework Vision -framework UniformTypeIdentifiers -o /tmp/nutrition-ocr-tests/NutritionOcrVisionRuntimeTests
/tmp/nutrition-ocr-tests/NutritionOcrVisionRuntimeTests

npx expo prebuild --platform ios --clean
cd ios && pod install
xcodebuild -workspace NutritionApp.xcworkspace -scheme NutritionApp -configuration Debug -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build
```

Automated Stage 5B runtime evidence: both Swift executables pass across all eight EXIF orientations, including mirrored variants. Focused TypeScript/mounted tests cover both acquisition sources, separate permissions, cancellation/failure, cache deletion, busy guards, stale result handling, aspect-fit overlay mapping, retries, and accessibility state.

No physical-device session was available during implementation. Portrait/landscape capture, camera denial, high-resolution/low-contrast capture, and live overlay inspection on real camera output remain the manual release-QA checklist. Stage 5 implementation is complete; this device QA should be completed before Stage 6 begins relying on capture geometry.
