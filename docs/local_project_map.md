# Nutrition local project map

## Selected instructions

The selected instruction set for future task intake is pinned at `6058b143610c1902faf1bf832227359c9fc4f5a4`.
Use the complete [daily issue procedure](../engineering/workflow/shared/start-an-issue.md)
and [SOURCE record](../engineering/workflow/shared/SOURCE.md). One author performs source-grounded
engineering and coding in a concise existing task record, followed by one fresh independent
reviewer. No capsule creator, dispatcher, separate implementor or planning-review stage is selected.
[Common and reviewer inputs](../engineering/workflow/shared/worker-instructions.md#role-index)
own review duties. Setup is conditional on a changed binding. Historical resources remain
reachable for pinned attempts; new instruction selection never repins active work.

The [workflow tools contract](../engineering/workflow/shared/workflow-tools.md) describes
independent helpers. Installed instruction hashes/declared link relocations derive from
`engineering/tooling/ri-helper-lock.json`; instruction and executable runtime revisions are separate.

## Runtime

### Selected navigation producer

RI supplies source navigation and comparison support; it grants no edit, qualification,
review or approval authority. Normal source preparation follows the selected
[task-directed source-preparation rule](../engineering/workflow/shared/start-an-issue.md#task-directed-source-preparation). The compatible producer is separately pinned in
[the RI runtime guide](../engineering/tooling/RI.md#pinned-installation-and-private-access)
and [runtime lock](../engineering/tooling/ri-lock.json): revision
`20a5039e7731eaa1303443b782caa81a383a0af1`, contracts navigation 7, inventory 16, adapter 13,
mapping v13, on macOS arm64 with Python 3.14. Do not select a newer producer or alter an accepted
runtime in place; do not substitute another historical or upstream revision.

Use the selected controller-owned external manifest at the actual path authenticated from the
active handoff or checkpoint, passed with `--runtime` and the selected Python interpreter.
Verify its installed bytes and source/runtime identities before and after a query.
The manifest path, interpreter and launcher are bindings to verify in the execution context;
they do not assert that a host is ready or that a tool is available. Use the repository's
[`scripts/ri` launcher](../scripts/ri) and its nested macOS network-denied sandbox; an outer host
denial is a reported failure, not a reason to bypass the sandbox.

Recheck readiness when a relevant source, runtime, command or environment input changes or a
capability fails. For exact-source queries, see the RI guide's
[source-selection rules](../engineering/tooling/RI.md#navigate-an-exact-source-selection) and
[comparison/evidence-reuse policy](../engineering/tooling/RI.md#comparison-and-review). Reuse
evidence only under the project's accepted equivalence policy when the source, transitive inputs
and environment remain eligible. RI locations are navigation hints; inspect the actual candidate
diff and source for acceptance.

Use the existing `./scripts/ri query` route where applicable and useful under that
rule, retaining its source-bound packet and raw-output references in the task. Elsewhere it remains
optional when useful; use the guide's exact-source selection and evidence rules for arguments and
output. A task-required operation that is unavailable needs owner disposition before dependent work;
direct inspection supplements required operation evidence. Documentation-only maintenance needs no parse.


### Optional source tools

Optional helper source revision: `8db4d56323db31f27af151c542967b4ef13a79af`

The authenticated RI checkout `/Users/mipoo/.codex/.chatgpt-projects/g-p-6a4ec47ceae88191bed1aad746811fd5/ri-source-bindings/8db4d56323db31f27af151c542967b4ef13a79af-gh422-clean` is the controller-selected clean same-revision checkout at the accepted revision above. The separately provisioned helper environment is `/Users/mipoo/.codex/.chatgpt-projects/g-p-6a4ec47ceae88191bed1aad746811fd5/ri-helper-environments/8db4d56323db31f27af151c542967b4ef13a79af-nutrition-runtime`; use its `bin/python`, never RI's development venv. The reproducible setup/verification command is `python3 scripts/setup-ri-helpers.py --source SOURCE --environment ENVIRONMENT --mode provision|verify` from the Nutrition root. The tracked `engineering/tooling/ri-helper-lock.json` binds exact source and resource identities; its `instruction_revision` selects the separately adopted 6058b14 instruction resources while `revision` retains the unchanged8db executable helper binding; upstream `pyproject.toml` owns dependency definitions. Provisioning is explicit controller work, never an automatic wrapper fallback or runtime upgrade. Keep historical e0/949 source bindings and old requests untouched.

Selected helper subprocesses authenticate exact source closure, interpreter and installed dependency identities before use. Public generation/preparation/execution/intake is supported only when its actual installed binding and acceptance proof are recorded, not by copying instructions. The completed consolidated pilot is retained in GH-422 and its external closeout evidence; later assignments still require their own authenticated execution binding and acceptance proof. The navigation producer/runtime and native guard below keep their independent selections.

Use the selected `section_reader`, `adoption`, `worker_execution` and `obligation_reconciliation` interfaces only through their authenticated source/environment bindings and the [workflow-tools contract](../engineering/workflow/shared/workflow-tools.md). Retained capsule/engineering derivation requires the declared Markdown parser stack. No manual dependency inventory, substituted parser, current-development environment or silent operation fallback is selected.

The additive accepted owning-definition path uses the same Nutrition wrapper: create the detached
workspace from the controller seed, then run `generate --request SEED --definition DEFINITION
--output GENERATED --evidence EVIDENCE`, followed by one `prepare`, the authorized `run`, and
read-only `intake` over the same generated request and `RETURN.json`. The definition owns the exact
native check request, original input identities and capsule/engineering selection; its exclusive
projection derives case selectors from those actual command IDs. Generation and every later public
operation authenticate the selected RI source and installed runtime before using the helper. The
controller's `task inspect-engineering-assignment ISSUE --request SEED` is a read-only checkpoint,
scope, profile and predecessor-sequence check before dispatch; it does not create authority or
replace substantive controller review. The completed GH-422 public pilot and installed verification remain historical proof;
current task acceptance and actual generated bindings remain task-specific.

### Optional task-output cleanup helper

Optional task-output cleanup helper revision: `949b838809bcddb01e2cbe161faed6f6f1f705fe`

The cleanup helper is separately selected from the authenticated RI checkout
`/Users/mipoo/.codex/.chatgpt-projects/g-p-6a4ec47ceae88191bed1aad746811fd5/ri-source-bindings/949b838809bcddb01e2cbe161faed6f6f1f705fe`
at that exact revision. It is used only when a controller explicitly selects
`task output-closeout --shared-helper`; authenticate the clean checkout and the
`output_cleanup` module plus its transitive source imports in an isolated process
before that operation. A missing or changed selected binding refuses that selected
operation without installation or fallback. Consumer-only closeout and ordinary
runner/native creation use Nutrition-owned `scripts/lib/task_output_cleanup.py`
and do not depend on this private checkout.

This optional selection does not repin the separately selected worker/execution helper binding,
00117 dispatch guard, 20a5039 producer/runtime, dependencies or any prepared request.
Existing attempts retain their original bindings and are not rewritten.

### Selected native dispatch decision binding

Native dispatch guard source revision: `00117a3b216b089e1e3a0a693c83efab9dcf12f0`
Native dispatch guard source checkout: `/Users/mipoo/.codex/.chatgpt-projects/g-p-6a4ec47ceae88191bed1aad746811fd5/ri-source-bindings/00117a3b216b089e1e3a0a693c83efab9dcf12f0`

For selected native Work worker launch/resumption transitions, the controller uses
[`scripts/native-dispatch`](../scripts/native-dispatch) before recording running or entering
completion wait, and consumes terminal evidence through the same decision. Its
[consumer contract](operations/testing.md#native-dispatch-transition-decisions) maps original
native call/reply and bounded state records from the existing assignment checkpoint. This separate
optional module selection does not repin the existing section/adoption/worker-execution helper
selection above or producer/runtime. Direct Work maintenance has no implementation-worker dispatch;
that nonapplicability does not exempt a later delegated review or normal worker path.
The guard does not launch, resume, wait, authenticate host/settings, grant retries or change state.
Source/module identity is checked before use; drift refuses, without installation or substitution.

## Nutrition permissions and routing

The owner sets intent, accepted risk and task/publication/integration permission. Authenticate
live issue authority, source and the actual checkpoint/assignment before dependent work. Preserve
unrelated edits, parked branches, paused queues and active instruction pins. Connector access,
a task file or passing check grants no additional Git, host/account/security or disclosure authority.
Use applicable recorded grants; request only uncovered actions.

| Actor | Requested environment | Requested model / effort |
| --- | --- | --- |
| Single engineering and coding author | Work | `gpt-6.1-sol` / `low` |
| Fresh independent reviewer | Work | `gpt-6.1-sol` / `low` |

Explicit owner overrides apply. Reuse accepted unchanged settings. Record owner-confirmed,
requested, host-confirmed and effective telemetry separately in existing external state; unknown
telemetry proves neither compliance nor mismatch. Never infer environment from tool names.
Nutrition accepts native `collaboration.spawn_agent` for fresh independent review with the selected
model/effort explicitly requested under the [native launch policy](../engineering/workflow/shared/new-project-setup.md#accepted-worker-launch-routes).
This is route acceptance, not measured execution. Actual rejection/mismatch returns to the author;
no substitute model or fabricated role is permitted. The author cannot review its own work.

Use the shared [serial phase sequence](../engineering/workflow/shared/start-an-issue.md#complete-the-phases),
[waiting/recovery](../engineering/workflow/shared/start-an-issue.md#wait-recover-and-resume),
and [evidence eligibility](../engineering/workflow/shared/start-an-issue.md#evidence-eligibility-and-corrections).
The author reads this map, the complete daily procedure, original issue and necessary local owners.
The reviewer receives the original requirements, concise task, exact full integration diff,
actual evidence, common contract and complete selected reviewer skill/locator. Product changes
also use [onboarding](project/onboarding.md#before-any-implementation), domain invariants and
task-relevant database/privacy/iOS standards. A link is not a requirement to read unrelated guides.

### Historical route compatibility

Direct Work controller maintenance: permitted

This line is retained only for explicit historical maintenance validation. Normal new work needs
no maintenance eligibility declaration, pilot waiver, separate planning handoff or role launcher.
Historical engineering assignments and native dispatch transitions retain their original bindings;
these are recovery interfaces, not extra steps in the new normal route.

## Standards and checks

Worker handoffs apply the canonical [local actor and timing rule](operations/session-contract.md#actor-and-timing)
within their selected role read scopes. Read-only result delivery is not task completion;
controller-owned acceptance checks remain required at their proper gates.

Use [AGENTS.md](../AGENTS.md), the [session contract](operations/session-contract.md#repository-session-contract),
the [testing guide](operations/testing.md#main-qualification-profiles), and Nutrition's
[authority contract](../engineering/workflow/AUTHORITY.md#current-interfaces). These current
project owners govern domain/security standards, session closeout, selected tests, task interfaces,
secret scanning, profile floors and protected acceptance.

For task-selected command evidence, use the authored mode of the existing
[`scripts/run-review.sh`](../scripts/run-review.sh):
`./scripts/run-review.sh --commands /absolute/path/request.json --attempt UNIQUE-ID`. The request
binds this repository, full expected HEAD, unique attempt, direct argv steps, repository-relative
working directories, explicit nonsecret environment overrides, earlier-step prerequisites and
mandatory/advisory designations. It uses the output root in `NUTRITION_REVIEW_OUTPUT_DIR` or the
runner default; attempts are exclusive and output must resolve outside this repository. The
[testing guide's authored-command section](operations/testing.md#authored-command-review-attempts)
contains the request shape and explains child inputs, source observations, logs/hashes and failure
eligibility. Treat a run result as command evidence only; controller acceptance, independent review,
approval and integration remain separate.

Before implementation run the read-only `./scripts/task validate-record --task-record
engineering/tasks/TASK-ID.md --route normal`. It checks readable nonempty, unambiguous Markdown;
it does not prescribe six headings or establish engineering adequacy/authority. Keep original
outcomes, exact base/scope, necessary design/context and expected proof in the existing concise record.
Historical `--route maintenance` and `--route engineering` retain their original validation.

The author uses existing `./scripts/task prepare ISSUE` with explicit task ID/base/paths/profiles,
`authorize ISSUE`, `qualify ISSUE --candidate-root PATH`, candidate-bound `verify ISSUE` and
`review ISSUE`, and authorized `integrate ISSUE --candidate-root PATH --human-owner-authorized`.
The executable controller still owns argument validation, live owner-bound authorization, locking,
profile floors and all protected decisions. In-scope rejected-candidate correction uses
`rework ISSUE --candidate-root PATH --expected-candidate-sha C1 --candidate-sha C2` under
[Nutrition recovery authority](../engineering/workflow/AUTHORITY.md#state-concurrency-and-recovery).



Qualification uses the dedicated App `4708441`'s successful exact-candidate-SHA `Main qualification`
check. Select the required profiles from the complete rename-aware changed-path
inventory and authenticated allowed scope, including old and new paths; meet every applicable
profile floor. Ordinary CI is a separate regression signal and does not qualify candidate C.
Explicit verification, independent review, owner approval and protected expected-main integration
are separate decisions. A changed C requires affected checks and independent review. The
[testing guide](operations/testing.md#test-selection-by-change) and
[session-end contract](operations/session-contract.md#session-end) define repository checks;
choose the focused set required by the task. Documentation-only work does not imply unrelated
backend/native suites or the retired adoption lifecycle. Record actual commands, source
identities, logs, failures and skips in the task's existing attempt record and selected external
evidence workspace.

## Storage and recovery

New task records live at `engineering/tasks/TASK-ID.md`; use the
[concise record guidance](../engineering/workflow/shared/start-an-issue.md#engineering-and-implementation) and
[local template](../engineering/tasks/TEMPLATE.md), or the selected maintenance handoff.
The public validator's record/map checks do not authenticate owner authority or acceptance.
Historical TOML contracts and C/R/T lineage remain at [TASK_CAPSULE](../engineering/workflow/TASK_CAPSULE.md#historical-capsule-contracts),
[STATES](../engineering/workflow/STATES.md#terminal-recording) and [HISTORY](../engineering/capsules/HISTORY.md).

Use the authenticated handoff's external evidence workspace. Default checkpoint:
`~/.nutrition-app/task-controller/issue-N.json`. Any `--state-dir` or
`NUTRITION_TASK_STATE_DIR` override must be explicitly selected and authorized;
use the actual supplied path, not an assumed default. Current state writers follow
[Nutrition's transaction/recovery contract](../engineering/workflow/AUTHORITY.md#state-concurrency-and-recovery).
Keep literal command/environment, exact source/dirty diff, all failures/stops and raw evidence
in that selected external record; private diagnostics do not belong in published source.

### Replacement-controller handoff

Use the selected [checkpoint/resume rule](../engineering/workflow/shared/start-an-issue.md#checkpoint-and-resume)
and [Nutrition recovery authority](../engineering/workflow/AUTHORITY.md#state-concurrency-and-recovery).
The outgoing handoff must identify the actual selected checkpoint file, its explicit state-dir
override and authoritative assignment/job/terminal-result recovery reference. Include exact
task/source, instruction identity and next authorized action. The documented default alone is
not recovery evidence. Missing supplied evidence is a precise gap: preserve state and recover
that reference; do not initialize another checkpoint, duplicate dispatch or clear a stop.
Keep private paths/job/chat identifiers in the external operational record, not public source.

#### Bounded recovery cases

- **Default location:** handoff explicitly supplies the existing default
  `~/.nutrition-app/task-controller/issue-N.json` and its actual assigned actor/job
  recovery reference. A replacement resolves that supplied file, verifies task,
  phase/source and assignment, and resumes reconciliation of that same assignment.
  A read-only `./scripts/task status N` reports state but does not itself authenticate
  live authority/job consumption; complete those supplied-reference checks. Do not
  call prepare or dispatch merely because the controller context changed.
- **Authorized alternate state dir:** handoff supplies the selected absolute
  checkpoint path and authorized override. Use `./scripts/task --state-dir SELECTED_DIR
  status N` (or the expressly selected `NUTRITION_TASK_STATE_DIR`) and reconcile its
  referenced assignment. A default or earlier-revision file is not a substitute.
  The bounded controlled-case copy used for verification is diagnostic only; it
  does not establish a second live authority or transfer the assignment.
- **Unavailable supplied evidence:** a missing/inaccessible selected file or
  assignment reference produces a precise recovery gap. Preserve accessible state,
  terminal evidence and valid completed work; do not infer no active work or create
  a default record. Required qualification, fresh review, protected integration
  and installed closeout remain unchanged after recovery.

The original #246/#256 capsule attempts were stopped under their original authority. Preserve
their branches, evidence, decisions and consumed allowances under [Nutrition recovery authority](../engineering/workflow/AUTHORITY.md#state-concurrency-and-recovery),
[STATES](../engineering/workflow/STATES.md), [TASK_CAPSULE](../engineering/workflow/TASK_CAPSULE.md),
and [HISTORY](../engineering/capsules/HISTORY.md). The completed fresh #246 attempt is distinct;
see its [historical task record](../engineering/tasks/GH-246-FRESH-20261005.md) and
[preserved capsule](../engineering/capsules/active/GH-246.md). Current status belongs to the live
[#246](https://github.com/MitCaine/Nutrition-App/issues/246) and
[#256](https://github.com/MitCaine/Nutrition-App/issues/256) issues, not the historical pause.
Never resume an old attempt implicitly.

## Integration and closeout

The selected [completion-record rule](../engineering/workflow/shared/start-an-issue.md#keep-completion-records-external)
owns candidate-freeze timing, historical preparation and later operational evidence.

Nutrition requires exact-candidate App qualification, explicit verification, independent review,
separate controller approval and current owner integration permission under
[AUTHORITY](../engineering/workflow/AUTHORITY.md#current-interfaces). The protected expected-main
compare-and-swap route remains mandatory. Apply the selected
[phase/installed closeout rule](../engineering/workflow/shared/start-an-issue.md#complete-the-phases)
and local [session-end contract](operations/session-contract.md#session-end) before closure/owned cleanup.
Record partial closeout when an obligation remains unresolved; never rewrite preserved attempts.

## Historical engineering selection

GH-422 retains its original engineering specification, assignments, instruction/runtime pins and
review evidence. It is not the new normal route. The retired creator, dispatcher, implementor and
planning-review resources remain reachable through [historical roles](../engineering/workflow/shared/worker-instructions.md#historical-roles).
