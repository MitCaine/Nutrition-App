# Testing guide

> **Document role: Operational Reference.**

The test strategy follows architectural claims. Fast unit tests explain behavior; Jest proves mobile
models, local-runtime parity, and rendered flows; native/file-backed SQLite qualification proves
local storage/lifecycle claims; host-executable Swift regression harnesses prove bounded Apple
Vision/image-quality behavior; PostgreSQL suites prove remote locking, role, migration, and
concurrency claims; MinIO suites prove
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

The canonical substantive backend baseline is defined by `scripts/lib/backend_qualification.py`;
`scripts/run-backend-baseline.sh` preserves the ordinary local interface, including
`--print-marker-expression` and explicit arguments such as `--collect-only -q`. It excludes the
registered PostgreSQL concurrency, Phase 5C T0 performance, Phase 5C4 control-PostgreSQL, MinIO,
and Docker-integration marker families. Those suites remain explicit qualification and must be
selected directly when their claims are in scope. Do not replace the ordinary runner with bare
`pytest`, because infrastructure availability must not change which tests belong to the ordinary
regression baseline.

The default test configuration selects test deployment mode and in-memory SQLite where a test does
not explicitly require PostgreSQL. This is appropriate for calculations, DRI/reference data,
parser, schema, API, and most service behavior. It is not evidence for PostgreSQL locking or
privilege claims.

The reproducible Python 3.14 development and CI environment is pinned in
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

### Nested Recipe selected amounts

Run `npm test -- --runInBand --runTestsByPath __tests__/nestedRecipeSelectedAmount.test.ts __tests__/localRecipePublicationRuntime.test.ts`
from `apps/mobile`. The selected-amount regression renders the ordinary ingredient picker and
Recipe form, submits the generated serving ID to the actual local runtime, and compares generated
100 g, default serving and gram entries at nontrivial quantities. Nested nutrition resolves the
selected compatibility serving against immutable publication amount semantics; generated 100 g
uses its gram basis, while a published default `1 serving` retains its per-serving basis. Ordinary Food
conversion remains unchanged.

The regression uses native Node SQLite with a temporary file and verifies publication amounts,
nutrients, Daily Logs and nutrient snapshots across reopen and mutable projection tampering. This
is real file-backed SQL evidence, with an Expo database interface adapter; it does not establish
`expo-sqlite` lifecycle or physical-device behavior. Immutable accepted history is never rewritten
by a recalculation. Existing publication/Log regression suites remain required alongside it.

### Target weight editing and storage

The GH-272 model and rendered settings regressions exercise canonical kilogram values at 30.000,
300.000, 60.000, and 70.123 kg while the form displays one-decimal pounds. The rendered test
presses the actual Save action, stores the submitted update in its test persistence seam, remounts
from that saved configuration, and checks a second exact payload. It also covers edited valid,
invalid, cleared, and edit-away-and-back pounds text. This proves the modeled application flow;
it does not prove native SQLite restart or physical-device behavior.

Run these suites from apps/mobile:

    npm test -- --runInBand --runTestsByPath __tests__/targetModel.test.ts __tests__/targetSettingsScreen.test.ts

Native/file-backed SQLite qualification is required for claims about `expo-sqlite` lifecycle,
migrations, transaction visibility, termination, backup/restore activation, and restart semantics
that mocks cannot establish. Native Apple Vision geometry/recognition/image-quality regressions live under
`modules/nutrition-ocr/ios-tests`. They are standalone host-executable Swift programs, not XCTest
cases or an iOS Simulator test target. Continuous native qualification runs those programs on the
macOS host and separately proves that the real generated application and `NutritionOcr` pod compile
for an iOS Simulator.


## Main qualification profiles

Task Capsules may select machine-executable qualification profiles through
`specialized_qualification` entries using `profile:lowercase-name`. The
repository registry owns five profiles:

| Profile | Required GitHub check |
| --- | --- |
| `repository` | `Repository validation` |
| `backend` | `Backend baseline` |
| `mobile` | `Mobile baseline` |
| `postgresql` | `Backend PostgreSQL 16 contracts` |
| `ios-native` | `iOS native qualification` |

Ordinary CI and dedicated-App trusted qualification have separate jobs. The trusted
planner selects only authorized profiles; its finalizer aggregates those job results into
an exact-candidate-SHA dedicated-App `Main qualification` check. Ordinary CI remains a
separate regression signal. Shared substantive commands prevent drift without running
another copy of a suite within a selected job.

