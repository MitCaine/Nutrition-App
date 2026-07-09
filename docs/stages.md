# Implementation Stages

## Stage 1: Foundation

- Monorepo structure.
- FastAPI shell.
- React Native TypeScript shell.
- PostgreSQL migration baseline.
- Shared nutrition domain model.
- Decimal-safe aggregation utilities.
- Test setup.

## Stage 2: Manual Foods + Daily Logging

- SQLAlchemy model classes before repositories. Do not build Stage 2 repositories
  directly against raw tables unless the project deliberately switches to a SQL-only
  data access strategy.
- Manual food creation, retrieval, search, update, duplicate, and soft delete.
- Serving definitions.
- Saved foods.
- Log by serving or grams where possible.
- Snapshot nutrients at log time.
- Aggregate daily totals from snapshots.
- Edit daily log amount/unit through `PATCH /api/v1/logs/{log_id}` and rebuild snapshots.
- Manual food form supports multiple serving definitions and native keyboard-safe scrolling.

Implemented API surface:

- `GET /api/v1/nutrients`
- `POST /api/v1/foods`
- `GET /api/v1/foods`
- `GET /api/v1/foods/{food_id}`
- `PATCH /api/v1/foods/{food_id}`
- `DELETE /api/v1/foods/{food_id}`
- `POST /api/v1/foods/{food_id}/duplicate`
- `POST /api/v1/logs`
- `GET /api/v1/logs?date=YYYY-MM-DD`
- `PATCH /api/v1/logs/{log_id}`
- `DELETE /api/v1/logs/{log_id}`
- `GET /api/v1/logs/daily-summary?date=YYYY-MM-DD`

## Stage 3: USDA Lookup/Import

- Backend-owned FoodData Central API integration using `USDA_FDC_API_KEY`.
- Search FoodData Central through normalized summaries.
- Preview selected USDA foods before import.
- Normalize USDA nutrients into the internal canonical nutrient model.
- Preserve missing nutrients as unknown/unavailable.
- Preserve explicit USDA zero values as zero.
- Represent USDA food nutrient records as `per_100g`.
- Import valid USDA serving/portion candidates only when gram weights are available.
- Select a branded serving with gram weight as default; otherwise default to `100 g`.
- Use deterministic USDA serving candidate IDs in preview contracts.
- Persist source provenance through `food_sources` and `food_items.source_id`.
- Prevent duplicate active imports by source identity, not name.
- Recover source-identity insert races by rolling back and returning the existing active import.
- Imported USDA foods reuse the normal saved-food and daily-log flows.

Implemented API surface:

- `GET /api/v1/usda/foods/search?query=banana`
- `GET /api/v1/usda/foods/{fdc_id}`
- `POST /api/v1/usda/foods/{fdc_id}/import`

## Stage 4: Recipes

- Recipe ingredients.
- Serving-count yield.
- Final cooked-weight yield.
- Publish recipe as reusable food.

## Stage 5: Apple Vision OCR Bridge

- Swift OCR native module.
- OCR capture flow.
- Development-only OCR diagnostics screen.

## Stage 6: Parser + Confirmation Flow

- Backend parser pipeline.
- Golden parser fixtures.
- User confirmation/edit screen.
- Correction traceability.

## Stage 7: Targets + Dashboard Polish

- Target-estimation service.
- FDA DV comparison.
- Dashboard progress bars.
- Recents/favorites/source labels.
