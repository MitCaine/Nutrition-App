# Development guide

> **Document role: Current Guide.**

Use this guide to turn “I need to modify…” into a bounded reading and testing plan. Start at the
mobile feature and `NutritionRuntime` boundary named below, then follow the selected authority.
Local application-data work continues through `apps/mobile/src/runtime/local` and SQLite; remote
work continues through the FastAPI/PostgreSQL path. Do not begin by editing migrations or
control-plane code.

Every implementation session must follow the mandatory
[Repository Session Contract](../operations/session-contract.md#repository-session-contract). The workflow
is defined there rather than duplicated in this guide.

## Configuration and startup

### Backend (remote authority only)

The backend is required for `remote` authority and backend-specific qualification; local
application-data mode does not require FastAPI or PostgreSQL.

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

The ordinary current-product path is local-first.

The preserved remote runtime requires PostgreSQL already provisioned and
qualified at `0033_complete_runtime_authority`.

Schema `0020_immutable_provenance_enforcement` is retained only as the
`LIMITED_PREACTIVATION_OPERATIONS_SANDBOX`; it is not current remote
feature-parity startup. `0021_target_activation_execution` remains an
operations-only activation boundary. Do not use an unqualified
`alembic upgrade head` to cross it.

For an already qualified current remote database:

```bash
docker compose up -d postgres
cd apps/backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.lock
python -m pip install --no-build-isolation --no-deps -e .
cp .env.example .env
alembic current
uvicorn app.main:app --reload
```

`alembic current` must report `0033_complete_runtime_authority`. Database
provisioning or progression across 0021 remains an explicit operations task;
use the applicable runbook rather than a development convenience migration.

A qualified production-like role profile runs migrations separately as
`nutrition_migrator` and the API as `nutrition_runtime`. The root
`scripts/start-backend.sh` implements only that qualified runtime launch and
deliberately does not run Alembic.

The current remote application migration head is
`0033_complete_runtime_authority`.

Root `VERSION` owns the canonical Version 2.0 repository release identity.
`apps/backend/pyproject.toml` mirrors `2.0.0`, requires the Python 3.12 release
line, and Ruff targets `py312`. `requirements-dev.lock` remains the reproducible
dependency lock.

`pyproject.toml` remains the dependency declaration. `requirements-dev.lock` pins the reproducible
Python 3.12 development and CI environment. Regenerate it from `apps/backend` with the documented
pip-tools version after changing `pyproject.toml`:

```bash
python -m pip install "pip-tools==7.6.0"
pip-compile --strip-extras --all-build-deps --allow-unsafe --extra dev \
  --output-file requirements-dev.lock pyproject.toml
```

### Mobile

Version 2.0 mobile development and qualification use Node 24. The package engine contract accepts the Node 24 line and excludes Node 25; `.nvmrc` remains the repository toolchain pin.

On a fresh checkout, or when the lockfile/dependency installation needs to be
reconciled:

```bash
cd apps/mobile
npm ci
```

`npm ci` is setup/dependency reconciliation, not a per-rebuild requirement.

For ordinary local-first JS/TS development with an appropriate native
development build already installed:

```bash
cd apps/mobile
EXPO_PUBLIC_NUTRITION_DATA_AUTHORITY=local \
EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE=development \
  npx expo start --dev-client
```

The root README owns the canonical local-iOS command set for destructive
simulator reset/rebuild, native rebuild without intentionally clearing installed
data, simulator no-rebuild launch, physical-iPhone LAN/Metro no-rebuild launch,
and the separate self-contained physical Release install.

Remote/reference development:

```bash
cd apps/mobile
EXPO_PUBLIC_NUTRITION_DATA_AUTHORITY=remote \
EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE=development \
EXPO_PUBLIC_NUTRITION_API_URL=http://localhost:8000/api/v1 \
  npm start
```

Data authority is explicit and independent of deployment mode. `local` requires neither an API URL
nor a bearer credential and opens the authoritative application SQLite database. `remote` has no
API URL fallback; use a LAN-reachable URL for a physical device. A private remote build requires
HTTPS and an injected private bearer credential. Never put a real credential in source or
documentation.

Apple Vision OCR, guided camera capture, and native image-quality inspection require an iOS native
development/release build rather than Expo Go. JS/TS-only changes generally require only Metro and
reload/relaunch of that installed development build. Changes to native modules, native
dependencies, app/native configuration, or config plugins require native regeneration/rebuild as
applicable; generated `apps/mobile/ios/` remains intentionally untracked.

For every feature change, determine whether the contract change is authority-neutral, local-only,
remote-only, or a parity change before editing implementation.

## If you need to modify Foods or servings

Begin with the behavior being changed, including nutrient-catalog changes when Foods carry the new
identity or unit:

1. `app/catalog/nutrients.py` for canonical nutrient identity/hierarchy/default units/reference metadata;
2. `app/api/v1/routers/foods.py` and `app/services/food_service.py` for remote Food mutations;
3. `app/repositories/food_repository.py` for reused/locking persistence queries;
4. `app/nutrition/serving_resolution.py`, `resolution.py`, and `units.py` for serving/nutrient semantics;
5. `app/models/food.py` and `app/schemas/food.py` for remote persistence/contracts;
6. `apps/mobile/src/features/foods`, `src/shared/nutrition`, and `src/runtime/local/localFoodsRuntime.ts` for mobile/local behavior.

Preserve unknown-versus-zero, nutrient-specific canonical units, one default serving, exact decimal
semantics, and explicit physical amount authority. Serving reference measurements are all-or-none:
`reference_quantity`, `reference_unit`, and `reference_gram_weight` must describe one complete
physical anchor. Cross-dimension unit edits must preserve gram equivalence or require review rather
than guess.

Manual Food authoring is a presentation over the full canonical nutrient/form model. Keep the
conventional fifteen Nutrition Facts fields as the immediate baseline, use the shared grouped `More
nutrients` interaction for extended Vitamins/Minerals/Fatty Acids and canonical Other reachability,
and preserve populated extended values on edit. Do not add another nutrient-value state authority or
infer zero from blank/absent fields.

Check effects on dependent Recipes and mutable-Food Log snapshot locking. Relevant late remote
migrations are:

- `0026_food_nutrient_integrity` — Food nutrient integrity hardening;
- `0027_serving_reference_measurement` — serving physical reference metadata;
- `0028_duplicate_food_source_identity` — duplicate Food source identity;
- `0029_expand_nutrient_catalog` — expanded canonical nutrient catalog;
- `0030_total_omega_3_nutrient` — source-reported total Omega-3 and hierarchy.

Run Food, nutrient-catalog/unit, serving-transition/integrity, ownership, idempotency,
nutrition-resolution, local-runtime parity, and affected mobile presentation tests.

## If you need to modify Recipes

Begin with `app/services/recipe_service.py`. Then read:

- `app/domain/recipe_nutrition_validation.py` and `recipe_projection.py`;
- `app/publication/recipe_revision.py`;
- Recipe and publication repositories/models;
- `apps/mobile/src/features/recipes`;
- `apps/mobile/src/shared/navigation/draftGuard.ts` when navigation/discard semantics are involved.

Ask whether the change affects only mutable authoring or also immutable publication. Never update a
published revision to represent a new draft. Check nested graph ownership, cycle validation, parent
serving remaps, `needs_republish`, compatibility projections, Recipe-based Log editing, serving
choice, and serving-count/cooked-weight yield semantics.

Recipe foundations span migrations 0004–0008, with dependency and idempotency hardening in
0013–0014. Historical conversion migrations 0015–0017 are not the place to add new Recipe feature
schema.

Unsaved Recipe authoring spans multiple routes. Changes to the form, ingredient picker, USDA
preview/import, or serving management must preserve the shared draft guard so dirty state is not
silently discarded and busy mutations cannot be abandoned through normal navigation.

## If you need to modify Daily Logs

Begin with:

1. `app/services/log_service.py`
2. `app/repositories/log_repository.py`
3. `app/nutrition/resolution.py` and `revision_resolution.py`
4. `app/nutrition/aggregation.py`
5. `app/models/log.py` and `app/schemas/log.py`
6. `apps/mobile/src/features/logging`

Preserve the rule that summaries aggregate snapshot rows only. Decide explicitly whether an edit
uses a mutable Food or immutable Recipe revision. Target/profile changes must never alter snapshot
rows. Run standard Log tests plus PostgreSQL log concurrency and Recipe-revision editing tests when
lock or snapshot behavior changes, and local Daily Log parity/recovery tests for local changes.

Complete and History remain Daily Logs responsibilities:

- remote Complete mutation/recovery begins in `app/services/log_day_completion_service.py`, with
  owner/date persistence and invalidation support in the Log repository/service;
- remote History evidence is exposed by the Logs router/service bounded range operation;
- local Complete and History behavior lives in `src/runtime/local/localDailyLogCompleteState.ts` and
  `localDailyLogsRuntime.ts` over the SQLite schema/migrations;
- authority-neutral contracts remain on `NutritionRuntime.dailyLogs`; and
- shared projection, query/cache identity, range/session behavior, and UI live under
  `apps/mobile/src/features/history`.

Preserve explicit positive date-owned Complete state, atomic invalidation with nutrition-changing
Log mutations, exact-snapshot-preserving exceptions, bounded 1–30-date evidence behavior, 7/30 product
UI, missing/zero/unknown distinctions, current-target-only presentation, and exactly one selected
authority with no fallback. Changes to any of these contracts should run the relevant E4 suites and
the consolidated [E4-16 qualification](../operations/testing.md#epic-4-history-release-qualification).

Relevant current remote migrations are:

- `0031_daily_log_complete_state` — additive owner/date Complete persistence with no backfill;
- `0032_qualifier_complete_read` — read authority for qualification; and
- `0033_complete_runtime_authority` — forward-only integration with the current PostgreSQL runtime
  authority.

## If you need to modify USDA

Begin at `NutritionRuntime.usda`, then separate the selected authority:

- local transport/mapping/import: `apps/mobile/src/runtime/local/localUsdaRuntime.ts`;
- local saved-Food authority: `localFoodsRuntime.ts` plus SQLite persistence;
- remote HTTP/key/timeouts/errors: `app/integrations/usda/client.py`;
- remote upstream-to-domain mapping: `app/integrations/usda/mappers.py`;
- remote service/API: `app/services/usda_service.py` and the USDA router;
- mobile query/preview/import presentation: `apps/mobile/src/features/usda`.

Local mode resolves a personal USDA credential at request time and must not persist or embed it.
Remote mode retains backend-owned USDA credentials. Preserve per-100g semantics,
unknown-versus-zero, qualified nutrient units, valid gram weights, expanded nutrient mapping,
source-identity deduplication, and explicit import in both authorities. Use mocked
transport/mapper tests for most changes; use live upstream checks only as explicit manual
qualification.

## If you need to modify OCR

Follow the flow in [OCR, Search, Offline Behavior, and Local Backup](../features/ocr-search-and-offline.md).

- Guided camera capture and lens selection: `apps/mobile/src/features/ocr/components/NutritionCameraCapture.tsx`, `apps/mobile/src/native/camera`;
- Native recognition and quality metrics: `apps/mobile/modules/nutrition-ocr`;
- TypeScript native boundary: `apps/mobile/src/native/ocr`;
- Quality-warning policy: `apps/mobile/src/features/ocr/quality`;
- Scan/review/diagnostics: `apps/mobile/src/features/ocr`;
- Pure parsers: `apps/backend/app/ocr/parser.py` and the local parser parity implementation;
- Confirmation transaction: `app/ocr/confirmation_service.py` and the local OCR runtime;
- Remote API: `app/api/v1/routers/ocr.py`.

Parser or nutrient-mapping changes require golden-fixture and local/remote parity review.
Confirmation changes require privacy, idempotency, ownership, and trace-lifecycle tests. Native
image-quality changes require Swift native tests plus TypeScript policy tests. Quality inspection is
best-effort/advisory: absence or failure of the inspector must not silently become a recognition
failure. Do not make persisted OCR traces, framing guides, or quality metrics nutrition resolver
inputs.

## If you need to modify Search or discovery

There is no standalone search subsystem. Saved Food filtering begins at the selected runtime's
`foods.list` implementation: local SQLite in local mode or the Food list endpoint/repository in
remote mode. Unified presentation is in the Saved Foods screen, debounced-query utilities,
unified-search composition, Food/USDA hooks, and Food discovery helpers for favorites/recents.

Preserve stale-query suppression, the USDA minimum query length, explicit source sections, and the
difference between importing an upstream Food and selecting a saved Food.

## If you need to modify Targets

Begin at `NutritionRuntime.targets`, then separate shared reference semantics from persistence:

- canonical backend target/reference logic: `app/services/target_service.py`, `app/targets`;
- canonical nutrient definitions/reference metadata: `app/catalog/nutrients.py`;
- local parity/runtime: `apps/mobile/src/runtime/local/localTargetsRuntime.ts`;
- shared mobile DRI/catalog helpers: `apps/mobile/src/shared/nutrition`;
- mobile configuration/presentation: `apps/mobile/src/features/targets`;
- generated/source reference data: `engineering/reference-data`, `engineering/generate_dri_reference.py`.

Target resolution is not the old manual/calorie/FDA-only model. Preserve the current policy:
explicit `ignored`/`amount_only` tracking preferences first, then manual override, the bounded
calorie estimate for calories, available DRI RDA/AI recommendation, FDA Daily Value fallback,
neutral amount-only handling for nutrients with no established goal, then explicit unavailable
state. Returned tracking modes are `recommended`, `custom`, `amount_only`, and `ignored`.

DRI support and calorie-estimation support have different scopes. DRI resolution covers adults 19+
where a recommendation exists and supports pregnancy/lactation for female reference profiles age
19–50. The Mifflin–St Jeor calorie estimate remains general-adult-only and age 19–78 with complete
profile inputs.

Reference-data changes require deterministic regeneration/parity checks and provenance/version
review. Target changes must never write Daily Logs, nutrient snapshots, or published Recipe
nutrition.

## If you need to modify local backup or restore

Begin under `apps/mobile/src/storage/backup`, then follow the bootstrap/settings integration:

- artifact creation, validation, staging, activation, rollback: `src/storage/backup/localBackup.ts` and `localBackupValidation.ts`;
- user workflow: `src/app/settings/LocalBackupSettings.tsx`;
- restart-time gate: `src/runtime/applicationRuntimeBootstrap.ts` and local-first startup/restore gate code;
- SQLite authority/schema compatibility: `src/storage/sqlite`.

Preserve the distinction between backup and synchronization. Export must produce one coherent
standalone validated SQLite snapshot. Inspection/staging must not modify the active database.
Activation happens before a normal local runtime opens, creates a rollback snapshot when prior data
exists, validates the replacement, and fails closed if safe rollback cannot be completed. Secrets
such as the USDA credential are outside the application SQLite artifact.

Run `localBackupValidation`, `localBackupActivation`, `localBackupSettings`, and
`localFirstStartRestoreGate` tests plus native/file-backed SQLite qualification when the claim
depends on actual SQLite lifecycle or restart behavior.

## If you need to modify navigation, route headers, or form-discard behavior

Cross-cutting mobile navigation/UI policy lives in shared code rather than independently in every
screen:

- fixed detail/authoring chrome: `src/shared/components/RouteScreenHeader.tsx`;
- dirty/busy exit policy: `src/shared/navigation/draftGuard.ts` and `UnsavedDraftDialog.tsx`;
- focus/status primitives: `src/shared/accessibility` and `src/shared/forms`;
- root/tab routing: `src/app/navigation`.

Keep route headers outside scrolling form/detail bodies where the established shared pattern
applies. Preserve accessible touch targets and bounded visual text growth for fixed chrome. A dirty
form requires explicit discard; a busy mutation blocks normal exit. Add or update the relevant
route-header, Dynamic Type, accessibility, and draft-guard tests when these patterns change.

## If you need to modify authentication or runtime configuration

Read `app/core/config.py`, `app/dependencies/user.py`, mobile `config/runtimeConfig.js`, and the
shared API client. Run the full release-configuration and API-client authentication suites.

Do not make `production` silently use development or private-single-user identity. The absence of a
production provider is an intentional fail-closed condition.

## If you need to modify migrations

### Local SQLite schema evolution

Local persistence is owned by `apps/mobile/src/storage/sqlite/schema.ts` and `migrations.ts`.
SQLite is a fresh semantic schema, not an Alembic replay. Preserve exact canonical value encodings,
schema-version bookkeeping, migration rollback, foreign-key integrity, backup compatibility, and
native lifecycle qualification. Do not import Phase 5/control-plane tables, PostgreSQL roles/grants,
or migration-by-migration historical machinery into SQLite.

### Remote application migrations

Create new remote revisions under `app/migrations/versions`; do not rewrite committed migration
history. Use `NUTRITION_DATABASE_URL` explicitly. Review both a fresh upgrade and the oldest
supported populated path.

Migration 0004 refuses populated legacy Recipe state by design. Migrations 0015–0017 support the
offline historical bridge/converter, 0018 adds promotion prerequisites, and 0019 adds
database-enforced ownership and resource membership. Read the corresponding Phase 5 record before
touching them. For 0019 operations, follow the
[resource-membership runbook](../operations/runbooks/resource-membership.md); its preflight is
read-only, the application migration requires a closed fence and drained runtime, and the revision
is forward-only.

### Control migrations

Control migrations use `alembic-control.ini`, an independent database, and the explicit
`NUTRITION_CONTROL_MIGRATION_DATABASE_URL`. Never point them at the remote application database and
never port them into local SQLite. Changes require role/grant, SECURITY DEFINER, qualification,
tamper, downgrade, and re-upgrade review.

Continue with the [Control Plane Guide](../operations/control-plane.md) before editing ops migrations.

## If you need to modify Epic 2 transfer/parity contracts

Epic 2 is complete. Its retained machine-readable fixtures under `packages/shared-contracts/e2-*`
are regression/transfer evidence, not an active implementation backlog and not a generated public
SDK. In particular, `e2-15` contains versioned source schema, target schema, transfer contract, and
representative-package artifacts used by PostgreSQL-to-SQLite transfer qualification.

If a current schema change affects transfer compatibility or a retained cross-runtime parity
contract, update the implementation and the appropriate versioned fixture deliberately; do not
silently reinterpret an existing versioned artifact. Use the completed Epic 2 records for the
original acceptance boundary, then document new current behavior in current guides.

## If you need to modify the Control Plane

Begin with [Control Plane Guide](../operations/control-plane.md), not the general FastAPI routers.
Depending on the change, the authority may live in canonical contracts, evidence collection/WORM
registration, Python operator clients, PostgreSQL control migrations, role policy, or
`test_phase5c4_*` suites.

Trace the database routine and transaction, not just its Python wrapper. Verify exact role grants,
server-time decisions, lock ordering, replay, immutable evidence, qualification coverage, and
empty-only downgrade semantics.

## Dependency and vulnerability maintenance

Do not fix a package vulnerability by forcing a version outside Expo's supported compatibility
range when that breaks the native stack. Dependabot is intentionally constrained for Expo-coupled
packages. Apply compatible updates when available and keep the remaining vulnerability state
visible rather than trading a known dependency issue for an unsupported mobile dependency graph.

## Change checklist

Before finishing any feature change:

- identify the authoritative layer and selected runtime(s);
- preserve owner scope and idempotency behavior;
- determine whether historical snapshots or revisions are involved;
- distinguish target/reference configuration from historical nutrition;
- preserve physical serving meaning when unit presentation changes;
- preserve explicit Complete state and atomically invalidate it whenever authoritative Daily Log
  nutrition changes;
- keep History bounded, snapshot-derived, target-history-free, and single-authority;
- update local and remote contracts together when the change is a parity contract;
- add a migration only for persistent schema change;
- update retained Epic 2 transfer/parity artifacts only when their bounded contract is actually affected;
- test the smallest unit plus the cross-layer flow;
- use native/file-backed SQLite qualification for claims about local SQLite lifecycle,
  backup/restore, transactions, schema evolution, or restart behavior;
- use PostgreSQL for remote row-lock, PostgreSQL constraint/grant, role, or multi-worker concurrency claims;
- update the reader guide if responsibility, a current capability, or an invariant changed.

## Next reading

- Use the [Testing Guide](../operations/testing.md) to select qualification proportional to the change.
- Revisit the relevant domain guide before changing an invariant or public contract.
- Use the [Architecture Decision Index](../architecture/decisions.md) when a design choice is unclear.

## See also

- [Repository Tour](repository-tour.md) for directory navigation
- [Architecture Overview](../architecture/overview.md) for responsibility boundaries
- [Glossary](../reference/glossary.md) for project-specific terms
- [Control Plane Guide](../operations/control-plane.md) only for Phase 5 and production-operations changes
