+++
schema_version = 1
id = "TASK-ID"
title = "Outcome-oriented task title"
state = "DRAFT"
task_type = "implementation"
risk = "medium"
created = "YYYY-MM-DD"
updated = "YYYY-MM-DD"
source_issue = ""
base_commit = ""
branch = ""
controller = "accountable-controller"
executor = "bounded-executor"
reviewer = "independent-reviewer"
blocked = false
blocked_reason = ""
blocked_since = ""
dependencies = []
planning_artifacts = []
specialized_qualification = []
+++

# TASK-ID — Outcome-oriented task title

## Goal

State the problem this task resolves.

## Outcome

State the observable successful result.

## Non-goals

- Name behavior, cleanup, architecture, or follow-up outside this task.

## Background

Provide only context a fresh executor needs; link rather than copy authority.

## Authority and precedence

- List authoritative repository artifacts in precedence order.
- Name the issue/backlog authority, or `Not applicable — <reason>`.

## Dependencies and prerequisites

- Task IDs, commits, services, decisions, environments, or generated artifacts.

## Owned surface

- Expected files, modules, contracts, tests, and documents.

## Allowed changes

- Narrow adjacent changes permitted for safe acceptance.

## Forbidden changes

- Preserved invariants, unrelated systems, contracts, migrations, or cleanup.

## Acceptance criteria

- [ ] Each criterion is observable and independently reviewable.

## Required verification

### Focused

- Exact tests or inspections for the changed contract.

### Baseline

- Affected baseline plus `Run Nutrition Review.command`.

### Specialized qualification

- Required PostgreSQL, MinIO, Docker, migration, performance, security, native,
  accessibility, or manual checks; otherwise `Not applicable — <reason>`.

## Return evidence

- Changed files/rationale; exact commands/outcomes; actual model/tool/delegation; contract and
  risk impact; warnings/deviations/deferred work; final review bundle identifier.

## Escalation conditions

- Conditions that stop execution for controller or human review.

## Decisions and assumptions

- Accepted decisions and unresolved assumptions. A material unresolved assumption blocks
  `READY`.

## State history

| Date | From | To | Actor | Reason/evidence |
| --- | --- | --- | --- | --- |
| YYYY-MM-DD | — | DRAFT | controller | Capsule created. |

## Completion record

- **Reviewed commit:**
- **Review disposition:**
- **Verification summary:**
- **Specialized qualification:**
- **Known warnings:**
- **Deferred work/follow-up IDs:**
- **Retrospective required:** yes/no — reason
