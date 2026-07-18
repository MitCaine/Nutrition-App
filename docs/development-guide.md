# Development guide

Use this guide to turn “I need to modify…” into a bounded reading and testing plan. Start at the
service or mobile feature named below; do not begin by editing migrations or control-plane code.

## Configuration and startup

### Backend

`apps/backend/app/core/config.py` is the configuration authority. Copy
`apps/backend/.env.example` to `.env` and set the deployment mode explicitly.

| Mode | Identity and transport boundary | Intended use |
| --- | --- | --- |
| `development` | Deterministic development user; explicitly configured local/LAN API URL; local HTTP allowed | Simulator or trusted local-device development |
| `test` | Deterministic test user and explicit test database | Automated tests only |
| `private_single_user` | Configured user plus at least 32-character shared bearer secret; non-local mobile URL must use HTTPS | Personally controlled private/internal build |
| `production` | Requires a production auth provider; none is installed, so startup is rejected | Deliberately blocked in this build |

Private-single-user authentication is not a scalable account system. Its token is embedded in the
mobile build and can be extracted, so backend exposure must remain narrowly controlled.

```bash
docker compose up -d postgres
cd apps/backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.lock
python -m pip install --no-build-isolation --no-deps -e .
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

Normal development uses one application URL for runtime and Alembic. A qualified production-like
role profile runs migrations separately as `nutrition_migrator` and the API as
`nutrition_runtime`. The root `scripts/start-backend.sh` implements only that qualified runtime
launch: it verifies the exact runtime database role and deliberately does not run Alembic.

`pyproject.toml` remains the dependency declaration. `requirements-dev.lock` pins the reproducible
Python 3.12 development and CI environment. Regenerate it from `apps/backend` with the documented
pip-tools version after changing `pyproject.toml`:

```bash
python -m pip install "pip-tools==7.6.0"
pip-compile --strip-extras --all-build-deps --allow-unsafe --extra dev \
  --output-file requirements-dev.lock pyproject.toml
```

### Mobile

```bash
cd apps/mobile
npm ci
EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE=development \
EXPO_PUBLIC_NUTRITION_API_URL=http://localhost:8000/api/v1 \
  npm start
