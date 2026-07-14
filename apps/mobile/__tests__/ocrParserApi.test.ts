import { parseNutritionLabel, parserRequestFromRecognition } from "../src/features/ocr/api/ocrApi";

const recognition = {
  fullText: "Calories 120", observations: [{ id: "obs-1", text: "Calories 120", confidence: 0.9876, boundingBox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 } }],
  image: { width: 100, height: 200, orientationApplied: true },
  recognition: { platform: "ios" as const, recognitionLevel: "accurate" as const, languages: ["en-US"], durationMs: 12 },
};

test("typed parser mapping uses observations and snake-case normalized boxes exactly", () => {
  const request = parserRequestFromRecognition(recognition);
  expect(request).toEqual({ full_text: "Calories 120", observations: [{ id: "obs-1", text: "Calories 120", confidence: 0.9876, bounding_box: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 } }] });
  expect(request).not.toHaveProperty("image");
});

test("malformed parser responses are rejected at the mobile boundary", async () => {
  const originalFetch = global.fetch;
  global.fetch = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ parser_version: "nutrition_label_v1", unexpected: true }) }) as typeof fetch;
  await expect(parseNutritionLabel(recognition)).rejects.toThrow();
  global.fetch = originalFetch;
});
