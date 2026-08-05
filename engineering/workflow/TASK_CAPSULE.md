# Task capsule contract

> **Document role: Engineering Process.** This page defines task capsule schema version 1.

A capsule is human-first Markdown with TOML front matter delimited by `+++`. TOML keeps
execution metadata readable by Python's standard library; Markdown owns rationale, scope,
acceptance, and evidence. Copy the [canonical template](../capsules/TEMPLATE.md).

## Required metadata

`schema_version`, `id`, `title`, `state`, `task_type`, `risk`, `created`, `updated`,
`source_issue`, `base_commit`, `branch`, `controller`, `executor`, `reviewer`, `blocked`,
`blocked_reason`, `blocked_since`, `dependencies`, `planning_artifacts`, and
`specialized_qualification`.

- `schema_version` is `1`.
- `task_type` is `product`, `architecture`, `implementation`, `correction`, `audit`,
  `documentation`, `tooling`, `operations`, or `release`.
- `risk` is `low`, `medium`, `high`, or `critical`.
- `state` comes from [Task States](STATES.md).
- `base_commit` and `branch` may be empty before `READY` but are mandatory at `READY`.
- Unknown schema versions are rejected rather than guessed.

## Required sections

Goal; Outcome; Non-goals; Background; Authority and precedence; Dependencies and prerequisites;
Owned surface; Allowed changes; Forbidden changes; Acceptance criteria; Required verification;
Return evidence; Escalation conditions; Decisions and assumptions; State history; Completion
record.

A section may say `Not applicable — <reason>` but may not disappear.

## Rules

- Acceptance describes observable outcomes, not implementation steps.
- `Owned surface` names expected files/modules/contracts; `Allowed changes` permits narrow
  adjacent work; `Forbidden changes` names explicit boundaries and preserved invariants.
- Necessary work outside the boundary stops execution until the controller revises the capsule
  or creates another task.
- After `READY`, changing goal, authority, acceptance, risk, owned surface, forbidden changes,
  or qualification invalidates readiness.
- Executor notes do not change scope.
- After `MERGED`, move the capsule to `completed/`; corrections are append-only and identify
  the correcting commit.
- Never rename, recycle, or repurpose an ID after execution begins.

Schema changes require a changelog entry, migration guidance, and a new `schema_version`.
Completed capsules remain readable under their original schema.