```

There is no API URL fallback. Use a LAN-reachable URL for a physical device. A private internal
build requires HTTPS and an injected private bearer credential. Never put a real credential in
source or documentation.

## If you need to modify Foods or servings

Begin with:

1. `app/api/v1/routers/foods.py`
2. `app/services/food_service.py`
3. `app/repositories/food_repository.py`
4. `app/nutrition/serving_resolution.py` and `resolution.py`
5. `app/models/food.py` and `app/schemas/food.py`
6. `apps/mobile/src/features/foods`

Check effects on dependent Recipes and mutable-Food Log snapshot locking. Relevant application
migrations include 0001–0003, 0012–0014. Run Food, serving-integrity, ownership, idempotency,
nutrition-resolution, and affected mobile tests.

## If you need to modify Recipes

Begin with `app/services/recipe_service.py`. Then read:

- `app/domain/recipe_nutrition_validation.py` and `recipe_projection.py`;
- `app/publication/recipe_revision.py`;
- Recipe and publication repositories/models;
- `apps/mobile/src/features/recipes`.

Ask whether the change affects only mutable authoring or also immutable publication. Never update a
published revision to represent a new draft. Check nested graph ownership, cycle validation, parent
serving remaps, `needs_republish`, compatibility projections, and Recipe-based Log editing.

Recipe foundations span migrations 0004–0008, with dependency and idempotency hardening in
0013–0014. Historical conversion migrations 0015–0017 are not the place to add new Recipe feature
schema.

## If you need to modify Daily Logs

Begin with:

1. `app/services/log_service.py`
2. `app/repositories/log_repository.py`
3. `app/nutrition/resolution.py` and `revision_resolution.py`
4. `app/nutrition/aggregation.py`
5. `app/models/log.py` and `app/schemas/log.py`
6. `apps/mobile/src/features/logging`

Preserve the rule that summaries aggregate snapshot rows only. Decide explicitly whether an edit
uses a mutable Food or immutable Recipe revision. Run standard Log tests plus PostgreSQL log
concurrency and Recipe-revision editing tests when lock or snapshot behavior changes.

## If you need to modify USDA

Begin at `app/services/usda_service.py`, then separate concerns:

- HTTP/key/timeouts/errors: `app/integrations/usda/client.py`
- upstream-to-domain mapping: `app/integrations/usda/mappers.py`
- public normalization contracts: integration schemas and USDA router
- mobile query/preview/import: `apps/mobile/src/features/usda`

Preserve backend-only API-key handling, per-100g semantics, unknown-versus-zero, valid gram weights,
and source-identity deduplication. Use mocked client/mapper tests for most changes; use live upstream
checks only as explicit manual qualification.

## If you need to modify OCR

Follow the flow in [OCR, Search, and Offline Behavior](ocr-search-and-offline.md).

- Native recognition: `apps/mobile/modules/nutrition-ocr`
- TypeScript native boundary: `apps/mobile/src/native/ocr`
- Capture/review: `apps/mobile/src/features/ocr`
- Pure parser: `apps/backend/app/ocr/parser.py`
- Confirmation transaction: `app/ocr/confirmation_service.py`
- API: `app/api/v1/routers/ocr.py`

Parser changes require golden-fixture review. Confirmation changes require privacy, idempotency,
ownership, and trace-lifecycle tests. Do not make persisted OCR traces resolver inputs.

## If you need to modify Search or discovery

There is no standalone search subsystem. Saved Food filtering begins at the Food list endpoint and
repository. Unified presentation is in:

- `SavedFoodsScreen.tsx`;
- `useDebouncedSearchQuery.ts`;
- `unifiedFoodSearch.ts`;
- Food and USDA query hooks;
- `foodDiscovery.ts` for favorites and recents.

Preserve stale-query suppression, the USDA minimum query length, explicit source sections, and the
difference between importing an upstream Food and selecting a saved Food.

## If you need to modify Targets

Begin with `app/services/target_service.py` and `app/targets`. The mobile implementation is under
`src/features/targets`. Target changes must not write Daily Logs or nutrient snapshots. Effective
authority remains manual override, calculated calorie estimate, FDA reference, then unavailable.

## If you need to modify authentication or runtime configuration

Read `app/core/config.py`, `app/dependencies/user.py`, mobile `config/runtimeConfig.js`, and the
shared API client. Run the full release-configuration and API-client authentication suites.

Do not make `production` silently use development or private-single-user identity. The absence of a
production provider is an intentional fail-closed condition.

## If you need to modify migrations

### Application migrations

Create new revisions under `app/migrations/versions`; do not rewrite committed migration history.
Use `NUTRITION_DATABASE_URL` explicitly. Review both a fresh upgrade and the oldest supported
populated path.

Migration 0004 refuses populated legacy Recipe state by design. Migrations 0015–0017 support the
offline historical bridge/converter, and 0018 adds promotion prerequisites. Read the corresponding
Phase 5 record before touching them.

### Control migrations

Control migrations use `alembic-control.ini`, an independent database, and the explicit
`NUTRITION_CONTROL_MIGRATION_DATABASE_URL`. Never point them at the application database. Changes
require role/grant, SECURITY DEFINER, qualification, tamper, downgrade, and re-upgrade review.

Continue with the [Control Plane Guide](control-plane.md) before editing ops migrations.

## If you need to modify the Control Plane

Begin with [Control Plane Guide](control-plane.md), not the general FastAPI routers. Depending on the
change, the authority may live in:

- canonical contracts: `app/operators/phase5c4_contracts.py`, control/admission/performance
  contract modules;
- evidence collection and WORM registration: `phase5c4_control_evidence.py`, `phase5c4_minio.py`;
- Python operator client: `phase5c4_control.py`;
- PostgreSQL authority: `app/control_migrations/versions`;
- role policy: `phase5c4_control_roles.py`;
- tests: `test_phase5c4_*`.

Trace the database routine and transaction, not just its Python wrapper. Verify exact role grants,
server-time decisions, lock ordering, replay, immutable evidence, qualification coverage, and
empty-only downgrade semantics.

## Change checklist

Before finishing any feature change:

- identify the authoritative layer;
- preserve owner scope and idempotency behavior;
- determine whether historical snapshots or revisions are involved;
- update backend and mobile contracts together where required;
- add a migration only for persistent schema change;
- test the smallest unit plus the cross-layer flow;
- use PostgreSQL, not SQLite, for claims about locks, constraints, grants, or concurrency;
- update the reader guide if responsibility or an invariant changed.

## Next reading

- Use the [Testing Guide](testing.md) to select qualification proportional to the change.
- Revisit the relevant domain guide before changing an invariant or public contract.
- Use the [Architecture Decision Index](architecture-decisions.md) when a design choice is unclear.

## See also

- [Repository Tour](repository-tour.md) for directory navigation
- [Architecture Guide](architecture.md) for responsibility boundaries
- [Glossary](reference/glossary.md) for project-specific terms
- [Control Plane Guide](control-plane.md) only for Phase 5 and production-operations changes
