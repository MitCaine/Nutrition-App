import Foundation

private func require(
  _ condition: @autoclosure () -> Bool,
  _ message: String
) {
  if !condition() {
    fatalError(message)
  }
}

private func approximatelyEqual(
  _ lhs: Double,
  _ rhs: Double,
  tolerance: Double = 0.000_001
) -> Bool {
  abs(lhs - rhs) <= tolerance
}

@main
enum NutritionImageQualityTests {
  static func main() {
    let black = NutritionImageQuality.luminanceMetrics(
      [0, 0, 0, 0]
    )

    require(
      approximatelyEqual(black.mean, 0),
      "Black mean luminance must be zero"
    )
    require(
      approximatelyEqual(black.darkFraction, 1),
      "Black pixels must all count as dark"
    )
    require(
      approximatelyEqual(black.brightFraction, 0),
      "Black pixels must not count as bright"
    )

    let white = NutritionImageQuality.luminanceMetrics(
      [255, 255, 255, 255]
    )

    require(
      approximatelyEqual(white.mean, 1),
      "White mean luminance must be one"
    )
    require(
      approximatelyEqual(white.darkFraction, 0),
      "White pixels must not count as dark"
    )
    require(
      approximatelyEqual(white.brightFraction, 1),
      "White pixels must all count as bright"
    )

    let mixed = NutritionImageQuality.luminanceMetrics(
      [0, 51, 128, 242, 255]
    )

    require(
      approximatelyEqual(
        mixed.mean,
        Double(0 + 51 + 128 + 242 + 255) / 5.0 / 255.0
      ),
      "Mixed mean luminance is incorrect"
    )
    require(
      approximatelyEqual(mixed.darkFraction, 0.4),
      "Dark-pixel boundary must be inclusive"
    )
    require(
      approximatelyEqual(mixed.brightFraction, 0.4),
      "Bright-pixel boundary must be inclusive"
    )

    let flat = NutritionImageQuality.laplacianVariance(
      Array(repeating: 128, count: 16),
      width: 4,
      height: 4
    )

    require(
      approximatelyEqual(flat, 0),
      "Flat image must have zero focus variance"
    )

    let checkerboard: [UInt8] = [
      0, 255, 0, 255,
      255, 0, 255, 0,
      0, 255, 0, 255,
      255, 0, 255, 0,
    ]

    let textured = NutritionImageQuality.laplacianVariance(
      checkerboard,
      width: 4,
      height: 4
    )

    require(
      textured > 1,
      "High-frequency detail must produce substantial focus variance"
    )

    let invalidShape = NutritionImageQuality.laplacianVariance(
      [0, 255, 0],
      width: 2,
      height: 2
    )

    require(
      approximatelyEqual(invalidShape, 0),
      "Malformed or undersized samples must fail conservatively"
    )

    print(
      "NutritionImageQualityTests passed: luminance, exposure boundaries, Laplacian focus variance, and malformed-sample fallback"
    )
  }
}
