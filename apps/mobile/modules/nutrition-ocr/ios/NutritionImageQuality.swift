import CoreGraphics
import Foundation
import ImageIO
import Vision

enum NutritionImageQuality {
  private static let maximumSampleDimension = 256
  private static let darkPixelValue: UInt8 = 51
  private static let brightPixelValue: UInt8 = 242

  static func inspect(
    _ cgImage: CGImage,
    orientation: CGImagePropertyOrientation
  ) throws -> [String: Any] {
    let sample = try grayscaleSample(from: cgImage)
    let luminance = luminanceMetrics(sample.pixels)
    let focusVariance = laplacianVariance(
      sample.pixels,
      width: sample.width,
      height: sample.height
    )
    let text = textCoverage(
      cgImage: cgImage,
      orientation: orientation
    )

    return [
      "width": cgImage.width,
      "height": cgImage.height,
      "meanLuminance": luminance.mean,
      "darkPixelFraction": luminance.darkFraction,
      "brightPixelFraction": luminance.brightFraction,
      "focusVariance": focusVariance,
      "textRegionCount": text.count,
      "textRegionAreaFraction":
        text.areaFraction.map { $0 as Any } ?? NSNull(),
    ]
  }

  static func luminanceMetrics(
    _ pixels: [UInt8]
  ) -> (
    mean: Double,
    darkFraction: Double,
    brightFraction: Double
  ) {
    guard !pixels.isEmpty else {
      return (0, 0, 0)
    }

    var sum = 0
    var darkCount = 0
    var brightCount = 0

    for pixel in pixels {
      sum += Int(pixel)

      if pixel <= darkPixelValue {
        darkCount += 1
      }

      if pixel >= brightPixelValue {
        brightCount += 1
      }
    }

    let count = Double(pixels.count)

    return (
      Double(sum) / count / 255.0,
      Double(darkCount) / count,
      Double(brightCount) / count
    )
  }

  static func laplacianVariance(
    _ pixels: [UInt8],
    width: Int,
    height: Int
  ) -> Double {
    guard
      width >= 3,
      height >= 3,
      pixels.count == width * height
    else {
      return 0
    }

    var sum = 0.0
    var squaredSum = 0.0
    var count = 0

    for y in 1..<(height - 1) {
      for x in 1..<(width - 1) {
        let index = y * width + x

        let center = Double(pixels[index]) / 255.0
        let left = Double(pixels[index - 1]) / 255.0
        let right = Double(pixels[index + 1]) / 255.0
        let above = Double(pixels[index - width]) / 255.0
        let below = Double(pixels[index + width]) / 255.0

        let laplacian =
          left +
          right +
          above +
          below -
          (4.0 * center)

        sum += laplacian
        squaredSum += laplacian * laplacian
        count += 1
      }
    }

    guard count > 0 else {
      return 0
    }

    let sampleCount = Double(count)
    let mean = sum / sampleCount
    let meanSquare = squaredSum / sampleCount

    return max(0, meanSquare - (mean * mean))
  }

  private static func grayscaleSample(
    from cgImage: CGImage
  ) throws -> (
    pixels: [UInt8],
    width: Int,
    height: Int
  ) {
    let sourceWidth = cgImage.width
    let sourceHeight = cgImage.height
    let sourceMaximum = max(sourceWidth, sourceHeight)

    let scale = min(
      1.0,
      Double(maximumSampleDimension) /
        Double(max(sourceMaximum, 1))
    )

    let width = max(
      1,
      Int((Double(sourceWidth) * scale).rounded())
    )
    let height = max(
      1,
      Int((Double(sourceHeight) * scale).rounded())
    )

    var pixels = [UInt8](
      repeating: 0,
      count: width * height
    )

    let colorSpace = CGColorSpaceCreateDeviceGray()

    let rendered = pixels.withUnsafeMutableBytes {
      rawBuffer -> Bool in

      guard let context = CGContext(
        data: rawBuffer.baseAddress,
        width: width,
        height: height,
        bitsPerComponent: 8,
        bytesPerRow: width,
        space: colorSpace,
        bitmapInfo: CGImageAlphaInfo.none.rawValue
      ) else {
        return false
      }

      context.interpolationQuality = .medium
      context.draw(
        cgImage,
        in: CGRect(
          x: 0,
          y: 0,
          width: width,
          height: height
        )
      )

      return true
    }

    guard rendered else {
      throw NSError(
        domain: "NutritionImageQuality",
        code: 1,
        userInfo: [
          NSLocalizedDescriptionKey:
            "The image quality sample could not be rendered."
        ]
      )
    }

    return (pixels, width, height)
  }

  private static func textCoverage(
    cgImage: CGImage,
    orientation: CGImagePropertyOrientation
  ) -> (
    count: Int,
    areaFraction: Double?
  ) {
    let request = VNDetectTextRectanglesRequest()
    request.reportCharacterBoxes = false

    do {
      try VNImageRequestHandler(
        cgImage: cgImage,
        orientation: orientation,
        options: [:]
      ).perform([request])
    } catch {
      // Text-region detection is advisory. Failure means uncertainty.
      return (0, nil)
    }

    let observations = request.results ?? []

    guard !observations.isEmpty else {
      return (0, nil)
    }

    let totalArea = observations.reduce(0.0) {
      partial, observation in

      let box = observation.boundingBox

      return partial +
        max(
          0,
          Double(box.width * box.height)
        )
    }

    return (
      observations.count,
      max(0, min(1, totalArea))
    )
  }
}