### Authored command review attempts

For a bounded review request whose checks are selected by the task, run the existing consumer
runner from the repository root:

```bash
./scripts/run-review.sh --commands /absolute/path/request.json --attempt ISSUE-attempt-1
```

Authored mode requires both options and does not combine with `--profile`, `--label`, or
`--no-package`. The JSON request binds a full expected HEAD, exact repository root, unique attempt
ID and ordered command steps. Each step has a unique ID, direct `argv` array, repository-relative
`cwd`, selected nonsecret environment overrides, earlier-step prerequisites, and a mandatory or
advisory designation. The runner does not interpret arguments through a shell or invent missing
prerequisites. For example:

```json
{
  "schema_version": 1,
  "repository": "/absolute/path/to/Nutrition App",
  "expected_head": "0123456789abcdef0123456789abcdef01234567",
  "attempt": "ISSUE-attempt-1",
  "steps": [
    {
      "id": "docs",
      "argv": ["/absolute/path/to/python", "scripts/validate-docs.py"],
      "cwd": ".",
      "env": {},
      "prerequisites": [],
      "designation": "mandatory"
    }
  ]
}
```

The output root is `NUTRITION_REVIEW_OUTPUT_DIR` when explicitly set, otherwise the runner's
documented sibling output directory. It must resolve outside and not alias the source repository.
`runs/<attempt>` is created exclusively; a repeated ID preserves existing evidence and exits before
running commands. The attempt retains the original request/hash, ordered arguments and selected
environment, effective child inputs, outcomes and exit codes, complete stdout/stderr logs and hashes,
existing runner logs, failures, warnings, and explicit incomplete/blocked states. Credential-like
environment names and values are rejected from retained request inputs.

If a command cannot launch (for example, it is missing or not executable), its child and command
exit codes remain null because no process ran. The executor returns a nonzero status to the shell
runner, which records a failed check and retains a failure-log copy with the launch diagnostic.
Dependent steps stay blocked; a later independent success cannot clear a mandatory launch failure.

Before and after observations bind HEAD, branch, index tree and entries, assume-unchanged and
skip-worktree flags, tracked and nonignored untracked file bytes/modes/symlinks, repository and
parent-directory modes, and Git status. Ignored runtime files are not inventoried. Any source drift
makes the attempt ineligible and blocks its bundle and PASS. Missing results or interruption retain
an incomplete attempt without a terminal pass marker. Failed prerequisites are blocked; later success
does not clear prior failure. Authored task-mandatory documentation checks fail the mandatory gate
even though documentation is advisory in an existing profile. The existing profile invocations and
their failure semantics remain unchanged. This runner records command evidence; it does not qualify,
verify, independently review, approve or integrate a candidate, and it does not run session-end unless
that command is explicitly authored.

| Dedicated-App profile | Covered checks |
| --- | --- |
| `repository` | Documentation, shell syntax, and the fixed trusted fast controller suite when tooling paths select it |
| `backend` | Ruff, canonical ordinary pytest marker exclusion, and portable repository session audit |
| `postgresql` | PostgreSQL16 version, the fixed eleven runtime/completed Epic4 contract files, and isolated schema/database cleanup assertions |
| `mobile` | Locked npm install, Expo configuration/compatibility/health, TypeScript and Jest |
| `ios-native` | Existing selected iOS native qualification route; separate physical/device attestations remain explicit |

Backend and PostgreSQL jobs each execute their selected pytest suite once. Ordinary CI
loads `scripts/lib/backend_qualification.py` from its checked-out SHA. Trusted jobs load
that helper from the authenticated dispatch workflow head's separate `trusted` checkout,
select its Python pin and locked dependencies, and pass the exact candidate root and SHA.
Candidate gate scripts do not supply the trusted definitions. Trusted backend/PostgreSQL
jobs install only trusted locked packages; they do not execute candidate editable-build
hooks. Explicit backend import path preserves candidate application/test imports. Candidate
pytest and conftest code execute as a separately provisioned nonroot `nutrition-candidate`
account, launched by the trusted helper through fixed sudo/env commands with an allowlisted
environment. The helper validates the account differs from its own UID. Candidate code
cannot write the runner-owned trusted checkout, installed packages or qualification
artifacts. The helper sets only the child HOME to its passwd home and child TMPDIR to
`NUTRITION_BACKEND_TEST_TMPDIR=/home/nutrition-candidate/tmp`, validating account
ownership and mode0700. Runner TMPDIR remains unchanged for trusted setup and installs. Fixed Git safe-directory configuration permits read-only exact-SHA validation
across checkout ownership. The ordinary CI helper interface remains unchanged.

