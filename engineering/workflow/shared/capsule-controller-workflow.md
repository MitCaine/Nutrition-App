# Lightweight controller workflow with RI

**Read the complete directed orientation material before acting.** Read the
selected execution instructions, local map, complete issue and required linked
specifications/decisions before task decisions, edits or dispatch. Resolve
contradictions and identify missing inputs before dependent work. Summaries do
not substitute for unread requirements; this does not require a whole-repository
read. Pass original required sources to each role, not only a controller summary.

This is the default RI-assisted workflow for projects adopting or explicitly
replacing an RI workflow. RI supplies source navigation/comparison; it does not
require a special capsule runner, SDK transport, evidence exporter or approval
service. Existing projects adopt this replacement under owner authority rather
than silently bypassing their current controls.

[Start an issue](start-an-issue.md) owns daily execution; this guide owns adoption
and replacement. Use the adopted map and active task, not archived procedures or
previous plans. Resolve conflicting routing before dispatch. This broader guide
is not required reading for every established-project issue.

## Keep the integration small

Keep one short project map at project-root `docs/local_project_map.md`.
Link it from the project README/AGENTS entrypoint. Record the selected RI
runtime/source and supported contract, shared instruction identity, repository
standards, normal test commands, permitted Git/issue actions, and completion
route. Pin the instruction bytes or their source commit; retain the map across
compaction. Do not duplicate the shared procedure in local manuals.

Choose a compatible RI runtime. A newer producer is a proposal until the
project's reader accepts its contract. Observe compatibility once at setup and
again when relevant runtime/reader inputs change, not on every conversation.
Use ordinary source files, Git diffs and test logs as evidence. RI declarations
help navigation; reviewing every declaration as a separate report entry is not
required by RI. Missing RI coverage requires direct source/diff inspection,
not an automatic cancellation of otherwise authorized work.

## Sequence

```text
Controller: authenticate objective, checkout, authority and usable tools
    |
Planner: supplied/explicitly authorized branch + bounded Markdown task
    | return branch/base, task path, scope, criteria, checks and gaps
Controller: inspect task and relevant source; resolve actual gaps
    |
Implementor: permitted edits + relevant tests
    | return changes, candidate/ref if authorized, results and gaps
Controller: inspect full diff/scope; capture exact candidate if needed
    |
Independent reviewer: read candidate, task, standards and real test evidence
    | concise evidence-backed verdict and actionable findings
    +-- defect --> bounded implementor correction --> affected checks/review
    |
Controller: authorized integration --> verify result --> close issue
    --> retain necessary evidence --> delete merged task branch when safe
```

