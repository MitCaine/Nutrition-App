# Nutrition local project map

Established-project work uses the complete [daily issue procedure](../engineering/workflow/shared/start-an-issue.md)
from RI commit `cdf64f5d27ef43e7e58e7b11f371a81d15687bdd`: 17374 bytes,
SHA-256 `cc5f69f8c8dd3f508feda911dbf93f1558e31c1ba4b9bd480b107ac81e136779`.
Read this map, the complete daily procedure, live issue/required linked decisions and
applicable standards before acting. The [adoption guide](../engineering/workflow/shared/capsule-controller-workflow.md)
is conditional on setup or owner-authorized replacement. [SOURCE](../engineering/workflow/shared/SOURCE.md)
records both exact instruction identities separately from the compatible runtime.
This is the sole authoritative local map at project-root `docs/local_project_map.md`.
Shared instructions govern the procedure; this map supplies local actors, commands,
paths and authority. Pins record provenance, not a cryptographic receipt chain.

## Local route

| Stage / actor | Nutrition interface and inputs | Returned result / authority |
| --- | --- | --- |
| Orient / controller | Authenticate live issue, checkout/base, current owner authorization, active task/checkpoint and selected instructions; use `./scripts/ri query` when useful | Preserve unrelated edits and paused states; create/publish the authorized dedicated non-main GitHub branch before planner dispatch |
| Capsule / planner | One native subagent with originals, this map, standards and [six-heading template](../engineering/tasks/TEMPLATE.md) | Bounded Markdown task, base/branch/scope/criteria/checks/gaps; controller checks full plan, commits/pushes capsule-only plan and verifies remote identity before implementation |
| Implement / implementor | One native subagent with published plan, complete daily instructions, AGENTS, checkout and actual command environment | Authorized edits, full source/diff and check-attempt/log inventory; controller checks full handoff and commits/pushes exact candidate on the same branch, verifies remote C before review |
| Independent review / reviewer | Fresh distinct native subagent; exact published C and full base-to-C diff, original requirements, task/standards and all relevant results/logs | Read-only evidence-backed disposition of every criterion and applicable standard, including docs; no self-review or test-inferred approval |
| Authorized integration / controller | Exact reviewed/qualified/verified C, live owner authorization and actual supported `./scripts/task` interfaces | Protected expected-main integration only under current owner permission and project checks; retain actual resulting source identity |
| Verify closeout / controller | Installed source, all original outcomes, remaining installed obligations, current references and authorized issue actions | Record actual proof externally; close only after outcomes pass, verify closure and safe verified merged local/remote branch cleanup; report partial results honestly |

Only the controller dispatches, using `collaboration.spawn_agent`, one assignment at a
time with fresh contexts by default. The normal path has one planner, one implementor
and one distinct independent reviewer. Workers do not recruit. Additional substantive
assignments require a specific rejected deliverable/failed required check, an authorized
scope change, confirmed assignee/host inability, or a concrete independent scope challenge
permitted by the daily plan-check step. First try the controller's plan check for a scope
finding; record the reason and bounded objective in the existing checkpoint before dispatch.
Clarification stays within the current assignment. Routine verification/bookkeeping/closeout
does not justify another assignment. The selected role pairs below are authoritative;
no model/effort fallback is authorized by this map. The selected role pairs are
controller, builder and reviewer `gpt-6.1-sol`/`low`, and implementor
`gpt-5.6-luna`/`max`; the controller records host-effective settings before each
dependent dispatch.

Give every role the complete selected procedure, task, relevant standards, original issue
and actual source/evidence locations; verify access before dispatch. Controller is the
sole Git actor for the normal route: workers return edits and do not commit/push.
Task-branch publication within the existing explicit task grant is separate from protected
main acceptance. This map grants no blanket Git permission, issue transition or settings
change. Resolve an actual permission conflict before dependent work; do not fabricate
authority from a document, remembered approval or test PASS.

Use supported native event-based blocking completion, retaining and authenticating terminal
handoffs. End a waiting controller turn only when idle wake-up for that exact host/route is
verified. Result delivery to an active parent is insufficient. External jobs use native
delivery or the [conditional queue route](../engineering/workflow/shared/skill-templates/capsule-queue/SKILL.md)
only with a supported observer and verified destination/delivery; CLI acceptance is not
consumption. Otherwise retain blocking waits. Do not poll or inspect unfinished jobs,
logs/workspaces/tests or issue interim acceptance judgments. Intervene only for delivered
actionable events, concrete safety concerns, failed delivery or owner status requests.
Task-appropriate deadlines and host wait resumptions do not authorize monitoring or duplicate
dispatch. Retain a completed handoff before closing an agent where supported; never close
running agents. Last-resort idle-context reuse requires the complete authenticated handoff
and preserved independence. Capacity failure follows the daily recovery rule; no retry loop.

