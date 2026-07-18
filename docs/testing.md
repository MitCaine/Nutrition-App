# Testing guide

The test strategy follows architectural claims. Fast unit tests explain behavior; PostgreSQL and
MinIO suites prove guarantees that mocks or SQLite cannot establish.

## Baseline validation

### Backend

```bash
cd apps/backend
source .venv/bin/activate
pytest
ruff check .
ruff format --check .
python -m compileall -q app tests scripts
```

The default test configuration selects test deployment mode and in-memory SQLite where a test does
not explicitly require PostgreSQL. This is appropriate for calculation, parser, schema, API, and
most service behavior. It is not evidence for PostgreSQL locking or privilege claims.

### Mobile

```bash
cd apps/mobile
npm test
npm run typecheck
EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE=development \
EXPO_PUBLIC_NUTRITION_API_URL=http://localhost:8000/api/v1 \
  npm run config:validate
```

Jest covers pure feature models, runtime validation, API mappings, cache invalidation, and rendered
flow behavior. Native Apple Vision geometry/runtime tests live under
`modules/nutrition-ocr/ios-tests` and must also run through the native iOS test target before an OCR
release.

## What each backend suite proves

| Suite family | Main claim |
| --- | --- |
| `test_nutrition_*`, `test_aggregation.py` | Decimal-safe resolution, unit rules, unknown/zero semantics |
| `test_stage2_*`, `test_stage3_*`, `test_stage4_*` | Feature/API contracts for Foods, Logs, USDA, and Recipes |
| `test_recipe_*` | Publication immutability, nested graphs, projections, revision logging/editing |
| `test_ocr_*` | Pure parsing, golden fixtures, bounded confirmation provenance, privacy |
| `test_create_operation_idempotency.py`, `test_log_idempotency.py` | Exact replay and payload conflict |
| `test_cross_user_ownership.py`, saved-Food tests | User boundary and cross-owner denial |
| `*_postgres.py` | Real PostgreSQL migrations, constraints, locks, races, and role behavior |
| `test_phase5c_*` | Historical bridge, conversion, qualification, performance, and restart guarantees |
| `test_phase5c4_*` | Contract canonicalization, roles, control routines, admission, WORM, tamper, and migration safety |

## PostgreSQL concurrency and migration tests

Start the repository PostgreSQL 16 service, then point only at a disposable test database/cluster:

```bash
docker compose up -d postgres
cd apps/backend
NUTRITION_TEST_POSTGRES_URL=postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app \
  pytest -m postgres_concurrency
```

These tests create and drop temporary databases and provision roles. Never supply a production or
valuable development database URL. PostgreSQL suites prove:

- Food/Recipe lock ordering and graph restart behavior;
- Daily Log snapshot consistency under concurrent mutation;
- migration upgrade/downgrade refusal and round trips;
- source/clone read-only and isolation contracts;
- role topology, grants, SECURITY DEFINER boundaries, and write fencing;
- control-plane replay, leases, immutable event/outbox behavior, and admission races.

Run a focused file while developing, then the complete marker before claiming a concurrency or
migration invariant.

## Phase 5C performance qualification

The full T0 fixture is opt-in because it creates and measures a disposable PostgreSQL workload:

```bash
NUTRITION_RUN_PHASE5C_T0=1 \
NUTRITION_TEST_POSTGRES_URL=postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app \
  pytest -m phase5c_performance_t0
```

Performance evidence does not replace correctness qualification. A scan or timing failure informs
a separate optimization decision; it cannot waive conversion, lineage, or immutable-history rules.

## Control-database qualification

The complete control PostgreSQL suite is:

```bash
NUTRITION_TEST_POSTGRES_URL=postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app \
  pytest -q tests/test_phase5c4_control_postgres.py
```

It provisions an isolated control database and managed roles, migrates through ops revisions,
executes routines through real credentials, tests concurrency/failure injection, tampers with
qualified objects, and exercises empty-only downgrade/re-upgrade behavior.

Qualification tests are security tests. When adding an authoritative table, routine, trigger,
constraint, grant, or registry row, add both a positive inventory assertion and a tamper case that
makes qualification fail.

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
exact version binding, replay, reconciliation, and restart persistence. They are not safe to point
at a shared or production object store.

## Test selection by change

| Change | Minimum affected validation |
| --- | --- |
| Pure calculation/parser | Focused unit tests, full backend baseline, Ruff |
| API/schema/service | Focused backend tests plus affected mobile mapping/flow tests |
| Food/Recipe dependency locks | Focused unit/API tests plus PostgreSQL concurrency marker |
| Migration | Fresh upgrade, supported populated upgrade, downgrade policy, re-upgrade, schema authority |
| Auth/config | Release configuration, API authentication, mobile runtime config, Compose validation |
| Control contract | Python canonical/tamper tests and cross-language PostgreSQL parity |
| Control routine/grant | Complete control PostgreSQL, role, qualification, replay, concurrency, downgrade suites |
| MinIO behavior | Unit adapter tests plus disposable integration and restart persistence |

## Final repository checks

For a cross-cutting change, also run:

```bash
docker compose -f docker-compose.yml config -q
git diff --check
```

Validate the Phase 5C4 Compose file with explicit disposable MinIO credentials. Review `git status`
so generated build output, `.env`, credentials, evidence, database dumps, or screenshots containing
personal data are not included.

## Next reading

- Return to the [Development Guide](development-guide.md) to verify the affected code path.
- Use the [Architecture Decision Index](architecture-decisions.md) to identify the invariant the
  test should prove.
- For Phase 5 qualification, continue with the optional [Control Plane Guide](control-plane.md).

## See also

- [Architecture Guide](architecture.md#testing-architecture) for the testing layers
- [Repository Tour](repository-tour.md) for test locations
- [Release Candidate QA](rc1-release-qa.md) for manual device and release checks