The two ordinary backend jobs use full-history checkout with
`persist-credentials: false`. Checkout removes its authentication configuration before
the shared helper authenticates source. Checkout's disabled sparse metadata is removed
only when its worktree extension is absent and its worktree config contains exactly the
three known sparse flags set to false. Enabled, unknown or externally included worktree
configuration fails closed. Persisted external Git `include`/`includeIf`
configuration is unsupported and remains rejected before source object reads; do not
relax that boundary to accommodate checkout credentials.

Isolated Python execution, explicit selection, cleared pytest addopts and disabled plugin
auto-loading prevent selector/config/environment overrides while retaining required backend
conftest fixtures. The repository tooling job provisions the same account for actual UID
negative/positive write-denial regression proof. Actual candidate Python remains untrusted;
separate-account execution protects trusted files rather than granting that Python approval
or privilege. These guarantees rely on disposable Ubuntu jobs, distinct UIDs, runner/root
ownership of trusted runtime/source/artifacts, and the candidate account having no sudo or
other escalation grants. Required UID proof fails closed when that host boundary is absent.

The PostgreSQL helper owns the fixed eleven-file selection, PostgreSQL16 assertion and
nine isolated schema/two database prefix families. Cleanup asserts absence, without
removing residual objects. Both workflows run cleanup with `always()` after successful
dependency installation, including when the selected suite fails; missing infrastructure
or residual objects fail the job. Baseline exclusion still leaves performance, control
PostgreSQL, MinIO and Docker integration opt-in; the PostgreSQL profile does not claim
all marked PostgreSQL or infrastructure suites executed.

The original trusted-gate introduction specified separately authorized exact-SHA diagnostic
canaries against the installed workflow before terminal issue closeout. This is historical
gate-installation scope, not a recurring RI adoption requirement. The current lightweight
adoption preserves the already installed workflow/backend helper and follows ordinary
required candidate qualification plus installed routing verification; it adds no diagnostic
project. A negative
baseline candidate includes a deliberately failing ordinary test and hostile candidate
helper/pytest addopts: installed trusted selection must execute and fail that test. A
negative PostgreSQL candidate leaves a selected-family residual schema after a passing
contract test: installed cleanup must fail. Separate clean positive controls must execute
and pass. Each probe uses explicit diagnostic compatibility authority based at installed
C, selected profiles, retained source refs and dedicated-App job/check evidence; probes
are never integrated. Pre-install Q(C) cannot replace these installed-gate observations.
Fresh GitHub Actions checkouts can omit terminal capsule recovery commits retained
only in local controller refs. The two CI workflows explicitly pass
`--portable-recovery` to the session audit; the default command remains strict
even if it inherits CI environment variables. Portable mode validates HISTORY
structure and all available
recovery objects, and reports unavailable objects as explicit warnings. It does
not claim to verify the missing capsule bytes or SHA-256. Local controller and
operator validation continue to use strict mode, which requires every recorded
recovery commit, path, identity, and digest to resolve before closeout. Do not
publish local-only or private recovery refs to make portable CI pass.
Until the trusted workflow definition on `main` contains the explicit argument,
`session-end.sh` recognizes only this repository's two named Linux GitHub Actions
workflows with a matching workspace and no caller arguments. That transition
path does not apply to an ordinary local audit or the controller's direct
capsule validation.
Select profiles from the changed runtime authority and concrete path impact.
The [combined pilot record](../../engineering/workflow/PILOT_2026-09-26.md)
distinguishes path-trigger tests and pilot App checks from actual native,
local/file-backed SQLite and remote PostgreSQL proof. A repository or mobile PASS
does not imply those specialist results; configuration and migration edits need
their own affected-contract review and selected opt-in checks.

