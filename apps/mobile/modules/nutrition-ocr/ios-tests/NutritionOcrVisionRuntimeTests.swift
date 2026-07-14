import AppKit
import CoreImage
import Foundation
import ImageIO
import UniformTypeIdentifiers
import Vision

private struct RuntimeObservation {
  let text: String
  let box: CGRect
}

private func runtimeRequire(_ condition: @autoclosure () -> Bool, _ message: String) {
  if !condition() {
    fatalError(message)
  }
}

@main
enum NutritionOcrVisionRuntimeTests {
  static func main() throws {
    let desiredImage = makeSyntheticLabel()
    let fixtureDirectory = URL(fileURLWithPath: NSTemporaryDirectory())
      .appendingPathComponent("nutrition-ocr-orientation-fixtures", isDirectory: true)
    try FileManager.default.createDirectory(at: fixtureDirectory, withIntermediateDirectories: true)

    let orientations: [CGImagePropertyOrientation] = [
      .up, .down, .left, .right,
      .upMirrored, .downMirrored, .leftMirrored, .rightMirrored,
    ]
    var baseline: CGRect?

    for orientation in orientations {
      let rawImage = inverseOrientedRawImage(from: desiredImage, orientation: orientation)
      let fixtureUrl = fixtureDirectory.appendingPathComponent("orientation-\(orientation.rawValue).jpg")
      try writeJpeg(rawImage, orientation: orientation, to: fixtureUrl)

      guard let source = CGImageSourceCreateWithURL(fixtureUrl as CFURL, nil),
            let decoded = CGImageSourceCreateImageAtIndex(source, 0, nil),
            let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
            let rawOrientation = properties[kCGImagePropertyOrientation] as? NSNumber,
            let decodedOrientation = CGImagePropertyOrientation(rawValue: rawOrientation.uint32Value) else {
        fatalError("Could not decode fixture \(fixtureUrl.lastPathComponent)")
      }
      runtimeRequire(decodedOrientation == orientation, "Fixture orientation metadata changed")

      let dimensions = NutritionOcrGeometry.displayedDimensions(
        width: decoded.width,
        height: decoded.height,
        orientation: decodedOrientation
      )
      runtimeRequire(dimensions.width == desiredImage.width, "Displayed width mismatch for \(orientation.rawValue)")
      runtimeRequire(dimensions.height == desiredImage.height, "Displayed height mismatch for \(orientation.rawValue)")

      let observation = try recognizeSyntheticText(in: decoded, orientation: decodedOrientation)
      runtimeRequire(observation.text.uppercased().contains("TOP"), "Synthetic text was not recognized for \(orientation.rawValue): \(observation.text)")
      let reactNativeBox = NutritionOcrGeometry.topLeftBoundingBox(from: observation.box)
      runtimeRequire(reactNativeBox.minX >= 0 && reactNativeBox.minY >= 0, "Negative normalized origin")
      runtimeRequire(reactNativeBox.maxX <= 1 && reactNativeBox.maxY <= 1, "Normalized box exceeded image")

      if let baseline {
        // JPEG encoding and Vision may shift edges slightly, but orientation-corrected
        // centers and sizes should remain in the same displayed coordinate space.
        runtimeRequire(abs(reactNativeBox.midX - baseline.midX) < 0.06, "Horizontal alignment mismatch for \(orientation.rawValue)")
        runtimeRequire(abs(reactNativeBox.midY - baseline.midY) < 0.06, "Vertical alignment mismatch for \(orientation.rawValue)")
        runtimeRequire(abs(reactNativeBox.width - baseline.width) < 0.06, "Width mismatch for \(orientation.rawValue)")
        runtimeRequire(abs(reactNativeBox.height - baseline.height) < 0.06, "Height mismatch for \(orientation.rawValue)")
      } else {
        baseline = reactNativeBox
      }
    }

    print("NutritionOcrVisionRuntimeTests passed: synthetic TOP fixture aligned across all 8 EXIF orientations")
  }

  private static func makeSyntheticLabel() -> CGImage {
    let size = NSSize(width: 800, height: 500)
    let image = NSImage(size: size)
    image.lockFocus()
    NSColor.white.setFill()
    NSBezierPath(rect: NSRect(origin: .zero, size: size)).fill()
    NSColor.black.setStroke()
    let border = NSBezierPath(rect: NSRect(x: 16, y: 16, width: 768, height: 468))
    border.lineWidth = 5
    border.stroke()
    let attributes: [NSAttributedString.Key: Any] = [
      .font: NSFont.systemFont(ofSize: 96, weight: .bold),
      .foregroundColor: NSColor.black,
    ]
    NSString(string: "TOP").draw(at: NSPoint(x: 55, y: 350), withAttributes: attributes)
    image.unlockFocus()
    var rect = NSRect(origin: .zero, size: size)
    guard let cgImage = image.cgImage(forProposedRect: &rect, context: nil, hints: nil) else {
      fatalError("Could not create synthetic label")
    }
    return cgImage
  }

  private static func inverseOrientedRawImage(
    from desiredImage: CGImage,
    orientation: CGImagePropertyOrientation
  ) -> CGImage {
    let inverse: CGImagePropertyOrientation
    switch orientation {
    case .left: inverse = .right
    case .right: inverse = .left
    default: inverse = orientation
    }
    let oriented = CIImage(cgImage: desiredImage).oriented(forExifOrientation: Int32(inverse.rawValue))
    let extent = oriented.extent.integral
    let translated = oriented.transformed(by: CGAffineTransform(translationX: -extent.minX, y: -extent.minY))
    guard let result = CIContext(options: [.useSoftwareRenderer: true]).createCGImage(
      translated,
      from: CGRect(origin: .zero, size: extent.size)
    ) else {
      fatalError("Could not create inverse-oriented fixture")
    }
    return result
  }

  private static func writeJpeg(
    _ image: CGImage,
    orientation: CGImagePropertyOrientation,
    to url: URL
  ) throws {
    guard let destination = CGImageDestinationCreateWithURL(
      url as CFURL,
      UTType.jpeg.identifier as CFString,
      1,
      nil
    ) else {
      fatalError("Could not create fixture destination")
    }
    let properties: [CFString: Any] = [
      kCGImagePropertyOrientation: orientation.rawValue,
      kCGImageDestinationLossyCompressionQuality: 1.0,
    ]
    CGImageDestinationAddImage(destination, image, properties as CFDictionary)
    runtimeRequire(CGImageDestinationFinalize(destination), "Could not write fixture")
  }

  private static func recognizeSyntheticText(
    in image: CGImage,
    orientation: CGImagePropertyOrientation
  ) throws -> RuntimeObservation {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["en-US"]
    request.usesLanguageCorrection = false
    try VNImageRequestHandler(cgImage: image, orientation: orientation, options: [:]).perform([request])

    let candidates = (request.results ?? []).compactMap { observation -> RuntimeObservation? in
      guard let candidate = observation.topCandidates(1).first else { return nil }
      return RuntimeObservation(text: candidate.string, box: observation.boundingBox)
    }
    guard let match = candidates.first(where: { $0.text.uppercased().contains("TOP") }) else {
      fatalError("TOP was not found. Candidates: \(candidates.map(\.text))")
    }
    return match
  }
}
