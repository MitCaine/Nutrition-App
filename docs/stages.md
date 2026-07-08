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
- Manual food creation.
- Serving definitions.
- Saved foods.
- Log by serving or grams where possible.
- Snapshot nutrients at log time.
- Aggregate daily totals from snapshots.

## Stage 3: USDA Lookup/Import

- Search FoodData Central.
- Import selected foods.
- Normalize USDA nutrients into the internal model.

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
