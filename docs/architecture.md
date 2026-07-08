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
