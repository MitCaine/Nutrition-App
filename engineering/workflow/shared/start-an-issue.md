# Start an issue in an established project — controller

**Read all directed orientation before acting:** this procedure, project-root
`docs/local_project_map.md`, the complete live issue and required linked
specifications/decisions, and applicable project instructions. Resolve conflicting
or missing inputs before dependent decisions, edits or dispatch; summaries do
not replace unread requirements. Read in bounded sections and recover truncated
portions before reliance. Select the checkpoint's active object, not its history.

This is the controller’s complete daily entrypoint. Workers use their own
[worker instructions](worker-instructions.md#role-index), not this whole procedure. Read
relevant source/standards as needed; RI architecture, setup and adoption history
are conditional. The project README/AGENTS points to the exact map above. If it
is missing, report and resolve that adoption input rather than substitute another
map or guess.

## Intake

Start each new issue with a fresh controller context. A replacement during an
active issue recovers its authenticated checkpoint and existing assignment;
replacement is not a new attempt or permission to duplicate dispatch.

- Check the map's selected instruction identity, compatible runtime, role/model
  settings, commands, standards and permitted Git/issue actions. Use the adopted
  version throughout the attempt; do not silently select new instructions,
  reinstall skills or upgrade the runtime. Resolve a conflicting map first.
- Authenticate the live issue, current base/branch and checkout. Preserve unrelated
  edits. Check for an active task/checkpoint before starting a duplicate attempt.
- Resolve missing product decisions; do not invent requirements or parameters.
  Check a suspected prerequisite against actual current callers, reachable behavior
  and its controlling requirement before expanding scope or starting a repair.
  Only a concrete changed setup input or failed capability needs setup diagnosis.

## Capsule format

RI owns this shared capsule format for every adopting project. Use one ordinary
Markdown task file with these headings:

- **Objective:** live issue and original required specifications/decisions.
- **Source and scope:** base revision, task branch, authorized edit paths and
  affected current documentation; preserve unrelated work.
- **Acceptance:** individual checkboxes stating observable outcomes and each
  outcome's concrete test or inspectable evidence, including documentation.
- **Checks:** literal required commands, intended environment and results to retain.
- **Prerequisites:** known dependencies, unresolved decisions, and any genuinely
  post-installation obligation with its satisfaction method.
- **Handoff and closeout:** authorized actor/actions, exact returned source/results,
  pending work and verification before issue closure and safe branch cleanup.

Keep these headings and their meaning the same across projects. The local map
supplies project values, commands, standards, permissions and the capsule storage
location; it points to this section in the selected RI instructions. Projects may
add necessary fields but must not replace the shared structure or duplicate its
instructions in a competing local template. No extra schema or historical runner
template is implied. Preserve frozen historical task formats without applying
them to new tasks.

## Execute serially

```text
Controller -> capsule builder -> controller checks plan
           -> implementor    -> controller checks candidate/results
           -> reviewer       -> controller integrates and closes
                        findings -> bounded correction -> review
```

### Assign roles and supply inputs

The controller owns assignment dispatch, including the bounded Codex dispatch
delegation below. Run assignments one at a time, using fresh
contexts by default. The normal path uses one capsule builder, one implementor
and one independent reviewer; already-satisfied work may use the no-change route
below. Workers do not recruit other workers.

Each assignment names its immediate return destination by concrete identifier and
the actor responsible for onward relay. Return the terminal handoff through that
route; the relay actor confirms controller consumption. A local report or send
acceptance does not establish delivery. Use the selected supported manual route
when direct messaging is unavailable.

### Execution routing, models and efforts

| Role | Execution environment | Model | Reasoning effort | Selector label |
| --- | --- | --- | --- | --- |
| Controller | Work | `gpt-6.1-sol` | `low` | Sol 6.1 Light |
| Capsule builder | Work | `gpt-6.1-sol` | `low` | Sol 6.1 Light |
| Implementor | Codex | `gpt-6-luna` | `max` | Luna 6 Max |
| Independent reviewer | Work | `gpt-6.1-sol` | `low` | Sol 6.1 Light |

Environment, model and effort are separate settings. Use the map's supported
route and these defaults unless the owner/map authorizes an override; no new
launcher or service is required. Configure each worker explicitly before dispatch
and match the full model ID: Sol 5.6/6 and Luna 5.6 do not satisfy these defaults.
Record requested settings separately from host-confirmed settings. A selected
host mode or authoritative configuration/session record confirming the setting
is sufficient evidence; dispatch options establish only what was requested.
The project map names accepted confirmation for required settings and the
response when confirmation is unavailable; it may select a shared policy.
Unknown proves neither compliance nor mismatch. Proceed only under that
authorization. Do not infer product mode from tool names, backing metadata or
an agent's self-description.
Distinguish confirmed configuration mismatch, unavailable routing, unknown
settings and confirmed provider capacity failure; apply capacity recovery only
to the last. Diagnose other failures narrowly and never silently substitute
an environment, model or effort. These settings do not reduce role duties.

When an owner asks a particular model to personally audit or review, that model
must perform the substantive inspection unless delegation is authorized. A
delegated review plus controller sign-off is not equivalent. Identify the actual
reviewer, environment, model/effort, controller's own inspection and evidence
limits; distinguish requested settings from verified settings.

### Work-to-Codex implementation handoff

Native subagents stay within their host; changing a model does not switch Work
and Codex. For mixed routing, use an existing Codex chat as a bounded implementation
dispatcher:

```text
Work controller -> Work capsule builder -> controller checks/publishes plan
                -> Codex chat -> one Codex implementor -> Codex terminal handoff
                -> Work controller verifies -> Work reviewer -> controller closeout
```

The owner creates the Codex chat, or explicitly authorizes its creation, and
authorizes messaging in both directions. Before implementation, verify both chats'
actual messaging and result-recovery capabilities with a small harmless handoff.
Reuse the established route until it changes or fails; sent-message acceptance
does not prove consumption or idle wake-up. Apply the existing waiting/recovery
rules, without polling loops or another transport framework.

Use one reusable Codex dispatcher chat per project with the selected
[dispatcher section](worker-instructions.md#codex-dispatcher). For each issue, give it the
implementation handoff location: exact task/attempt, published capsule/branch/SHA,
selected role instructions and bounded implementation inputs, read/edit scopes, checks,
evidence locations, Git ownership and return destination. The dispatcher launches
the implementor under the selected
[context and fallback rules](worker-instructions.md#read-and-dispatch), then relays
its terminal result; it does not repeat controller orientation, replan, review or
integrate. Only the assigned actor edits/publishes;
prevent simultaneous edits. Work authenticates the result before independent
review. Unavailable routing requires an explicit decision, not substitution.

### Additional assignments and orientation

An additional substantive assignment requires one of these reasons:

- A specific rejected deliverable or failed required check.
- An authorized scope change.
- A confirmed inability of the assignee or host to proceed.
- An independent scope challenge permitted in step 2.

Before dispatch, record the reason and bounded objective in the existing
checkpoint. Existing availability and recovery limits still apply. Clarification
stays within the current assignment; do not use it to introduce new substantive
work. Preserve completed phases and limit recovery to necessary corrections,
affected checks and independent re-review. Routine controller verification,
bookkeeping and closeout do not justify another assignment.

Retain and authenticate each completed agent's terminal handoff before closing
it through the host's supported operation to free capacity. Do not close running
agents. Give each worker its selected [worker instructions](worker-instructions.md#role-index), bounded
task inputs appropriate to its role, applicable standards, authorized source-read
locations, commands, edit limits and actual evidence. Original issues and required
decision history go to the builder and reviewer; the implementor receives a
complete accepted capsule and bounded implementation inputs, and the dispatcher
only authenticates and relays the handoff. Follow the role-specific reading rules. Supply the relevant
project-map requirements and their original locations; workers do not repeat
controller intake or workflow selection. Do not supply the whole controller
procedure as mandatory worker reading. Authenticate role resources from the same
adopted RI revision; record their locations in the existing handoff.

For example: “Your role is Implementor. At the selected RI revision, read
`docs/worker-instructions.md` sections Shared worker rules and Implementor in full.
Then read the accepted published capsule, authorized implementation source and
applicable implementation standards linked in this handoff. Do not retrieve the
original issue or decision history.” Name stable headings, not line numbers;
use a section-bounded read where supported, since an anchor alone does not limit
loaded context.

Before builder dispatch, supply it with the original issue and required
orientation sources, their selected identities/locations, confirmed requirements
and unresolved questions. A controller summary alone is insufficient. Each role
reads its complete directed role/task inputs before acting; inaccessible material is
a reported gap, not permission to guess.

### Publish the task branch and handoffs

Before builder dispatch, the controller creates and publishes the dedicated
non-main task branch on GitHub from the authenticated base. The builder returns
the capsule; the map assigns its capsule-only commit/push to the builder or
controller. Publish the planning commit before implementor dispatch. Implementation
uses the same branch; its assigned actor publishes the exact candidate before
independent review. The controller publishes for roles without Git authority.
Use clear commit messages describing the changes. Verify remote refs at each
handoff. Task-branch publication is separate from approval
or main integration; main changes remain behind acceptance. If a project control
blocks this sequence, resolve that explicit conflict before dispatch rather than
silently substitute a local-only workflow. No subagent pushes to main.

### Complete the phases

Before establishing or changing inputs to a required downstream gate, verify
its applicable source, history, authorization and configuration constraints.
Resolve conflicts before acting. Use bounded prerequisite checks, not premature
qualification; recheck when relevant inputs change. History constraints and any
authorized-base reconciliation are defined by the consumer project, not a
universal RI linear-history requirement.

The actor launching a command verifies its required inputs in the actual
execution context before expensive or dependent work: command, working directory,
paths and effective child configuration, not merely the parent's. The controller verifies dispatch prerequisites and may
rely on authenticated launcher or worker checks. Examples include guarded
authentication, temporary paths, recovery objects and CI trigger/check identity.
Use the smallest sufficient checks, not a product-suite rehearsal or unrelated
setup investigation. Reuse readiness only while relevant inputs remain unchanged;
recheck affected prerequisites on changes or capability failure, and report
unresolved prerequisites before proceeding. After setup fails, continue only
checks whose own prerequisites are satisfied. Results qualify for acceptance only
when source, dependencies and environment meet the selected requirements;
otherwise label them diagnostic and report required checks still blocked.
Where required gate order permits, run inexpensive source-validity checks before
costly qualification. On failure, report before further expensive checks unless
the assignment requires collecting independent results. This grants no frozen
candidate edits or omission of required checks.

1. **Capsule builder:** use the supplied branch and [shared format](#capsule-format).
   Require affected stale docs/examples/maps/links to be corrected, or justify why
   documentation is unaffected. Name genuine post-installation checks and their
   satisfaction method. Return the capsule for publication, or publish it under
   the map's explicit capsule-only grant.
2. **Controller:** check the returned plan against the original orientation, issue
   and relevant source, including scope, criteria, documentation and proof routes.
   Resolve scope/specification gaps. An independent scope
   challenge is permitted only for a concrete unresolved scope finding or an
   explicit project requirement. The controller may resolve findings through its
   plan check, but may satisfy a required review only when that requirement permits
   controller review. A required separate independent reviewer cannot be replaced
   by the controller. Follow the additional
   assignment rule above; a scope challenge is not a routine fourth role.
3. **Implementor:** make only authorized changes, including affected docs, and run
   relevant checks. Return source/branch identity, changes, results/skips and gaps.
   Commit/push only when the map grants that action. Keep useful work for corrections.
   Follow the worker instructions for alternate execution paths and their tests.
4. **Controller:** inspect the full diff, scope, documentation and criterion evidence;
   capture/publish the exact candidate when assigned that responsibility and verify
   the remote branch matches it. Supply the reviewer with that source, the full
   diff, capsule, standards and actual test/log evidence. Use the project's existing
   source-capture and evidence route; this instruction does not itself require
   a new export, manifest, upload or local copy.
   Checks must use a stable, identifiable source snapshot. Verify the tested source
   and actual workflow/check identity; a matching check name alone is insufficient.
5. **Independent reviewer:** remain read-only and review the full change, not just
   RI declarations or a summary; return concise evidence-backed
   dispositions for every criterion and applicable standard. Check docs too.
   Missing evidence already due cannot pass. For post-installation obligations,
   assess the implementation/check plan now; installed proof remains due at closeout.
6. **Controller:** return in-scope findings to an implementor, then obtain affected
   checks and independent review. Approval must cover the actual integrated result.
   Use authorized integration, verify it and any pending installed checks, record
   necessary evidence and the final accepted source. Resolve each retained finding
   and obligation as satisfied, explicitly deferred under separate authority, or
   still blocking; original required outcomes cannot be silently deferred to close.
   Close only when all outcomes pass, then safely delete the verified merged branch.
   Verify actual issue closure and applicable local/remote branch cleanup before
   recording success. If either fails, retain and report partial closeout rather
   than claiming completion.

   Reconcile every current reference to this task's state
   in the map, active checkpoint, entrypoints and capsule indexes with the verified
   closure and cleanup. Search for the task ID and stale status wording; preserve
   clearly historical stops and records. Do not declare closeout complete while
   current references still say stopped, active or pending. Keep durable workflow
   maps task-neutral where possible, pointing to the active checkpoint for status.
   Preserve unrelated work and unmerged recovery evidence.

### Keep completion records external

Finalize tracked preparation records before freezing the candidate for
exact-candidate qualification and review: label preparation snapshots historical
and point current status to the live issue and external controller checkpoint.
Record subsequent check attempts and operational outcomes, including integration,
issue closure and cleanup, externally in those existing records. Do not create
another candidate merely to append completion evidence. A necessary tracked
correction creates a new candidate and follows the existing affected-check,
review and authorized-publication rules; operational bookkeeping does not.

### Planning-only and no-change outcomes

RI is navigation/comparison support. Direct source, full diffs and ordinary logs
suffice; RI gaps do not prove absence. No special runner, exporter, per-declaration
verdict or new mandatory record is required. Already-satisfied work can receive
independent no-change review and authorized closeout without an artificial commit.
For a planning-only or no-change outcome, record why implementation and integration
are unnecessary. Preserve the published capsule as the project requires, then use
its authorized disposition for the unmerged planning branch. Do not describe that
branch as merged or invent a product change merely to clean it up.

## Wait, recover and resume

### Wait for completion

- **Native subagents:** use the supported event-based blocking wait. Result
  delivery to an active parent does not prove an idle parent will start a new turn.
  End the turn only with verified idle wake-up for that controller/host route.
- **External jobs:** use native delivery or the [queue skill](skill-templates/capsule-queue/SKILL.md)
  with a supported watcher and verified wake-up. CLI acceptance alone is not
  consumption. Reuse a proven route until it changes or fails; do not add duplicate
  notifications or restart a job to attach a watcher. Otherwise keep blocking wait.
- **While waiting:** no status polling, active-workspace/log/test inspection,
  repetitive commentary or interim acceptance judgments. Verify candidate scope
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
  delivery and controller continuation. Use existing records where available;
  mark missing timestamps unknown. A human bump alone does not prove a terminal
  result was waiting or that notification failed. No new timing ledger is required.

### Diagnose blockers and recover

At a blocker, hold consequential work and do one bounded authorized read-only
sweep to consolidate real failures and unknowns. Routine clarification, diagnosis
and in-scope correction need no repeated human approval. STOP_REPLAN, replan,
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
diagnostic reviewer under the additional-assignment rule. Supply original
requirements, relevant source, capsule and retained rejection history. Ask it to
identify missing decisions, a misstated capsule, missed implementation requirements
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

After correction, the controller selects reruns from changed inputs and the
project's accepted evidence-equivalence policy. Preserve eligible results under
their original source/command/environment identities; never label them newly
executed. Run full qualification when required, or record why reuse is insufficient.
Rerun affected checks when equivalence is unknown. Equivalence covers relevant
transitive inputs and environment changes, not merely unchanged tests/helpers.
Workers follow assigned checks and cannot waive them independently.
When a reported pass conflicts with a later result, compare source, command,
working directory, toolchain and configuration. Record the demonstrated cause or
remaining uncertainty; do not reuse the earlier pass without establishing its
eligibility. A successful repetition alone does not explain the discrepancy.
Changed integration source needs affected checks/review. An ordinary blocking-wait
interval expiring means continue waiting. A reported delivery failure or task
deadline permits bounded reconciliation of authoritative assignment state and
cleanup before retrying; it does not authorize unfinished-work inspection or a
monitoring loop.

### Handle model capacity

Provider model capacity is an availability failure, not a capsule defect or an
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

If fresh agents cannot be created or freed,
last-resort idle-context reuse is permitted with a complete handoff. The candidate
implementor/author must never be its reviewer. If independence is unavailable,
report that blocker. No allowance reset or self-approval is permitted.
