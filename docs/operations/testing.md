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
../../scripts/run-backend-baseline.sh
ruff check .
python -m compileall -q app tests scripts
```

The canonical ordinary backend baseline is `scripts/run-backend-baseline.sh`. It excludes the
registered PostgreSQL concurrency, Phase 5C T0 performance, Phase 5C4 control-PostgreSQL, MinIO,
and Docker-integration marker families. Those suites remain explicit qualification and must be
selected directly when their claims are in scope. Do not replace the ordinary runner with bare
`pytest`, because infrastructure availability must not change which tests belong to the ordinary
regression baseline.

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


## Main qualification profiles

Task Capsules may select machine-executable qualification profiles through
`specialized_qualification` entries using `profile:lowercase-name`. The initial
repository registry owns four profiles:

| Profile | Required GitHub check |
| --- | --- |
| `repository` | `Repository validation` |
| `backend` | `Backend baseline` |
| `mobile` | `Mobile baseline` |
| `postgresql` | `Backend PostgreSQL 16 contracts` |

The existing CI jobs remain the qualification authorities; `Main qualification`
aggregates their exact-SHA results rather than duplicating their test commands.
Pushing an exact commit to a temporary `qualification/TASK-ID/SHA-PREFIX` ref
causes the normal CI workflow and the aggregator to run against that unchanged
commit. Unknown or unavailable profiles fail closed.

`./scripts/capsule qualify TASK-ID --evidence-dir PATH` is the normal
repository entry point for this remote qualification. It requires a clean task
worktree, exact branch/base authority, scope conformity, and a GitHub-visible
unchanged SHA. After PASS it downloads the retained qualification artifact,
records the workflow/check identity, GitHub artifact ID/digest, and local
manifest SHA-256, then removes the temporary ref. A failed qualification
retains the ref for explicit inspection rather than silently waiving the
failure.

The `Main qualification` profile is commit qualification, not acceptance or
review judgment. Task Capsule acceptance criteria, reviewer disposition, scope
exceptions, architecture stops, and human-owner `MERGED` authority remain
separate explicit decisions.


## High-value current feature suites

| Area | Representative proof |
| --- | --- |
| Nutrition units/catalog | `test_nutrient_catalog.py`, nutrition resolution/aggregation tests, `nutrientSections.test.ts` |
| Food/serving semantics | `test_stage2_foods.py`, Food integrity tests, serving unit/reference transition tests, `foodForm*.test.ts` |
| USDA expanded mapping | `test_stage3_usda_*`, `localUsdaRuntime.test.ts`, USDA mobile tests |
| Recipe publication/history | `test_recipe_*`, publication/revision tests, Recipe serving/yield tests |
| Daily Logs | stage-2 Log tests, revision Log tests, local Daily Log tests, logging integration/display tests |
| Complete and Nutrition History | E4-01–E4-06 contracts, E4-09–E4-12 presentation, E4-15 durability, E4-16 local/PostgreSQL/shared-projection parity |
| DRI and target resolution | `test_dri_recommendations.py`, `test_targets.py`, `test_target_tracking_preferences.py`, `driRecommendations.test.ts`, `localTargetsRuntime.test.ts`, `target*.test.ts` |
| OCR parser/confirmation | `test_ocr_parser.py`, golden fixtures, `test_ocr_confirmation.py`, local OCR parser/runtime tests, confirmation tests |
| Guided OCR capture/quality | `nutritionScanAccessibility.test.ts`, `ocrImageQuality.test.ts`, native Swift image-quality tests |
| Local backup/restore | `localBackupValidation.test.ts`, `localBackupActivation.test.ts`, `localBackupSettings.test.ts`, `localFirstStartRestoreGate.test.ts` |
| Navigation/UI protections | `draftGuard.test.ts`, `fixedChromeDynamicType.test.ts`, route-header/detail layout tests, feature accessibility tests |
| E2-15 transfer | backend exporter/package/schema tests, mobile importer/validator tests, versioned `packages/shared-contracts/e2-15` fixtures |

These names are representative, not permission to skip affected neighboring tests. Use the complete
backend/mobile baseline before declaring a cross-cutting feature change finished.

## What each backend suite proves

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

## Epic 4 History release qualification

The completed E4-16 harness remains available as a retained regression
qualifier for Complete/History behavior:

```bash
./scripts/run-e4-16-qualification.sh
```

Use it when a change crosses that qualified boundary; it is not the current
release-state authority and does not replace affected baseline or focused
tests. Historical device/release evidence is retained in
`engineering/capsules/HISTORY.md` and the historical Epic 4 package.
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

## Control-database qualification

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

### Phase 5C4.9 Version 1.0 release gate

Version 1.0 qualification is historical. Its frozen command/evidence manifest
is the
[Version 1.0 PostgreSQL Release Qualification](../historical/releases/version-1.0-release-qualification.md).

The initial-migration replay test remains useful when migration replay
compatibility changes:

```bash
REQUIRE_POSTGRES_TESTS=1 \
  pytest -q tests/test_initial_migration_replay_postgres.py
