# Repository-owned task workflow

> **Document role: Engineering Process.** These documents define how an approved unit of work
> becomes bounded implementation, deterministic evidence, and review. Product behavior,
> architecture, invariants, operations policy, approved backlogs, and GitHub Issues remain
> authoritative in their owning artifacts.

## Purpose

A task capsule is the durable execution contract. Chat may explain or reconstruct rationale, but
it cannot silently change scope, authority, risk, or completion. Codex and reviewers should
consume the same repository artifacts.

## Index

| Artifact | Responsibility |
| --- | --- |
| [Workflow](WORKFLOW.md) | End-to-end gates, exceptions, human decisions, and automation eligibility |
| [States](STATES.md) | Task state machine, blocking overlay, and readiness gate |
| [Task Capsule Contract](TASK_CAPSULE.md) | Versioned Markdown/TOML capsule schema |
| [Routing](ROUTING.md) | Controller, executor, reviewer, risk, and model routing |
| [Evidence](EVIDENCE.md) | Implementation return, review bundle, and reproducibility contract |
| [Failure Taxonomy](FAILURE_TAXONOMY.md) | Failure classes, stop conditions, and correction boundary |
| [Workflow Changelog](CHANGELOG.md) | Evidence-backed process qualification history |
| [Task Capsules](../capsules/README.md) | Template, active capsules, and completed records |

## Authority order

1. Explicit human product decisions and accepted requirements.
2. Current architecture, invariants, operations guides, and accepted decisions.
3. Approved backlog and GitHub Issue.
4. Task capsule.
5. Implementation notes and generated evidence.
6. Conversation history.

Stop when higher-authority artifacts conflict. A capsule coordinates execution; it cannot
override higher authority.

## Non-negotiable rules

- One accountable controller owns scope, routing, state, integration, and final synthesis.
- `READY` requires an exact base commit, branch, objective acceptance, verification, and
  escalation.
- Executors implement the capsule; they do not invent product or architecture policy.
- Scope expansion requires a reviewed capsule revision before editing continues.
- Actual model/tool identity and delegation are recorded; unknown is not presented as verified.
- Passed, failed, not run, blocked, and not applicable remain distinct.
- Repository drift between verification and packaging is a critical failure.
- Human approval is required for policy, trust, privacy, security, destructive behavior,
  irreversible action, migration authority, risk tolerance, or material tradeoffs.

Workflow v3 foundation begins as **EXPERIMENTAL**. It is not the default until qualification in
the [Workflow Changelog](CHANGELOG.md) is satisfied.
