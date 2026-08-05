# Task routing

> **Document role: Engineering Process.** This page defines accountable roles, model
> preferences, risk, and delegation boundaries.

## Roles

- **Human repository owner:** product intent, risk tolerance, irreversible decisions,
  commit/merge.
- **Accountable controller:** scope, artifacts, decomposition, routing, state, integration,
  synthesis.
- **Executor:** bounded implementation and focused return evidence.
- **Verifier:** mechanical evidence independent of implementation claims.
- **Reviewer:** issue satisfaction, architecture, invariants, risk, evidence, and disposition.

One accountable controller remains named even when work is delegated.

## Current model mapping

- **Sol-class reasoning in ChatGPT Work:** controller, grilling, architecture, audit,
  decomposition, high-risk synthesis, and review planning.
- **Luna-class Codex execution:** bounded implementation, tests, tooling, and documentation from
  a `READY` capsule.
- **Independent ChatGPT review context:** review bundle plus implementation return against the
  capsule and repository authority.

Model names are preferences, not permanent schema. Record actual identity and delegation. A
mismatch on a route that depends on identity is `MODEL_OR_TOOL_MISMATCH`, not a detail to omit.

## Routing matrix

| Work | Controller | Executor | Verification/review |
| --- | --- | --- | --- |
| Product grill, PRD, policy | Sol-class plus human decisions | Controller | User approval and consistency review |
| Architecture, invariants, migration, concurrency, trust | Sol-class | Controller or tightly bounded executor after approval | Independent architecture review and qualification plan |
| Bounded feature implementation | Sol-class | Luna-class Codex | Focused tests, affected baseline, review bundle, independent review |
| High-risk cross-cutting implementation | Sol-class | Sol-class or narrow Luna subcapsules | Independent verifier and specialized qualification; integration stays with controller |
| Bounded correction | Sol-class | Luna-class Codex | Defect reproduction, regression test, affected baseline, review bundle |
| Mechanical docs/tooling | Sol-class | Luna-class Codex | Docs/static checks and proportional review bundle |
| Audit/investigation | Sol-class | Independent audit agent or controller | Evidence-backed findings; no mixed implementation |
| Destructive operations/release | Human plus Sol-class | Qualified operator path | Exact runbook, fail-closed confirmation, release evidence |

Risk is based on consequence and detectability: `low`, `medium`, `high`, or `critical`.
Historical data, ownership, public contracts, migrations, concurrency, security, native
integration, recovery, or broad cross-layer impact is at least high; destructive or
irreversible authority is critical.

## Delegation rules

Delegate only bounded work with explicit inputs, outputs, paths, and stop conditions. Keep
shared contracts, migrations, transaction semantics, locking order, integration, and final
validation with the controller. Parallel tasks may not edit the same authority or rely on
unstated intermediate state. Subagent output is evidence, not authority.