Before building a qualification plan, the trusted controller enforces a path floor:
`apps/backend/` requires `backend`, `apps/mobile/` requires `mobile`, and PostgreSQL
migrations/configuration plus backend database, ORM model, repository, operator
authority paths, and `apps/backend/tests/*_postgres.py` require `postgresql`. The
existing iOS-native triggers remain additive, so `apps/mobile/app.json` requires
both `mobile` and `ios-native`. These rules match complete path components. The
controller checks observed changes and exact authorized paths or concrete scoped
subtrees, including when a planning commit changes only its capsule. A broad
`apps/backend/**` authorization requires `backend`; it does not imply `postgresql`
unless the concrete scope names a PostgreSQL authority subtree or the changed paths
enter one. The controller rejects an owner authorization that omits a required
profile; it never edits the selected profile list to make the plan pass.

If the external owner authorization is too narrow, stop before dispatch. The owner
must issue a new authorization revision with the full profile set through
`scripts/task prepare` and `scripts/task authorize`. Rebuild the plan against that
new comment and rerun qualification for the exact planning and candidate commits.
Do not edit the old comment or rely on a local capsule profile change to supply the
missing authority.

For fresh lightweight `standard` tasks, obtain ordinary CI through a pull request
from the published task branch to `main`. Both ordinary backend jobs explicitly
check out `github.event.pull_request.head.sha || github.sha` and pass that same SHA
to every shared-helper invocation. This authenticates the task head on pull requests
and the pushed commit on pushes. Record the candidate and actual tested identities;
repository/mobile jobs retain GitHub's default pull-request merge revision, so do not
label their execution as task-head proof. Ordinary CI remains separate from the trusted
controller's exact-SHA dedicated-App qualification.

The `qualification/**` namespace belongs to retained legacy capsule qualification.
Pushing a temporary `qualification/TASK-ID/SHA-PREFIX` ref also triggers its legacy
aggregator, which requires the historical capsule contract. Fresh standard tasks
must not use that namespace solely to obtain ordinary CI or select a paused capsule
to satisfy the legacy aggregator. Unknown or unavailable profiles fail closed.

`./scripts/capsule qualify TASK-ID --evidence-dir PATH` is the retained legacy
capsule qualification interface. It cannot replace the trusted controller or supply
the dedicated-App protected-main authority by itself. It requires a clean task
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

### iOS native qualification

`ios-native` is the continuous Apple-native compilation profile. Its substantive implementation is
repository-owned by `scripts/ios-native-qualification.sh`; the GitHub workflow is intentionally a
thin macOS wrapper.

On a qualified macOS host, run:

    bash scripts/ios-native-qualification.sh \
      --evidence-dir /tmp/nutrition-ios-native-evidence \
      --runner local \
      --compilation-mode clean

The qualifier requires the repository Node pin and Xcode 26.4 or newer, creates a disposable clean
Git worktree whose path contains spaces, runs `npm ci`, regenerates iOS through clean Expo CNG,
validates `NutritionOcr` autolinking, installs CocoaPods, compiles the generated application for a
generic iOS Simulator without distribution signing, and runs the three retained standalone Swift
regression programs. Generated `ios/`, Pods, DerivedData, harness binaries, and the disposable
worktree are removed before PASS in clean mode. The simulator build records its literal argv and
uses `ENABLE_DEBUG_DYLIB=NO` with `LD_GENERATE_MAP_FILE=YES` so Xcode emits application link maps.
Because universal simulator builds may map architecture-specific linker outputs before `lipo`
creates the final app executable, the qualifier authenticates those thin maps against the final
application slices before accepting module linkage. Detailed logs and a compact `manifest.json`
remain as evidence.

Compilation reuse is not supported by the native qualifier. An explicit
`--compilation-mode incremental` request fails with
`IOS_NATIVE_INCREMENTAL_COMPILATION_UNSUPPORTED:negative-evaluation`; the removed
`--compilation-cache-dir` option is rejected. The qualifier never falls back to clean mode while
claiming a reuse run.

