# TASK-ID — Outcome

Use this bounded Markdown task record for the current [route](../../docs/local_project_map.md).
Store new records under `engineering/tasks/`; `capsules/active/` is preserved historical
TOML state. Existing paused capsules must not be replaced or converted silently.

- Issue/objective:
- Exact base/branch and candidate when captured:
- Owner authorization and permitted Git/issue actions:
- Controller, planner, implementor and distinct independent reviewer:
- Allowed and forbidden paths:
- Relevant standards/domain/security boundaries:
- Prerequisites, inspected environment and known gaps:

## Acceptance criteria

- [ ] AC-1: Observable required result.

## Required checks

Record exact commands and required qualification profiles; preserve actual failures/skips.

## Check attempts

Append one row for every attempt, including failures, reruns, skips and partial/ambiguous
results. Never replace an earlier row or overwrite its log. Use unique attempt IDs and
log paths; record the literal command and relevant environment/interpreter without secrets.
Exact source means commit plus the retained complete diff digest for dirty work (including
untracked in-scope files), or the clean candidate SHA. Keep large logs outside source in
the selected evidence workspace; record their location and SHA-256 here.

| Attempt / check | Exact source / diff identity | Command / environment | Status / exit code | Log location / SHA-256 | Eligibility / disposition |
| --- | --- | --- | --- | --- | --- |

Only the latest eligible complete success on the required source satisfies a check.
Unknown exit code, partial/ambiguous delivery, skips, unavailable checks, missing logs or
source mismatch cannot satisfy it. Resolve any later failed or ambiguous attempt explicitly
before relying on a prior success; retain all attempts for review. This inventory supports
the existing verification evidence field and does not replace qualification or review gates.

## Handoff and result

Provide the complete shared procedure, local map, task, applicable standards, exact source/diff
and real evidence. Record changed paths, tested source/commands/environment, review findings,
remaining obligations and safe next action. Native completion returns to the controller.

## History and preservation

Append decisions, corrections, stops, cancellation and integration receipts. Do not rewrite
failed attempts as success or silently reset a paused task's authority/allowances.
