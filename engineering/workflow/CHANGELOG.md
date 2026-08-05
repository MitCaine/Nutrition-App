# Workflow changelog

> **Document role: Engineering Process.** Workflow changes advance only through observed
> evidence.

| Status | Meaning |
| --- | --- |
| `EXPERIMENTAL` | Defined but not representative-proven; never mandatory. |
| `TRIAL` | Used on bounded tasks with explicit observation and fallback. |
| `QUALIFIED` | Repeated evidence shows reliability within named limits. |
| `DEFAULT` | Standard for declared scope; exceptions require rationale. |
| `DEPRECATED` | Replacement and compatibility/migration period are documented. |

Promotion requires evidence, known limits, and accountable approval. New evidence may regress a
workflow to an earlier state.

## 2026-08-04 — Workflow v3 repository foundation

**Status:** `EXPERIMENTAL`

Added repository-owned workflow, states, versioned human-first capsules, routing, evidence,
failure taxonomy, active/completed storage, model identity rules, readiness gates, and workflow
qualification states.

**Reason:** reduce chat reconstruction, move uncertainty upstream, bound delegation, and let
Codex and independent review consume the same durable authority.

**Required for `TRIAL`:** validate one real capsule mechanically, execute from its exact base
commit, produce the review bundle, and record whether the capsule reduced ambiguity without
disproportionate overhead.

**Not yet included:** capsule validator, task launcher, automatic implementation-result
artifact, Codex launch integration, PR automation, or regression-case generation.

## 2026-08-04 — Mechanical task-capsule validation

**Status:** `EXPERIMENTAL`

Added a standard-library validator with human and JSON output, strict schema and section checks,
stable acceptance IDs, capsule revisions, machine-readable scope, delegation constraints,
authority-path validation, state-transition validation, completion validation, exact Git commit and
branch checks, and a clean-worktree execution preflight.

The `READY` capsule is committed above its recorded implementation baseline only when the complete
committed overlay is that capsule itself. Repository closeout now validates all active and completed
capsules, and focused tests qualify valid, invalid, blocked, authority-missing, dirty-tree,
unverified-acceptance, and unrelated-overlay cases.

Schema version 1 was completed before any real task capsule existed, so no capsule migration was
required.

**Required for `TRIAL`:** create and execute one real `READY` capsule through validation,
implementation, review-bundle generation, independent review, and completion-state validation.

## 2026-08-04 — Validated execution-handoff rendering

**Status:** `EXPERIMENTAL`

Added a fail-closed renderer that consumes one committed `READY` capsule, repeats strict execution
preflight, and writes a durable Markdown/JSON handoff bundle outside the repository. The handoff
records exact repository identity, capsule checksum and revision, controller/executor/reviewer,
delegation, authority, scope, specialized qualification, execution protocol, and required return
evidence. Focused tests cover valid generation, exact capsule inclusion, dirty-worktree rejection,
in-repository output rejection, and stable content under a fixed handoff timestamp.

**Required for `TRIAL`:** commit this tooling, create one real READY capsule as the sole overlay above
its implementation baseline, generate its handoff, execute the task from that artifact, and compare
the result against the capsule and final review bundle.

## 2026-08-04 — Capsule-aware documentation validation

**Status:** `EXPERIMENTAL`

Separated documentation executable-reference validation from task-capsule scope semantics. TOML front matter under `engineering/capsules/` may declare future `owned_paths` and `allowed_paths` without being treated as an assertion that those executables already exist. Capsule Markdown bodies remain subject to normal documentation checks, and malformed or unterminated front matter is not silently suppressed.

`planning_artifacts`, scope syntax, and capsule structure remain fail-closed under `scripts/validate-task-capsules.py`. Focused regression tests preserve both sides of the boundary: capsule front matter is excluded, while ordinary Markdown remains fully scanned.

**Required for `TRIAL`:** pass repository documentation validation and CI with a real READY capsule that owns a not-yet-created executable, then execute and review that capsule.