Follow the [daily published-branch sequence](start-an-issue.md#execute-serially):
the controller creates the GitHub task branch and the assigned actor publishes the capsule,
and the assigned actor publishes implementation on that same branch before
independent review. Bind handoffs to verified remote commits. Task publication
is not main acceptance; no subagent pushes to main. Resolve conflicting project
controls before dispatch rather than silently keeping the task local.

Initial implementation starts from validated planning state. A correction starts
from the authenticated recovery source/parent and retained finding, not from an
artificial requirement that the branch still heads the original planning commit.
Keep the original objective and scope; preserve any project-required lineage and
remaining allowance. Check the actual recovery inputs before dispatch.

If inspection establishes that the requested behavior already exists, return
**no changes needed** with criterion-specific source/test evidence. The controller
checks that evidence and obtains applicable independent review before the
project's authorized issue closeout. Do not manufacture an edit, candidate commit
or merge solely to fit the diagram. Retain the reviewed source identity; if a
criterion remains unresolved, the task is not complete.

Run one subagent assignment at a time. Use fresh contexts by default. After
retaining the terminal handoff, close completed agents where supported. If fresh
creation is blocked and capacity cannot be released, reuse an idle context as a
last resort with a complete reauthenticated handoff. A candidate's author or
implementor cannot review it. If no independent reviewer is available, report
that specific blocker rather than self-approving.

For provider model capacity failures, follow the [daily recovery rule](start-an-issue.md#wait-recover-and-resume):
preserve work, establish job state and use only authorized model/effort fallbacks.
Keep optional fallback choices in the map to avoid repeated owner decisions;
model availability does not justify a capsule replan or duplicate dispatch.

The capsule records the objective/issue, base/branch, permitted edit scope,
checkable acceptance criteria, required test commands and known prerequisites.
Use the [shared RI Markdown capsule format](start-an-issue.md#capsule-format).
Projects supply values and necessary extra fields, not a replacement format.
RI adds no mandatory JSON
schema, signed packet, planning-history layout or finite launch budget.
Independent scope challenge is optional unless a separately adopted project
requirement needs it; do not add a second review just for changing ordinary files.

## Required task completion

Each capsule must include these requirements in its existing task record; no
additional report or gate file is needed:

- Resolve objective/specification gaps before implementation. Do not invent
  product parameters or expand the objective to make a task executable.
- Update affected current documentation, examples, local maps and incoming links
  when behavior, commands, versions or workflow change. Remove stale or
  contradictory wording within that affected surface. Identify those paths in
  scope; preserve clearly marked historical records. Record a supported
  not-applicable conclusion when no documentation is affected. This does not
  require a repository-wide documentation rewrite for every task.
- Give every acceptance criterion a concrete test or inspectable source/result;
  report failures and skips honestly. A passing aggregate test count does not
  prove an omitted required case. Explain any required proof left unexecuted.
- At each handoff, return the source/branch identity, completed work, actual
  results, unresolved findings and next permitted action. Supply each role with
  its selected [worker instructions](worker-instructions.md#role-index), task inputs and relevant project
  requirements; workers do not repeat controller orientation. Controller
  checks returned scope and evidence before dispatching the next role; it does
  not implement or self-review the assigned source changes.
- Review the affected documentation alongside code and tests. Approval and
  relevant test evidence must cover the candidate actually integrated. If that
  candidate changes, reconcile the diff and obtain affected checks/review before
  integration; do not transfer a verdict silently to new bytes.
- Close only after verifying authorized integration (or the reviewed no-change
  outcome) and all original criteria,
  including any explicitly deferred installation/closeout obligations. Retain a
  concise result and necessary evidence in the existing project record. Remove
  only the verified merged task branch when safe; preserve unrelated work and
  unmerged recovery evidence. If any required outcome remains pending, leave
  the issue open and state it. Follow the [daily closeout step](start-an-issue.md#execute-serially)
  to reconcile current task-state references; historical records remain unchanged.
  Prefer task-neutral maps with a pointer to the active checkpoint.

Record each post-installation obligation's stage and satisfaction method in the
capsule. Review its implementation and check plan before integration; perform
installed checks afterward and before closure. Do not demand proof that depends
on prior approval, or defer prerequisites already due. Installed failure leaves
the issue open for bounded recovery.

Before dispatch, confirm the role's required access/runtime and command environment.
Planner intake needs the objective/base, not its future capsule/candidate. Rehearse
known sandbox-sensitive commands narrowly; no mandatory adoption specimen chain.
Setup proof does not replace actual candidate checks or honest results/skips.

Review covers the full change, original criteria and applicable standards. A
normal supported independent subagent reading source/diffs/logs is sufficient
for RI; RI does not require a custom app-server gateway, report-file schema,
retrieval transcript or OS isolation harness. Preserve independently required
project confidentiality and permission boundaries. Use the project's supported
review route if one is required for reasons independent of RI.

## Waiting and recovery

Follow [the daily waiting and recovery rules](start-an-issue.md#wait-recover-and-resume).
Native subagents use an event-based blocking wait; idle wake-up requires separate
verification. Queue is conditional on a supported observer and verified delivery.
Do not inspect unfinished work or fill waiting time with monitoring. Diagnose
suspected missed delivery from available completion/delivery/continuation events,
not from a human bump alone. A failure callback starts bounded diagnosis, not an
automatic cascade of prerequisite capsules. Check actual callers and the
controlling requirement before declaring a repair necessary.

Set any required finite deadline according to the actual task size and host
limits. Do not impose an arbitrary 300-second model-review cap. Validate the
timeout before dispatch, allowing for instruction/source
reading and producing the verdict. Preserve genuine historical timeout receipts;
they are not current configuration. If a timeout occurs, reconcile completion
and cleanup before an authorized recovery rather than repeatedly launching the
same full review under a known inadequate limit. Host-enforced hard limits must
be reported and handled through a supported route, not bypassed.

Routine evidence reads, role clarification, handoff validation, cancellation,
cleanup and authorized in-scope recovery are included in the task authorization.
Do not ask the owner again just to discover why an assigned role stopped.
Request new authority only for a concrete uncovered scope/permission/disclosure
or reserved action. Respect host denials and actual project limits.

When a blocker appears, hold edits and consequential actions. Perform one bounded
read-only sweep of related task/runtime/command/delivery prerequisites within
existing authority; return supported blockers together with unknown/unchecked
items. Uninspected evidence is not failed authentication. Opening progress is
nonterminal. Follow the [daily last-resort recovery rule](start-an-issue.md#wait-recover-and-resume)
before STOP_REPLAN, replan, scope expansion or broader-authority requests: verify
exact source, controlling requirements and existing authorized routes; prefer
bounded correction and valid work reuse. STOP_REPLAN is not an opening
acknowledgement. Confirmed violations or explicit owner stops halt
execution immediately; read-only diagnosis may continue if permitted.

If a stop is already terminal, preserve it. A diagnostic-only follow-up can
explain that attempt without resuming it. Correct ordinary in-scope defects under
the existing task authority, preserving useful code. Replan only for actual
changes to objective, scope, base or authority. Do not reset existing allowances
or invent unlimited retries. Lost replies require checking actual operation state
before repeating a launch or integration. If main moved, compare the actual
integration result with the reviewed candidate; changed source or merge resolution
needs affected checks and independent review before acceptance. After compaction,
recover the current phase, selected instructions, source, active job and pending
obligations from the existing checkpoint. Do not launch a duplicate job or restart
planning merely because conversation context was lost.

Repeat checks when their relevant inputs change or project rules require them.
Prior results keep their original source/command/environment identities; do not
present reused evidence as newly executed. Retaining unchanged evidence requires
the project's accepted equivalence policy, not an RI waiver. RI imposes no broad
native/backend run solely because a packaging or documentation record changed.

## Replace an entangled adoption

An owner-authorized replacement may proceed as bounded ordinary maintenance;
it need not repair the obsolete adoption mechanism before retiring it. Preserve
paused product work and historical evidence. Inspect actual dependencies and
classify each local RI artifact as keep, remove or replace in the existing record.

Keep independently needed product tests, permissions, standards and acceptance.
Remove duplicate procedure and machinery used solely for the retired RI route.
Repair incoming references and tests of the changed interfaces. Archive historical
receipts without requiring them as inputs to new daily tasks. Do not delete
unrelated local work or discard source/evidence needed for retention.

Implement on a reversible branch, run meaningful focused checks and documentation
checks, obtain one independent review through the simplest supported route, then
use the owner-authorized integration commands. Verify current entrypoints select
only this route and a compatible runtime. Retire obsolete prerequisite issues as
superseded after integration eliminates their need; do not call their failed
implementations successful. Keep product issues paused until separately resumed.
