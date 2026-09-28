# Repository-owned task workflow

> **Document role: Engineering Process.** These documents define how an approved unit of work
> becomes bounded implementation, deterministic evidence, and review. Product behavior,
> architecture, invariants, operations policy, approved backlogs, and GitHub Issues remain
> authoritative in their owning artifacts.

## Purpose

Start with [START_HERE](START_HERE.md) and the [authority contract](AUTHORITY.md).
The accepted public operator entrypoint is `./scripts/task`. Under the owner's
[2026-09-27 rollout decision](https://github.com/MitCaine/Nutrition-App/issues/187#issuecomment-5859326452),
new tasks normally attach a capsule and RI source evidence to that trusted controller.
Existing unattached and legacy capsule interfaces remain available for in-flight and
explicitly justified compatibility work.

When a task uses the repository-owned workflow, its task capsule is the durable
execution contract while that task remains non-terminal. Chat may explain or
reconstruct rationale, but it cannot silently change scope, authority, risk,
or completion. Codex, executors, verifiers, and reviewers consume the same
repository artifacts.

The full capsule remains in `engineering/capsules/active/` through review.
Terminal outcomes are represented by the task's unique record in
`engineering/capsules/HISTORY.md`, which preserves an exact Git recovery
commit/path and SHA-256 for the historical full capsule.

## Index

| Artifact | Responsibility |
| --- | --- |
| [Start here](START_HERE.md) | Current operator sequence |
| [Responsibility Map](RESPONSIBILITY_MAP.md) | Owners, crossing interfaces and decision boundaries |
| [Authority](AUTHORITY.md) | Ownership, attachment design, compatibility and cutover boundaries |
| [Bounded execution](EXECUTION.md) | Optional READY command transport and checkpoints |
| [Candidate evidence](CANDIDATE_EVIDENCE.md) | Default attached candidate checks, RI evidence and observed independent review |
| [Repository Intelligence](../tooling/RI.md) | Pinned committed-source navigation and structural evidence |
| [Workflow](WORKFLOW.md) | End-to-end gates, exceptions, human decisions, and automation eligibility |
| [States](STATES.md) | Task state machine, blocking overlay, and readiness gate |
| [Task Capsule Contract](TASK_CAPSULE.md) | Versioned Markdown/TOML capsule schema |
| [Routing](ROUTING.md) | Controller, executor, reviewer, risk, and model routing |
| [Evidence](EVIDENCE.md) | Implementation return, review bundle, and reproducibility contract |
| [Failure Taxonomy](FAILURE_TAXONOMY.md) | Failure classes, stop conditions, and correction boundary |
| [Workflow Changelog](CHANGELOG.md) | Evidence-backed process qualification history |
| [Combined pilot record](PILOT_2026-09-26.md) | Python/TSX outcomes, failures, routing, host limits and rollout decision |
| [Task Capsules](../capsules/README.md) | Template, active capsules, terminal HISTORY records, and recovery rules |

## Authority order

1. Explicit human product decisions and accepted requirements.
2. Current architecture, invariants, operations guides, and accepted decisions.
3. Approved backlog, GitHub Issue and resolved trusted external task authorization.
4. Explicitly selected task capsule within that authorization.
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

The combined capsule/RI path is the normal route for new tasks. The trusted controller
remains the single authorization, qualification, review and integration authority;
the capsule and RI never replace those gates. The legacy standalone Workflow v3
capsule command is a compatibility interface, not the current default. The
[Workflow Changelog](CHANGELOG.md) records the decision, evidence and remaining
measurement limits. Active capsules retain full text through review; terminal
HISTORY records bind exact recoverable bytes.
