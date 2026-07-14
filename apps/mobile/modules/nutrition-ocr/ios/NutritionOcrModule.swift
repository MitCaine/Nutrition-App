import ExpoModulesCore
import Foundation
import ImageIO
import Vision

private enum OcrRecognitionLevel: String, Enumerable {
  case accurate
  case fast
}

private struct OcrRecognitionOptions: Record {
  @Field var recognitionLevel: OcrRecognitionLevel = .accurate
  @Field var languages: [String] = ["en-US"]
  @Field var usesLanguageCorrection: Bool = false
  @Field var minimumTextHeight: Double?
}

private enum OcrFailure {
  case invalidImageUri
  case imageNotFound
  case imageDecodeFailed
  case recognitionFailed

  var code: String {
    switch self {
    case .invalidImageUri: return "ocr_invalid_image_uri"
    case .imageNotFound: return "ocr_image_not_found"
    case .imageDecodeFailed: return "ocr_image_decode_failed"
    case .recognitionFailed: return "ocr_recognition_failed"
    }
  }

  var message: String {
    switch self {
    case .invalidImageUri: return "The OCR image must be a valid local file URI."
    case .imageNotFound: return "The selected OCR image no longer exists. Choose it again."
    case .imageDecodeFailed: return "The selected file could not be decoded as a supported image."
    case .recognitionFailed: return "Apple Vision could not recognize text in the selected image."
    }
  }

  var exception: Exception {
    Exception(name: "NutritionOcrException", description: message, code: code)
  }
}

public final class NutritionOcrModule: Module {
  public func definition() -> ModuleDefinition {
    Name("NutritionOcr")

    Function("isSupported") {
      true
    }

    AsyncFunction("recognizeTextFromImage") { (imageUri: String, options: OcrRecognitionOptions) throws -> [String: Any] in
      try Self.recognizeText(from: imageUri, options: options)
    }
    .runOnQueue(DispatchQueue.global(qos: .userInitiated))
  }

  private static func recognizeText(from imageUri: String, options: OcrRecognitionOptions) throws -> [String: Any] {
    guard let url = URL(string: imageUri), url.isFileURL else {
      throw OcrFailure.invalidImageUri.exception
    }
    guard FileManager.default.fileExists(atPath: url.path) else {
      throw OcrFailure.imageNotFound.exception
    }
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
          CGImageSourceGetCount(source) > 0,
          let cgImage = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
      throw OcrFailure.imageDecodeFailed.exception
    }

    let orientation = imageOrientation(from: source)
    let dimensions = NutritionOcrGeometry.displayedDimensions(width: cgImage.width, height: cgImage.height, orientation: orientation)
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = options.recognitionLevel == .fast ? .fast : .accurate
    request.recognitionLanguages = options.languages
    request.usesLanguageCorrection = options.usesLanguageCorrection
    if let minimumTextHeight = options.minimumTextHeight {
      request.minimumTextHeight = Float(minimumTextHeight)
    }

    let startedAt = CFAbsoluteTimeGetCurrent()
    do {
      try VNImageRequestHandler(cgImage: cgImage, orientation: orientation, options: [:]).perform([request])
    } catch {
      #if DEBUG
      NSLog("NutritionOcr Vision request failed: %@", String(describing: error))
      #endif
      throw OcrFailure.recognitionFailed.exception
    }
    let durationMs = Int(((CFAbsoluteTimeGetCurrent() - startedAt) * 1_000).rounded())

    let observations = (request.results ?? []).compactMap { observation -> NativeObservation? in
      guard let candidate = observation.topCandidates(1).first else { return nil }
      return NativeObservation(
        text: candidate.string,
        confidence: min(max(candidate.confidence, 0), 1),
        boundingBox: NutritionOcrGeometry.topLeftBoundingBox(from: observation.boundingBox)
      )
    }
    let ordered = NutritionOcrGeometry.observationsInReadingOrder(observations)
    let encoded = ordered.enumerated().map { index, observation in
      [
        "id": String(format: "observation-%04d", index + 1),
        "text": observation.text,
        "confidence": Double(observation.confidence),
        "boundingBox": [
          "x": Double(observation.boundingBox.origin.x),
          "y": Double(observation.boundingBox.origin.y),
          "width": Double(observation.boundingBox.width),
          "height": Double(observation.boundingBox.height)
        ]
      ] as [String: Any]
    }

    return [
      "observations": encoded,
      "fullText": ordered.map(\.text).joined(separator: "\n"),
      "image": [
        "width": dimensions.width,
        "height": dimensions.height,
        "orientationApplied": NutritionOcrGeometry.orientationApplied(orientation)
      ],
      "recognition": [
        "platform": "ios",
        "recognitionLevel": options.recognitionLevel.rawValue,
        "languages": options.languages,
        "durationMs": durationMs
      ]
    ]
  }

  private static func imageOrientation(from source: CGImageSource) -> CGImagePropertyOrientation {
    guard let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
          let rawValue = properties[kCGImagePropertyOrientation] as? NSNumber,
          let orientation = CGImagePropertyOrientation(rawValue: rawValue.uint32Value) else {
      return .up
    }
    return orientation
  }

}