The historical same-source cold/warm evaluation on candidate
`591ac008e56219474ddd326c673a8e85b24f9744` was negative. Both runs took 97 seconds overall; Xcode
took 71 seconds cold and 70 seconds warm. The warm restore missed because clean regeneration
changed the generated `apps/mobile/ios/NutritionApp.xcodeproj/project.pbxproj` identity (cold
SHA-256 `d086670f42ec1e9f2b2953ae7a290de794988cbca06163d13d48a121c282ba53`, warm SHA-256
`5e9fcae69528d9e979d3fff62df9a15850ca282663d7415e04f6870744715b25`). Each retained cache was
about 3.38 GB; removing the cache took about 1.86 seconds. During those runs, generated `ios/`,
Pods, `node_modules`, the disposable worktree, and harness binaries were removed, while external
DerivedData including `BuildProducts` remained between cold and warm runs until the controller
removed the evaluation cache. The miss produced no measured total benefit. The hosted qualification
jobs remain necessary because the trusted finalizer has no accepted evidence-adoption interface.
The complete cold/warm manifests and logs remain historical evidence under
`issue-285-evidence/native-C3-incremental-cold` and `native-C3-incremental-warm`.

The application/module proof records candidate autolinking, the generated `ExpoModulesProvider`
class/import/module registration, and Pod target/source membership, built NutritionOcr
module/archive/object outputs, and NutritionOcr's presence in the final application link. The build
explicitly uses `ENABLE_DEBUG_DYLIB=NO` and `LD_GENERATE_MAP_FILE=YES`; both flags appear in the
captured invocation and exact compilation identity. Before link-map validation or generated-output
cleanup, the qualifier retains every app-scheme candidate map, the generated provider and source
membership inputs, the final application executable, and each map's direct or exact app-target thin
linker output when available. This capture also runs when `xcodebuild` fails, so diagnostics survive
cleanup.

Xcode's universal simulator build may write architecture-specific maps whose `# Path:` points to
`Objects-normal/<architecture>/Binary/<app>` before `lipo` assembles the final application. Such a
map is accepted only when its path matches that exact app-target output layout, its architecture is
present in the final app according to `lipo -archs`, and `lipo -thin` plus `cmp -s` proves that the
retained linker output is byte-identical to the extracted final-app slice. A direct map naming the
final app executable is accepted directly. Other products, similarly named binaries, and library
search paths never count as application linkage. `application-link-proof.json` records each map's
classification and object-table evidence, plus hashes and results. For thin maps it also records the
architecture, lipo extraction, and byte-comparison commands. Missing or unlinked module fixtures
fail the native stage. GitHub ordinary and trusted workflows explicitly select clean mode, matching
the qualifier's only supported compilation mode and preserving the #167 clean-generation contract.

GitHub uses the explicit `macos-26` runner authority rather than floating `macos-latest`.
Obviously native-affecting paths fail closed when a Task Capsule omits `ios-native`; this path floor
includes the mobile dependency manifests, `app.json`, repository-owned mobile plugins, Expo-module
configuration, module `ios/` sources, and the native qualification/profile workflow itself.
Documentation-only and terminal capsule/HISTORY bookkeeping do not imply native compilation.

This profile proves generated-project compilation and host Swift regressions. It does not prove
physical-iPhone signing/install, real camera/photo-library behavior, VoiceOver/manual accessibility,
physical-device OCR accuracy, or device lifecycle behavior that requires separate native/manual
qualification.


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

For OCR parser and confirmation changes, run the shared local/backend parser regressions and the
ordinary rendered review flow. The golden fixtures should distinguish comparator conflicts from
identical duplicates, retain warning and observation IDs, and check both input orders. Parser-derived
drafts should also prove that low-confidence identity or unusable required fields remain unresolved,
while exact high-confidence controls preserve the established 0.8 boundary. These focused commands
are a starting point; run the affected suites and full baselines selected for the change:

```bash
(cd apps/mobile && npm test -- --runInBand --runTestsByPath __tests__/localOcrParser.test.ts __tests__/ocrConfirmation.test.ts __tests__/nutritionConfirmationScreen.test.ts)
(cd apps/backend && "$NUTRITION_BACKEND_PYTHON" -m pytest -q --strict-markers tests/test_ocr_parser.py tests/test_ocr_parser_golden.py tests/test_ocr_parser_api.py)
```

OCR temporary camera cleanup uses the explicit `expo-file-system/legacy` API at the
selected dependency version. `ocrFilesystemBoundary.test.ts` exercises the real installed
JavaScript entrypoint with only its native bridge substituted and distinguishes the root
throwing stub. Scan/diagnostics caller tests cover completion, retake, cancellation and late
camera completion, camera versus photo-library ownership and honest cleanup failure.
These checks and native compilation do not measure physical-device file removal or cache lifetime.

