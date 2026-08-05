# Evidence contract

> **Document role: Engineering Process.** This page defines evidence for implementation,
> verification, review, and completion.

## Principles

Evidence belongs to a task, capsule revision, command, and repository state. Raw output remains
available behind summaries. Passed, failed, skipped, blocked, and not applicable stay distinct.
Warnings are surfaced. Evidence from a different source tree is invalid.

## Implementation return

Until result artifacts are automated, the executor returns a structured summary containing:

- task ID, capsule state/revision, actual model/tool identity, and delegation;
- base commit, branch, and repository assumptions;
- changed files and rationale;
- implemented and intentionally unchanged behavior;
- migration, API/schema, ownership/security, concurrency, recovery, and compatibility impact;
- exact focused, baseline, and specialized-check outcomes;
- warnings, limitations, assumptions, deviations, deferred work, and review questions.

Future `implementation-result.md` and `implementation-result.json` artifacts must preserve this
shape.

## Review bundle and reproducibility

`Run Nutrition Review.command` supplies the normal local bundle: validated secret-excluding
source, complete logs, failure/warning extracts, human and JSON summaries,
command/exit/duration/severity, environment versions, initial/final Git state, repository drift
fingerprints, and explicit opt-in qualification not run.

The reproducibility envelope records repository, full commit, branch, dirty state, capsule ID
and schema, UTC timestamp, OS/tool versions, exact commands, infrastructure identities,
model/tool identities, delegation, and checksums when available.

## Verification and disposition

Map each material acceptance criterion to inspection, focused tests, contract/integration
tests, PostgreSQL/MinIO/Docker/native/performance/manual qualification, or independent review.
Unsupported claims remain unverified.

Review disposition is exactly one of:

- **Approved** — acceptance and repository integrity are sufficiently evidenced.
- **Bounded correction** — narrow correction without changing authority, acceptance, risk,
  surface, or qualification.
- **Stop and replan** — scope, authority, architecture, risk, or evidence is materially invalid.

Before completion, record reviewed commit, disposition, verification, specialized
qualification, known warnings, deferred work, and follow-up IDs in the capsule.
