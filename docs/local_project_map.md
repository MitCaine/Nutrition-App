# Nutrition local project map

## Selected instructions

This is the sole project-root local execution map. The selected and adopted RI instruction set for
future task intake is pinned at `841d57571983b5b7cec0071263fad7f78d809e20`: controllers use the complete
[daily issue procedure](../engineering/workflow/shared/start-an-issue.md) and
[setup guidance](../engineering/workflow/shared/new-project-setup.md); workers use the selected
[worker role index](../engineering/workflow/shared/worker-instructions.md#role-index) and assigned
section. The [Shared worker rules](../engineering/workflow/shared/worker-instructions.md#shared-worker-rules)
and role sections govern worker inputs, scope and return duties. Preserve each active attempt's
selected instruction inputs through acceptance. A future-intake pin does not repin an active or
historical attempt.

The adopted [SOURCE record](../engineering/workflow/shared/SOURCE.md) is authoritative for upstream
bytes, local transformations/relocations, kickoff-folder identities and compatible runtime. Pins
identify selected inputs; they do not grant permission or create a receipt or approval mechanism.
The [adoption/replacement guide](../engineering/workflow/shared/capsule-controller-workflow.md#replace-an-entangled-adoption)
applies only to owner-authorized setup or replacement, not ordinary issue intake.

## Runtime

RI is optional source navigation and comparison support; it grants no edit, qualification,
review or approval authority. The compatible producer is separately pinned in
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

`./scripts/ri query` is optional when useful; use the guide's exact-source selection and evidence
rules for its arguments and output.

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

The normal route has the Work controller dispatch a capsule builder and a distinct independent
reviewer. The optional maintenance route omits the builder and planning-only publication only after
the controller confirms eligibility and records the brief handoff in the existing task record. The
default maintenance route delegates implementation through the owner-designated Codex dispatcher
to exactly one implementor. Direct Work controller implementation is permitted only for that
controller-confirmed eligible maintenance selection and when the permission line above remains
present exactly once in this section. Record `Requested route: maintenance` and
`Implementation execution: direct Work controller` in the same existing task record, and record the
actual direct author in that handoff or existing operational record. The controller assumes the
implementor's duties, scope limits and checks, uses its already selected Work settings and
confirmation, and does not apply the implementor's Codex defaults. This selection has no capsule
builder, Codex dispatcher or separate implementor assignment; it requires a fresh nonauthor
independent review of the exact candidate, plus qualification, verification, approval, integration
and closeout. The author cannot review its own work. If implementation is delegated, the owner-designated Codex dispatcher
authenticates the complete accepted task handoff, launches one implementor and relays its terminal
result. Tool or agent-spawn capability alone does not authorize an implementation route; workers do
not recruit. The delegated dispatcher launches exactly one implementor.

Maintenance eligibility follows the selected [governing rule](../engineering/workflow/shared/start-an-issue.md#optional-maintenance-route):
the bounded objective, scope, decisions and verification must be sufficiently understood.
An identified dependency/runtime update or inspected RI adoption with necessary bounded local
workflow/tooling alignment is not categorically excluded. Unresolved design, substantial migration
or unexpected wider impact requires a controller decision/normal planning; pause only the affected
part and retain valid work/evidence. A failed focused check alone permits bounded in-scope correction,
affected checks and fresh review. This selection supplies no additional task or host permissions.

Before direct edits, authenticate the current checkpoint, selected Work actor and live assignments.
Refuse direct execution when a builder, dispatcher or implementor assignment is active or unresolved;
preserve that assignment and return for bounded reconciliation instead of taking it over. Missing or
unresolved assignment evidence is a hold, not evidence that the task is idle. Before review, use the
existing controller authentication route to identify the actual author and reviewer. Refuse review
when those authenticated actors are the same or the reviewer identity is unresolved, and preserve
state; actor text in the task record does not establish independence. If review requests changes, return bounded correction to the selected direct
author under the unchanged scope, retain C1 findings/proof, run affected C2 checks and require fresh
nonauthor C2 review. Do not recruit an implementor solely for this correction.

The project-scoped Codex kickoff folders are `.agents/skills/ri-work-kickoff/` and
`.agents/skills/ri-codex-dispatcher-kickoff/`. Their presence does not prove fresh Codex discovery
or register a Work skill. Verify each host through its supported selector/import route; use direct
document-based kickoff when Work registration is unavailable or unverified.

The selected role settings are owner-authorized requests:

| Role | Environment | Model / effort |
| --- | --- | --- |
| Controller, capsule builder and independent reviewer | Work | `gpt-6.1-sol` / `low` |
| Implementor | Codex | `gpt-6-luna` / `max` |

The table records the owner-selected requested settings. Direct Work controller implementation
continues with the already selected controller settings and their existing confirmation; it does
not create an implementor launch or transfer the implementor's settings to the controller. Dispatch options establish only the
request; they do not establish a worker's launch or effective settings. Retain the existing
owner-confirmed selection of the identified Work controller chat without asking for that selection
again. That owner confirmation establishes the selected Work chat settings; it does not replace
authenticated external Nutrition task authorization. The trusted Work owner record confirms
selected Work configuration, not provider-effective telemetry. Record the selection in the
existing external task checkpoint before dependent work.

Nutrition explicitly selects the [native Work policy](../engineering/workflow/shared/new-project-setup.md#accepted-worker-launch-routes)
for builders and reviewers: `collaboration.spawn_agent` is accepted with the configured model/effort
requested explicitly. Missing selector fields or measured telemetry remain unverified; policy
acceptance does not claim measured execution. Actual launch failure, contradictory evidence or a
genuinely missing required capability blocks dependent work. Missing reading resources are source
prerequisites, not proof of a missing launch route.

Configure and confirm each worker separately through its supported role-appropriate launch
route. For each separately configured builder, implementor, and reviewer, proceed when the
supported role-appropriate launch route accepts the requested environment/model/effort and reports
no mismatch or substitution.

Record requested environment/model/effort separately from host-confirmed settings. Record
requested settings and launch evidence separately from owner selection, available host-confirmed
settings, and provider-effective telemetry. Before dependent work, persist each worker's requested
settings, launch evidence, available host-confirmed settings, and any unverified telemetry
disposition in the existing external checkpoint.

When effective telemetry is unavailable, record it as unverified: missing telemetry proves neither
compliance nor mismatch and is not a capacity failure. Unavailable host confirmation or effective
telemetry remains unverified; it is not evidence of verified compliance. Do not infer mode, model
or effort from tools, a selector, app name or backing metadata, or inherit confirmation from the
controller or another worker.

If host confirmation is genuinely mandatory for a worker under its authenticated task requirements
and remains unresolved, return to the controller before dependent work; do not infer that
requirement from telemetry availability. A rejected configuration, confirmed mismatch or
substitution, or unavailable required route blocks dependent work and returns to the controller.
No fallback is selected here. Do not silently substitute an environment, model or effort. Reuse an
accepted route only while its route and configuration remain unchanged.

For an owner-authorized cross-host assignment, verify the selected host route's messaging and
result-recovery capability before relying on it. Keep the route identity in the existing
operational record, not this durable map; reuse the verified route until relevant inputs or
delivery changes or fails, then recheck. If direct messaging is unavailable, use only the
selected manual route. Work-to-Codex implementor results return to the assigned Codex dispatcher,
who relays them to the Work controller and records controller consumption. Native child results
return to their parent. Use supported blocking completion for active assignments unless the exact
idle-wake route is verified. A terminal result already delivered can be consumed immediately;
that result needs no separate idle-wake proof. Sending or backing metadata alone proves neither
consumption nor idle wake-up. Do not publish private conversation identifiers.

The adopted [serial assignment and role rules](../engineering/workflow/shared/start-an-issue.md#execute-serially),
[Work-to-Codex handoff](../engineering/workflow/shared/start-an-issue.md#work-to-codex-implementation-handoff),
[task inputs and return destination](../engineering/workflow/shared/start-an-issue.md#assign-roles-and-supply-inputs),
[execution settings](../engineering/workflow/shared/start-an-issue.md#execution-routing-models-and-efforts),
[task-branch publication rules](../engineering/workflow/shared/start-an-issue.md#publish-the-task-branch-and-handoffs),
[additional-assignment limits](../engineering/workflow/shared/start-an-issue.md#additional-assignments-and-orientation),
[waiting and recovery rules](../engineering/workflow/shared/start-an-issue.md#wait-recover-and-resume),
[model-capacity recovery](../engineering/workflow/shared/start-an-issue.md#handle-model-capacity),
[bounded correction and evidence-reuse rules](../engineering/workflow/shared/start-an-issue.md#diagnose-blockers-and-recover),
[worker return rules](../engineering/workflow/shared/worker-instructions.md#shared-worker-rules),
[builder duties](../engineering/workflow/shared/worker-instructions.md#capsule-builder),
[implementor duties](../engineering/workflow/shared/worker-instructions.md#implementor),
[independent-review duties](../engineering/workflow/shared/worker-instructions.md#independent-reviewer),
[Codex dispatcher duties](../engineering/workflow/shared/worker-instructions.md#codex-dispatcher)
own the normal sequence, assignment limits, bounded correction, waits and evidence reuse. The
map keeps only Nutrition's actor, permission, model and route bindings.

## Standards and checks

Worker handoffs apply the canonical [local actor and timing rule](operations/session-contract.md#actor-and-timing)
within their selected role read scopes. Read-only result delivery is not task completion;
controller-owned acceptance checks remain required at their proper gates.

Use [AGENTS.md](../AGENTS.md), the [session contract](operations/session-contract.md#repository-session-contract),
the [testing guide](operations/testing.md#main-qualification-profiles), and Nutrition's
[authority contract](../engineering/workflow/AUTHORITY.md#current-interfaces). These current
project owners govern domain/security standards, session closeout, selected tests, task interfaces,
profile floors and protected acceptance.

Before dispatch, the controller runs the read-only public record check:
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
must reauthenticate live owner authority at dependent gates. Rework keeps the same authorized
base, paths and profiles, retains C1's qualification/verification/review/operation history, and
clears active proof before C2 is qualified, verified and independently reviewed from scratch.
Each rework qualification checks its operation ID against every retained correction archive and
refuses reuse before publishing a candidate ref or dispatching. A C1 qualification failure may be
archived only with a failed exact-C1 verification; a passing verification cannot validate a failed
qualification. Rework grants no new authority and does not convert compatibility or historical records.
Before a transition or qualification, the controller checks generated archive identities, terminal
operation cleanup, adjacent candidate links, and retained authority/scope bindings. It checks stored
checkpoint digests by format without reconstructing historical checkpoint contents and preserves
opaque unrelated history and failure evidence.
Repeated calls, `STOP_REPLAN`, unsupported phases, and overlapping or unresolved
qualification/integration operations are refused without checkpoint mutation. An owner pause is
a controller hold outside checkpoint state, not a serialized phase; the controller must not
invoke rework until the owner explicitly continues. The separate fresh-authorized-attempt route
uses `prepare` with current matching owner authorization and a separately selected state
location, preserving the existing checkpoint and its consumed allowances.

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

New task records live at `engineering/tasks/TASK-ID.md`. The normal route uses the
[shared six-heading format](../engineering/workflow/shared/start-an-issue.md#capsule-format) and
[task template](../engineering/tasks/TEMPLATE.md#check-attempts). Under explicit controller-selected
maintenance, the same task record carries objective, exact base, allowed changes, required checks,
concrete return destination and a recorded `Decision: eligible`; direct selection also records its
literal route and execution fields plus the actual author in that handoff or existing operational
record. There is no separate maintenance file or history store. The public validator checks the
selected record fields and, for direct selection only, the exact local-map permission; it does not
determine eligibility, author identity, reviewer independence, live assignment state or owner
authority. Existing full TOML capsules under
`engineering/capsules/active/` remain historical recovery records through
`REVIEWED` or their last nonterminal state; preserve their bytes and legal transitions. The
[capsule record contract](../engineering/workflow/TASK_CAPSULE.md#historical-capsule-contracts),
[state machine](../engineering/workflow/STATES.md#terminal-recording), and immutable
[capsule history](../engineering/capsules/HISTORY.md) own that lifecycle.

Use the selected external evidence workspace named in the authenticated task handoff. The
default controller checkpoint is `~/.nutrition-app/task-controller/issue-N.json`; an
`NUTRITION_TASK_STATE_DIR` or `--state-dir` override must be explicitly selected and authorized.
Follow the adopted [checkpoint and resume rules](../engineering/workflow/shared/start-an-issue.md#checkpoint-and-resume):
recover the actual authenticated active checkpoint and live assignment, not an earlier history
entry. Do not guess private paths, invent another state store, or reset a transaction.
Retain each attempt's exact source or complete dirty diff (including untracked files), literal
command and environment, exit/status, immutable log identity and digest, skips, failures, stops
and consumed allowances. Keep private diagnostics outside published source and reuse evidence
only when its original identity remains eligible.

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

Before candidate C is frozen for exact-candidate qualification and review, finalize the
tracked task preparation/check ledger, label it historical and point current status to the live
issue and existing external controller checkpoint. After C is frozen, record every later attempt,
failure, rerun, qualification, review, integration, issue closure and cleanup outcome in those
existing operational records. Do not create another candidate solely to append completion
evidence. The adopted [completion-record rule](../engineering/workflow/shared/start-an-issue.md#keep-completion-records-external)
defines this boundary.

Only the controller performs authorized integration and closeout, after exact-candidate
qualification, explicit verification, independent review and current owner permission. The
protected expected-main update must satisfy the current rules and compare-and-swap checks; no
bypass is authorized. After integration, verify the installed source, all original outcomes and
post-installation obligations. After those checks pass, close the issue and verify its actual
closed state. Then safely clean up the verified merged local/remote branches and verify the
cleanup. If a required outcome, issue closure or cleanup is unresolved, preserve state and report
partial closeout. The [daily phase and closeout procedure](../engineering/workflow/shared/start-an-issue.md#complete-the-phases)
and [task authority](../engineering/workflow/AUTHORITY.md) remain the governing anchors.
