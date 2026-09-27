+++
schema_version = 1
capsule_revision = 2
id = "GH-218-capsule-default"
title = "Make capsule/RI the normal workflow for new tasks"
state = "IMPLEMENTED"
task_type = "documentation"
risk = "medium"
created = "2026-09-27"
updated = "2026-09-27"
source_issue = "https://github.com/MitCaine/Nutrition-App/issues/218"
base_commit = "21869a4da3578858de7ee5668ffcdc67eb4cf80b"
branch = "task/GH-218-capsule-default-r2"
controller = "Codex Nutrition controller"
executor = "Codex bounded implementor"
reviewer = "Fresh independent exact-candidate reviewer"
delegation = "none"
delegation_constraints = []
blocked = false
blocked_reason = ""
blocked_since = ""
dependencies = []
planning_artifacts = ["AGENTS.md", "engineering/workflow/START_HERE.md", "engineering/workflow/AUTHORITY.md", "engineering/tooling/RI.md"]
owned_paths = ["AGENTS.md", "engineering/workflow/README.md", "engineering/workflow/START_HERE.md", "engineering/workflow/AUTHORITY.md", "engineering/workflow/CHANGELOG.md", "engineering/workflow/WORKFLOW.md", "engineering/workflow/TASK_CAPSULE.md", "engineering/tooling/RI.md", "scripts/README.md", "engineering/capsules/active/GH-218-capsule-default.md"]
allowed_paths = []
forbidden_paths = []
specialized_qualification = ["profile:repository", "evidence:focused", "evidence:baseline"]
+++

# GH-218-capsule-default — Combined workflow default

## Goal

Align current operator guidance with the owner's 2026-09-27 decision that capsule/RI is normal for new Nutrition tasks.

## Outcome

Current entrypoints route new tasks through the trusted task controller with capsule attachment and RI evidence, while preserving explicit compatibility and specialist qualification boundaries.

## Non-goals

No product behavior, authorization schema, ruleset, RI pin, dependency lock, legacy-interface retirement or historical evidence rewrite.

## Background

#187 records the owner decision and #218 bounds the documentation cutover. #216 and #217 provide live guarded Python and TSX closeouts. The historical active-time baseline is unavailable and a speed benefit is unproven.

## Authority and precedence

Issue #218, the owner decision on #187, external revision-one authorization, this capsule, and repository domain/operations contracts. RI supplies evidence only; the trusted controller retains authority.

## Dependencies and prerequisites

Exact authorized main base, clean separate task checkout, repository qualification, independent review, and separate guarded terminal HISTORY closeout.

## Owned surface

Current workflow entrypoints and changelog, plus capsule lifecycle. Review only the authorized files listed above.

## Allowed changes

Documentation wording and links required to make the new default clear; lifecycle-only capsule transitions after READY.

## Forbidden changes

No product or executable changes, historical record rewriting, relaxed gate, omitted specialization, compatibility removal or claim of measured speed improvement.

## Acceptance criteria

- [ ] AC-1: Current operator entrypoints clearly make capsule/RI normal for new tasks, with the trusted controller and exact authorization/qualification/review/integration/HISTORY gates intact.
- [ ] AC-2: Compatibility and in-flight exceptions remain explicit; RI never grants edit or approval authority, and unsupported files require full diff review.
- [ ] AC-3: Changelog records the owner decision and evidence limits without rewriting the historical no-promotion decision or claiming a speed benefit.
- [ ] AC-4: The frozen documentation and repository checks pass at C; RI records all changed paths and explicitly routes unsupported Markdown to direct full-diff review. Independent approval and separate R/T closeout remain later mandatory gates, not candidate-provided evidence.

## Required verification

```nutrition-evidence-v1
[
  {"id":"focused","kind":"focused","required":true,"argv":["{python}","scripts/validate-docs.py"]},
  {"id":"baseline","kind":"baseline","required":true,"argv":["./scripts/session-end.sh"]}
]
```

```nutrition-ri-v1
{"schema_version":1,"scope":"changed-files-v1"}
```

### Focused

Validate current documentation links, navigation and required state contracts.

### Baseline

Run repository session-end mechanical and focused audit checks.

### Specialized qualification

Dedicated App repository profile. No product, native, PostgreSQL or infrastructure path is authorized; actual triggers still govern.

## Return evidence

Return exact B/P/C, frozen command records, dedicated App check, RI changed-path coverage including unsupported Markdown/full-diff obligations, independent AC/path review, and separate R/T terminal evidence. Missing timing or comparison is reported as missing.

## Escalation conditions

Changed issue authority, conflicting policy, missing RI/runtime, failed check, incomplete review, scope drift or unrelated main movement stops and preserves evidence.

## Decisions and assumptions

The owner explicitly selected the new default on #187 after seeing the measured limitations. No existing compatibility caller is retired under this issue.

## State history

| Date | From | To | Actor | Reason/evidence |
| --- | --- | --- | --- | --- |
| 2026-09-27 | — | DRAFT | controller | Bounded owner rollout decision and #218 issue. |
| 2026-09-27 | DRAFT | GRILLED | controller | Evidence limits, compatibility and irreversible gate boundaries examined. |
| 2026-09-27 | GRILLED | SPECIFIED | controller | Four acceptance criteria and repository verification selected. |
| 2026-09-27 | SPECIFIED | DECOMPOSED | controller | Documentation-only owned paths and terminal lifecycle separated. |
| 2026-09-27 | DECOMPOSED | READY | controller | Revision-two external authorization comment 5859403898 and exact base verified; revision-one review STOP_REPLAN preserved separately. |
| 2026-09-27 | READY | IN_PROGRESS | Codex controller | Qualified P2 and reapplied only reviewed documentation bytes from failed first candidate. |
| 2026-09-27 | IN_PROGRESS | IMPLEMENTED | Codex controller | Bounded documentation cutover committed for new independent gates. |

## Completion record

- **Reviewed commit:** Pending independent review.
- **Merged commit:** Pending protected integration.
- **Review disposition:** Pending.
- **Verification summary:** Pending.
- **Specialized qualification:** Pending dedicated App repository check.
- **Known warnings:** Historical active-time baseline unavailable; no speed comparison. Revision-one reviewer STOP_REPLAN on circular AC-4 is preserved; no old gate transfers.
- **Deferred work/follow-up IDs:** None.
- **Retrospective required:** yes — #187 rollout record.
