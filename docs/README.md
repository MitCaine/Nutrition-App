# Documentation index

> **Document role: Current Guide.** This is the authoritative navigation entry
> point for repository knowledge. It routes readers to the document that owns a
> fact; it does not duplicate current status or historical inventories.

## Start here

### Implementing a change

1. Follow the mandatory [Repository Session Contract](operations/session-contract.md#repository-session-contract).
2. Read [Current State](project/current-state.md) for what is true now.
3. Read the [Project Constitution](project/constitution.md) and [Project Invariants](project/invariants.md).
4. Use the [Development Guide](project/development-guide.md) to locate the owning code and validation.
5. Load only the affected feature, architecture, or operations guide.

Use the [GitHub Implementation Workflow](project/github-workflow.md) after
planning is approved and implementation work needs to be represented in GitHub.

### Reviewing architecture

Read [Current State](project/current-state.md), [Project Invariants](project/invariants.md),
the [Architecture Overview](architecture/overview.md), the
[Architecture Decision Index](architecture/decisions.md), and the affected
feature or operations guide. Historical records are additional provenance, not
current behavior authority.

### Joining or returning to the project

Start with [Onboarding](project/onboarding.md), then use the
[Repository Tour](project/repository-tour.md) for codebase topology and the
[Development Guide](project/development-guide.md) for change-specific routing.

## Documentation taxonomy

| Area | Purpose | Ordinary implementation context |
| --- | --- | --- |
| [`project/`](project/onboarding.md) | Current state, roadmap, invariants, onboarding, repository topology, development routing, and planning workflow | Yes |
| [`architecture/`](architecture/overview.md) | Current system boundaries and accepted structural decisions | When a change crosses a boundary |
| [`features/`](features/foods-and-nutrition.md) | Current implemented domain behavior | Only the affected guide |
| [`operations/`](operations/README.md) | Testing, session validation, transfer, PostgreSQL/control-plane operation, and runbooks | For validation or operational work |
| [`reference/`](reference/glossary.md) | Stable terminology and lookup material | As needed |
| [`historical/`](historical/README.md) | Completed programs, release evidence, phase chronology, and implementation provenance | Only when provenance is relevant |

## Current canonical project knowledge

- [Current State](project/current-state.md): current product line, runtime
  authority, migration heads, supported boundaries, and known limitations.
- [Current Product Roadmap](project/product-roadmap.md): canonical Epic
  numbering and current product-planning status.
- [Project Constitution](project/constitution.md): enduring purpose, scope,
  non-goals, deployment model, and priorities.
- [Project Invariants](project/invariants.md): cross-cutting technical truths
  that changes must preserve.
- [Onboarding](project/onboarding.md): minimum useful implementation/review
  context.
- [Repository Tour](project/repository-tour.md): filesystem and code-layer
  topology.
- [Development Guide](project/development-guide.md): startup, task-to-code
  routing, migrations, validation selection, and change checklist.
- [GitHub Implementation Workflow](project/github-workflow.md):
  planning-to-GitHub artifact responsibilities.
- [Future Product and Scalability Options](project/future-product-and-scale.md):
  deliberately non-roadmap idea register.

## Current repository status

[Current State](project/current-state.md) owns live release, runtime, migration,
maintenance, and limitation facts. The
[Current Product Roadmap](project/product-roadmap.md) owns current Epic status.
This navigation index intentionally does not duplicate either inventory.

## Retained Version 1.2 Epic 4 planning and delivery records

The completed package is indexed under
[Historical Knowledge](historical/README.md). Open it only for Epic 4 planning,
architecture, acceptance, or delivery provenance.

## Completed planning and implementation records

Completed Version 1.1 and other implementation records are indexed under
[Historical Knowledge](historical/README.md). They do not define current
feature or release state.

## Architecture

- [Architecture Overview](architecture/overview.md): current runtime, layer,
  persistence, authority, configuration, and testing boundaries.
- [Architecture Decision Index](architecture/decisions.md): accepted and
  superseded structural decisions with their provenance.
- [PostgreSQL Runtime-Authority Evolution](engineering/postgresql-runtime-authority.md): preserved remote-authority
  relation classification, privilege boundaries, write-fence integration, and PostgreSQL 16 proof.

## Feature guides

- [Foods and Nutrition](features/foods-and-nutrition.md)
- [Recipes and Nutrition History](features/recipes-and-logging.md)
- [OCR, Search, Offline Behavior, and Local Backup](features/ocr-search-and-offline.md)

Feature guides own current implemented domain behavior. Historical PRDs and
backlogs do not override them.

## Operations

- [Operations Index](operations/README.md)
- [Testing Guide](operations/testing.md)
- [Dependency Risk Management](operations/dependency-risk-management.md)
- [PostgreSQL-to-SQLite Personal Transfer](operations/postgresql-to-sqlite-transfer.md)
- [Control Plane Guide](operations/control-plane.md)

The Operations Index owns navigation to current runbooks and retained
qualification entry points.

## Reference

Use the [Glossary](reference/glossary.md) for repository-specific terminology.

## Historical knowledge and learning

Use the [Historical Knowledge Index](historical/README.md) for completed
version programs, release records, production-hardening chronology, evidence,
and retained implementation lessons.

Historical documents preserve point-in-time assertions. Correct present-day
guidance in current documents instead of rewriting historical prose.

## Canonicality rules

- Implementation and migrations own implemented behavior and schema state.
- [Current State](project/current-state.md) owns current release/runtime,
  migration-head, support-boundary, and limitation summaries.
- [Current Product Roadmap](project/product-roadmap.md) owns current Epic
  numbering and planning status.
- [Project Constitution](project/constitution.md) owns enduring product scope
  and priorities.
- [Project Invariants](project/invariants.md) owns cross-cutting invariants.
- Current architecture, feature, and operations guides own their bounded
  implementation guidance.
- Historical records own provenance only.
- Prefer one canonical explanation and links from other documents.

## See also

- [Root README](../README.md)
- [Contributing](../CONTRIBUTING.md)
- [Engineering Workflow](../engineering/README.md)
