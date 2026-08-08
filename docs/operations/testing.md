# Testing guide

> **Document role: Operational Reference.**

The test strategy follows architectural claims. Fast unit tests explain behavior; PostgreSQL and
MinIO suites prove guarantees that mocks or SQLite cannot establish.

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
not explicitly require PostgreSQL. This is appropriate for calculation, parser, schema, API, and
most service behavior. It is not evidence for PostgreSQL locking or privilege claims.

The reproducible Python 3.12 development and CI environment is pinned in
`requirements-dev.lock`. `pyproject.toml` remains the dependency declaration; use the regeneration
command in the [Development Guide](../project/development-guide.md#configuration-and-startup) after changing
dependencies.

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

### Issue 17 isolated Phase 5C clone

Use the Issue 17 workflow when accessibility qualification needs an application
database that has traversed the historical Phase 5C conversion path through
`0024_recipe_log_current_provenance`:

```bash
./scripts/run-issue17-phase5c-clone.sh
```

The wrapper starts the repository-pinned PostgreSQL 16 image without a volume,
publishes PostgreSQL only on a temporary loopback port, and creates unique
historical source and conversion-clone databases. It refuses a cluster with an
existing `nutrition_app` database, Phase 5C managed roles, or any unexpected
non-template database. The normal workflow removes the exact disposable
container on success, failure, interrupt, and termination. The existing local
`nutrition_app` database is intentionally excluded: it is an application-head
database, not a frozen-0003 conversion source, and must not be downgraded or
used as conversion evidence.

The retained private JSON artifacts include source and clone identities,
fixture seed metadata, inventory, planning and execution attestations, clone
marker, bridge result, conversion plan and receipts, restart verification,
0017/0018 qualifications, role qualification, promotion-target initialization,
maintenance and write-fence transitions, exact-0020 immutable-provenance
qualification, the post-head observation, and the final artifact/digest
manifest. Artifacts are mode `0600`; database URLs, role passwords, and the
container administrator credential are not written to them. Use `--output-dir`
only with an empty, non-symlink directory when a known evidence location is
needed.

For physical-device E1-17 testing, retain and open the disposable target with:

```bash
./scripts/run-issue17-phase5c-clone.sh --manual-test
```

After the real `alembic upgrade head` reaches 0024, manual-test mode uses the
installed schema-0021 test activation surface and explicit synthetic bindings
to open only this disposable target. It prints a `nutrition_runtime` loopback
database URL, an exact backend startup command that listens on `0.0.0.0:8000`,
and an exact `docker rm -f ...` cleanup command. The container is retained only
after complete success; any setup, conversion, migration, qualification, or
activation failure still triggers automatic removal. Run the printed cleanup
command after VoiceOver, Dynamic Type, and related device checks finish.

The test-only schema-0021 bindings and local runtime opening are regression and
manual-qualification authority only. They are not signed production
authorization, do not exercise the durable control-database authorization
chain, and must never be cited as production promotion or activation evidence.
Production activation continues to require the existing control-plane
authorization and target-action workflow.

The opt-in integration coverage is:

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

Performance evidence does not replace correctness qualification. A scan or timing failure informs
a separate optimization decision; it cannot waive conversion, lineage, or immutable-history rules.

## Control-database qualification

The complete control PostgreSQL suite through Phase 5C4.7b is:

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

It provisions an isolated control database and managed roles, migrates through ops revisions,
executes routines through real credentials, tests concurrency/failure injection, tampers with
qualified objects, and exercises empty-only downgrade/re-upgrade behavior.

Qualification tests are security tests. When adding an authoritative table, routine, trigger,
constraint, grant, or registry row, add both a positive inventory assertion and a tamper case that
makes qualification fail.

Phase 5C4.7b also requires the application-migration, contract, signerless CLI,
target-local CLI, and target concurrency boundary:

```bash
pytest -q \
  tests/test_phase5c4_activation_execution.py \
  tests/test_phase5c4_execution_authorization_cli.py \
  tests/test_phase5c4_target_activation_cli.py

NUTRITION_TEST_POSTGRES_URL=postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app \
  pytest -q tests/test_phase5c4_target_activation_postgres.py
```

The target PostgreSQL suite must use a disposable PostgreSQL 16 database. It
proves authorized schema-0021 installation, the closed-after-migration
boundary, exact target role admission, one-use activation, authoritative
observation, emergency close, replay/conflict handling, and the forward-only
application downgrade policy. A successful application or control migration
alone is not evidence that these tests passed.

### Phase 5C4.8 bounded recovery qualification

The pure preactivation-cutback contract suite is:

```bash
pytest -q tests/test_phase5c4_cutback.py
```

It covers deterministic Ed25519 framing, canonical JSON, signature and key
substitution, validity boundaries, exact authority bindings, and strict
safety, route, and source-restoration observation shapes.

`tests/test_phase5c4_recovery_qualification_control_postgres.py` proves the
ops-0011 cumulative qualifier and audit-only recovery snapshot behavior against
disposable PostgreSQL 16. `tests/test_phase5c4_recovery_qualification.py`
proves the mutation-free postactivation PITR evidence contract.

`tests/test_phase5c4_cutback_control_postgres.py` proves the executable ops-0011
authority chain against disposable PostgreSQL 16: exact verifier grants,
trusted admission, concurrent replay, one-use consumption, route failure and
later authoritative success, source-restoration ambiguity and reconciliation,
terminal convergence, immutability, and downgrade refusal.

Run the destructive local infrastructure qualifier explicitly:

```bash
NUTRITION_PHASE5C4_QUALIFICATION_CONFIRM=phase5c4_infrastructure_destroy_disposable \
NUTRITION_PHASE5C4_QUALIFICATION_RETAIN_EVIDENCE=1 \
  ./scripts/qualify-phase5c4-infrastructure.sh
```

Prerequisites are Docker with Compose, OpenSSL, the repository virtual
environment, and unused loopback ports 59100–59104. The command generates all
credentials and refuses caller-supplied qualification credentials. It removes
the generated Compose project, including profile-scoped restored volumes, on
success and failure. Retention preserves only the canonical summary and
private restore intent/completion journals; it never preserves the generated
TLS private key.

The opt-in pytest wrapper is
`tests/test_phase5c4_infrastructure_integration.py` under
`phase5c4_docker_integration`; ordinary and session-end suites do not start
Docker. A qualified summary proves the local provider, PostgreSQL/pgBackRest,
MinIO, and selected control scenarios named in that summary. It explicitly
skips schema-0021 application-domain restoration, one-saga binding between
provider observations and control admission, and production-vendor
certification, so it must not be cited as proof of those gates.

### Phase 5C4.9 Version 1.0 release gate

The current application migration head is `0021_target_activation_execution`;
the current control migration head is `ops_0011_phase5c4_recovery_audit`.
Release qualification does not change either head.

The single authoritative command manifest is
[Version 1.0 PostgreSQL Release Qualification](version-1.0-release-qualification.md). It combines
the required fail-closed PostgreSQL suites and the separately retained infrastructure evidence
gate. The focused commands below are developer conveniences and are not release qualification.

Run the frozen-0001 replay comparison against disposable PostgreSQL 16:

```bash
REQUIRE_POSTGRES_TESTS=1 \
  pytest -q tests/test_initial_migration_replay_postgres.py
```

Before creating final infrastructure evidence, commit the exact release source
state and verify `git status --porcelain` is empty. Then run the destructive
local infrastructure qualifier above with evidence retention enabled. Its
canonical summary records the exact commit, clean/dirty state, control-plane
inventory digest, Compose/pgBackRest/qualifier configuration digests,
qualification result, RPO/RTO measurements, and individual scenario results.
Evidence with `dirty_tree: true` is not Version 1.0 release evidence.

Developer convenience commands elsewhere in this guide may skip when optional PostgreSQL, MinIO,
Docker, provider, performance, or Apple infrastructure is unavailable. Such skips are acceptable
for focused development feedback but are not a passing Version 1.0 release result.

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
python scripts/validate-docs.py
bash -n scripts/*.sh
docker compose -f docker-compose.yml config -q
git diff --check
```

GitHub Actions runs the fast backend, mobile, documentation, and shell baseline. PostgreSQL,
control-database, MinIO, performance, and native iOS qualification remain manual or explicitly
opt-in because their authority depends on disposable services or Apple tooling.

Validate the Phase 5C4 Compose file with explicit disposable MinIO credentials. Review `git status`
so generated build output, `.env`, credentials, evidence, database dumps, or screenshots containing
personal data are not included.

## Next reading

- Return to the [Development Guide](../project/development-guide.md) to verify the affected code path.
- Use the [Architecture Decision Index](../architecture/decisions.md) to identify the invariant the
  test should prove.
- For Phase 5 qualification, continue with the optional [Control Plane Guide](control-plane.md).

## See also

- [Architecture Overview](../architecture/overview.md#testing-architecture) for the testing layers
- [Repository Tour](../project/repository-tour.md) for test locations
- [Release Candidate QA](../historical/releases/rc1-qa.md) for manual device and release checks
