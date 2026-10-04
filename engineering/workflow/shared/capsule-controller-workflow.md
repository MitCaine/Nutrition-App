# Lightweight controller workflow with RI

This is the default RI-assisted workflow for projects adopting or explicitly
replacing an RI workflow. RI supplies source navigation/comparison; it does not
require a special capsule runner, SDK transport, evidence exporter or approval
service. Existing projects adopt this replacement under owner authority rather
than silently bypassing their current controls.

## Keep the integration small

Keep one short project map in the existing entrypoint. Record the selected RI
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
Planner: dedicated branch + bounded Markdown capsule/task record
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

The capsule records the objective/issue, base/branch, permitted edit scope,
checkable acceptance criteria, required test commands and known prerequisites.
Use the project's existing task format where useful. RI adds no mandatory JSON
schema, signed packet, planning-history layout or finite launch budget.
Independent scope challenge is optional unless a separately adopted project
requirement needs it; do not add a second review just for changing ordinary files.

Before dispatch, verify actual required access/runtime and that the commands are
usable in their intended environment. Use a small relevant rehearsal for a known
sandbox-sensitive command; no mandatory full adoption specimen chain. Setup proof
is not candidate proof. Run required project checks on the candidate and preserve
actual results/skips. Do not replace a project's substantive tests with RI output.

Review covers the full change, original criteria and applicable standards. A
normal supported independent subagent reading source/diffs/logs is sufficient
for RI; RI does not require a custom app-server gateway, report-file schema,
retrieval transcript or OS isolation harness. Preserve independently required
project confidentiality and permission boundaries. Use the project's supported
review route if one is required for reasons independent of RI.

## Waiting and recovery

Use native completion or one supported bounded blocking wait. Queue is useful
only for an external gate lacking native completion. No repeated controller
polls or invented work to avoid waiting. A failure callback wakes diagnosis,
not an automatic cascade of prerequisite capsules.

Set any required finite deadline according to the actual task size and host
limits. Do not inherit an arbitrary 300-second model-review cap from retired RI
transport. Validate the timeout before dispatch, allowing for instruction/source
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
nonterminal. STOP_REPLAN is a last-resort result for an established blocker, not
an opening acknowledgement. Confirmed violations or explicit owner stops halt
execution immediately; read-only diagnosis may continue if permitted.

If a stop is already terminal, preserve it. A diagnostic-only follow-up can
explain that attempt without resuming it. Correct ordinary in-scope defects under
the existing task authority, preserving useful code. Replan only for actual
changes to objective, scope, base or authority. Do not reset existing allowances
or invent unlimited retries. Lost replies require checking actual operation state
before repeating a launch or integration.

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

The [historical extended controller reference](archive/extended-controller-workflow-2026-10-02.md) and its
[evidence helper templates](skill-templates/README.md) remain optional material
for separately justified consumer controls, not extra gates in this default route.
