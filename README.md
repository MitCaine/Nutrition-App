# Nutrition App

Portfolio-quality iOS-first nutrition tracker built around native OCR, a FastAPI parser/calculation backend, and a normalized PostgreSQL nutrition model.

## Stage 1 Scope

This stage establishes the architecture and invariants:

- React Native TypeScript app shell.
- FastAPI backend shell.
- PostgreSQL schema baseline with Alembic.
- Shared nutrition domain contracts.
- Decimal-safe nutrition aggregation utilities.
- Test scaffolding.

No OCR, USDA import, recipes, or dashboard UI is implemented yet.

## Architectural Invariants

- Daily log history is immutable with respect to food edits. When a food is logged, resolved nutrient amounts for the consumed quantity are copied into `daily_log_nutrient_snapshots`; daily totals aggregate snapshots, not current `food_nutrients`.
- Missing nutrient data is not zero. Use `known`, `unknown`, `estimated`, and `zero` explicitly.
- FDA Daily Values are stored in `nutrient_reference_values`, not directly on nutrients, so future DRI/RDA/AI/UL references can coexist.
- `user_profiles.biological_sex_for_reference_calculations` exists only for target/reference calculations and is consumed by the target-estimation service.
- Nutrient identity is separate from presentation hierarchy through `parent_nutrient_id` and `display_order`.
- Parser corrections are traceable to OCR scan, parse result, parser version, nutrient ID, parsed value, and confirmed value.
- OCR diagnostics are development-only surfaces, not normal user navigation.

## Local Development

Backend:

```bash
cd apps/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
uvicorn app.main:app --reload
```

PostgreSQL row-lock concurrency tests (the default URL matches `docker-compose.yml`):

```bash
cd apps/backend
NUTRITION_TEST_POSTGRES_URL=postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app \
  pytest -m postgres_concurrency
```

Database:

```bash
docker compose up -d postgres
cd apps/backend
alembic upgrade head
```

Mobile shell:

```bash
cd apps/mobile
npm install
npm test
```
