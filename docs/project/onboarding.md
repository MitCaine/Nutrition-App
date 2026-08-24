# Project onboarding

> **Document role: Current Guide.** This page defines the minimum useful
> context for an engineer or implementation agent before changing the
> repository.

## Before any implementation

1. Run the start step in the mandatory [Repository Session Contract](../operations/session-contract.md#repository-session-contract).
2. Read the [Project Constitution](constitution.md).
3. Read [Current State](current-state.md).
4. Read [Project Invariants](invariants.md).
5. Use the [Development Guide](development-guide.md) to locate the owning code
   and validation.
6. Load only the affected feature, architecture, or operations guide from the
   [Documentation Index](../README.md).

That is the default context budget. Historical planning and release evidence
are not prerequisite reading for ordinary implementation.

## Primary runtime orientation

The normal application path is:

`screen / feature hook -> NutritionRuntime -> local runtime -> SQLite`

The preserved alternate path is:

`screen / feature hook -> NutritionRuntime -> remote adapter -> FastAPI -> PostgreSQL`

Exactly one application-data authority is selected for a running context.
Local SQLite is not a PostgreSQL cache, and there is no synchronization,
dual-write, hidden fallback, or automatic failover.

Local backup/restore is validated replacement of the local authority, not a
second live authority. Transfer from PostgreSQL to SQLite is likewise a
one-time cutover operation, not synchronization.

## Current program orientation

[Current State](current-state.md) owns what is implemented now and the
[Current Product Roadmap](product-roadmap.md) owns current Epic status.
Completed versioned planning packages are historical provenance only.

## Task routing

| Task | Read next |
| --- | --- |
| Foods, nutrient units, serving, USDA, search, Targets/DRI | [Foods and Nutrition](../features/foods-and-nutrition.md) |
| Recipes, publication/revisions, Daily Logs, Complete, History | [Recipes and Nutrition History](../features/recipes-and-logging.md) |
| OCR, guided capture, offline behavior, local backup/restore | [OCR, Search, Offline Behavior, and Local Backup](../features/ocr-search-and-offline.md) |
| Runtime, persistence, authentication, or authority boundary | [Architecture Overview](../architecture/overview.md) and [Decision Index](../architecture/decisions.md) |
| Navigation chrome, draft guards, accessibility infrastructure | [Repository Tour](repository-tour.md#cross-cutting-mobile-ui-paths) and [Development Guide](development-guide.md#if-you-need-to-modify-navigation-route-headers-or-form-discard-behavior) |
| PostgreSQL-to-SQLite transfer | [PostgreSQL-to-SQLite Transfer](../operations/postgresql-to-sqlite-transfer.md) |
| Remote migrations, roles, recovery, release qualification, control plane | [Operations Index](../operations/README.md) |
| Terminology | [Glossary](../reference/glossary.md) |
| Historical decision or delivery provenance | [Historical Knowledge Index](../historical/README.md) |

The [Development Guide](development-guide.md) owns detailed task-to-code and
task-to-test routing.

## Architecture review path

Read the Constitution, Current State, Project Invariants, Architecture
Overview, relevant decisions, and the affected current guide. Consult
historical material only when provenance or a retained compatibility contract
is part of the review.

## Human orientation path

Use the same minimum path above. The
[Repository Tour](repository-tour.md) is the codebase map; the
[Development Guide](development-guide.md) owns modification procedures.

## Working rules

- Determine the selected application-data authority before tracing behavior.
- Treat implementation and migrations as authoritative when documentation drifts.
- Preserve the invariants named by [Project Invariants](invariants.md).
- Use native/file-backed SQLite evidence for local persistence claims and
  PostgreSQL evidence for remote Alembic, role, grant, locking, and
  concurrency claims.
- Finish with the [Testing Guide](../operations/testing.md) and the repository
  session-end contract.

## What stays outside ordinary context

Completed program plans, release manifests, phase chronology, manual QA
evidence, and implementation lessons remain reachable through
[Historical Knowledge](../historical/README.md). Load them only when the task
requires provenance, compatibility evidence, or a past decision.
