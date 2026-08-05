# Task capsule contract

> **Document role: Engineering Process.** This page defines task capsule schema version 1.

A capsule is human-first Markdown with TOML front matter delimited by `+++`. TOML keeps execution
metadata readable by Python's standard library; Markdown owns rationale, scope, acceptance,
verification, evidence, and escalation. Copy the
[canonical template](../capsules/TEMPLATE.md).

## Required metadata

`schema_version`, `capsule_revision`, `id`, `title`, `state`, `task_type`, `risk`, `created`,
`updated`, `source_issue`, `base_commit`, `branch`, `controller`, `executor`, `reviewer`,
`delegation`, `delegation_constraints`, `blocked`, `blocked_reason`, `blocked_since`,
`dependencies`, `planning_artifacts`, `owned_paths`, `allowed_paths`, `forbidden_paths`, and
`specialized_qualification`.

- `schema_version` is `1`; `capsule_revision` is a positive integer identifying the current
  execution-contract revision.
- `task_type` is `product`, `architecture`, `implementation`, `correction`, `audit`,
  `documentation`, `tooling`, `operations`, or `release`.
- `risk` is `low`, `medium`, `high`, or `critical`.
- `state` comes from [Task States](STATES.md).
- `delegation` is `none` or `bounded`; bounded delegation requires explicit constraints.
- `base_commit` may be empty before `READY`. At `READY`, it is an exact lowercase 40-character
  commit identifying the implementation baseline, and `branch` names the expected branch.
- `planning_artifacts` contains existing repository-relative authority paths. A Markdown fragment
  may follow `#`.
- `owned_paths`, `allowed_paths`, and `forbidden_paths` use repository-relative POSIX paths or
  patterns for mechanical scope enforcement.
- Unknown schema versions or metadata keys are rejected rather than guessed.

## Required sections

Goal; Outcome; Non-goals; Background; Authority and precedence; Dependencies and prerequisites;
Owned surface; Allowed changes; Forbidden changes; Acceptance criteria; Required verification;
Return evidence; Escalation conditions; Decisions and assumptions; State history; Completion
record.

A section may say `Not applicable — <reason>` but may not disappear. `Required verification`
contains `Focused`, `Baseline`, and `Specialized qualification` subsections in that order.

## Mechanical validation

Validate all active and completed capsules:

```bash
python3 scripts/validate-task-capsules.py --all
```

Produce machine-readable evidence:

```bash
python3 scripts/validate-task-capsules.py --all --json
python3 scripts/validate-task-capsules.py --all --output /tmp/capsule-validation.json
```

Before execution, set `base_commit` to the exact commit containing approved planning authority,
advance the capsule to `READY`, and commit only the capsule overlay. Then run:

```bash
python3 scripts/validate-task-capsules.py \
  --execution engineering/capsules/active/TASK-ID.md
```

Execution preflight requires a clean worktree, the expected branch, `READY`, no blocking overlay,
an existing base commit, and exactly one committed path after the base: that capsule. This avoids
the self-reference problem of requiring a capsule to contain the hash of its own commit.


Render the qualified executor handoff:

```bash
python3 scripts/render-task-handoff.py \
  engineering/capsules/active/TASK-ID.md
```

The renderer repeats strict execution validation, embeds the exact capsule and execution protocol,
records repository/routing/scope metadata in JSON, and writes all output outside the repository so
preflight cleanliness is preserved.

## Rules

- Acceptance describes observable outcomes, not implementation steps. At `READY` or later, every
  checkbox has a stable ID such as `AC-1`; at `VERIFIED` or later, every acceptance checkbox is
  checked.
- `Owned surface` names expected files/modules/contracts; `Allowed changes` permits narrow adjacent
  work; `Forbidden changes` names explicit boundaries and preserved invariants.
- Necessary work outside the boundary stops execution until the controller revises the capsule or
  creates another task.
- After `READY`, changing goal, authority, acceptance, risk, scope, delegation, qualification, or
  escalation invalidates readiness. Increment `capsule_revision`, return `READY` to `DECOMPOSED`,
  append State History, and requalify.
- Executor notes do not change scope.
- State History is append-only. Its final state matches TOML `state`, and its final date matches
  `updated`.
- After `MERGED`, `RETROSPECTED`, or `CANCELLED`, fill Completion record and move the capsule to
  `completed/`.
- Never rename, recycle, or repurpose an ID after execution begins.

Schema changes require a changelog entry, migration guidance, and a new `schema_version`.
Completed capsules remain readable under their original schema.
