# Evidence contract

> **Document role: Engineering Process.** This page defines evidence for implementation,
> verification, review, and completion.

## Principles

Evidence belongs to a task, capsule revision, command, and repository state. Raw output remains
available behind summaries. Passed, failed, skipped, blocked, and not applicable stay distinct.
Warnings are surfaced. Evidence from a different source tree is invalid.

## Capsule qualification evidence

`validate-task-capsules.py` provides human-readable validation and a versioned JSON document
containing repository identity, capsule metadata, findings, execution overlay paths, and pass/fail
status. Execution begins only after strict `--execution` preflight passes.

## Execution handoff evidence

`render-task-handoff.py` repeats strict READY preflight and creates a bundle outside the repository
containing the exact capsule, a human executor prompt, a machine-readable routing/scope envelope,
validation JSON, and checksums. The generated handoff records the implementation baseline and the
current capsule-only overlay; it cannot replace higher repository authority.

## Implementation return

Until result artifacts are automated, the executor returns a structured summary containing:

- task ID, capsule revision/state, actual model/tool identity, and delegation;
- base commit, branch, and repository assumptions;
- changed files and rationale;
- implemented and intentionally unchanged behavior;
- migration, API/schema, ownership/security, concurrency, recovery, and compatibility impact;
- exact focused, baseline, and specialized-check outcomes;
- warnings, limitations, assumptions, deviations, deferred work, and review questions.

Future `implementation-result.md` and `implementation-result.json` artifacts must preserve this
shape.

## Review bundle and reproducibility

`Run Nutrition Review.command` supplies the normal local bundle: validated secret-excluding source,
complete logs, failure/warning extracts, human and JSON summaries, command/exit/duration/severity,
environment versions, initial/final Git state, repository drift fingerprints, and explicit opt-in
qualification not run.

The reproducibility envelope records repository, full commit, branch, dirty state, capsule ID and
revision, UTC timestamp, OS/tool versions, exact commands, infrastructure identities, model/tool
identities, delegation, and checksums when available.

## Verification and disposition

Map each material acceptance criterion to inspection, focused tests,
contract/integration tests, PostgreSQL/MinIO/Docker/native/performance/manual
qualification, or independent review. Unsupported claims remain unverified.

Review disposition is exactly one of:

- **Approved** — acceptance and repository integrity are sufficiently evidenced.
- **Bounded correction** — narrow correction without changing authority,
  acceptance, risk, surface, or qualification.
- **Stop and replan** — scope, authority, architecture, risk, or evidence is
  materially invalid.

Before leaving the non-terminal lifecycle, record reviewed commit,
disposition, verification, specialized qualification, known warnings,
deferred work, and follow-up IDs in the active capsule.

After successful integration, terminal closeout writes the task's unique
`MERGED` record to `engineering/capsules/HISTORY.md`. The terminal record
preserves final verification, review, and integration evidence plus the exact
Git recovery commit/path and SHA-256 for the historical full capsule. The
active capsule is removed in the same closeout change.

Cancellation uses the same evidence boundary with a `CANCELLED` history
record. A later retrospective updates the existing unique record to
`RETROSPECTED`; it does not recreate a full terminal capsule in the current
tree.
