# Nutrition authority

The owner sets product intent, accepted risk and integration permission. Current migrations,
database constraints, executable tests and approved issues define product behavior.
The trusted-owner issue comment binds repository, task/issue ID, exact base, revision,
nonce, allowed/forbidden paths and qualification profiles. Candidate text or chat cannot
fabricate that authenticated comment or a passed check.

## Current interfaces

- `./scripts/task validate-record --task-record PATH` is a read-only public format check for current normal task records; `./scripts/task validate-record --task-record PATH --route maintenance` selects a brief handoff. Normal requires the six-heading format; maintenance requires the five handoff inputs and a recorded `Decision: eligible`. An explicit direct Work controller maintenance selection also requires exactly one literal `Requested route: maintenance` field, one literal `Implementation execution: direct Work controller` field, and exactly one visible `Direct Work controller maintenance: permitted` line in the selected project's `docs/local_project_map.md` under `## Nutrition permissions and routing`; use the existing `--repo-root` option to select that project. Direct selection with the normal route is refused. Normal and delegated-maintenance validation retain their shape-only behavior. The command reports record selections and map permission separately, but it does not authenticate the live controller decision, owner authority, semantic eligibility, actual direct author, reviewer independence, active assignments, qualification, or acceptance. A passing record is not permission to execute. This interface is not added to historical qualification or recovery gates.
- `scripts/task.py` prepares and authenticates the owner-bound `standard` workflow selection.
  This is the normal source/diff/subagent review route, not a compatibility exception.
- `scripts/lib/task_authorization.py` retains authorization versions, path semantics, current
  identity checks, profile floors and exact candidate scope validation.
- Trusted qualification workflows, `trusted_qualification.py` and `qualification_profiles.py`
  retain candidate-independent planning, credential/cache isolation and dedicated-App checks.
  App `4708441` produces exact-SHA `Main qualification`; ordinary push CI is insufficient.
- `task status ISSUE` leaves checkpoint bytes and stdout state unchanged, and emits read-only
  `status_diagnostics` JSON on stderr. Exit zero means the state was read, not acceptance.
  Recorded integration requires current `INTEGRATED` phase and matching candidate/origin-main-after
  binding. Only current `execution` and `execution_checkpoint` optional summaries are diagnosed;
  histories and archives remain opaque. Their `installed_checks_due` booleans report pending or
  reported satisfaction, while explicit reviewer `active` or `PASS consumed`/`consumed` values report
  current activity or reported consumption. Missing/unrecognized values remain unknown.
  Recorded integration conflicts with a true `integration_authorized_but_not_performed` flag.
  A current `VERIFIED_TERMINAL_CLOSEOUT_COMPLETE` summary conflicts with pending installed checks
  or an active reviewer. Diagnostics never establish installed success or consumed review from
  integration, verify optional claims, clear duties, repair historical records or dispatch work.
- `task verify` and `task review` retain explicit candidate-bound decisions. The reviewer
  must be independent of implementation. The controller records actual evidence and actor;
  an asserted actor string alone is not evidence that independent review occurred.
  Under the selected daily procedure, the controller authenticates candidate identity, authorized
  scope, required check completion and evidence identity; the fresh independent reviewer assesses
  substantive correctness and test adequacy. Review PASS does not establish controller approval or
  protected integration.
- `scripts/run-review.sh --commands REQUEST --attempt ID` records bounded task-authored command
  evidence through the existing runner. It does not authenticate authority, determine test adequacy,
  accept a candidate, verify it, approve it or integrate it. Mandatory and advisory outcomes, source
  drift and incomplete attempts retain their documented evidence semantics in the testing guide.
- `task output-closeout ISSUE --execution-record PATH --durable-evidence PATH` reads the current
  owner-bound creation receipt and checkpoint and defaults to a per-output dry run. Execution requires
  explicit `--execute --human-owner-authorized`, live terminal/current-reference validation and a
  recoverable quarantine intent under the existing issue transaction. `--shared-helper` explicitly
  selects the separate optional RI949 source; consumer-only mode remains the public default. This route
  does not adopt unreceipted paths, authorize native cache removal, replace `finalize-cleanup`, or alter
  qualification, review, approval or integration authority.
