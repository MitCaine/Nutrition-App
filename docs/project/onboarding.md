# Project onboarding

> **Document role: Current Guide.** This page defines the minimum useful context for future engineers, implementation agents, and architecture reviewers.

## Before any implementation

1. Run the start step in the mandatory [Repository Session Contract](../operations/session-contract.md#repository-session-contract).
2. Read the [Project Constitution](constitution.md) for enduring scope and priorities.
3. Read [Current State](current-state.md) for what is true now.
4. Read [Project Invariants](invariants.md) for technical truths the change must preserve.
5. Locate the owning code and validation in the [Development Guide](development-guide.md).
6. Load only the affected feature, architecture, or operations guide from the [Documentation Index](../README.md).

This is the default context budget. Do not load completed Version 1.1 planning, phase histories, release evidence, or every feature guide before an ordinary change.

## Primary runtime orientation

The normal application path is local-first:

`screen / feature hook -> NutritionRuntime -> local runtime -> SQLite`

The preserved remote/reference path is explicit:

`screen / feature hook -> NutritionRuntime -> remote adapter -> FastAPI -> PostgreSQL`

Exactly one application-data authority is selected for a running context. Local SQLite is not a cache of PostgreSQL. There is no dual-write, synchronization, automatic failover, background replication, or silent authority mixing.

For new feature work, assume the local SQLite authority is primary unless the task explicitly concerns remote/reference parity, PostgreSQL behavior, transfer, or control-plane operations.

## Task routing

| Task | Add to the minimum context |
| --- | --- |
| Food, serving, USDA, search, or Targets | [Foods and Nutrition](../features/foods-and-nutrition.md) |
| Recipe publication, revisions, projections, or Daily Logs | [Recipes and Nutrition History](../features/recipes-and-logging.md) |
| OCR, confirmation, mobile search, caching, or offline behavior | [OCR, Search, and Offline Behavior](../features/ocr-search-and-offline.md) |
| Cross-layer runtime, persistence, authentication, or authority change | [Architecture Overview](../architecture/overview.md) and [Decision Index](../architecture/decisions.md) |
| Local SQLite schema/lifecycle/transaction work | [Architecture Overview](../architecture/overview.md) plus the relevant local-runtime tests/qualification |
| Remote FastAPI/PostgreSQL parity or reference behavior | [Architecture Overview](../architecture/overview.md) plus the relevant backend tests |
| Transfer, migration, role, qualification, release, recovery, or control-plane work | [Operations Index](../operations/README.md) |
| Terminology lookup | [Glossary](../reference/glossary.md) |
| Decision provenance or learning from project evolution | [Historical Knowledge Index](../historical/README.md) and, when relevant, completed `project/version-1.1/` records |

## Architecture review path

An architecture reviewer should read the Constitution, Current State, Project Invariants, the Architecture Overview, the relevant entries in the Decision Index, and the affected feature or operations guide. Review against the [change checklist](development-guide.md#change-checklist). Load completed versioned planning or historical records only when verifying why or when a boundary was introduced.

## Human orientation path

An experienced engineer can become productive by reading, in order:

1. the [Project Constitution](constitution.md);
2. [Current State](current-state.md);
3. [Project Invariants](invariants.md);
4. the [Architecture Overview](../architecture/overview.md);
5. the relevant sections of the [Repository Tour](repository-tour.md); and
6. the owning section of the [Development Guide](development-guide.md).

Feature and operations guides are task-specific follow-up reading, not a prerequisite bundle.

## Working rules

- Treat implementation as authoritative and report documentation drift.
- Treat local SQLite as the primary application runtime unless the task explicitly targets the preserved remote/reference authority.
- Determine the selected application-data authority before tracing a feature.
- Preserve immutable Daily Log nutrition history, immutable Recipe publication revisions, fixed historical source identity, ownership, exact decimal semantics, unknown-versus-zero semantics, OCR correction provenance, idempotency/replay behavior, transactional rollback, and confirmed-versus-unresolved mutation outcomes.
- Use native/file-backed SQLite evidence for local schema/lifecycle/transaction claims; use PostgreSQL for remote Alembic, row-lock, role, grant, and multi-worker concurrency claims.
- Do not infer authority from a command return when an authoritative observation is required.
- Keep completed Version 1.1 and historical records point-in-time; update current guides and link back to the record.
- Finish with the validation selected by the Testing Guide and the session-end contract.

## What stays outside ordinary context

Completed Version 1.1 planning/backlog material, historical stage documents, production-hardening chronology, release evidence, manual QA worksheets, and retained qualification manifests remain discoverable under `project/version-1.1/`, `historical/`, or evidence directories. They are valuable for learning, audit, and provenance, but loading them by default increases context without improving most current implementation decisions.
