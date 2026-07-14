import Foundation
import ImageIO

struct NativeObservation {
  let text: String
  let confidence: Float
  let boundingBox: CGRect
}

enum NutritionOcrGeometry {
  static func displayedDimensions(
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

  static func orientationApplied(_ orientation: CGImagePropertyOrientation) -> Bool {
    orientation != .up
  }

  // VNImageRequestHandler receives the source orientation, so Vision observations
  // are already normalized against the displayed orientation, including mirrored
  // cases. Only Vision's lower-left origin must be converted for React Native.
  static func topLeftBoundingBox(from visionBox: CGRect) -> CGRect {
    CGRect(
      x: clamp(visionBox.minX),
      y: clamp(1 - visionBox.maxY),
      width: clamp(visionBox.width),
      height: clamp(visionBox.height)
    )
  }

  static func clamp(_ value: CGFloat) -> CGFloat {
    min(max(value, 0), 1)
  }

  // Conservative row grouping followed by left-to-right ordering. This produces
  // stable line joining without attempting nutrition-label layout interpretation.
  static func observationsInReadingOrder(_ observations: [NativeObservation]) -> [NativeObservation] {
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
