# TASK-ID — Outcome

Use the [shared six-heading format](../workflow/shared/start-an-issue.md#capsule-format)
with the [local map](../../docs/local_project_map.md) for the normal route. A controller-confirmed
eligible mechanical change may use the same `engineering/tasks/TASK-ID.md` record for a brief
maintenance handoff with `## Objective`, `## Exact base`, `## Allowed changes`, `## Required checks`,
`## Return destination`, and `## Controller eligibility` sections. Record one full 40- or
64-character hexadecimal commit ID, a concrete stable return locator, and the exact line
`Decision: eligible` under Controller eligibility. Before dispatch, run the public
`./scripts/task validate-record` command with the selected route; its field checks do not decide
semantic eligibility. Store new records under `engineering/tasks/`;
preserve historical formats and stopped attempts unchanged.

## Objective

- Live issue and original required specifications/decisions:
- Required outcome; unresolved requirements must not be invented:

## Source and scope

- Authenticated exact base, dedicated task branch and published planning identity:
- Owner authorization and permitted Git/issue actions:
- Controller, capsule builder, implementor and distinct independent reviewer:
- Allowed/forbidden paths and affected current documentation:
- Relevant standards/domain/security boundaries; unrelated work preserved:

## Acceptance

- [ ] AC-1: Observable required result and its concrete test or inspectable evidence.

## Checks

Record literal required commands, intended environment and selected qualification
profiles; preserve actual failures/skips and exact source/results for each attempt.

### Check attempts

Append one row for every attempt, including failures, reruns, skips and partial/ambiguous
results. Never replace an earlier row or overwrite its log. Use unique attempt IDs and
log paths; record the literal command and relevant environment/interpreter without secrets.
Exact source means commit plus the retained complete diff digest for dirty work (including
untracked in-scope files), or the clean candidate SHA. Keep large logs outside source in
the selected evidence workspace; record portable location identities and SHA-256 here.
Keep absolute private locations and diagnostic payloads in the external inventory.

| Attempt / check | Exact source / diff identity | Command / environment | Status / exit code | Log location / SHA-256 | Eligibility / disposition |
| --- | --- | --- | --- | --- | --- |

Only the latest eligible complete success on the required source satisfies a check.
Unknown exit code, partial/ambiguous delivery, skips, unavailable checks, missing logs or
source mismatch cannot satisfy it. Resolve any later failed or ambiguous attempt explicitly
before relying on a prior success; retain all attempts for review. This inventory supports
the existing verification evidence field and does not replace qualification or review gates.

## Prerequisites

- Known dependencies, inspected environment, unresolved decisions and gaps:
- Genuine post-installation obligations, their stage and satisfaction method:

## Handoff and closeout

Provide the controller with the complete selected daily procedure. Provide each worker with
Shared worker rules and its assigned unique level-two section of
[`worker-instructions.md`](../workflow/shared/worker-instructions.md#role-index), read
through the next level-two heading or end of file, plus the needed map sections, task, applicable
standards, exact source/diff and real evidence. Give an initial builder the original objective/base
and requirements without a future capsule; implementors and reviewers receive the accepted capsule.
Return changed paths, tested source/commands/environment,
results/skips, unresolved findings and next permitted action. The Work controller directly
dispatches the capsule builder and distinct independent reviewer. The owner-designated Codex
dispatcher authenticates the accepted implementation handoff and launches one implementor;
workers do not recruit. Use supported blocking completion while an assignment is active unless
its exact idle-wake route is verified. A terminal result already delivered can be consumed
immediately without idle-wake proof. Queue is conditional on a supported observer and verified
delivery.

Freeze this tracked preparation/check ledger before candidate C is frozen for exact-candidate
qualification and review. Label the snapshot historical and point current status to the live
issue and existing authenticated external controller checkpoint (record its portable selected
identity). After C is frozen, keep every later attempt, failure, rerun, qualification, review,
integration, issue closure and cleanup outcome in those existing operational records. Do not
create another candidate solely for completion evidence. A later real tracked-document correction
needs affected checks/review and authorized publication.

Preserve append-only preparation decisions, corrections, stops and failed attempts here; never
reset recorded authority or allowances. Preserve later operational history externally.
Verify all original outcomes and installed obligations before authorized closure; verify
actual closure and applicable local/remote merged-branch cleanup. Report partial closeout
honestly. Reserved actions retain their existing owner permission requirements.
