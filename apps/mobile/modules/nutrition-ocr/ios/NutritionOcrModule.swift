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

private struct NativeObservation {
  let text: String
  let confidence: Float
  let boundingBox: CGRect
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
    let dimensions = displayedDimensions(width: cgImage.width, height: cgImage.height, orientation: orientation)
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
        boundingBox: topLeftBoundingBox(from: observation.boundingBox)
      )
    }
    let ordered = observationsInReadingOrder(observations)
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
        "orientationApplied": orientation != .up
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

  private static func displayedDimensions(
    width: Int,
    height: Int,
    orientation: CGImagePropertyOrientation
  ) -> (width: Int, height: Int) {
    switch orientation {
    case .left, .leftMirrored, .right, .rightMirrored:
      return (height, width)
    default:
      return (width, height)
    }
  }

  // Vision uses a lower-left origin. React Native consumers receive an upper-left
  // origin in the displayed, orientation-corrected image coordinate space.
  private static func topLeftBoundingBox(from visionBox: CGRect) -> CGRect {
    CGRect(
      x: clamp(visionBox.minX),
      y: clamp(1 - visionBox.maxY),
      width: clamp(visionBox.width),
      height: clamp(visionBox.height)
    )
  }

  private static func clamp(_ value: CGFloat) -> CGFloat {
    min(max(value, 0), 1)
  }

  // Conservative row grouping followed by left-to-right ordering. This produces
  // stable line joining without attempting nutrition-label layout interpretation.
  private static func observationsInReadingOrder(_ observations: [NativeObservation]) -> [NativeObservation] {
    let topToBottom = observations.sorted(by: stableTopToBottom)
    var rows: [[NativeObservation]] = []

    for observation in topToBottom {
      guard let lastRow = rows.last, let anchor = lastRow.first else {
        rows.append([observation])
        continue
      }
      let threshold = max(anchor.boundingBox.height, observation.boundingBox.height) * 0.5
      if abs(anchor.boundingBox.midY - observation.boundingBox.midY) <= threshold {
        rows[rows.count - 1].append(observation)
      } else {
        rows.append([observation])
      }
    }

    return rows.flatMap { row in
      row.sorted {
        if $0.boundingBox.minX != $1.boundingBox.minX { return $0.boundingBox.minX < $1.boundingBox.minX }
        return stableTopToBottom($0, $1)
      }
    }
  }

  private static func stableTopToBottom(_ lhs: NativeObservation, _ rhs: NativeObservation) -> Bool {
    if lhs.boundingBox.minY != rhs.boundingBox.minY { return lhs.boundingBox.minY < rhs.boundingBox.minY }
    if lhs.boundingBox.minX != rhs.boundingBox.minX { return lhs.boundingBox.minX < rhs.boundingBox.minX }
    if lhs.boundingBox.height != rhs.boundingBox.height { return lhs.boundingBox.height > rhs.boundingBox.height }
    return lhs.text < rhs.text
  }
}
