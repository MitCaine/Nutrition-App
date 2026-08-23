import { z } from "zod";

import {
  confirmNutritionLabel,
} from "../src/features/ocr/api/ocrApi";

const foodId =
  "11111111-1111-4111-8111-111111111111";

const traceId =
  "77777777-7777-4777-8777-777777777777";

const timestamp =
  "2026-08-22T18:00:00Z";

const canonicalFood = {
  id: foodId,
  name: "Scanned Food",
  brand: null,
  notes: null,
  source_type: "ocr",
  source_id: null,
  is_recipe: false,
  source_kind:
    "ocr_confirmed" as const,
  source_label:
    "Scanned label",
  is_favorite: false,
  can_favorite: true,
  created_at: timestamp,
  updated_at: timestamp,
  serving_definitions: [],
  nutrients: [],
};

const input = {} as Parameters<
  typeof confirmNutritionLabel
>[0];

function mockJson(
  value: unknown,
): void {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 201,
    json: async () => value,
  });
}

test(
  "OCR confirmation validates strict wrapper UUID and reuses canonical Food parser",
  async () => {
    const response = {
      food: canonicalFood,
      trace_id: traceId,
    };

    mockJson(response);

    await expect(
      confirmNutritionLabel(input),
    ).resolves.toEqual(response);

    expect(global.fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/ocr/nutrition-label/confirm",
      expect.objectContaining({
        method: "POST",
      }),
    );
  },
);

test.each([
  [
    "invalid trace UUID",
    {
      food: canonicalFood,
      trace_id: "trace-1",
    },
  ],
  [
    "unexpected wrapper field",
    {
      food: canonicalFood,
      trace_id: traceId,
      unexpected: true,
    },
  ],
  [
    "missing Food timestamps",
    {
      food: (() => {
        const food = {
          ...canonicalFood,
        } as Record<string, unknown>;

        delete food.created_at;
        return food;
      })(),
      trace_id: traceId,
    },
  ],
  [
    "Food source-label mismatch",
    {
      food: {
        ...canonicalFood,
        source_label: "Manual",
      },
      trace_id: traceId,
    },
  ],
  [
    "non-object Food",
    {
      food: null,
      trace_id: traceId,
    },
  ],
])(
  "OCR confirmation rejects malformed successful response: %s",
  async (_name, response) => {
    mockJson(response);

    await expect(
      confirmNutritionLabel(input),
    ).rejects.toBeInstanceOf(
      z.ZodError,
    );
  },
);
