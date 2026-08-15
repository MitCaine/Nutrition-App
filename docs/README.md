# Documentation index

> **Document role: Current Guide.** This is the authoritative navigation entry point for repository knowledge.

The documentation is organized by purpose. Current product state, architecture, feature guides, operations, reference material, and historical implementation records have separate homes so ordinary work does not require loading the project's construction history.

## Start here

### Implementing a change

1. Follow the mandatory [Repository Session Contract](operations/session-contract.md#repository-session-contract).
2. Read the [Project Constitution](project/constitution.md) and [Current State](project/current-state.md).
3. Read [Project Invariants](project/invariants.md) and the relevant section of the [Development Guide](project/development-guide.md).
4. Load one affected [feature guide](#feature-guides), or the [Architecture Overview](architecture/overview.md) for a cross-cutting change.
5. Select validation from the [Testing Guide](operations/testing.md).

For a feature that has completed planning, follow the [GitHub Implementation Workflow](project/github-workflow.md) to translate the approved backlog into milestones, an Epic, child issues, and an optional Project.

Historical records are not part of the default implementation context. Open them only when a current guide links to a specific record or the task concerns provenance, migration history, or a past decision.

### Reviewing architecture

1. Read the [Project Constitution](project/constitution.md), [Current State](project/current-state.md), [Project Invariants](project/invariants.md), and the [Architecture Overview](architecture/overview.md).
2. Use the [Architecture Decision Index](architecture/decisions.md) to locate accepted decisions.
3. Read the affected feature or operations guide.
4. Apply the [Development Guide change checklist](project/development-guide.md#change-checklist).
5. Consult [historical engineering knowledge](historical/README.md) only for decision provenance.

### Joining the project

Start with [Onboarding](project/onboarding.md). It gives the shortest productive reading path for engineers, implementation agents, and architecture reviewers.

## Documentation taxonomy

| Area | Purpose | Included in ordinary implementation context? |
| --- | --- | --- |
| [`project/`](project/onboarding.md) | Current state, invariants, onboarding, repository navigation, and development workflow | Yes |
| [`architecture/`](architecture/overview.md) | Current system boundaries and accepted decision index | When the change crosses a boundary |
| [`features/`](features/foods-and-nutrition.md) | Current domain and user-facing subsystem guides | Only the affected guide |
| [`operations/`](operations/README.md) | Testing, session validation, transfer, control-plane operation, release qualification, and runbooks | Only for validation or operational work |
| [`reference/`](reference/glossary.md) | Stable lookup material | As needed |
| [`historical/`](historical/README.md) | Stage chronology, production-hardening records, release evidence, and learning routes | No, unless provenance is relevant |
| [`project/version-1.1/`](project/version-1.1/version-1.1-roadmap.md) | Completed Version 1.1 planning and implementation records | No, unless reviewing that program or its evidence |

## Current canonical project knowledge

- [Current State](project/current-state.md): current Version 1.2 product line, primary local-first runtime, preserved remote/reference runtime, supported boundaries, and current limitations.
- [Project Constitution](project/constitution.md): enduring purpose, scope, non-goals, quality standards, deployment model, and priorities.
- [Project Invariants](project/invariants.md): canonical cross-cutting technical invariants and rationale.
- [Onboarding](project/onboarding.md): minimum human and AI reading paths.
- [Repository Tour](project/repository-tour.md): directory map and change walkthroughs.
- [Development Guide](project/development-guide.md): code ownership, configuration, and change checklist.
- [GitHub Implementation Workflow](project/github-workflow.md): planning-to-delivery flow, GitHub artifact responsibilities, and backlog automation.
- [Implementation Lessons](project/implementation-lessons.md): retained engineering lessons from completed implementation work.

## Completed planning and implementation records

The Version 1.1 planning and local-first implementation program is complete. Its files remain available as historical implementation evidence rather than current planning state:

- [Version 1.1 Product Roadmap](project/version-1.1/version-1.1-roadmap.md).
- [Epic 1 Daily Logging Flow Grill](project/version-1.1/epic-1/grill.md).
- [Epic 1 Feature PRD](project/version-1.1/epic-1/feature-prd.md).
- [Epic 1 Architecture Review](project/version-1.1/epic-1/architecture-review.md).
- [Epic 1 Implementation Backlog](project/version-1.1/epic-1/implementation-backlog.md).
- [E1-17 Accessibility Remediation Stage 1](project/version-1.1/epic-1/accessibility-remediation-stage-1.md).
- [E1-17 Accessibility Remediation Stage 2](project/version-1.1/epic-1/accessibility-remediation-stage-2.md).
- [Epic 1 release qualification](project/version-1.1/epic-1/release-qualification.md).
- [Epic 2 Local-First Runtime Implementation Backlog](project/version-1.1/epic-2/implementation-backlog.md).
- [E2-15 Transfer Architecture and Runbook](project/version-1.1/epic-2/e2-15-transfer-architecture.md).
- [E2-16 Closure Evidence](project/version-1.1/epic-2/e2-16-closure-evidence.md).
- [E2-18 Release Qualification / Closure Evidence](project/version-1.1/epic-2/e2-18-closure-evidence.md).

## Architecture

- [Architecture Overview](architecture/overview.md): system, layer, persistence, runtime, and test boundaries.
- [Architecture Decision Index](architecture/decisions.md): concise accepted decisions with links to canonical explanations and provenance.

The default application-data authority is local SQLite. FastAPI/PostgreSQL remains a preserved alternate/reference authority. The two application-data authorities do not synchronize, dual-write, fail over, or silently mix.

## Feature guides

- [Foods and Nutrition](features/foods-and-nutrition.md): nutrients, servings, Foods, USDA, discovery, and Targets.
- [Recipes and Nutrition History](features/recipes-and-logging.md): authoring, immutable publication, revisions, projections, and Daily Logs.
- [OCR, Search, and Offline Behavior](features/ocr-search-and-offline.md): native recognition, parsing, provenance, search composition, caching, and network boundaries.

## Operations

Use the [Operations Index](operations/README.md) for the mandatory session workflow, testing, transfer qualification, preserved remote/PostgreSQL operations, control-plane material, and reproducible historical release qualification. Operational documents remain authoritative for their bounded areas but are not prerequisites for ordinary local-first feature work.

## Reference

- [Glossary](reference/glossary.md): canonical project vocabulary.

## Historical knowledge and learning

Use the [Historical Knowledge Index](historical/README.md) for stage records, production-hardening chronology, release evidence, manual QA evidence, and guided learning paths. Historical records preserve their point-in-time assertions and are never the authority for current repository state.

## Canonicality rules

- Implementation remains authoritative for behavior.
- [Project Constitution](project/constitution.md) owns enduring purpose, scope, non-goals, and engineering priorities.
- [Current State](project/current-state.md) owns current release/product-line, runtime-authority, migration-head, and deployment-boundary summaries.
- [Project Invariants](project/invariants.md) owns cross-cutting invariants and rationale.
- Current architecture, feature, and operations guides own their respective working guidance.
- Versioned planning directories and historical/evidence records preserve point-in-time context; correct present-day guidance in current docs rather than rewriting history.
- Prefer one canonical explanation and links from other documents.

## See also

- [Project README](../README.md)
- [Contributing](../CONTRIBUTING.md)
- [Repository Session Contract](operations/session-contract.md#repository-session-contract)
