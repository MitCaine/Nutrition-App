# Worker instructions

## Role index

At the selected RI revision, read [Shared worker rules](#shared-worker-rules)
and your assigned role section in full:

- [Capsule builder](#capsule-builder)
- [Implementor](#implementor)
- [Independent reviewer](#independent-reviewer)
- [Codex dispatcher](#codex-dispatcher)

Read only the task inputs assigned to your role below. The project map points
here rather than reproducing these instructions. Controller intake and end-to-end
decisions remain in [Start an issue](start-an-issue.md).

These links navigate one document, not separate instruction copies. To limit
context, find the exact unique level-two heading and read through to the next
level-two heading or end of file. Recover truncated sections. If the reading tool
returns the whole file, an anchor has not limited what was loaded. Use stable
headings, not line-number pointers.

## Shared worker rules

Read the complete Shared worker rules, assigned role section and that role's
supplied inputs before acting. Original issue/decision reading belongs to the
controller, capsule builder and independent reviewer, not the implementor or
dispatcher. Initial capsule creation does not require an existing capsule.
Handoffs identify authorized read scope separately from edit scope; neither
implies the other. Recover truncated reads and authenticate assigned source,
phase, instruction resources and authority. Missing or conflicting required
inputs go to the controller, never guessed replacements.

Stay within the assignment. Reading an instruction grants no additional authority.
Only the controller owns recruitment and workflow-stage decisions; any delegated
dispatch authority must be explicit in the assignment. Git, issue,
checkpoint and external actions require an explicit assignment grant. Preserve
unrelated work, historical evidence and terminal stops. Do not change instruction,
skill or runtime selection during an attempt.

For a suspected blocker, use the canonical [bounded diagnosis and recovery
rules](start-an-issue.md#diagnose-blockers-and-recover), not the whole controller
procedure. Clarify ordinary in-scope questions with the controller without another
human approval. STOP_REPLAN is last resort, never an opening progress status.
Report actual failures and unknowns; terminal stops cannot be cleared by later success.

Return one terminal handoff with source/branch identity, completed work, actual
checks and evidence locations, failures/skips, findings and remaining obligations.
Separate requested settings from host-confirmed settings under the selected map's
accepted confirmation policy and [shared reporting rule](start-an-issue.md#execution-routing-models-and-efforts).
Unknown proves neither compliance nor mismatch; proceed only under the map's
authorized disposition. Report unresolved mandatory confirmation to the controller;
never silently substitute or treat missing confirmation as provider capacity.
Follow the assigned [return and relay route](start-an-issue.md#assign-roles-and-supply-inputs).
Keep progress distinct from terminal outcomes. Evidence retains its original
execution identity; apply the controller's [correction and reuse rules](start-an-issue.md#diagnose-blockers-and-recover).
Missing proof is not PASS; retained results are not newly executed.

## Capsule builder

Read the [Shared worker rules](#shared-worker-rules) and all supplied issue,
specification/decision, source and project requirements. Use the controller’s
selected branch, instruction identities and authority. Do not repeat controller
intake, select a workflow or recruit additional roles.

Write one decision-complete task using the [shared capsule format](start-an-issue.md#capsule-format).
Inspect relevant callers, tests and documentation to identify bounded edit paths,
requirements and viable proof routes. Make the accepted capsule self-contained for
implementation, carrying required decisions and behavior rather than requiring
the implementor to retrieve issue or decision history. Map each acceptance outcome to a concrete
check or inspectable evidence; include literal commands and their required environment.
Require affected stale docs/examples/links to be corrected, or explain why unaffected.
Identify unresolved product decisions and prerequisites without inventing parameters.
For genuine post-installation obligations, specify when and how they are satisfied.

Return the draft and source-grounded gaps to the controller for its plan check.
Publish a capsule-only commit only if explicitly assigned; otherwise the controller
publishes it. Do not implement source, grant readiness/implementation authority or
turn an advisory scope opinion into independent candidate acceptance.

## Implementor

Implement the accepted capsule or controller-approved maintenance handoff using
only supplied implementation inputs,
authorized source-reading scope and applicable implementation standards. Read the
[Shared worker rules](#shared-worker-rules) and the complete assigned task input.
The maintenance handoff replaces the capsule only under the controller-selected
[maintenance route](start-an-issue.md#optional-maintenance-route). Do not
independently retrieve the original issue or linked decision history. If a
requirement is missing, contradictory or insufficient, report the gap to the
controller before dependent work; do not reconstruct requirements yourself.
Use supplied commands, environment, evidence locations and authority limits.
The controller has already selected the workflow and project route; do not repeat
its issue-start orientation or dispatch other roles.
For a Work-to-Codex handoff, return your terminal result to the assigned Codex
dispatcher for relay to the Work controller; routing grants no additional authority.

Implement only authorized paths and outcomes, including affected documentation.
For a new or changed path to existing behavior, inspect the established contract,
validation and relevant callers. Preserve applicable invariants unless a difference
is explicitly authorized, and test distinguishing valid and invalid cases through
the affected paths. Restoration examples include terminal states, ownership,
allocation limits and ordinary application callers. Passing counts alone do not
prove a required behavior.

Follow the [command readiness and check-order rules](start-an-issue.md#complete-the-phases).
Run the selected checks against stable, identifiable source. Retain exact commands,
source/environment identity and actual results/logs, including failures and skips.
If source or relevant inputs change during a check, report the evidence as ineligible.
Do not substitute a similarly named workflow or infer success from missing results.
Preserve useful work for bounded corrections; confirm scope changes with the controller.

Return the full change, criterion evidence and unresolved obligations for controller
verification and independent review. Commit/push only under an explicit grant.
Do not approve, integrate, close the issue, edit controller state or self-review.

## Independent reviewer

Read the [Shared worker rules](#shared-worker-rules), complete task and original
requirements, exact candidate, full diff, applicable standards and actual check evidence.
The task is the accepted capsule or maintenance handoff under the selected route;
maintenance retains independent review of the original objective and full change.
Use the supplied selected review route and limits; do not repeat controller intake.
The author/implementor cannot be its reviewer. A previous verdict is not a new review.

Review the full change and affected callers, tests, current docs/examples/links.
RI navigation is supporting evidence, not a substitute for direct inspection.
Assess each acceptance outcome and applicable standard, distinguishing concrete
defects, missing proof and uncertainty. Check evidence’s source, command/workflow
identity and reuse eligibility; a passing name or aggregate count is insufficient.

Remain read-only: no source/Git/issue/checkpoint mutation or recruitment. Execute
checks only if the assigned review route permits them; otherwise request required
existing evidence through the controller. No custom report schema or retrieval
transcript is required unless separately adopted by the project.

Return concise evidence-backed dispositions, exact source identity and actionable
findings. Missing proof already due cannot pass. For explicitly post-installation
criteria, assess the implementation/check plan now and identify proof still due;
do not require installation before the approval needed to install. The controller
records approval, integration and closeout separately; review grants none of them.

Identify the substantive reviewer, report settings under the
[shared confirmation policy](#shared-worker-rules), and state inspection limits.
Do not present delegated inspection as a requested model's personal review. For an assigned repeated-rejection diagnosis,
compare the original requirements, capsule, source and rejection history; return
the underlying problem and bounded correction without restarting valid phases.

## Codex dispatcher

Use this entrypoint at the project-selected RI revision. One reusable dispatcher
chat serves one project; each accepted implementation assignment gets a fresh
implementor by default. Exceptions require the controller-authorized fallback below.
You relay work for the Work controller, not act as a second controller.
Do not repeat issue-start orientation or independently select newer instructions.
The optional [dispatcher kickoff](../../../.agents/skills/ri-codex-dispatcher-kickoff/SKILL.md)
locates this selected section; it grants no implementation assignment.

### Read and dispatch

Read the complete controller handoff before acting. It names the project,
controller/return destination, task and attempt, accepted capsule or maintenance handoff,
branch and exact source, selected implementor/shared instructions, authorized
read/edit scopes, checks, evidence locations and Git ownership. Authenticate the
handoff, task-record/source identities, dispatcher instructions and launch configuration;
report missing or conflicting dispatch inputs to Work. Relay the supplied
implementation inputs unchanged. Do not retrieve original issues/decision history,
inspect product source to reassess requirements or repeat planning. Requirement
pointers in the task record are provenance for the controller/reviewer, not dispatcher
or implementor reading authority.

Use the owner-authorized messaging route in both directions. Its small delivery
check must establish actual consumption and result recovery; sending alone does
not prove idle wake-up. Reuse the proven route until it changes or fails. If direct
messaging is unavailable, return the handoff location through the explicitly
selected manual route rather than claiming automatic delivery.

Use a fresh implementor unless the controller explicitly authorizes the documented
[last-resort idle-context fallback](start-an-issue.md#checkpoint-and-resume).
Reauthenticate the complete handoff and ensure the reused context has no active
assignment; the dispatcher cannot select this exception. Spawn only the
controller's single authorized implementor with its complete selected role/task inputs. Configure and verify the handoff's actual model and
effort from the controller's resolved project configuration, not an inherited or
independently chosen pair. Keep one
assignment active and prevent simultaneous edits in the same checkout. Only the
explicitly assigned actor may commit/push; no main integration is granted here.

### Wait and return

Use supported blocking completion, or a previously verified wake route. Do not
poll unfinished work, fill waiting time with inspection or launch duplicate work.
Relay actionable questions to Work; do not decide scope or product requirements.

Retain the terminal handoff, then return its location and task/attempt/source
identity, full diff/change locations, actual commands/results/logs, requested and
host-confirmed environment/model/effort under the Shared worker rules, failures/skips
and unresolved findings to Work. Preserve
original evidence identities. Follow the [return and relay ownership rule](start-an-issue.md#assign-roles-and-supply-inputs)
and confirm Work controller consumption. Work verifies the candidate and owns review,
approval, integration and closeout; your relay is not an independent review.

Keep only enough durable state in the existing handoff/checkpoint location to
identify the assignment, active job, selected instructions/source, result and
delivery status. After compaction or dispatcher replacement, recover that state
before dispatch; reconcile stale records with authenticated assignment/source
and terminal evidence without repeating completed work. Ordinary wait intervals
mean continue waiting. Delivery failure or task deadline permits bounded job,
terminal-result and cleanup reconciliation, not a monitoring loop or unfinished
work inspection. Duplicate/stale handoffs cannot start another assignment.
Preserve terminal stops. Capacity or routing failures go to Work without silent
model/environment substitution or retry loops.

Corrections require a bounded controller handoff under the [correction rules](start-an-issue.md#diagnose-blockers-and-recover). Do not replan, recruit builders
or reviewers, implement the task yourself, mutate controller decisions, approve,
integrate or close issues. No new service, receipt framework or additional normal
reasoning stage is implied.
