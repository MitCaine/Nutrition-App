# Task states

> **Document role: Engineering Process.** This page defines task state machine version 1.

| State | Meaning | Owner |
| --- | --- | --- |
| `DRAFT` | Intent exists; authority or scope is incomplete. | Controller |
| `GRILLED` | Material ambiguity is resolved or explicitly not applicable. | Controller/user as needed |
| `SPECIFIED` | Stable outcome and acceptance requirements exist. | Controller |
| `DECOMPOSED` | Work is divided into bounded execution units. | Controller |
| `READY` | Capsule passes every execution precondition. | Controller |
| `IN_PROGRESS` | Verified executor is working from the qualified repository state. | Executor |
| `IMPLEMENTED` | Bounded implementation and return evidence are complete. | Executor |
| `VERIFIED` | Required checks have explicit outcomes. | Verifier/controller |
| `REVIEWED` | Independent review has an explicit disposition. | Reviewer/controller |
| `MERGED` | Reviewed work is committed or merged at the recorded commit. | Human owner |
| `RETROSPECTED` | Reusable workflow lessons were evaluated and recorded. | Controller |
| `CANCELLED` | Work ended without merge; reason and partial-work disposition are recorded. | Controller/human owner |

Normal path:

```text
DRAFT → GRILLED → SPECIFIED → DECOMPOSED → READY → IN_PROGRESS
      → IMPLEMENTED → VERIFIED → REVIEWED → MERGED → RETROSPECTED
```

A planning gate may be `Not applicable — <reason>` but remains visible. `REVIEWED` may return to
`IN_PROGRESS` only for a bounded correction. Any non-terminal state may become `CANCELLED`.

## Blocking overlay

Blocking does not erase the last qualified state:

```toml
blocked = true
blocked_reason = "Exact dependency or decision required"
blocked_since = "2026-08-04"
```

## READY checklist

- Stable ID, schema version, task type, risk, and role ownership are present.
- Source authority, exact base commit, and expected branch are recorded.
- Goal, outcome, non-goals, context, dependencies, and precedence are sufficient for a fresh
  executor.
- Owned, allowed, and forbidden surfaces are bounded.
- Acceptance is objective; verification and specialized qualification are classified.
- Return evidence and escalation conditions are explicit.
- Material assumptions are decided or recorded as blockers.
- The controller confirms implementation can proceed without inventing policy.

Only the controller promotes planning and `READY`; the executor sets `IN_PROGRESS` and
`IMPLEMENTED`; verification sets `VERIFIED`; review sets `REVIEWED`; the human owner records
`MERGED`. Every state change updates `updated` and appends State History. Regressions require a
reason; never rewrite history to imply a gate passed earlier.
