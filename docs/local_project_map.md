# Nutrition local project map

## Selected instructions

This is the sole project-root local execution map. The selected and adopted RI instruction set for
future task intake is pinned at `685a2584a38cbc23286eda9c11a0404835059773`: controllers use the complete
[daily issue procedure](../engineering/workflow/shared/start-an-issue.md) and
[setup guidance](../engineering/workflow/shared/new-project-setup.md); workers use the selected
[worker role index](../engineering/workflow/shared/worker-instructions.md#role-index) and assigned
section. The [Shared worker rules](../engineering/workflow/shared/worker-instructions.md#shared-worker-rules)
and role sections govern worker inputs, scope and return duties. Preserve each active attempt's
selected instruction inputs through acceptance. A future-intake pin does not repin an active or
historical attempt.

The adopted [SOURCE record](../engineering/workflow/shared/SOURCE.md) is authoritative for upstream
bytes, local transformations/relocations, kickoff-folder identities and compatible runtime. The selected
[workflow tools contract](../engineering/workflow/shared/workflow-tools.md) documents optional helpers and
consumer-owned command evidence. Pins
identify selected inputs; they do not grant permission or create a receipt or approval mechanism.
The [adoption/replacement guide](../engineering/workflow/shared/capsule-controller-workflow.md#replace-an-entangled-adoption)
applies only to owner-authorized setup or replacement, not ordinary issue intake.

## Runtime

### Selected navigation producer

RI supplies source navigation and comparison support; it grants no edit, qualification,
review or approval authority. Normal capsule preparation follows the selected
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

Use the existing `./scripts/ri query` route for applicable normal capsule preparation under that
rule, retaining its source-bound packet and raw-output references in the task. Elsewhere it remains
optional when useful; use the guide's exact-source selection and evidence rules for arguments and
output. Required-operation inability needs the selected owner disposition before dependent dispatch;
direct inspection supplements required operation evidence. Documentation-only maintenance needs no parse.


### Optional source tools

Optional helper source revision: `e0b82f52cdd728b4ef80986a3541fc8f1d07486a`

Optional section-reader and adoption helpers are separate from producer/runtime `20a5039` and are
selected from the authenticated RI checkout `/Users/mipoo/.codex/.chatgpt-projects/g-p-6a4ec47ceae88191bed1aad746811fd5/ri-source-bindings/e0b82f52cdd728b4ef80986a3541fc8f1d07486a` at
revision `e0b82f52cdd728b4ef80986a3541fc8f1d07486a`. Before use, confirm that exact HEAD and a clean
worktree, then authenticate imports with the existing
`/Users/mipoo/Projects/Repository Intelligence/.venv/bin/python` (Python 3.14.8), `PYTHONPATH=src`,
and module source paths. The compatible installed helper dependencies are tree-sitter 0.25.1 and
tree-sitter-markdown 0.5.1. Do not install, upgrade, substitute the producer environment, or infer
host skill discovery/import registration from local module invocation.

Optional output-cleanup helper revision: `949b838809bcddb01e2cbe161faed6f6f1f705fe`

The separate controller closeout helper is selected only by explicit
`task output-closeout ... --shared-helper`. Its authenticated output-cleanup checkout
`/Users/mipoo/.codex/.chatgpt-projects/g-p-6a4ec47ceae88191bed1aad746811fd5/ri-source-bindings/949b838809bcddb01e2cbe161faed6f6f1f705fe`
must remain at the exact clean revision above. Authenticate the complete selected
import closure before use: `output_cleanup.py` SHA-256:
`500f09b11db44fea5f8a0ffeafeb922c23138872290281507d9422df93d7f0b7`;
`worker_execution.py` SHA-256:
`254fc4ece0c4b5732378903f9941c9d087fb2d636db9208988a813e9f7000676`;
`adapter_conformance.py` SHA-256:
`663d62abf07888d6e6c1ce7fcea89bf2a5ecaecb794eb61cb476fc200c024da3`;
`adoption.py` SHA-256:
`4d642a3ab03537e398e4aa4506acafc809b921c084cd848a30968a0147a92f98`.
The helper runs in an isolated subprocess, not through a previously cached import.
A missing, stale or substituted selected source refuses before action. The public
consumer-only mode is the default and does not read this optional binding; public
runner and native creation paths never import it. Keep this binding separate from
the active e0b82 worker-helper selection and the 20a5039 producer/runtime.

From that exact RI root, use `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src
"/Users/mipoo/Projects/Repository Intelligence/.venv/bin/python" -m
repository_intelligence.section_reader --help` or
`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src
"/Users/mipoo/Projects/Repository Intelligence/.venv/bin/python" -m repository_intelligence.adoption --help`; request execution is
`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src
"/Users/mipoo/Projects/Repository Intelligence/.venv/bin/python" -m repository_intelligence.section_reader --request
/absolute/path/selection.json` and
`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src
"/Users/mipoo/Projects/Repository Intelligence/.venv/bin/python" -m repository_intelligence.adoption --request
/absolute/path/inventory.json --mode preview|verify|apply`. Supply authenticated exact-source requests
and retain results in the existing task evidence location. Apply only under existing task authority,
after complete inventory validation and preview inspection. Incomplete reads, preview differences,
unavailable filesystem capabilities and refusals remain explicit; they do not authorize substitution
or dependency installation.

These revision-specific standalone checkouts are retained exact source bindings: never switch
or repoint them; provision a new revision directory under explicit task authority when needed.
Their tracked bytes are authenticated at use, not protected by filesystem immutability. The shared
RI development checkout may advance without changing either source. Controller provisioning is
separate from wrapper execution; no loader installs or updates sources. Existing helper requests
keep their original bound source; only new preparation selects the current map.

Nutrition has not selected automatic runner-owned inventory export, generation wiring or
automatic helper/runtime provisioning.
The existing authored-input/TOOLS inventory remains explicit; shared source adoption and
fixtures do not prove normal-route consumer integration. Helper source selection remains
separate from future instruction intake; preparation reads its explicit pin above.

Optional worker-execution linkage is discoverable from that same selected source with
`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src
"/Users/mipoo/Projects/Repository Intelligence/.venv/bin/python" -m repository_intelligence.worker_execution --help`.
Its [binding contract](../engineering/workflow/shared/workflow-tools.md#prepared-worker-execution-linkage)
is the authority for required consumer inputs. Nutrition's optional
[`scripts/worker-execution`](../scripts/worker-execution) binding is selected only when named in an
authorized handoff; its [consumer contract](operations/testing.md#prepared-worker-execution-binding)
defines disposable detached capture, the existing authored runner and terminal evidence mapping.
The handoff supplies the frozen tool location, exact request, allowed inputs/edits, capture grant,
evidence location and return destination. Workers use the assigned wrapper's `run` command after
controller preparation. Ordinary supported routes remain available for unselected assignments.
Resource copies, generated readiness and helper availability grant no authority. The controller
retains publication, qualification, independent review, approval, integration and installed closeout.

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

The owner sets product intent, accepted risk and integration permission. The controller
authenticates the live external Nutrition task authorization and the current task/checkpoint
before dependent work; candidate text, a task file or a passing check cannot create that external
task authorization. The controller alone owns Git and task-stage decisions. Preserve unrelated
edits and historical attempt state. A task
branch or other action requires its current explicit grant; this map is not blanket Git, issue
or settings permission.

Direct Work controller maintenance: permitted

GitHub connector access is separate from task authority. Use `@GitHub` when supported or another
permitted GitHub route. An owner may explicitly select the [reusable task grant](../engineering/workflow/shared/new-project-setup.md#access-and-task-authority)
for named issues; authenticate its applicability and retain the selection in the existing external
checkpoint. Loading a skill or this map supplies no grant. Existing Nutrition owner-bound task
authorization and protected procedures still govern publication, qualification, review and integration;
no additional host/account/security permissions or cross-chat disclosure are implied.

Use the selected [daily procedure](../engineering/workflow/shared/start-an-issue.md) and
[worker role index](../engineering/workflow/shared/worker-instructions.md#role-index)
for execution and role duties.
The selected shared handoff message boundary governs all controller/dispatcher exchanges;
qualification, review, integration, closeout and queue progress stay in controller records.

Select eligibility and the brief handoff under the
[canonical maintenance rule](../engineering/workflow/shared/start-an-issue.md#optional-maintenance-route).
Direct Work controller maintenance is available only
while the exact permission line above remains present once in this section and current external
authority and live checkpoint are authenticated. A direct selection records `Requested route:
maintenance` and `Implementation execution: direct Work controller` in that task record, plus the
actual author in the existing handoff or operational record. Execution duties and independent review follow that same canonical maintenance rule.
This map gives no additional task, host, Git, issue or settings authority.

The project-scoped Codex kickoff folders are `.agents/skills/ri-work-kickoff/` and
`.agents/skills/ri-codex-dispatcher-kickoff/`. Their presence does not prove fresh Codex discovery or
register a Work skill. Verify each host through its supported selector/import route; use direct
document-based kickoff when Work registration is unavailable or unverified. Each folder's selected
project-procedure locator links the optional [workflow tools contract](../engineering/workflow/shared/workflow-tools.md);
the linked modules remain optional source tools and are not host skills.

The selected role settings are owner-authorized requests:

| Role | Environment | Model / effort |
| --- | --- | --- |
| Controller, capsule builder and independent reviewer | Work | `gpt-6.1-sol` / `low` |
| Implementor | Codex | `gpt-6-luna` / `max` |

The table records owner-selected requested settings. Direct Work controller implementation continues
with the existing controller settings; it neither creates an implementor launch nor transfers
implementor settings to the controller. Dispatch options establish a request, not a worker launch or
effective settings. Retain the already owner-confirmed selected Work controller chat without asking
again for that selection. It establishes selected Work configuration, not external Nutrition task
authority or provider-effective telemetry. Preserve the
distinction between requested settings, launch evidence, host-confirmed settings and measured
telemetry in the existing external checkpoint. When effective telemetry is unavailable, record it as
unverified. Do not
infer mode, model or effort from tools, selector, app name, backing metadata or another worker's
confirmation.

Nutrition selects the [native Work policy](../engineering/workflow/shared/new-project-setup.md#accepted-worker-launch-routes)
for builders and reviewers: `collaboration.spawn_agent` is accepted when requested with the
configured model and effort. Policy acceptance does not establish measured execution. Actual launch
failure, confirmed mismatch or substitution, or an unavailable capability required by the
authenticated task goes back to the controller; no fallback is selected here. An owner-authorized
cross-host assignment uses its authenticated messaging and result-recovery route, with route identity
and delivery state retained in the existing operational record. Work-to-Codex implementor results
return through the assigned dispatcher to the Work controller. Do not publish private conversation
identifiers.

The selected [serial assignments](../engineering/workflow/shared/start-an-issue.md#execute-serially),
[waiting/recovery](../engineering/workflow/shared/start-an-issue.md#wait-recover-and-resume) and
[evidence rules](../engineering/workflow/shared/start-an-issue.md#evidence-eligibility-and-corrections)
own shared execution. The [worker role index](../engineering/workflow/shared/worker-instructions.md#role-index),
including the [assigned dispatcher](../engineering/workflow/shared/worker-instructions.md#codex-dispatcher),
owns role duties. Nutrition keeps owner authority, actor/model requests, permissions, profile
floors, secret controls and protected approval/integration boundaries here and at local owners.

### Role-specific local inputs

The selected [ownership and handoff contract](../engineering/workflow/shared/new-project-setup.md#instruction-ownership-and-handoffs)
owns the complete generic role-input set and receiver duties. This table selects local inputs;
it does not require workers to read controller setup or every navigation link. All roles retain
host-supplied AGENTS; apply its domain sections when relevant. Read selected sections in full,
following directed required links; a heading anchor does not itself bound a tool read.

| Role | Local map sections supplied with its task | Additional local owners when applicable |
| --- | --- | --- |
| Controller | Complete map; complete selected daily procedure and live issue/required decisions | Standards and commands needed for the task; setup only for a changed binding/adoption; actual checkpoint/assignment for recovery |
| Capsule builder | Selected instructions, [Selected navigation producer](#selected-navigation-producer) for applicable navigation, Nutrition permissions and routing, Standards and checks, Storage and recovery | AGENTS/domain contracts, source/callers/tests and task-selected proof prerequisites; shared capsule format/source-preparation rules |
| Implementor | Selected instructions, Nutrition permissions and routing; task-selected runtime/tool and command sections | Accepted complete task/source/standards; local session Actor and timing; product implementation onboarding below when applicable |
| Independent reviewer | Selected instructions, Nutrition permissions and routing, Standards and checks; task-selected runtime/tool sections | Original requirements/task/full diff/evidence; local session Actor and timing; relevant domain and acceptance owners |
| Dispatcher | Selected instructions, Nutrition permissions and routing; Storage and recovery's actual supplied assignment binding | Its kickoff locator/Shared and Dispatcher, complete authorized handoff; command/runtime sections only when used to authenticate its own route, no product/controller intake |

Local product orientation remains in [onboarding](project/onboarding.md#before-any-implementation)
for product implementation; schema/migrations and nutrient semantics remain in AGENTS,
[project invariants](project/invariants.md), [development](project/development-guide.md) and the
[RI domain map](../engineering/tooling/RI.md#nutrition-authority-map). Local database replacement
safety remains in [backup operations](features/ocr-search-and-offline.md#local-backup-and-restore); native/iOS and protected
qualification stay in the testing guide below. These are task-dependent owners, not default
instructions to load every document for tooling-only work. Normal/correction/replacement handoffs
use actual accessible selected outputs plus settled decisions; no automatic inventory exporter is
selected and no generic manual inventory or new handoff schema is required.

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

Before implementation dispatch or direct implementation, the controller runs the
read-only public record check:
`./scripts/task validate-record --task-record engineering/tasks/TASK-ID.md --route normal`
for the six-heading capsule, or explicitly `--route maintenance` for a brief maintenance handoff.
For direct Work controller maintenance, include the selected repository root with the existing
global option, for example `./scripts/task --repo-root "$PWD" validate-record --task-record
engineering/tasks/TASK-ID.md --route maintenance`. A direct selection must contain the two literal
selection fields above and the selected project's map must contain the exact affirmative permission
line in this section. Normal and delegated-maintenance checks retain their shape-only behavior. The
command reports record and map fields separately; the controller still authenticates live authority,
semantic eligibility, actual author, reviewer independence and active assignments. A passing record
does not authorize execution. The controller then uses the actual `./scripts/task` interfaces:
`prepare ISSUE` with the explicit task ID, base, paths and profiles; `authorize ISSUE`;
`qualify ISSUE --candidate-root PATH`;
`verify ISSUE` with candidate SHA, actor, decision and evidence; `review ISSUE` with candidate
SHA, actor, decision and summary; and
`rework ISSUE --candidate-root PATH --expected-candidate-sha C1 --candidate-sha C2` after a
standard `REVIEWED_CHANGES_REQUESTED`; and
`integrate ISSUE --candidate-root PATH --human-owner-authorized`. The executable controller owns their exact argument validation and
must reauthenticate live owner authority at dependent gates. Correction and interrupted-operation
recovery follow [Nutrition state, concurrency and recovery](../engineering/workflow/AUTHORITY.md#state-concurrency-and-recovery).

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
[shared format](../engineering/workflow/shared/start-an-issue.md#capsule-format) and
[local template](../engineering/tasks/TEMPLATE.md#check-attempts), or the selected maintenance handoff.
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

For task-owned generated-output cleanup, use the public `task output-closeout ISSUE
--execution-record PATH --durable-evidence PATH` dry run after current checkpoint
verification. Actual quarantine requires `--execute --human-owner-authorized` under
the explicit owner grant and is recorded as recoverable output closeout; it is distinct
from legacy `finalize-cleanup` C/R/T recovery. Public cleanup defaults to
`consumer-only`; opt into the separately authenticated RI949 helper only with
`--shared-helper`. The selected helper source is documented above and must refuse on
missing, stale or substituted inputs without falling back.