```

Current application and control migration identities are owned by
[Current State](../project/current-state.md), not by the frozen Version 1.0
release boundary.
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
| Complete/History semantics or UI | Relevant E4 focused suites plus `scripts/run-e4-16-qualification.sh`; repeat physical device evidence when the changed claim is physical |
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

## Trusted task-controller bootstrap

GH-165-P3 introduces a candidate-independent qualification boundary without activating it live.

GH-165-P3 originally introduced `.github/workflows/trusted-qualification.yml` as a
single `workflow_dispatch` qualification workflow. GH-171 subsequently separates the trusted
dispatch boundary from candidate execution so untrusted candidate code does not execute in a
default-branch cache-write-capable `workflow_dispatch` run.

The steady-state entrypoint remains `.github/workflows/trusted-qualification.yml` and is dispatched
explicitly at the exact authorized `main` commit. That workflow does not check out or execute the
candidate. It validates the controller-supplied scalar identities and publishes them as a
short-retention `trusted-qualification-dispatch` artifact.

`.github/workflows/trusted-qualification-execute.yml` is triggered by successful completion of that
entrypoint through `workflow_run`. It requires the triggering run to be a same-repository
`workflow_dispatch` on `main`, requires the executor/default-branch SHA to equal the triggering
controller SHA, downloads and validates the exact handoff artifact, then performs trusted planning
and selected candidate qualification. Candidate jobs retain read-only repository permissions and do
not enable dependency caching. GitHub also gives `workflow_run` executions read-only access to the
default branch cache scope, preventing candidate code from creating or overwriting default-branch
cache entries.

The `trusted-qualification` GitHub environment is reserved for the privileged finalizer. The
dedicated qualification App private key must be stored only as the environment secret
`NUTRITION_QUALIFICATION_APP_PRIVATE_KEY`. The environment variable
`NUTRITION_QUALIFICATION_APP_CLIENT_ID` identifies the App client, and
`NUTRITION_QUALIFICATION_APP_INTEGRATION_ID` records the reviewed App integration ID. Candidate
jobs must not reference this environment or any of those credentials.

The executor finalizer re-fetches the exact authorization comment, rebuilds the qualification plan
using trusted controller code bound to the triggering `main` SHA, requires the same plan digest
observed by the initial trusted planner, binds selected GitHub job results, and only then mints an
installation token. The token is requested with Checks write permission and is used only to create
the exact-SHA `Main qualification` check. Candidate code is never executed in the finalizer and
never receives the qualification App credential.

P3 tested the original contract deterministically. No private key, environment, live workflow
dispatch, ruleset, or protected-main mutation was required during that bootstrap. GH-165-P4 then
performed the live provisioning and pilot.

GH-171-P1 is itself a bounded security bootstrap. Because a new `workflow_run` workflow cannot
participate until that workflow file exists on the default branch, P1 is qualified through the
pre-GH-171 dispatch workflow with authorization restricted to workflow/documentation files and the
repository profile. The bootstrap candidate cannot modify the scripts executed by that profile.
After P1 integration, subsequent candidate execution uses the cache-safe `workflow_run` executor.

### GH-165-P4 live protected pilot and cutover

GH-165-P4 is the first live task that uses the trusted controller rather than a Task Capsule.
Authority-sensitive controller commands run from a clean, synchronized `main` checkout. Candidate
worktrees are untrusted inputs supplied with `--candidate-root`; they never supply their own
authorization, workflow authority, or qualification profile.

The first protected-main pilot must prove the complete trust boundary before the ruleset becomes
normal repository governance:

1. Provision a dedicated GitHub App installed only on this repository. Its repository permission
   surface is Checks write plus GitHub's implicit Metadata read. Store its private key only in the
   `trusted-qualification` environment secret `NUTRITION_QUALIFICATION_APP_PRIVATE_KEY`; record the
   App client ID and reviewed App integration ID in the corresponding environment variables.
2. Run `./scripts/task prepare ISSUE` with explicit allowed paths, forbidden paths, profiles,
   revision, exact `origin/main` base, and a fresh nonce; then run `./scripts/task authorize ISSUE`
   so the exact canonical authorization becomes a trusted-author GitHub Issue comment outside
   candidate history.
3. Build the candidate only from the authorized base and scope. Unexpected or forbidden paths,
   edited/ambiguous authorization, stale base authority, or unsupported profiles must fail closed.
4. From synchronized `main`, run `./scripts/task qualify ISSUE --candidate-root PATH`. Qualification
   may publish only the exact candidate SHA to its temporary candidate ref, must dispatch
   `.github/workflows/trusted-qualification.yml` explicitly from `main`, and must require the
   dedicated App's successful exact-SHA `Main qualification` check before removing the temporary
   ref.
5. Demonstrate the negative trust cases before ruleset activation: forged, edited, or ambiguous
   authorization is rejected; an out-of-scope candidate is rejected; a same-named check from an
   integration other than the configured dedicated App is not accepted as qualification; and
   stale or mismatched SHA/check identity is rejected.
6. Build and validate the `main` governance plan with `scripts/main-governance.py` using the reviewed
   dedicated-App integration ID. The planned policy must require `Main qualification` from that App,
   use the approved loose required-status semantics, prohibit deletion and non-fast-forward updates,
   and contain no routine bypass actor.
7. Activate the `main` ruleset only after the live qualification and negative trust proofs pass.
   Then use a disposable unqualified commit to prove GitHub rejects an ordinary direct update to
   `main`; the failed probe must not change remote `main`.
8. Record independent verification explicitly with `./scripts/task verify` and independent review
   explicitly with `./scripts/task review`. Tests and successful qualification do not infer either
   decision.
9. After explicit human-owner approval, run
   `./scripts/task integrate ISSUE --candidate-root PATH --human-owner-authorized`. Integration
   re-fetches external authority, requires the exact qualified SHA, successful explicit verification,
   Approved review, the current dedicated-App `Main qualification`, and then attempts only the exact
   protected update.
10. Confirm remote `main`, ruleset identity, issue disposition, temporary-ref cleanup, and local
    worktree cleanup. Any contradiction or unsupported GitHub behavior remains a stop condition
    rather than a reason to weaken the governance contract.

After the GH-165-P4 pilot is successfully integrated and accepted, this controller sequence is the
default workflow for new tasks. GH-171 changes the internal GitHub Actions transport from a
single dispatch execution to the dispatch-handoff plus `workflow_run` executor described above;
the operator-facing controller commands remain unchanged:

1. `./scripts/task prepare ISSUE ...`
2. `./scripts/task authorize ISSUE`
3. bounded candidate implementation
4. `./scripts/task qualify ISSUE --candidate-root PATH`
5. explicit `./scripts/task verify ISSUE ...`
6. explicit `./scripts/task review ISSUE ...`
7. explicit human-owner authorization followed by
   `./scripts/task integrate ISSUE --candidate-root PATH --human-owner-authorized`

`Main qualification` is valid only when its exact SHA, name, conclusion, authorization identity,
and producing App match the controller's trusted configuration.
`NUTRITION_QUALIFICATION_APP_INTEGRATION_ID` must identify the dedicated qualification App; the
generic GitHub Actions integration ID 15368 is never an acceptable substitute.
