# Stage 6A: nutrition-label parser foundation

Stage 6A adds a deterministic, backend-owned parser for normalized OCR text. It returns a provenance-rich draft for later confirmation. It does not accept images, invoke Apple Vision, create Foods, persist parse results, or implement the Stage 6B confirmation UI.

## Boundary and stages

`POST /api/v1/ocr/nutrition-label/parse` accepts `full_text` plus ordered normalized OCR observations containing an ID, text, confidence, and optional normalized bounding box. Apple-specific image and observation types remain on mobile.

The parser is split into explicit stages:

1. normalize OCR text into deterministic source lines;
2. join narrowly supported broken amount/Daily Value observations;
3. detect the Nutrition Facts header;
4. extract serving information;
5. extract calories;
6. match and extract nutrient rows;
7. extract Daily Value percentages;
8. validate duplicate, conflicting, missing, and ambiguous values;
9. produce stable warnings, ranking confidence, provenance, and unparsed lines.

Bounding boxes are validated but are not required for successful parsing. Ordered text is the functional fallback, and Stage 6A does not reconstruct tables or depend on physical camera-overlay geometry.

## Supported draft

The parser version is `nutrition_label_v1`. Every response includes that version and is deterministic for the same normalized request.

Serving output preserves servings per container, the original serving display phrase, household quantity/unit, parenthetical gram weight, and an `about` qualifier. Missing gram weight produces a warning but does not prevent a draft.

Supported canonical nutrient mappings use the existing catalog: total fat, saturated fat, trans fat, cholesterol, sodium, total carbohydrate, dietary fiber/fibre, total sugars, added sugars, protein, vitamin D, calcium, iron, and potassium. Matching is case-, whitespace-, and punctuation-tolerant but limited to controlled variants. Unknown amount/unit rows remain in the nutrient list with no canonical ID.

Each parsed field contains its parser-derived value, original source text, source observation IDs, status, warning codes, and confidence. `<1g` is represented as value `1` plus `comparison: "less_than"`. Printed zero remains numeric zero; missing or unreadable values remain `null` with a missing or ambiguous status.

## Numeric and warning behavior

The parser supports `g`, `mg`, `mcg`, `%`, decimals, unambiguous decimal/thousands commas, separated amount/unit tokens, and adjacent amount/Daily Value tokens. It never globally rewrites `O` to zero. A `q` is interpreted as `g` only for a canonical nutrient expected in grams, with `ocr_character_correction_applied` and reduced confidence. Malformed punctuation remains ambiguous.

Current stable warning paths include:

- `nutrition_header_not_found`
- `serving_size_missing`
- `serving_grams_missing`
- `calories_missing`
- `nutrient_amount_missing`
- `nutrient_amount_ambiguous`
- `nutrient_unit_unknown`
- `daily_value_ambiguous`
- `nutrient_name_unmatched`
- `ocr_character_correction_applied`
- `duplicate_nutrient_row`
- `conflicting_nutrient_values`

Confidence combines OCR confidence with conservative reductions for controlled aliases, corrections, missing structure, unmatched names, and conflicts. Scores are ranking and confirmation aids, not calibrated probabilities.

## API, privacy, and limits

The endpoint is scoped through the existing development-user dependency. Requests are limited to 50,000 full-text characters, 500 observations, 2,000 characters per observation, confidence in `0...1`, and boxes wholly within normalized bounds. Invalid requests return HTTP 400 with `invalid_ocr_parse_request` and structured validation details.

The API accepts JSON only—never multipart image data. Parser requests/results are not persisted, and the parser path does not log raw OCR text, source lines, image paths, or nutrient values.

## Golden corpus and validation

The checked-in corpus contains 21 synthetic normalized OCR contracts: modern and old-style labels, compact/fraction/multi-serving layouts, explicit zeros, missing optional micronutrients, `<1g`, broken and split observations, `g`/`q` confusion, duplicates, low confidence, missing grams/calories, unknown/conflicting nutrients, orientation-normalized order, marketing noise, malformed decimals, and non-label text. Golden expectations cover serving/calorie/nutrient values, statuses, warnings, comparisons, confidence bounds, and stable unparsed lines.

```bash
cd apps/backend
.venv/bin/pytest -q tests/test_ocr_parser.py tests/test_ocr_parser_golden.py tests/test_ocr_parser_api.py
.venv/bin/pytest -q
.venv/bin/ruff check .

cd ../mobile
npm test -- --runInBand __tests__/nutritionOcr.test.ts __tests__/ocrDiagnostics.test.ts __tests__/ocrOverlayLayout.test.ts __tests__/ocrDiagnosticsScreen.test.ts
npm test -- --runInBand
npm run typecheck
```

Stage 6B must provide user confirmation/editing, decide which serving definition to persist, compare parser suggestions with confirmed/edited values, and only then create or update Foods. Physical-device Stage 5 camera and overlay QA remains outstanding before geometry is used as stronger parsing evidence.
