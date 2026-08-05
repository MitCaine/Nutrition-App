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
