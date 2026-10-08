# Nutrition authority

The owner sets product intent, accepted risk and integration permission. Current migrations,
database constraints, executable tests and approved issues define product behavior.
The trusted-owner issue comment binds repository, task/issue ID, exact base, revision,
nonce, allowed/forbidden paths and qualification profiles. Candidate text or chat cannot
fabricate that authenticated comment or a passed check.

## Current interfaces

- `scripts/task.py` prepares and authenticates the owner-bound `standard` workflow selection.
  This is the normal source/diff/subagent review route, not a compatibility exception.
- `scripts/lib/task_authorization.py` retains authorization versions, path semantics, current
  identity checks, profile floors and exact candidate scope validation.
- Trusted qualification workflows, `trusted_qualification.py` and `qualification_profiles.py`
  retain candidate-independent planning, credential/cache isolation and dedicated-App checks.
  App `4708441` produces exact-SHA `Main qualification`; ordinary push CI is insufficient.
- `task verify` and `task review` retain explicit candidate-bound decisions. The reviewer
  must be independent of implementation. The controller records actual evidence and actor;
  an asserted actor string alone is not evidence that independent review occurred.
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
qualification, verification and review. A closed issue or remembered PASS is not live proof.

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