## Authority and recovery

[AGENTS](../AGENTS.md) owns domain/security standards; [AUTHORITY](../engineering/workflow/AUTHORITY.md)
owns existing protected Git acceptance. Routine evidence reads, handoff validation,
clarification, cancellation, bounded in-scope recovery and authorized bookkeeping are
controller actions under existing task authorization, without repeated owner prompts.
Hold consequential work on a blocker, consolidate actual failures/unknowns through one
bounded authorized read-only sweep, then correct in scope and rerun affected checks/review.
Request new authority only for concrete uncovered scope, permission, disclosure, settings
or genuinely reserved actions. Existing main integration, issue closure and branch cleanup
retain their current owner permission requirements; prior task grants do not transfer.

The existing trusted `./scripts/task prepare`, `authorize`, `qualify`, `verify`, `review`
and `integrate` interfaces enforce live authenticated owner authority, exact-SHA dedicated
App `4708441` qualification, project-selected profiles and protected expected-main updates.
They are Nutrition controls, not RI requirements. The actual rename-aware candidate path
inventory selects profile floors; historical passes and automatic push CI cannot satisfy
current qualification. A changed C requires affected checks and independent review before
acceptance. No protection bypass, controller replacement or hosted runner is added here.

Preserve failed/terminal stops and consumed allowances. Diagnose a terminal attempt only
within authorized read-only scope; do not resume it implicitly or relabel later success.
Cancellation preserves terminal returns and changed bytes; remove only authorized disposable
resources after verifying operation state/cleanup. After compaction authenticate the active
checkpoint, phase, source, selected instructions, active assignment and pending obligations;
do not restart planning or duplicate dispatch.

## Task and checkpoint locations

Use `engineering/tasks/TASK-ID.md` with the [shared format](../engineering/workflow/shared/start-an-issue.md#capsule-format)
and [template](../engineering/tasks/TEMPLATE.md). Finalize tracked preparation snapshots
BEFORE final candidate review, label them historical, and point current status to the live
issue and existing external controller checkpoint. Select and authenticate that active object,
not its historical entries. Supported default state is `~/.nutrition-app/task-controller/issue-N.json`,
or the explicitly selected `NUTRITION_TASK_STATE_DIR` / `--state-dir`. Record the actual selected
checkpoint's portable identity in the task; never guess its private absolute location.

After review, qualification, integration, issue closure and merged-branch cleanup belong
in those existing operational records. Do not create another candidate solely to append
completion evidence to tracked tasks. A genuine later tracked-document correction requires
affected checks, review and authorized publication. Durable maps stay task-neutral.
Keep large logs and private diagnostics outside published source in the selected evidence
workspace. The [append-only inventory](../engineering/tasks/TEMPLATE.md#check-attempts) retains
exact source/complete dirty diff including untracked files, literal command/environment,
status/exit, unique log location/digest and eligibility/disposition for every attempt.
Supply complete relevant inventory/logs, including failures, skips and reruns, to review.
Only the latest eligible complete success on required source satisfies a check; unknown
exit, unavailable check, missing log, partial/ambiguous delivery, skip or source mismatch
does not. Resolve later failures/ambiguity before relying on prior success.

## Checks and preserved boundaries

[RI tooling](../engineering/tooling/RI.md) remains producer
`2f28da4d326ff12da5dc9270eb57910303e4a737`, navigation 6, inventory 13,
adapter 10, mapping v10; no silent upgrade. Read the [domain invariants](project/invariants.md),
[session contract](operations/session-contract.md) and [testing guide](operations/testing.md)
for applicable commands/profiles. Run meaningful focused checks, affected documentation
validation and session closeout. Unsupported RI coverage requires direct source/diff reading.
RI imposes no broad backend/native suite solely for documentation maintenance. Required
project profiles, secret/permission controls and protected acceptance remain enforced.

The compatible RI launcher uses Python 3.14 and an authenticated external runtime manifest.
Setup proof is repeated only when relevant inputs change or a capability actually fails.
Use the selected launcher and its nested macOS network-denied sandbox; an outer host denial
is an observed failure, not permission to bypass it. Keep original source/runtime/command
identities when reusing unchanged evidence under the project's accepted equivalence policy.

Historical completed task records retain their original preparation/completion annotations;
they do not select current operational status or authorize new work. #246 and #256 remain
paused, preserving capsules, branches, C/R/T recovery, evidence, decisions and consumed
allowances. [STATES](../engineering/workflow/STATES.md), [TASK_CAPSULE](../engineering/workflow/TASK_CAPSULE.md)
and immutable [history](../engineering/capsules/HISTORY.md) retain those recovery contracts.
Historical attached readers are recovery tools, not current dispatch entrypoints.