- `task rework ISSUE --candidate-root PATH --expected-candidate-sha C1 --candidate-sha C2`
  handles an authorized corrected candidate under the canonical
  [state, concurrency and recovery rules](#state-concurrency-and-recovery).
- `task integrate` requires owner authorization, live exact check/authority, clean candidate,
  and protected expected-main update. Ruleset `21357860` remains protected; no routine bypass.
  Ref compare-and-swap, stale-main rejection and interrupted-push reconciliation remain.
- Session, secret scanning, source packaging, database/native/security tests and independently
  required profile floors remain project controls. RI supplies none of their authority.

## Automation authority

Automation may execute only eligible steps under the [execution policy](EXECUTION.md#automation-eligibility).
It must not automatically decide product policy or irreversible actions. Owner intent,
accepted risk and integration permission remain explicit; detectable stops halt dependent
work without resetting historical decisions or consumed allowances.

## State, concurrency and recovery

Current standard tasks use a bounded Markdown record and controller state, without a
mandatory RI JSON packet or capsule-only planning history. Changing base/scope/profiles or
external authority requires fresh matching authorization. Changed C requires candidate-bound
qualification, verification and review. The explicit same-checkpoint `task rework` transition
is limited to `REVIEWED_CHANGES_REQUESTED`; it binds exact C1 and clean C2 identities under the
issue lock, preserves C1 history and requires fresh C2 qualification, verification and review.
Repeated calls, `STOP_REPLAN`, unsupported phases, overlapping or unresolved qualification and
integration operations block it without checkpoint mutation. An owner pause is a controller
hold outside checkpoint state, not a serialized phase; the controller must not invoke rework
until the owner explicitly continues. A separate fresh-authorized-attempt `prepare` uses current
matching owner authorization and a separately selected state location, preserving the existing
checkpoint and its consumed allowances. A closed issue or remembered PASS is not live proof.

Existing attached and compatibility records remain readable with their original identities;
new CLI preparation cannot select attached RI. Public `task evidence` and `task execution`
are retired. Historical readers in `scripts/lib/legacy_ri/` preserve old bindings and recovery;
they are not an executor or reviewer service. No old STOP or allowance is reset. The original
#246/#256 capsule attempts remain stopped under their original authority; that historical attempt
state does not set current issue status. The completed fresh #246 attempt is distinct. See the
[local map](../../docs/local_project_map.md) for the existing historical record and live issue
status. Never reset or resume a stopped attempt through silent conversion to standard mode.

Every checkpoint writer uses the issue-scoped transaction contract: acquire the exclusive
checkpoint lock, reread the latest record, validate the intended mutation against that
record, then replace it atomically after flushing the file. Long qualification work runs
outside that lock after a persisted operation identity binds the candidate, authorization
and dispatch. Terminal qualification application reauthenticates live authority and the
candidate under serialization; uncertain launch or cleanup states are retained for an
exact-operation reconciliation path without redispatch. Integration pending and completion
also revalidate the current candidate-bound qualification, verification, review and owner
authority before persisting a transition. Finalize/cancel/cleanup intents use the same
read-modify-write contract and preserve newer fields, stops and history.

Task-output closeout is a separate synchronous per-item recovery operation. It holds the
creation owner's process lock, copies and authenticates the full retained evidence closure,
then persists current-reference and pending-operation bindings through the same issue lock.
Immediately before a move it rereads terminal disposition, current reference, operation intent,
filesystem identity, protected inputs and retained hashes under that transaction. It quarantines
to a new same-filesystem path and records zero physical reclamation; unknown or interrupted
locations remain pending for exact-location reconciliation. Native linked roots and registered
worktrees use the public Nutrition non-following route and cannot become PASS until cleanup and
retained evidence both verify.

Authorization publication uses that same issue lock and checkpoint. New preparation records
explicitly record that publication has not started. Before posting, `task authorize` persists
the exact task/repository/base/revision/nonce/payload/workflow and draft-body identity as
pending, then retains a known created comment ID before refetch. Lost replies and refetch
failures leave this intent intact. Retry lists all issue comments through existing validated
pagination and recovers only one fully validated matching comment; it never reposts pending
or legacy-unknown publication. Empty, malformed, mismatched and ambiguous observations remain
unresolved/refused. A single empty lookup does not prove that an earlier POST never occurred.
Completed authorization retains publication identity; no comments or historical records are deleted.

Qualification also holds an issue-scoped process-held qualification ownership lock, separate
from the checkpoint transaction lock, from operation persistence through hosted work and cleanup.
The persisted binding is valid only for its supported local host and controller-state location.
Reconciliation takes the same lock and fails without checkpoint or ref changes while a live
holder owns it (`QUALIFICATION_OWNER_ACTIVE`). Missing, legacy or unknown bindings require an
explicit controller disposition. `./scripts/task qualify-reconcile ISSUE --candidate-root PATH`
discovers the existing workflow run and never dispatches; a no matching run leaves the operation
unresolved with its ref evidence retained and reports non-success. A running run is left for later
reconciliation. Finished evidence must pass the exact workflow, candidate, current-authorization
and dedicated-App checks before terminal state or ref cleanup is applied. Reconciliation rechecks
the latest checkpoint before cleanup and preserves `STOP_REPLAN` or superseding authority.

For a previously attached capsule, retain its full nonterminal bytes, legal state/history,
separate candidate C, full recovery R and terminal T identities. Existing guarded finalizers
and `task_closeout.py` remain recovery tools. A terminal update has its own authorization,
qualification, verification and review; recovery bytes must remain reachable. Never reset main
or rewrite failed history to force a gate. [STATES](STATES.md) describes retained transitions.

## Host and transport

[local project map](../../docs/local_project_map.md) is the local route. The controller receives the complete
pinned daily procedure; each serial worker receives Shared worker rules and its assigned unique
level-two section of the pinned [worker instructions](shared/worker-instructions.md#role-index),
through the next level-two heading or end of file, with the task and standards. Ordinary read-only
independent source/diff review is sufficient for RI.
Actual host permissions, confidentiality, secret scanning and protected Git/issue authority
remain enforced. No private source or diagnostic export is implied.