Rendered Jest tests exercise screen behavior and confirmation traces; they do not prove native
compilation, physical-device capture, VoiceOver behavior, or real-camera OCR accuracy. Use the
separately selected native and device evidence for those claims.

Shared Decimal request validation is covered by `test_decimal_request_validation.py` across
Food nutrient/original/serving fields, Recipe and ingredient fields, and Daily Log create/update.
Malformed conversion, unsupported types (including booleans), and nonfinite values return
field-level schema errors (`decimal_invalid`, `decimal_type`, `decimal_not_finite`) through the
normal structured HTTP 422 boundary. Finite precision, exponent notation, blank/null semantics,
existing caller range/unit rules and storage scale remain unchanged. API regressions compare full
synthetic persisted state after each invalid request, including history and mutation receipts;
these validation-before-mutation tests do not substitute for PostgreSQL concurrency qualification.

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

The local backup Jest suites are lifecycle fixtures: they deliberately inject SQLite/file deletion
failures, no-op deletion, rename failures, replacement rollback, and retained consumed paths to
prove control flow and UI state. Cancellation is a success only when the pending file is absent;
activation first moves the pending file to a verified consumed path, so disposable consumed-path
cleanup may fail without making a later startup replay the restore. A verified consumption-boundary
failure must fail closed before local runtime opening. These fixtures do not establish native
filesystem or process-restart behavior. That claim requires retained file-backed SQLite and native
app termination/relaunch evidence with exact candidate, instrumentation, simulator, and command
identities; generated compilation or OCR host results do not substitute for it.

For OCR native changes, select the `ios-native` profile in addition to affected TypeScript OCR
tests. The profile compiles the real generated application and runs the standalone Swift programs
under `modules/nutrition-ocr/ios-tests`; those programs are not XCTest. Image-quality inspection is
intentionally best-effort; tests must preserve the contract that an unavailable/failing inspector
does not convert into a recognition failure.

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

## GH-271 Daily Log summary and create replay

The focused GH-271 regressions exercise both local and remote authorities:

```bash
cd apps/mobile
npm test -- --runInBand --runTestsByPath \
  __tests__/localDailyLogsRuntime.test.ts \
  __tests__/e2_15TransferImporter.test.ts

cd ../backend
.venv/bin/python -m pytest -q --strict-markers \
  tests/test_log_idempotency.py \
  tests/test_e4_07_daily_summary_complete.py \
  tests/test_issue_138_target_calendar_authority.py

REQUIRE_POSTGRES_TESTS=1 \
NUTRITION_TEST_POSTGRES_URL='postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app' \
.venv/bin/python -m pytest -q --strict-markers \
  tests/test_log_concurrency_postgres.py
```

The local summary tests use a temporary file with native `node:sqlite`, separate WAL reader and
writer connections, and explicit barriers around the two reads. They prove the production runtime
and coordinator behavior for bounded file-backed SQLite visibility; they do not prove physical
Expo lifecycle, app termination, or device behavior. Transfer-import coverage runs summary through
the supplied transaction handle without a nested transaction and verifies rollback when totals
qualification fails.

The ordinary backend endpoint tests verify projection and replay behavior against their configured
test database. The PostgreSQL concurrency tests assert server major version 16 and use multiple
sessions to force the former gap between Complete and snapshot reads and the create/calendar lock
wait. The summary statement includes owner/date-scoped snapshot evidence and the matching
owner/date Complete assertion. PostgreSQL execution, not an ordinary backend or SQLite result, is
the evidence for this SQL and lock behavior. The totals-only `LogService.daily_summary` remains
covered for target comparison. The retained E4-16 script complements these regressions but does not
replace them.

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

Use the public task-record validator and focused controller-tooling tests when a change affects
normal or maintenance handoff routing. The route validator checks local record shape; it does not
replace authenticated owner authorization, exact-candidate qualification, verification, or review.

| Change | Minimum affected validation |
| --- | --- |
| Task record route | Public `./scripts/task validate-record` cases for normal and explicit maintenance inputs; affected controller-tooling tests, docs checks, and session closeout. This format check is not owner authorization, qualification, or independent review. |
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
| E2 transfer contract | Backend `tests/test_e2_15_exporter.py` and `tests/test_e2_15_exporter_postgres.py` on disposable PostgreSQL 16 + mobile E2-15 tests + versioned shared-contract fixtures |
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

