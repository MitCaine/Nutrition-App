# Architecture

## Layers

Mobile:

```text
screen -> feature hook/use case -> API client/state -> domain utilities
```

Backend:

```text
router -> service -> repository/domain utility -> database or integration
```

Screens and route handlers stay thin. Nutrition math, parser behavior, persistence decisions, USDA mapping, and target estimation live in dedicated modules.

## Historical Log Snapshot Rule

Food definitions are editable. Logs are historical facts.

When a user logs food, the backend resolves the consumed amount into nutrient amounts and writes those resolved values to `daily_log_nutrient_snapshots`. Daily totals must aggregate snapshots only. They must not join back to current `food_nutrients` for nutrient math.

This prevents edits to a saved food from rewriting past days.

When a daily log amount is updated, that log's snapshots are deliberately deleted and rebuilt in the same service operation using the current food definition at update time. Food edits never recalculate existing log snapshots.

Snapshot provenance is intentionally nullable for food nutrient and serving rows:

- `daily_log_nutrient_snapshots.source_food_item_id` remains a live foreign key because foods are soft deleted.
- `daily_log_nutrient_snapshots.source_food_nutrient_id` uses `ON DELETE SET NULL`.
- `daily_log_nutrient_snapshots.serving_definition_id` uses `ON DELETE SET NULL`.
- `daily_logs.serving_definition_id` uses `ON DELETE SET NULL`.

This preserves historical nutrient math while allowing manual food edits to replace nutrient and serving rows without violating production PostgreSQL foreign keys.

## Serving Resolution

Stage 2 supports serving-count logging and gram logging.

- Serving-count logging requires a serving definition.
- Gram logging is allowed when the food has per-gram/per-100g nutrients or the selected/default serving definition has a valid `gram_weight`.
- Household measures do not imply grams unless `gram_weight` is present.
- Serving and gram resolution lives in `app/nutrition/serving_resolution.py`.

Mobile manual-food editing supports multiple serving definitions with stable local keys while editing. The API still enforces exactly one default serving.

## Units

Stage 2 supports `kcal`, `g`, `mg`, and `mcg`.

Mass units are normalized for aggregation when compatible. Incompatible units are rejected instead of being merged. Backend nutrition math uses `Decimal`, not floating point.

## USDA FoodData Central

FoodData Central access is backend-only. The React Native app never receives or stores
`USDA_FDC_API_KEY`, and mobile screens consume normalized USDA contracts rather than raw
FoodData Central payloads.

Integration boundary:

- `app/integrations/usda/client.py` owns HTTP calls, API-key attachment, timeout handling,
  upstream HTTP errors, and malformed response handling.
- `app/integrations/usda/mappers.py` maps USDA payloads into canonical app nutrients,
  servings, diagnostics, and source metadata.
- `app/services/usda_service.py` orchestrates search, preview, import, duplicate detection,
  and normal food persistence.

USDA nutrient mapping uses stable USDA nutrient IDs first and nutrient numbers second.
Display-name aliases are only a narrow fallback for payload variation. Imported nutrients
are stored in `food_nutrients`; JSON source payloads are provenance, not the primary nutrient
model.

USDA nutrient amounts are represented as `per_100g` when imported from FoodData Central
food nutrient records. Imported foods always receive a `100 g` serving definition with a
valid gram weight, and additional servings are added only when USDA provides a valid gram
weight. Household measures are never converted to grams by inference.

USDA serving default selection is deterministic:

- valid branded serving with gram weight is the default
- otherwise `100 g` is the default
- exactly one imported serving definition is default

USDA serving preview candidates carry deterministic candidate IDs for React Native list
keys: `basis:100g`, `branded:serving-size`, or a USDA portion ID when available.

Missing USDA nutrients remain `unknown`. Explicit USDA zero values are stored as `zero`.
Unsupported units or ambiguous portions become diagnostics instead of silent coercions.

USDA duplicate import behavior is source-identity based:

- active food with the same `user_id`, `source_type = usda`, and FDC ID returns the existing
  local food
- a concurrent insert race that loses the PostgreSQL source-identity unique index is rolled
  back and recovered by returning the now-existing active food
- soft-deleted prior imports may be imported again as a new local food
- unrelated foods are not deduplicated by name

## Aggregation Semantics

Daily summaries return, per nutrient:

- known amount
- estimated amount
- display unit
- whether unknown contributors exist
- unknown contributor count

Explicit zero contributes zero to known totals and does not count as unknown. Estimated amounts stay separate from known amounts.

## Reference Values

Reference nutrition values live in `nutrient_reference_values`:

- `FDA_DV`
- future `DRI_RDA`
- future `DRI_AI`
- future `DRI_UL`

The `nutrients` table defines nutrient identity and display hierarchy only.

## Parser Corrections

Corrections are first-class data. A correction should identify:

- `ocr_scan_id`
- `parse_result_id`
- `parser_version`
- canonical `nutrient_id` or parsed field name
- parsed value
- confirmed value
- user confirmation action

This makes parser regressions testable without requiring an ML feedback system.
