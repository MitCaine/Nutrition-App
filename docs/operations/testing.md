# Testing guide

> **Document role: Operational Reference.**

The test strategy follows architectural claims. Fast unit tests explain behavior; Jest proves mobile
models, local-runtime parity, and rendered flows; native/file-backed SQLite qualification proves
local storage/lifecycle claims; native Swift tests prove Apple Vision/image-quality behavior;
PostgreSQL suites prove remote locking, role, migration, and concurrency claims; MinIO suites prove
object-retention behavior.

## Baseline validation

### Backend

```bash
cd apps/backend
source .venv/bin/activate
pytest
ruff check .
python -m compileall -q app tests scripts
```

The default test configuration selects test deployment mode and in-memory SQLite where a test does
not explicitly require PostgreSQL. This is appropriate for calculations, DRI/reference data,
parser, schema, API, and most service behavior. It is not evidence for PostgreSQL locking or
privilege claims.

The reproducible Python 3.12 development and CI environment is pinned in
`requirements-dev.lock`. `pyproject.toml` remains the dependency declaration; use the regeneration
command in the [Development Guide](../project/development-guide.md#configuration-and-startup) after changing
dependencies.

### Mobile

```bash
cd apps/mobile
npm test
npm run typecheck

EXPO_PUBLIC_NUTRITION_DATA_AUTHORITY=local \
EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE=development \
  npm run config:validate

EXPO_PUBLIC_NUTRITION_DATA_AUTHORITY=remote \
EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE=development \
EXPO_PUBLIC_NUTRITION_API_URL=http://localhost:8000/api/v1 \
  npm run config:validate
```

Jest covers pure feature models, explicit authority routing, local-runtime parity, remote API
mappings, cache/recovery scoping, DRI/Target parity, local backup policy/activation, draft guards,
shared route chrome, OCR quality policy, and rendered flow behavior.

Native/file-backed SQLite qualification is required for claims about `expo-sqlite` lifecycle,
migrations, transaction visibility, termination, backup/restore activation, and restart semantics
that mocks cannot establish. Native Apple Vision geometry/recognition/image-quality tests live under
`modules/nutrition-ocr/ios-tests` and must run through the native iOS test target before a release
claim that depends on those native behaviors.

## High-value current feature suites

| Area | Representative proof |
| --- | --- |
| Nutrition units/catalog | `test_nutrient_catalog.py`, nutrition resolution/aggregation tests, `nutrientSections.test.ts` |
| Food/serving semantics | `test_stage2_foods.py`, Food integrity tests, serving unit/reference transition tests, `foodForm*.test.ts` |
| USDA expanded mapping | `test_stage3_usda_*`, `localUsdaRuntime.test.ts`, USDA mobile tests |
| Recipe publication/history | `test_recipe_*`, publication/revision tests, Recipe serving/yield tests |
| Daily Logs | stage-2 Log tests, revision Log tests, local Daily Log tests, logging integration/display tests |
| DRI and target resolution | `test_dri_recommendations.py`, `test_targets.py`, `test_target_tracking_preferences.py`, `driRecommendations.test.ts`, `localTargetsRuntime.test.ts`, `target*.test.ts` |
| OCR parser/confirmation | `test_ocr_parser.py`, golden fixtures, `test_ocr_confirmation.py`, local OCR parser/runtime tests, confirmation tests |
| Guided OCR capture/quality | `nutritionScanAccessibility.test.ts`, `ocrImageQuality.test.ts`, native Swift image-quality tests |
| Local backup/restore | `localBackupValidation.test.ts`, `localBackupActivation.test.ts`, `localBackupSettings.test.ts`, `localFirstStartRestoreGate.test.ts` |
| Navigation/UI protections | `draftGuard.test.ts`, `fixedChromeDynamicType.test.ts`, route-header/detail layout tests, feature accessibility tests |
| E2-15 transfer | backend exporter/package/schema tests, mobile importer/validator tests, versioned `packages/shared-contracts/e2-15` fixtures |

These names are representative, not permission to skip affected neighboring tests. Use the complete
backend/mobile baseline before declaring a cross-cutting feature change finished.

## What each backend suite family proves

| Suite family | Main claim |
| --- | --- |
| `test_nutrition_*`, `test_aggregation.py`, `test_nutrient_catalog.py` | Decimal-safe resolution, qualified unit rules, catalog integrity, unknown/zero semantics |
| `test_dri_recommendations.py`, `test_targets.py`, `test_target_tracking_preferences.py` | DRI selection/scope, calorie-estimate boundary, tracking modes, FDA fallback/reference behavior |
| `test_stage2_*`, `test_stage3_*`, `test_stage4_*` | Feature/API contracts for Foods, Logs, USDA, and Recipes |
| `test_recipe_*` | Publication immutability, nested graphs, projections, revision logging/editing |
| `test_ocr_*` | Pure parsing, expanded nutrient mapping, golden fixtures, bounded confirmation provenance/privacy |
| `test_create_operation_idempotency.py`, `test_log_idempotency.py` | Exact replay and payload conflict |
| `test_cross_user_ownership.py`, saved-Food tests | User boundary and cross-owner denial |
| `*_postgres.py` | Real PostgreSQL migrations, constraints, locks, races, and role behavior |
| `test_phase5c_*` | Historical bridge, conversion, qualification, performance, and restart guarantees |
| `test_phase5c4_*` | Contract canonicalization, roles, control routines, admission, WORM, tamper, and migration safety |

## PostgreSQL concurrency and migration tests

Start repository PostgreSQL 16, then point only at a disposable test database/cluster:

```bash
docker compose up -d postgres
cd apps/backend
NUTRITION_TEST_POSTGRES_URL=postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app \
  pytest -m postgres_concurrency
```

These tests may create/drop temporary databases and provision roles. Never supply a production or
valuable development database URL. PostgreSQL suites prove:

- Food/Recipe lock ordering and graph restart behavior;
- Daily Log snapshot consistency under concurrent mutation;
- Food source/name/integrity constraints under races;
- migration upgrade/downgrade/refusal and current-head replay;
- source/clone read-only and isolation contracts;
- role topology, grants, SECURITY DEFINER boundaries, and write fencing;
- control-plane replay, leases, immutable event/outbox behavior, and admission races.

Run a focused file while developing, then the complete relevant marker/suite before claiming a
PostgreSQL concurrency or migration invariant.

## Native and local SQLite qualification

Jest mocks and pure TypeScript tests are not sufficient evidence for claims about actual
`expo-sqlite` connection lifecycle, WAL/foreign-key behavior, restart visibility, or native-module
behavior. Use the repository's native qualification harnesses documented by the completed Epic 2
records when the change crosses those boundaries.

Epic 2 is complete; its E2-02 through E2-18 fixtures/harness records are retained as regression
proof and parity contracts, not an active implementation backlog. A current change that affects a
retained versioned fixture must update/version the fixture deliberately and rerun the corresponding
local/native/remote parity proof.

For local backup/restore specifically, run the focused Jest suites listed above and native/file-backed
SQLite qualification when the change affects backup copy coherence, schema compatibility,
replacement/rollback, or restart-time activation. A mocked filesystem/database test alone cannot
prove safe replacement of the real local authority.

For OCR native changes, run the Swift test target under `modules/nutrition-ocr/ios-tests` in addition
to TypeScript OCR tests. Image-quality inspection is intentionally best-effort; tests must preserve
the contract that an unavailable/failing inspector does not convert into a recognition failure.

## Issue 17 isolated Phase 5C clone

This retained workflow exists for historical/application-path qualification that specifically needs
a disposable database traversing the Phase 5C conversion path. It is not needed for ordinary
local-first feature work.

```bash
./scripts/run-issue17-phase5c-clone.sh
```

The wrapper starts a repository-pinned disposable PostgreSQL 16 container, creates isolated source
and conversion-clone databases, refuses unsafe pre-existing cluster state, and removes the exact
container on normal success/failure unless explicit manual-test retention is requested. It must not
use or downgrade a valuable/current application-head database.

For the retained physical-device/manual path:

```bash
./scripts/run-issue17-phase5c-clone.sh --manual-test
```

The resulting test-only schema-0021 activation bindings are regression/manual-qualification
authority only. They are not signed production authorization and must never be cited as production
promotion/activation evidence.

Opt-in integration coverage:

```bash
cd apps/backend
NUTRITION_RUN_ISSUE17_PHASE5C_CLONE=1 \
  .venv/bin/python -m pytest -q --strict-markers \
  tests/test_issue17_phase5c_clone_workflow_postgres.py
```

## Phase 5C performance qualification

The full T0 fixture is opt-in because it creates and measures a disposable PostgreSQL workload:

```bash
NUTRITION_RUN_PHASE5C_T0=1 \
NUTRITION_TEST_POSTGRES_URL=postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app \
  pytest -m phase5c_performance_t0
```

Performance evidence does not replace correctness qualification. A timing result cannot waive
conversion, lineage, immutable-history, or authority rules.

## Control database and production-hardening tests

The control/Phase 5C4 suites are security/authority qualification. Use only disposable PostgreSQL
and follow the [Control Plane Guide](control-plane.md) and exact runbook associated with the stage.
Representative control PostgreSQL qualification through the implemented activation path is:

```bash
NUTRITION_TEST_POSTGRES_URL=postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app \
  pytest -q \
    tests/test_phase5c4_control_postgres.py \
    tests/test_resource_membership_control_postgres.py \
    tests/test_immutable_provenance_control_postgres.py \
    tests/test_phase5c4_recovery_control_postgres.py \
    tests/test_phase5c4_authorization_control_postgres.py \
    tests/test_phase5c4_authorization_migration_postgres.py \
    tests/test_phase5c4_promotion_authorization_control_postgres.py \
    tests/test_phase5c4_target_activation_control_postgres.py
```

Qualification tests are security tests. When adding an authoritative control table, routine,
trigger, constraint, grant, or registry row, add both a positive inventory assertion and a tamper
case that makes qualification fail.

Phase 5C4.7b also has application-migration/authorization/target-local boundaries:

```bash
pytest -q \
  tests/test_phase5c4_activation_execution.py \
  tests/test_phase5c4_execution_authorization_cli.py \
  tests/test_phase5c4_target_activation_cli.py

NUTRITION_TEST_POSTGRES_URL=postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app \
  pytest -q tests/test_phase5c4_target_activation_postgres.py
```

The target PostgreSQL suite must use disposable PostgreSQL 16. A successful migration alone is not
evidence that authorization, activation, replay/conflict, emergency close, or forward-only policy
passed.

### Phase 5C4.8 bounded recovery qualification

The pure preactivation-cutback contract suite is:

```bash
pytest -q tests/test_phase5c4_cutback.py
```

The implemented ops-0011 recovery/control suites additionally cover cumulative qualification,
audit snapshots, executable cutback authority, reconciliation, and PITR evidence. Run the
destructive local infrastructure qualifier only with its explicit disposable confirmation:

```bash
NUTRITION_PHASE5C4_QUALIFICATION_CONFIRM=phase5c4_infrastructure_destroy_disposable \
NUTRITION_PHASE5C4_QUALIFICATION_RETAIN_EVIDENCE=1 \
  ./scripts/qualify-phase5c4-infrastructure.sh
```

Ordinary/session-end suites do not start this destructive topology. A qualified local summary is
proof only of the bounded provider/PostgreSQL/pgBackRest/MinIO scenarios named by that qualifier; it
is not production-vendor certification.

### Phase 5C4.9 / Version 1.0 frozen release boundary

The preserved Version 1.0 release boundary remains application
`0021_target_activation_execution` and control `ops_0011_phase5c4_recovery_audit`. Current remote
application development has advanced to `0030_total_omega_3_nutrient`; this does not rewrite the
historical release head.

The authoritative frozen command/evidence manifest is
[Version 1.0 PostgreSQL Release Qualification](version-1.0-release-qualification.md). Developer
convenience commands in this guide do not substitute for that release manifest.

## MinIO object-lock integration

Use only the disposable loopback profile and explicit confirmation variables:

```bash
NUTRITION_PHASE5C4_TEST_MINIO_ROOT_USER=stage5c4root \
NUTRITION_PHASE5C4_TEST_MINIO_ROOT_PASSWORD=stage5c4-disposable-secret \
  docker compose -f docker-compose.phase5c4.yml \
  --profile phase5c4-evidence up -d minio

cd apps/backend
NUTRITION_PHASE5C4_TEST_MINIO_DISPOSABLE=nutrition_phase5c4_test_only \
NUTRITION_PHASE5C4_TEST_DOCKER_RESTART=nutrition_phase5c4_test_only \
NUTRITION_PHASE5C4_TEST_MINIO_ENDPOINT=127.0.0.1:59000 \
NUTRITION_PHASE5C4_TEST_MINIO_ROOT_USER=stage5c4root \
NUTRITION_PHASE5C4_TEST_MINIO_ROOT_PASSWORD=stage5c4-disposable-secret \
  pytest -q tests/test_phase5c4_minio.py tests/test_phase5c4_minio_integration.py
```

These tests may restart the named Compose service. They prove versioning, COMPLIANCE retention,
exact version binding, replay, reconciliation, and restart persistence. Never point them at a
shared or production object store.

## Test selection by change

| Change | Minimum affected validation |
| --- | --- |
| Pure calculation/parser | Focused unit tests, full backend baseline, Ruff |
| Nutrient catalog/qualified units | Nutrient catalog + resolution + Food validation + affected mobile nutrition tests |
| DRI/Target/reference logic | Backend DRI/Target/tracking suites + local target/DRI parity + affected UI tests |
| API/schema/service | Focused backend tests plus affected mobile mapping/flow tests |
| Food/Recipe dependency locks | Focused unit/API tests plus PostgreSQL concurrency marker |
| Serving/reference measurement | Backend serving/Food integrity + local serving transition/form tests + Recipe dependency tests |
| Migration | Fresh upgrade, supported populated upgrade, downgrade policy, re-upgrade, schema authority |
| Auth/config | Local/remote mobile runtime config, remote API authentication, release configuration, Compose validation |
| Local SQLite persistence/runtime | Focused local runtime/Jest plus native/file-backed SQLite qualification for lifecycle/transaction claims |
| Local backup/restore | Backup validation/activation/settings/start gate + native/file-backed SQLite for actual replacement/restart claims |
| OCR camera/quality | Scan/accessibility + quality policy + native Swift tests when native metrics/capture change |
| Route header/draft guard/accessibility | Shared header/draft/Dynamic Type tests plus each affected screen flow |
| E2 transfer contract | Backend/mobile E2-15 tests + versioned shared-contract fixtures |
| Control contract | Python canonical/tamper tests and cross-language PostgreSQL parity |
| Control routine/grant | Complete control PostgreSQL, role, qualification, replay, concurrency, downgrade suites |
| MinIO behavior | Unit adapter tests plus disposable integration and restart persistence |

## Final repository checks

For a cross-cutting change, also run:

```bash
python scripts/validate-docs.py
bash -n scripts/*.sh
docker compose -f docker-compose.yml config -q
git diff --check
```

GitHub Actions runs the fast backend, mobile, documentation, and shell baseline. PostgreSQL,
control-database, MinIO, performance, destructive recovery, and native iOS qualification remain
manual or explicitly opt-in because their authority depends on disposable services or Apple
tooling.

Review `git status` before publishing so generated output, `.env`, credentials, evidence, database
dumps, or screenshots containing personal data are not included.

## Next reading

- Return to the [Development Guide](../project/development-guide.md) to verify the affected code path.
- Use the [Architecture Decision Index](../architecture/decisions.md) to identify the invariant the
  test should prove.
- For Phase 5 qualification, continue with the optional [Control Plane Guide](control-plane.md).

## See also

- [Architecture Overview](../architecture/overview.md#testing-architecture) for testing layers
- [Repository Tour](../project/repository-tour.md) for test locations
- [Release Candidate QA](../historical/releases/rc1-qa.md) for historical manual device/release evidence
