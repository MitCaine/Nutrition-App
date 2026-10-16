# TASK-ID — Outcome

Use the [shared six-heading format](../workflow/shared/start-an-issue.md#capsule-format)
with the [local map](../../docs/local_project_map.md) for the normal route. A controller-confirmed
eligible bounded change may use the same `engineering/tasks/TASK-ID.md` record for a brief
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
- Applicable [source preparation](../workflow/shared/start-an-issue.md#task-directed-source-preparation):
  invocation/source/runtime/parser/coverage and retained raw/packet references; validated generated
  pointers or bounded mechanical projection, limits and required dispositions:
- AC-1 implementation steps: owning seams, related callers/interfaces/tests, settled decisions
  and consequential order/dependencies; link to [AC-1 proof](#ac-1-proof):

## Acceptance

- [ ] AC-1: Original observable required result; [linked proof](#ac-1-proof). Preserve the original ID.

## Checks

Record literal required commands, intended environment and selected qualification
profiles; preserve actual failures/skips and exact source/results for each attempt.

### AC-1 proof

Use the [shared proof-entry rule](../workflow/shared/start-an-issue.md#capsule-format) and link
this entry to AC-1's implementation steps; this adds no acceptance criterion.

- Setup/preconditions:
- Action or isolated fault reaching the actual owner/caller:
- Independently expected observation and distinguishing plausible defect/control:
- Due stage, literal command/environment and retained result references:

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

Use the selected [role index](../workflow/shared/worker-instructions.md#role-index) and
[ownership/handoff contract](../workflow/shared/new-project-setup.md#instruction-ownership-and-handoffs).
The controller supplies the selected role/assignment/route, applicable local sections and
consequential settled decisions. Bind known source/input/evidence facts by accessible references
to actual selected query, runner and checkpoint outputs; record unavailable facts as gaps.
Use existing assignment notes/sketch/terminal handoff for receiver role/outcome understanding
and conflicting/missing inputs, including correction/replacement; no new acknowledgment stage.

Follow the selected [completion-record rule](../workflow/shared/start-an-issue.md#keep-completion-records-external)
for tracked preparation timing and later operational evidence.

Preserve append-only preparation decisions, corrections, stops and failed attempts here; never
reset recorded authority or allowances. Preserve later operational history externally.
Verify all original outcomes and installed obligations before authorized closure; verify
actual closure and applicable local/remote merged-branch cleanup. Report partial closeout
honestly. Reserved actions retain their existing owner permission requirements.
