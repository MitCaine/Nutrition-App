# Nutrition local project map

## Selected instructions

This is the sole project-root local execution map. The adopted Repository Intelligence (RI)
instructions are pinned at `20a5039e7731eaa1303443b782caa81a383a0af1`: controllers use the
complete [daily issue procedure](../engineering/workflow/shared/start-an-issue.md), and workers
use the selected [worker role index](../engineering/workflow/shared/worker-instructions.md#role-index)
and their assigned section. The [Shared worker rules](../engineering/workflow/shared/worker-instructions.md#shared-worker-rules)
and role sections govern worker inputs, scope and return duties. Controllers read the live issue,
required linked specifications and applicable project standards; a handoff summary does not
replace an unread source. The adopted procedure governs controller intake and directed reading.

The adopted [SOURCE record](../engineering/workflow/shared/SOURCE.md) is authoritative for the
selected instruction bytes and their provenance. It separates the controller procedure,
worker instructions, conditional adoption guide and compatible runtime. Pins identify selected
inputs; they do not grant permission or create a receipt or approval mechanism. The
[adoption/replacement guide](../engineering/workflow/shared/capsule-controller-workflow.md#replace-an-entangled-adoption)
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
authenticates live owner authorization and the current task/checkpoint before dependent work;
candidate text, chat, a task file or a passing check cannot create authority. The controller
alone owns Git and task-stage decisions. Preserve unrelated edits and paused history. A task
branch or other action requires its current explicit grant; this map is not blanket Git, issue
or settings permission.

The selected role settings are:

| Role | Environment | Model / effort |
| --- | --- | --- |
| Controller, capsule builder and independent reviewer | Work | `gpt-6.1-sol` / `low` |
| Implementor | Codex | `gpt-6-luna` / `max` |

Record requested environment/model/effort separately from host-confirmed settings. Use an actual
selected host mode or authoritative configuration/session record to confirm settings; a trusted
Work owner record may confirm selected Work configuration. Dispatch options establish only the
request. Under the owner's selected policy, unavailable effective settings are unverified; do
not infer them from a selector, app name or backing metadata. Do not silently substitute an
environment, model or effort. No fallback is selected here; any fallback requires separate
owner authorization and the adopted capacity-recovery rule.

For an owner-authorized cross-host assignment, verify the selected host route's messaging and
result-recovery capability before relying on it. Keep the route identity in the existing
operational record, not this durable map; reuse the verified route until relevant inputs or
delivery changes or fails, then recheck. If direct messaging is unavailable, use only the
selected manual route. Work-to-Codex implementor results return to the assigned Codex dispatcher,
who relays them to the Work controller and records controller consumption. Native
child results return to their parent. Sending or backing metadata does not prove consumption or
idle wake-up; keep blocking until the exact idle route is verified. Do not publish private
conversation identifiers.

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

Use [AGENTS.md](../AGENTS.md), the [session contract](operations/session-contract.md#repository-session-contract),
the [testing guide](operations/testing.md#main-qualification-profiles), and Nutrition's
[authority contract](../engineering/workflow/AUTHORITY.md#current-interfaces). These current
project owners govern domain/security standards, session closeout, selected tests, task interfaces,
profile floors and protected acceptance.

The controller uses the actual `./scripts/task` interfaces: `prepare ISSUE` with the explicit
task ID, base, paths and profiles; `authorize ISSUE`; `qualify ISSUE --candidate-root PATH`;
`verify ISSUE` with candidate SHA, actor, decision and evidence; `review ISSUE` with candidate
SHA, actor, decision and summary; and
`integrate ISSUE --candidate-root PATH --human-owner-authorized`. The executable controller owns their exact argument validation and
must reauthenticate live owner authority at dependent gates.

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

New bounded Markdown tasks live at `engineering/tasks/TASK-ID.md`, using the
[shared task format](../engineering/workflow/shared/start-an-issue.md#capsule-format) and
[task template](../engineering/tasks/TEMPLATE.md#check-attempts). Existing full TOML
capsules under `engineering/capsules/active/` remain historical recovery records through
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

BEFORE final candidate review, finalize the tracked task preparation snapshot, label it
historical and point current status to the live issue and external controller checkpoint.
After review, qualification, integration, issue closure and cleanup belong in those existing
operational records. Do not create another candidate solely to append completion evidence. The
adopted [completion-record rule](../engineering/workflow/shared/start-an-issue.md#keep-completion-records-external)
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
