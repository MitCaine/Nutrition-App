# Start an issue — author and independent reviewer

This is the single current issue procedure. Read it, the project's current
`docs/local_project_map.md`, complete live issue and required decisions, and applicable
project instructions before acting. Recover truncated inputs. Setup and package
references are conditional; a link does not require reading every linked document.
The [common contract](worker-instructions.md) supplies reviewer duties. Historical
capsule and dispatcher resources are unselected for new work, not additional stages.

## Intake

One Work author performs source-grounded engineering and implementation. A fresh
independent Work reviewer examines the exact candidate. The author also coordinates
checks, records a separate approval after review, and performs only authorized
publication, integration and closeout. The author cannot supply independent review.
Use the [selected configuration](new-project-setup.md#role-model-and-effort-defaults)
and explicit applicable owner overrides. Neither tools nor a role name grant authority.

A new or existing chat may start through `ri-work-kickoff`. Fresh author chats are
optional when preferred by the owner or needed for unreliable context. Before each
new issue, authenticate repository path, HEAD/base, current map and selected
instructions separately; preserve parked branches and unrelated edits. Reconcile
existing assignments from authoritative checkpoints and native job state. An empty
assignee or default checkpoint does not prove inactivity. A kickoff during unfinished
work recovers that work rather than replacing it or duplicating an assignment.

Establish the issue's bounded scope, settled decisions, authority and checkpoint in
existing records. Inspect directly linked operational docs before fixing allowed
changes. Do not reconstruct missing product decisions from issue history or guess
parameters: return unresolved consequential choices to the owner before dependent
work. Relevant source, callers, tests and contracts beyond initial pointers are
permitted reads; they do not expand edit authorization. No rigid reading/file limit.

Reuse applicable standing grants and unchanged accepted settings; prior issue
approvals and evidence are not new authority or proof. Follow [access and authority](new-project-setup.md#access-and-task-authority).
Active attempts retain their instruction/runtime identity. New issues use the then-
adopted revision. An instruction migration must reconcile local validators and
actual callers explicitly, without bypassing qualification or repinning active work.
After verified closeout, advance an authorized queue under [queue rules](new-project-setup.md#issue-queues).

## Engineering and implementation

In the existing task record retain the objective/original outcomes, exact base,
allowed changes, consequential decisions, relevant design/context, and expected
checks. Keep it concise and sufficient to implement and review. No mandatory capsule,
six-heading format, planning-only publication, separate creator, planning reviewer,
dispatcher, Luna implementor, pseudocode or second planning handoff is required.
Unresolved design or substantial migration calls for enough engineering to settle
it, or an owner decision; it does not automatically create more roles or a framework.

### Task-directed source preparation

Use the project's compatible Tree-sitter source-navigation route where applicable
and useful. Start with relevant terms and paths, inspect exact returned source and
owning symbols, then follow relevant callers, interfaces, contracts and tests.
[Navigation](https://github.com/MitCaine/repository-intelligence/blob/6058b143610c1902faf1bf832227359c9fc4f5a4/docs/consumer-guide.md#navigate-before-expanding-scope) supplies locations,
source identity, parser/coverage and lexical hints, not a resolved call graph or
engineering judgment. Retain the actual invocation/output and limits in existing
evidence, or reference eligible unchanged results. Documentation-only work needs no
meaningless parse. Unsupported syntax, zero matches, incomplete coverage or missing
tooling remain explicit; where a project requires a selected operation, resolve its
unavailability under that project's authority rather than silently substituting.

Tools derive mechanical facts from their owning definitions: dependency/input
inventories, identities, validated command options, native case outcomes and retained
artifact references. Do not handwrite another inventory when the selected runner can
supply it. Missing consumer wiring is an owning-component gap, not completed automation.
Use [tool boundaries](capsule-controller-workflow.md#keep-the-integration-small).

Implement coherent groups of related behavior and proof within authorized scope.
For a new path to existing behavior, inspect the established validation, contracts
and relevant callers; preserve applicable invariants unless a difference is authorized.
Test distinguishing valid and invalid cases, including terminal states, ownership
and allocation limits where relevant. A failed focused check permits ordinary bounded
correction, not automatic replanning. Preserve failures, valid work and original
source identities. If wider impact emerges, pause only the affected part for a scope
or consequential-decision resolution; do not silently expand edits or discard proof.

Before claiming ready, reconcile all original outcomes and individually prescribed
proof against actual execution, native case results and readable retained artifacts.
Use the project's existing automated reconciliation binding where selected; do not
invent a parallel report, registry or per-declaration verdict. Missing already-due
proof blocks readiness. Legitimate installed checks remain due with their owner.
Tools establish mechanical coverage; the independent reviewer judges assertion
adequacy and fidelity to the original requirements.

## Execute serially

### Publish the task branch and handoffs

Use the project's existing task branch, source-capture and evidence route. Publish
the exact candidate when its authority/procedures require it and verify the remote
identity before independent review. No new export, manifest, upload or local copy
is required by these words. Finalize tracked preparation before freezing the candidate;
subsequent operational outcomes stay external under the completion rule below.

### Execution routing, models and efforts

The [setup mapping](new-project-setup.md#role-model-and-effort-defaults) owns the
selected author/reviewer defaults. Record requested settings separately from owner-
confirmed selection, host-confirmed settings and unresolved telemetry under the map's
accepted policy. Unknown telemetry proves neither mismatch nor compliance. Do not
infer product mode from tools, backing metadata or an agent's self-description.
Reuse unchanged accepted selections without repeated owner confirmation. An actual
launch failure differs from unsupported configuration or missing telemetry; only
confirmed provider capacity failure uses capacity recovery.

### Complete the phases

1. The author completes engineering, code and affected documentation; runs selected
   checks and reconciles due outcomes against real evidence. Authenticate the exact
   candidate, full integration baseline and proposed diff, scope and proof before
   requesting review. Do not report a matching check name or aggregate exit as proof.
2. Assign one fresh nonauthor reviewer the original issue/settled decisions, task
   record, exact candidate/full integration diff, applicable standards and actual
   evidence. Use [reviewer instructions](worker-instructions.md#independent-reviewer).
   This is the normal separate assignment, not a mandatory earlier planning review.
3. Preserve all findings. The same author corrects in-scope defects and selects
   affected checks/re-review under evidence eligibility. Corrections retain full
   integration scope; a small correction diff does not hide earlier changes.
4. After independent PASS for the actual candidate and all due project gates,
   record the author's separate approval and use authorized integration. Verify
   resulting main/source and pending installed obligations. A new integration
   source requires affected checks/review, not approval transfer.
5. Close only when every required outcome passes or a reserved decision explicitly
   changes it. Verify issue closure and safe owned-ref cleanup. Partial integration,
   installed verification or cleanup remains partial, with exact remaining obligations.
   Reconcile current task references/checkpoint; keep maps task-neutral and clearly
   historical preparation/stops intact. Do not add a tracked completion commit.

Additional assignments are conditional recovery for concrete failures or an explicit
owner/project requirement, not the retired normal ladder under new names. Do not
review one's own work, silently take over another editor, or duplicate active jobs.
A replacement authenticates the existing job, source and retained decisions first.

### Command readiness

Before establishing or changing inputs to a required downstream gate, verify
its applicable source, history, authorization and configuration constraints.
Resolve conflicts before acting. Use bounded prerequisite checks, not premature
qualification; recheck when relevant inputs change. History constraints and any
authorized-base reconciliation are defined by the consumer project, not a
universal RI linear-history requirement.

The actor launching a command verifies its required inputs in the actual
execution context before expensive or dependent work: command, working directory,
paths and effective child configuration, not merely the parent's. The author verifies reviewer-launch prerequisites and may
rely on authenticated launcher or worker checks. Examples include guarded
authentication, temporary paths, recovery objects, runner acceptance of executable
paths (including symlink handling), and CI trigger/check identity.
Use the smallest sufficient checks, not a product-suite rehearsal or unrelated
setup investigation. Reuse readiness only while relevant inputs remain unchanged;
recheck affected prerequisites on changes or capability failure, and report
unresolved prerequisites before proceeding. After setup fails, continue only
checks whose own prerequisites are satisfied. Results qualify for acceptance only
when source, dependencies and environment meet the selected requirements;
otherwise label them diagnostic and report required checks still blocked.
Where required gate order permits, run inexpensive source-validity, compiler and
lint checks before
costly qualification. On failure, report before further expensive checks unless
the assignment requires collecting independent results. This grants no frozen
candidate edits or omission of required checks.

### Select checks and control runtime

Select required checks in the existing task record before
implementation, with literal commands, intended phase, affected scope, relevant
transitive inputs/environment and the reason for broader coverage. During
implementation test changed behavior and affected callers. After correction rerun
failed cases and checks affected by the correction; the author updates the
selection when scope changes. Before acceptance run broader checks required by
the actual change risk and project gates. A full suite needs a project requirement
or a concrete cross-cutting risk, such as shared execution, authentication or
serialization. Do not repeat it automatically after every correction; an ordinary
documentation pin change does not itself justify expensive integration fixtures.
Assigned reviewers follow this selection rather than guessing which required checks to skip.

Use owning runner records for individual durations, command/source identity and
relevant dependency/tool/configuration bindings. Reuse unaffected evidence only
under [input equivalence](#evidence-eligibility-and-corrections), preserving its
original execution identity. A wrapper's total time is not each nested gate's time;
missing input coverage or runtime data remains unknown, never inferred.

Give expensive suites project-defined runtime investigation budgets in their
existing check definitions, informed by retained measurements where available.
Tooling signals exceedance for bounded investigation before further expensive
work; an actual completed pass and an exceeded budget are separate observations.
A budget does not waive required proof or convert a timeout, omitted test or
unfinished result into PASS. Preserve those as incomplete and reconcile the active
operation before retry. Missing budget controls are an owning-runner integration
gap, not permission to invent a pass or another monitoring framework.

### Retain evidence and dispose of owned outputs

Use the existing task/execution and closeout records for the lifecycle of local
workspaces and generated outputs. At creation, the consumer's actual output owner
mechanically records the task/attempt, exact path and filesystem identity from the
same selected definition that creates and validates the output. Do not ask an agent
to maintain a second inventory. Existing unknown directories are not owned merely
because their names look familiar, they are ignored, or they are under a temporary
root. Consumer adapters own build-target, cache, worktree and runtime semantics;
the optional [worker-output interface](workflow-tools.md#task-output-lifecycle)
can carry those observations, but does not discover owners or grant authority.

Before disposal, reconcile current assignments and processes. Only an exclusively
owned regenerable output after verified completion, or a superseded **terminal**
attempt no longer needed for recovery, can be eligible. Preserve active and paused
work, live/shared/reused caches, unique uncommitted source, referenced exact-source
inputs, and selected runtimes/helpers even under temporary roots. A pushed branch
preserves committed source, not ignored files, logs or unique work. Unknown ownership,
use or retention blocks that item, not unrelated verified-safe items.

First retain required successful/failed results, raw logs, review/approval and source
recovery in the project's existing durable evidence area. Verify complete coverage,
readability and original hashes there. Relocate current required references and
verify they resolve before removing originals; retain original execution/source/
environment identities. An incidental historical path mention does not require
keeping every regenerable cache. Do not repair failed history or attribute a missing
runtime to cleanup without evidence.

Use the existing closeout route for a dry-run of exact paths, ownership, current
eligibility, measured sizes and leftover reasons. Recheck path/ancestor identities,
symlink/escape hazards, protected inputs and retention immediately before authorized
execution; exclude concurrent writers and activity using the consumer's existing
mechanism. Prefer recoverable disposal where practical. Permanent deletion of user
data or uncertain artifacts requires specific authority, not this instruction.
Record actual per-item outcomes, safe retries and partial failures truthfully.
An absent owned path is a no-op, not newly reclaimed space; quarantine retains its
bytes, and logical file sizes do not establish physical disk reclamation. Report
reclaimed bytes only when measured, otherwise unknown. Retain uncertain leftovers
with their reasons. No global cache purge, budget, watcher, extra stage or new state
store is required. Necessary consumer wiring and its normal-path tests remain
separate from the shared interface; adopting these words alone proves no cleanup.

### Keep completion records external

Finalize tracked preparation records before freezing the candidate for
exact-candidate qualification and review: label preparation snapshots historical
and point current status to the live issue and external author checkpoint.
Record subsequent check attempts and operational outcomes, including integration,
issue closure and cleanup, externally in those existing records. Do not create
another candidate merely to append completion evidence. A necessary tracked
correction creates a new candidate and follows the existing affected-check,
review and authorized-publication rules; operational bookkeeping does not.

## Wait, recover and resume

### Wait for completion

- **Native subagents:** use the supported event-based blocking wait. Ordinary wait
  expiry means continue waiting; delivery failure or a task deadline permits bounded
  reconciliation of authoritative job state, terminal evidence and cleanup before
  retry, never an unfinished-work inspection or monitoring loop. Result
  delivery to an active parent does not prove an idle parent will start a new turn.
  End the turn only with verified idle wake-up for that author/host route.
- **External jobs:** use native delivery or the [queue skill](https://github.com/MitCaine/repository-intelligence/blob/6058b143610c1902faf1bf832227359c9fc4f5a4/docs/skill-templates/capsule-queue/SKILL.md)
  with a supported watcher and verified wake-up. CLI acceptance alone is not
  consumption. Reuse a proven route until it changes or fails; do not add duplicate
  notifications or restart a job to attach a watcher. Otherwise keep blocking wait.
- **While waiting:** no status polling, active-workspace/log/test inspection,
  repetitive commentary or interim acceptance judgments. Keep routine progress
  in existing records, not user-facing updates. “Still waiting,” “no new evidence”
  and ordinary blocking-wait expiry are not reportable events. Surface terminal
  results, actionable blockers requiring intervention, or requested status replies.
  Verify candidate scope
  and evidence after terminal handoff. Receive unsolicited progress without
  starting a monitoring loop. Use task-appropriate deadlines; supported wait
  resumptions at host limits do not authorize extra checks.
- **After a status reply:** resume the recorded next authorized action, or return
  to blocking wait for active work. Suspend only for an explicit pause, missing
  authority or a confirmed blocker; answering a question does not end the task.
- **Intervene only** for a delivered actionable blocker/clarification, concrete
  safety concern, failed delivery or owner status request, then return to waiting.
  Wait by default. Independent preparation must be one genuinely useful, named,
  already-authorized activity identified beforehand that
  does not inspect or depend on unfinished work; stop when its output is complete.
- **Diagnose delays from events:** distinguish dispatch, terminal completion,
  delivery and author continuation. Use existing records where available;
  mark missing timestamps unknown. A human bump alone does not prove a terminal
  result was waiting or that notification failed. No new timing ledger is required.

### Diagnose blockers and recover

At a blocker, hold consequential work and do one bounded authorized read-only
sweep to consolidate real failures and unknowns. Routine clarification, diagnosis
and in-scope correction need no repeated human approval. The author
may diagnose and repair ordinary compile, lint and test failures throughout the
accepted task scope and authorized edit boundaries without a new grant or handoff
for each fix. Before nontrivial correction, inspect the complete supplied review/failure
set. Establish the observed failure and causal evidence; reexamine implementation,
fixture, independently justified expectations and execution setup when they conflict.
Inspect relevant source, tests and callers for related uses sharing the assumption,
including incomplete migrations, and choose a distinguishing check. Revise only
affected working references to original obligations before building on changed assumptions.
Incomplete evidence permits bounded probes and explicit uncertainty, not a confident
diagnosis. Scale obvious compile/format fixes proportionately; no new planning stage,
whole-file mandate or grant is required. Repair related mistakes within authorized
edits before costly qualification, preserving intentional historical behavior.
The terminal handoff accounts for every applicable finding as addressed with new
evidence, unresolved or needing an owner/author decision; a partial repair cannot claim
correction-complete. Never weaken tests or change expectations merely to match output,
or guess acceptance
decisions. Requirement changes, protected inputs, wider scope or new
permissions return to the author. STOP_REPLAN, replan,
scope expansion and requests for broader authority are last resorts. First verify
the blocker against exact source, controlling requirements and existing authorized
routes; distinguish observed failures from assumptions. Prefer bounded in-scope
correction and reuse valid work. Report confirmed blockers promptly; never bypass
required checks. A failed command or terminal worker handoff does not itself stop
an active task: preserve the result and use authorized in-scope correction.
An explicit task/attempt stop or owner pause blocks execution until continuation
is authorized; diagnosis grants no continuation authority. STOP_REPLAN is not
opening progress, and later success cannot clear a terminal stop. Request new
authority only for uncovered scope, permission, disclosure or reserved actions.

After roughly three rejection/correction rounds in the same stage, use a fresh
diagnostic reviewer only for a concrete repeated failure. Supply original
requirements, relevant source, task record and retained rejection history. Ask it to
identify missing decisions, an incomplete task record, missed implementation requirements
or incorrect workflow execution, and return one bounded correction. Preserve valid
completed phases; this conditional recovery is not another normal review or an
automatic increase in effort. Record the trigger and scope in the checkpoint.

Identify the authenticated correction recovery source separately from the full
integration baseline. A correction does not reset task scope or narrow acceptance
to its own diff. Supply the full proposed integration diff and retained findings.
Keep correction handoffs short: identify the rejected finding, authorized changes,
recovery source, changed execution inputs, required checks and return destination.
Reference unchanged instructions/evidence by authenticated accessible location;
repeat only to resolve ambiguity. Workers still read their required role-specific inputs.

### Evidence eligibility and corrections

Use the [shared disposition contract](workflow-tools.md#consequential-dispositions)
for consequential judgments and obligation coverage; author and reviewer retain
separate authority.

Checks must use a stable, identifiable source snapshot. Authenticate tested source,
command/workflow and evidence identity; a matching name or aggregate exit code
does not establish that every required gate passed. A source or relevant-input
change during a check makes its result ineligible. Evaluate each gate's actual exit/result,
including failures/skips; resolve failed required gates before acceptance.

After correction, the author applies [check selection](#select-checks-and-control-runtime)
and selects reruns from changed inputs and the
project's accepted evidence-equivalence policy. Preserve eligible results under
their original source/command/environment identities; never label them newly
executed. Run full qualification when required, or record why reuse is insufficient.
Rerun affected checks when equivalence is unknown. Equivalence covers relevant
transitive inputs and environment changes, not merely unchanged tests/helpers.
Reviewers follow assigned checks and cannot waive them independently.
When a reported pass conflicts with a later result, compare source, command,
working directory, toolchain and configuration. Record the demonstrated cause or
remaining uncertainty; do not reuse the earlier pass without establishing its
eligibility. A successful repetition alone does not explain the discrepancy.
Changed integration source needs affected checks/review.

### Handle model capacity

Provider model capacity is an availability failure, not a task defect or an
agent-slot limit. Dispatch once. On confirmed capacity failure, first establish
whether work started or remains active; preserve the assignment and partial work.
If safe to redispatch, try one map/owner-authorized model/effort fallback and
record the actual selection. If none is authorized or that attempt also fails,
save the checkpoint and report the availability blocker. No retry loop, repeated
availability polling or follow-up messages merely to test capacity. Retry the
original model only on a new availability signal from the host/provider or an
explicit instruction; elapsed time alone is not such a signal.
Do not replan, reset allowances or launch parallel duplicate jobs. Resume an
interrupted nonterminal assignment only after checking its state; a replacement
keeps the bounded handoff and role independence. Idle-agent reuse cannot solve
unavailable model capacity.

### Checkpoint and resume

The project map names the active checkpoint and standard closeout route. Update
that checkpoint after each authenticated transition, retaining phase, selected
instructions, source, active job, results, pending obligations and next action.
Record unknown or partial outcomes honestly and preserve this state across
compaction. On recovery, reconcile the checkpoint with authenticated source,
active-assignment state and retained terminal evidence before selecting the next
action. Preserve history and record the reconciliation; do not repeat completed
work merely because the checkpoint is stale. This grants no additional writer
or dispatch authority.
After a lost response, establish the actual operation state before repeating a
launch or integration; an uncertain reply is not proof that the action failed.

If fresh agents cannot be created or freed,
last-resort idle-context reuse is permitted with a complete handoff. The candidate
author must never be its reviewer. If independence is unavailable,
report that blocker. No allowance reset or self-approval is permitted.

## Historical route compatibility

The following anchors preserve incoming references from pinned tools and historical
resources. They do not select old role instructions for new work. Consumers still
using those contracts migrate explicitly; do not bypass a local validator or rewrite
old evidence. The previous complete procedure is retained at
[the last pre-migration revision](https://github.com/MitCaine/repository-intelligence/blob/c25603685e66cd057db12026f3701e33cb456b60/docs/start-an-issue.md).

### Optional maintenance route

Historical compatibility reference; use [the current issue procedure](#intake) for new work.

### Controller-authored mechanical corrections

Historical compatibility reference; use [the current issue procedure](#intake) for new work.

### Experimental engineering route

Historical compatibility reference; use [the current issue procedure](#intake) for new work.

### Capsule format

Historical compatibility reference; use [the current issue procedure](#intake) for new work.

### Assign roles and supply inputs

Historical compatibility reference; use [the current issue procedure](#intake) for new work.

### Work-to-Codex implementation handoff

Historical compatibility reference; use [the current issue procedure](#intake) for new work.

### Additional assignments and orientation

Historical compatibility reference; use [the current issue procedure](#intake) for new work.

### Planning-only and no-change outcomes

Historical compatibility reference; use [the current issue procedure](#intake) for new work.
