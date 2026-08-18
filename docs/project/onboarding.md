# Project onboarding

> **Document role: Current Guide.** This page defines the minimum useful context for future engineers, implementation agents, and architecture reviewers.

## Before any implementation

1. Run the start step in the mandatory [Repository Session Contract](../operations/session-contract.md#repository-session-contract).
2. Read the [Project Constitution](constitution.md) for enduring scope and priorities.
3. Read [Current State](current-state.md) for what is true now.
4. Read [Project Invariants](invariants.md) for technical truths the change must preserve.
5. Locate the owning code and validation in the [Development Guide](development-guide.md).
6. Load only the affected feature, architecture, or operations guide from the [Documentation Index](../README.md).

This is the default context budget. Do not load completed Version 1.1/Epic 2 planning, phase histories,
release evidence, or every feature guide before an ordinary change.

## Primary runtime orientation

The normal application path is local-first:

`screen / feature hook -> NutritionRuntime -> local runtime -> SQLite`

The preserved remote/reference path is explicit:

`screen / feature hook -> NutritionRuntime -> remote adapter -> FastAPI -> PostgreSQL`

Exactly one application-data authority is selected for a running context. Local SQLite is not a
cache of PostgreSQL. There is no dual-write, synchronization, automatic failover, background
replication, or silent authority mixing.

Local backup/restore is a separate maintenance/bootstrap path:

`Settings -> validate/stage backup -> restart -> pre-runtime activation/rollback -> local SQLite`

It replaces one local authority with one validated snapshot; it does not create a concurrent
authority or synchronization path.

For new feature work, assume the local SQLite authority is primary unless the task explicitly
concerns remote/reference parity, PostgreSQL behavior, transfer, or control-plane operations.

## Current program orientation

Version 1.1 and Epic 2 are complete. Their planning/backlog/closure files remain as historical
implementation evidence. Current `main` also contains post-Epic-2 nutrition-model, serving,
DRI/Target, local-backup, OCR camera/quality, draft-protection, fixed-header, and accessibility work.
Do not use an old backlog to decide whether a current capability exists; use implementation and the
current guides.

## Task routing

| Task | Add to the minimum context |
| --- | --- |
| Food, nutrient catalog/units, serving, USDA, search, or Targets/DRI | [Foods and Nutrition](../features/foods-and-nutrition.md) |
| Recipe authoring/yields/publication, revisions, projections, or Daily Logs | [Recipes and Nutrition History](../features/recipes-and-logging.md) |
| OCR, guided capture, image quality, confirmation, mobile search, offline behavior, local backup/restore | [OCR, Search, Offline Behavior, and Local Backup](../features/ocr-search-and-offline.md) |
| Cross-layer runtime, persistence, authentication, or authority change | [Architecture Overview](../architecture/overview.md) and [Decision Index](../architecture/decisions.md) |
| Local SQLite schema/lifecycle/transaction or backup activation work | [Architecture Overview](../architecture/overview.md) plus the relevant local/native SQLite tests/qualification |
| Navigation chrome, draft guards, Dynamic Type, accessibility infrastructure | [Repository Tour](repository-tour.md#cross-cutting-mobile-ui-paths), [Development Guide](development-guide.md#if-you-need-to-modify-navigation-route-headers-or-form-discard-behavior) |
| Remote FastAPI/PostgreSQL parity or reference behavior | [Architecture Overview](../architecture/overview.md) plus the relevant backend tests |
| E2-15 transfer or retained Epic 2 parity fixtures | [E2-15 Transfer Architecture](version-1.1/epic-2/e2-15-transfer-architecture.md), current transfer tests, and `packages/shared-contracts/e2-15` |
| Transfer, migration, role, qualification, release, recovery, or control-plane work | [Operations Index](../operations/README.md) |
| Terminology lookup | [Glossary](../reference/glossary.md) |
| Decision provenance or learning from project evolution | [Historical Knowledge Index](../historical/README.md) and, when relevant, completed `project/version-1.1/` records |

## Architecture review path

An architecture reviewer should read the Constitution, Current State, Project Invariants, the
Architecture Overview, the relevant entries in the Decision Index, and the affected feature or
operations guide. Review against the [change checklist](development-guide.md#change-checklist). Load
completed versioned planning or historical records only when verifying why/when a boundary was
introduced or when a retained compatibility artifact explicitly owns the contract being reviewed.

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

- Treat implementation and migrations as authoritative and report documentation drift.
- Treat local SQLite as the primary application runtime unless the task explicitly targets the preserved remote/reference authority.
- Determine the selected application-data authority before tracing a feature.
- Preserve immutable Daily Log nutrition and Recipe revisions; Target/profile/reference changes stay outside that history.
- Preserve exact decimal, qualified nutrient-unit, unknown-versus-zero, and serving/gram/reference semantics.
- Preserve bounded OCR correction provenance; camera framing/quality hints are acquisition aids, not nutrition authority.
- Preserve ownership, idempotency/replay, transactional rollback, and confirmed-versus-unresolved mutation outcomes.
- Treat local backup as validated replacement with staged activation/rollback, never as merge/sync by implication.
- Preserve dirty/busy navigation protection and shared route-header/accessibility semantics when touching guarded mobile flows.
- Use native/file-backed SQLite evidence for local schema/lifecycle/backup/transaction claims; use PostgreSQL for remote Alembic, row-lock, role, grant, and multi-worker concurrency claims.
- Do not infer authority from a command return when an authoritative observation is required.
- Keep completed Version 1.1/Epic 2 and historical records point-in-time; update current guides and link back to the record.
- Do not force Expo-coupled dependency versions outside supported compatibility merely to silence a vulnerability scanner; apply compatible upstream fixes when available and keep the limitation visible until then.
- Finish with validation selected by the Testing Guide and the session-end contract.

## What stays outside ordinary context

Completed Version 1.1/Epic 2 planning/backlog material, historical stage documents,
production-hardening chronology, release evidence, manual QA worksheets, and retained qualification
manifests remain discoverable under `project/version-1.1/`, `historical/`, or evidence/contract
directories. They are valuable for learning, audit, provenance, and versioned compatibility, but
loading them by default increases context without improving most current implementation decisions.
