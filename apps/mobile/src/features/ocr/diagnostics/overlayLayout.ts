import type { OcrBoundingBox } from "../../../native/ocr/NutritionOcr";

export type LayoutSize = { width: number; height: number };
export type LayoutRect = { x: number; y: number; width: number; height: number };

export function containedImageRect(container: LayoutSize, image: LayoutSize): LayoutRect {
  if (container.width <= 0 || container.height <= 0 || image.width <= 0 || image.height <= 0) {
    return { x: 0, y: 0, width: 0, height: 0 };
  }
  const scale = Math.min(container.width / image.width, container.height / image.height);
  const width = image.width * scale;
  const height = image.height * scale;
  return {
    x: (container.width - width) / 2,
    y: (container.height - height) / 2,
    width,
    height,
  };
}

export function normalizedBoxToScreenRect(box: OcrBoundingBox, imageRect: LayoutRect): LayoutRect {
  return {
    x: imageRect.x + box.x * imageRect.width,
    y: imageRect.y + box.y * imageRect.height,
    width: box.width * imageRect.width,
    height: box.height * imageRect.height,
  };
}
