import { containedImageRect, normalizedBoxToScreenRect } from "../src/features/ocr/diagnostics/overlayLayout";

test("portrait images are centered with horizontal letterboxing", () => {
  expect(containedImageRect({ width: 300, height: 300 }, { width: 1000, height: 2000 })).toEqual({
    x: 75,
    y: 0,
    width: 150,
    height: 300,
  });
});

test("landscape images are centered with vertical letterboxing", () => {
  expect(containedImageRect({ width: 300, height: 300 }, { width: 2000, height: 1000 })).toEqual({
    x: 0,
    y: 75,
    width: 300,
    height: 150,
  });
});

test("normalized boxes map into the actual aspect-fit image rectangle", () => {
  const imageRect = containedImageRect({ width: 400, height: 300 }, { width: 1000, height: 2000 });
  expect(normalizedBoxToScreenRect(
    { x: 0.1, y: 0.2, width: 0.5, height: 0.25 },
    imageRect,
  )).toEqual({ x: 140, y: 60, width: 75, height: 75 });
});

test("invalid layout dimensions return an empty contained rectangle", () => {
  expect(containedImageRect({ width: 0, height: 300 }, { width: 1000, height: 2000 })).toEqual({
    x: 0, y: 0, width: 0, height: 0,
  });
});