The accepted operator entrypoint is [local project map](../local_project_map.md).
The [authority contract](../../engineering/workflow/AUTHORITY.md) records retained
project interfaces and historical recovery contracts. The
bootstrap history below explains the trust boundary; it is not an instruction to
recreate the existing App or reactivate an already active ruleset.

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
and selected candidate qualification. The iOS candidate job restores only exact-key npm and
CocoaPods download caches into runner-temporary locations, then still runs `npm ci`, clean Expo
prebuild, autolinking, `pod install`, the simulator build, and all three Swift harnesses. It has
read-only Actions permission and never saves a cache. The ordinary iOS workflow uses the same
input-derived keys and locations and may save download caches after a successful qualification;
fork or unavailable-cache runs continue as fresh installs. Neither route caches `node_modules`,
generated `ios/`, `Pods`, `DerivedData`, compiled products, harness binaries, or worktrees. GitHub
also gives `workflow_run` executions read-only access to the default branch cache scope, preventing
candidate code from creating or overwriting default-branch cache entries.

The qualifier retains an explicit status and restored identity for each cache, plus elapsed seconds
and status for npm installation, clean prebuild/plugin checks, autolinking, Pods, Xcode build, Swift
harnesses, cleanup, and the total boundary. To measure download caching, run two fresh exact-
candidate qualifications with isolated empty npm and CocoaPods cache directories: the cold run
must record misses, and the warm run must restore the same exact keys and record hits while still
performing every substantive check. Compare the stage timings, cache restore/save operations, and
workflow overhead separately; a cache miss or unavailable cache is valid execution but does not
provide warm-run evidence. The retained baseline's compilation time remains outside this download
cache claim, and network, hosted-runner, toolchain, and cache-service variability limit any measured
gain.

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

### Guarded capsule closeout

The trusted `task finalize` command is the guarded capsule terminal transaction.
It records implementation intent before the protected update, accepts a separately
authorized and qualified direct-child HISTORY/deletion commit, verifies the reachable
full REVIEWED capsule by SHA-256, and closes the issue only after remote main is T.
An interrupted invocation is resumed with the same C, T and R; a moved main or changed
check/authorization/review stops. Capsule-only planning P ordinarily remains on its
planning ref; any publication of P to protected main has its own narrow authority and
exact dedicated-App qualification, never a bypass.

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

Use [local project map](../local_project_map.md) for the normal standard workflow.
The owner-bound task controller prepares/authorizes, runs selected qualification, records
explicit verification and independent source/diff review, then performs owner-authorized
protected integration. Attached RI SDK preflight/evidence commands are retired.
After a standard `REVIEWED_CHANGES_REQUESTED`, the supported correction route is
`./scripts/task rework ISSUE --candidate-root PATH --expected-candidate-sha C1 --candidate-sha C2`.
The controller requires C1 to match its current qualified, verified, rejected review and C2 to
be the clean candidate HEAD. It reauthenticates the same owner authorization, base, scope and
profiles, and accepts C1's qualification operation only after terminal result and candidate-ref
cleanup are reconciled. Uncertain qualification or integration state blocks the transition.
C1 proof and operation history remain archived; C2 begins without transferred checks, approval
or review and must pass fresh qualification, verification and independent review. Rework does
not create authority or convert legacy records. Before rework or qualification, the controller
validates generated archive proof and operation identities, terminal cleanup, adjacent candidate
links and retained authority/scope bindings. Archived checkpoint digests are checked by format
without reconstructing historical checkpoint contents; opaque unrelated history and failure
evidence remain intact.
Repeated calls, `STOP_REPLAN`, unsupported phases, and overlapping or unresolved
qualification/integration operations are refused without checkpoint mutation. An owner pause is
a controller hold outside checkpoint state, not a serialized phase; the controller must not
invoke rework until the owner explicitly continues. The separate fresh-authorized-attempt route
uses `prepare` with current matching owner authorization and a separately selected state
location, preserving the existing checkpoint and its consumed allowances.

