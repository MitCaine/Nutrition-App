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

Active Recipe ingredients never rely on default-serving fallback: serving-mode ingredients
store an explicit serving ID, while gram-mode ingredients store no serving ID. Replacing a
Food's serving generation remaps an ingredient only when exactly one successor has the same
normalized quantity, case-insensitive unit, and gram weight. Labels are presentation-only.
Missing or ambiguous successors reject the Food update atomically. Equivalent remaps and
nutrient changes mark published parent Recipes as needing explicit republication without
changing their immutable active revision or compatibility projection.

## Food and Recipe lock protocol

Mutations that can change Food/Recipe dependency membership use one database lock order:

1. Food rows, sorted by UUID when more than one is referenced.
2. Active dependent Recipe rows, sorted by UUID.

Food update, serving-default changes, Food deletion, Recipe ingredient authoring, Recipe
publication/deletion projection work, and mutable-Food log snapshot creation follow this
order. Food dependency operations recheck the active Recipe ID set after both lock classes
are held. A changed set rolls back and restarts; three unstable attempts return the structured
`food_dependencies_unstable` conflict. Mutable Manual, USDA, OCR-confirmed, and duplicated
Food logs reload resolver children after locking the Food, so a snapshot cannot combine
servings and nutrients from different committed Food generations. Immutable Recipe revision
logging retains its revision lock path.

Authored Recipe graph-edge creation and replacement add a narrower per-owner boundary before
that order:

1. Lock the owning `users` row for the transaction.
2. Lock referenced Food rows in sorted UUID order.
3. Lock the Recipe being updated.
4. Traverse the now-current committed Recipe graph and validate ownership, activity, serving
   membership, and cycles.
5. Replace ingredients and commit.

The owner row is a database lock, not a Python-process lock or a global application lock.
Consequently, graph mutations for one owner serialize, different owners remain independent,
and no advisory-key collision is possible. Under PostgreSQL `READ COMMITTED`, a waiter begins
all graph reads only after the preceding owner transaction commits or rolls back, so graph
membership discovery does not require a separate restart loop. SQLite's test strategy uses
the same explicit query; its ordinary tests are single-writer, while concurrency guarantees
are proven by the PostgreSQL suite. Ingredient removals during Food or child-Recipe deletion
do not acquire this owner boundary because removing edges cannot introduce a cycle and their
Food-before-Recipe locks already prevent concurrent dependency additions.

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

Stage 6A parsing is a pure backend operation over normalized OCR input. It does not accept images and does not persist requests or drafts. Observations are authoritative when present; `full_text` is fallback-only when observations are absent. Parser suggestions retain source text and observation IDs so Stage 6B confirmation can identify:

- `ocr_scan_id`
- `parse_result_id`
- `parser_version`
- canonical `nutrient_id` or parsed field name
- parsed value
- confirmed value
- user confirmation action

Stage 6B persists this bounded, versioned suggestion/confirmation trace beside an ordinary Manual Food in the same transaction. It never stores the image, image path, complete raw OCR text, or an unbounded parser response. The trace is service-immutable / append-only creation provenance: no public route or production service updates or independently deletes it, and the Food relationship does not use delete-orphan. It is not nutrition resolver input. Exact per-user client-request replay is idempotent; payload-changing reuse conflicts, and only the named request-uniqueness constraint is eligible for race recovery. Stage 6C binds mobile request IDs to canonical submitted payloads and preserves ordered review/provenance arrays in backend fingerprints. Stage 6D retires only structurally identified conflicting mobile intents and recursively rejects path/URI material from every persisted trace string without blocking normal nutrition punctuation. This makes parser regressions and user corrections testable without introducing an ML feedback system.

## Nutrition target authority

Stage 7A keeps targets outside the historical nutrition record. Daily comparisons consume the existing snapshot-derived daily summary; profile changes and target overrides cannot rewrite Daily Logs or nutrient snapshots. Effective authority is manual override, calculated personal calorie estimate, FDA Daily Value fallback, then unavailable. FDA Daily Values are versioned regulatory references, while Mifflin–St Jeor maintenance calories are optional general estimates. Personal protein, carbohydrate, and fat targets are manual only in this phase.
