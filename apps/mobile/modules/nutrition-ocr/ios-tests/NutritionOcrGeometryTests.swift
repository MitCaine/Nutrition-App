import Foundation
import ImageIO

private func require(_ condition: @autoclosure () -> Bool, _ message: String) {
  if !condition() {
    fatalError(message)
  }
}

private func approximatelyEqual(_ lhs: CGFloat, _ rhs: CGFloat) -> Bool {
  abs(lhs - rhs) < 0.000_001
}

@main
enum NutritionOcrGeometryTests {
  static func main() {
    let orientations: [(CGImagePropertyOrientation, Int, Int, Bool)] = [
      (.up, 1200, 800, false),
      (.down, 1200, 800, true),
      (.left, 800, 1200, true),
      (.right, 800, 1200, true),
      (.upMirrored, 1200, 800, true),
      (.downMirrored, 1200, 800, true),
      (.leftMirrored, 800, 1200, true),
      (.rightMirrored, 800, 1200, true),
    ]

    for (orientation, expectedWidth, expectedHeight, applied) in orientations {
      let dimensions = NutritionOcrGeometry.displayedDimensions(width: 1200, height: 800, orientation: orientation)
      require(dimensions.width == expectedWidth, "Unexpected displayed width for orientation \(orientation.rawValue)")
      require(dimensions.height == expectedHeight, "Unexpected displayed height for orientation \(orientation.rawValue)")
      require(NutritionOcrGeometry.orientationApplied(orientation) == applied, "Unexpected applied flag for orientation \(orientation.rawValue)")

      // Vision observations are documented/treated as orientation-corrected by
      // VNImageRequestHandler. The React Native transform is therefore identical
      // for every EXIF orientation, mirrored cases included.
      let converted = NutritionOcrGeometry.topLeftBoundingBox(
        from: CGRect(x: 0.1, y: 0.2, width: 0.3, height: 0.4)
      )
      require(approximatelyEqual(converted.minX, 0.1), "Unexpected x")
      require(approximatelyEqual(converted.minY, 0.4), "Unexpected y")
      require(approximatelyEqual(converted.width, 0.3), "Unexpected width")
      require(approximatelyEqual(converted.height, 0.4), "Unexpected height")
      require(converted.minX >= 0 && converted.minY >= 0 && converted.width <= 1 && converted.height <= 1, "Box left normalized range")
    }

    require(NutritionOcrGeometry.clamp(-0.2) == 0, "Negative clamp failed")
    require(NutritionOcrGeometry.clamp(1.2) == 1, "Upper clamp failed")
    require(NutritionOcrGeometry.clamp(0.4) == 0.4, "Interior clamp failed")

    let observations = [
      NativeObservation(text: "right", confidence: 1, boundingBox: CGRect(x: 0.6, y: 0.1, width: 0.2, height: 0.1)),
      NativeObservation(text: "below", confidence: 1, boundingBox: CGRect(x: 0.1, y: 0.5, width: 0.2, height: 0.1)),
      NativeObservation(text: "left", confidence: 1, boundingBox: CGRect(x: 0.1, y: 0.1, width: 0.2, height: 0.1)),
    ]
    let ordered = NutritionOcrGeometry.observationsInReadingOrder(observations).map(\.text)
    require(ordered == ["left", "right", "below"], "Reading order was not deterministic: \(ordered)")

    print("NutritionOcrGeometryTests passed: 8 EXIF orientations, coordinate conversion, clamp, and ordering")
  }
}