Qualification recovery holds a separate issue-scoped process-held qualification ownership lock
from before operation persistence through dispatch, polling, terminal application and ref cleanup.
The lock is distinct from the short checkpoint transaction lock, so unrelated checkpoint writes
can proceed during hosted calls. The operating system releases ownership when the controller
process exits. Its lock file is stored under the canonical controller-state directory, so different
`TMPDIR` settings still address the same issue lock. Reconciliation takes the same lock; a live
holder returns `QUALIFICATION_OWNER_ACTIVE` without changing the checkpoint or candidate ref. Its
persisted binding identifies the supported local host and controller-state location. Missing, legacy,
unknown or different-domain bindings fail closed and require an explicit controller disposition.

After the interrupted process exits, run
`./scripts/task qualify-reconcile ISSUE --candidate-root PATH`. This command discovers the hosted
run for the persisted operation and never dispatches. A no matching run leaves operation and ref
evidence unchanged and returns a non-success result; a still-running run remains available for a
later reconciliation. A completed run is accepted only after exact workflow/candidate identity,
current authorization and the dedicated App's exact-candidate check are revalidated. The command
then records the terminal outcome and safely cleans up that operation's exact candidate ref.
Repeat the same command after another interruption. A missing run or released process lock alone
does not authorize a fresh qualification attempt.

`Main qualification` is valid only when its exact SHA, name, conclusion, authorization identity,
and producing App match the controller's trusted configuration.
`NUTRITION_QUALIFICATION_APP_INTEGRATION_ID` must identify the dedicated qualification App; the
generic GitHub Actions integration ID 15368 is never an acceptable substitute.

## Automatic fast controller qualification

The trusted repository profile now has a mechanical tooling floor for the scripts
component tree (including its root), engineering/tooling, .python-version and the
two trusted qualification workflows. Planned wildcard authority conservatively
selects this floor; lookalike directory prefixes do not. Existing backend, mobile,
PostgreSQL and iOS native floors still compose independently.

Trusted planning digests the tooling decision. The repository job checks out the
trusted runner separately from the exact candidate, installs accepted Python 3.14
and requirements-dev.lock (pytest 9.1.1), and executes the fixed project-control
selection in scripts/lib/tooling_qualification.py. Candidate configuration,
selectors, credentials and native opt-in environment cannot select weaker tests.
The runner uses --noconftest, an empty pytest configuration, verbose skip details
and no pytest cache. The job has read-only contents permission, no App secret, and
no dependency cache beyond the explicit read-only cache restores in the trusted iOS
job; the finalizer alone publishes the dedicated-App result.

The sixteen-file pre-dispatch diagnostic took about 39 seconds: 296 passed,
17 explicitly skipped native fixtures, and seven stale iOS composition assertions
failed. That diagnostic is not candidate proof. Expect approximately one minute
for the fast test subprocess, plus checkout and locked installation. The revision4
protected local transport rehearsal passed 302 tests and 121 subtests with 17
explicit opt-in/unsupported-host skips in 40.60 seconds; session-end additionally
passed 82 audit-tooling tests in 12.45 seconds. Original and tested source identities
remained unchanged. These are pre-freeze rehearsals, not attached remote
qualification or installed canary proof. Exact final
local and installed CI timings are retained in controller/terminal evidence.

Private RI runtime, iOS/device, PostgreSQL, MinIO,
Docker and performance opt-in oracles remain separate. Their explicit skips do
not imply those suites passed. The preceding timings and canary obligations describe
the historical trusted-gate installation, not the current lightweight RI replacement.
That replacement retains the installed gate and requires normal exact-candidate
qualification, independent review and installed routing/entrypoint verification.


Isolated backend source access authenticates exact tracked commit bytes, modes and real Git
identity before execution. A bounded no-includes parser rejects external/included, worktree
and promisor configuration before ordinary Git reads (local config: 64 KiB, 4,096 lines and
bytes per line; continued lines unsupported). Only an authenticated EACCES probe may create
a runner-owned full tracked tree beneath validated `/tmp`, bounded to 100,000 files,
512 MiB and 64 MiB per object. All ACLs and special modes are sealed before descendant
read/search grants, with root access last. Before any possible launch, a runner-private
receipt binds C/tree/inode/UID and the existing job's single launch. Success, failure,
cancellation and unknown launch state retain that read-only stage; leader exit proves no
process quiescence. Existing ephemeral job teardown owns its lifetime. Persistent-host
retained stages are never silently reused or removed: later cleanup requires their exact
owned identity and verified quiescence. Prelaunch setup failures alone remove their exact
owned stage. Original home/source permissions, child temporary state, substantive test
selection and runtime protection remain unchanged.
