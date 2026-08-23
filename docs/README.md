# Documentation index

> **Document role: Current Guide.** This is the authoritative navigation entry point for repository knowledge.

The documentation is organized by purpose. Current product state, architecture, feature guides,
operations, reference material, and historical implementation records have separate homes so
ordinary work does not require loading the project's construction history.

## Start here

### Implementing a change

1. Follow the mandatory [Repository Session Contract](operations/session-contract.md#repository-session-contract).
2. Read the [Project Constitution](project/constitution.md) and [Current State](project/current-state.md).
3. Read [Project Invariants](project/invariants.md) and the relevant section of the [Development Guide](project/development-guide.md).
4. Load one affected [feature guide](#feature-guides), or the [Architecture Overview](architecture/overview.md) for a cross-cutting change.
5. Select validation from the [Testing Guide](operations/testing.md).

For a new feature that has completed planning, follow the [GitHub Implementation Workflow](project/github-workflow.md)
to translate approved scope into implementation artifacts. Do not treat completed Version 1.1/Epic 2
backlogs or closed issues as current work simply because their records remain in the repository.

Epic 4 — Nutrition History and Trends is implemented and qualified. Current feature, architecture,
project, and testing guides own the delivered behavior. The frozen
[Epic 4 Planning and Delivery Index](project/version-1.2/epic-4/README.md) remains easy to reach as
point-in-time research, decision, architecture, backlog, delivery, and closure provenance.

Historical records are not part of the default implementation context. Open them only when a
current guide links to a specific record or the task concerns provenance, migration history,
compatibility evidence, or a past decision.

### Reviewing architecture

1. Read the [Project Constitution](project/constitution.md), [Current State](project/current-state.md), [Project Invariants](project/invariants.md), and the [Architecture Overview](architecture/overview.md).
2. Use the [Architecture Decision Index](architecture/decisions.md) to locate accepted decisions.
3. Read the affected feature or operations guide.
4. Apply the [Development Guide change checklist](project/development-guide.md#change-checklist).
5. Consult [historical engineering knowledge](historical/README.md) only for decision provenance.

### Joining or returning to the project

Start with [Onboarding](project/onboarding.md), then use the [Repository Tour](project/repository-tour.md).
The current repository is beyond the completed Version 1.1/Epic 2 implementation program, so current
guides—not old planning artifacts—are the source for implemented feature scope. Version 1.2 planning
is retained historical provenance and does not govern current Version 2.0 implementation work.

## Documentation taxonomy

| Area | Purpose | Included in ordinary implementation context? |
| --- | --- | --- |
| [`project/`](project/onboarding.md) | Current state, invariants, onboarding, repository navigation, development workflow, and active versioned product planning | Yes |
| [`architecture/`](architecture/overview.md) | Current system boundaries and accepted decision index | When the change crosses a boundary |
| [`features/`](features/foods-and-nutrition.md) | Current implemented domain and user-facing subsystem guides | Only the affected guide |
| [`operations/`](operations/README.md) | Testing, session validation, transfer qualification, preserved remote/PostgreSQL operations, control-plane operation, release qualification, runbooks | Only for validation or operational work |
| [`reference/`](reference/glossary.md) | Stable lookup material | As needed |
| [`historical/`](historical/README.md) | Stage chronology, production-hardening records, release evidence, learning routes | No, unless provenance is relevant |
| [`project/version-1.1/`](project/version-1.1/version-1.1-roadmap.md) | Completed Version 1.1/Epic 1/Epic 2 planning, implementation, and closure records | No, unless reviewing that program or retained compatibility evidence |
| [`project/version-1.2/epic-4/`](project/version-1.2/epic-4/README.md) | Frozen Epic 4 planning, architecture, backlog, delivery, and closure provenance | Only for Epic 4 provenance or retained acceptance evidence |

## Current canonical project knowledge

- [Version 2.0 Release Record](project/version-2.0-release.md): canonical source/GitHub release identity, supported toolchains, runtime boundaries, qualification, known limitations, and post-review publication sequence.
- [Current State](project/current-state.md): current Version 2.0 product line, completed Epics,
  local-first authority, preserved remote/reference runtime, current capabilities/limitations, and
  dependency-maintenance boundary.
- [Current Product Roadmap](project/product-roadmap.md): canonical current Epic numbering, completion
  and implementation status, and the mapping from historical Version 1.1 product numbering.
- [Epic 4 Planning and Delivery Index](project/version-1.2/epic-4/README.md): frozen Nutrition History
  and Trends research/Grill, Feature PRD, data/runtime contracts, architecture review,
  implementation backlog, and delivery links retained as planning and closure provenance.
- [Project Constitution](project/constitution.md): enduring purpose, scope, non-goals, quality standards,
  deployment model, and priorities.
- [Project Invariants](project/invariants.md): canonical cross-cutting technical invariants and rationale,
  including immutable history, serving authority, Target/reference separation, and local backup semantics.
- [Onboarding](project/onboarding.md): minimum human and AI reading paths.
- [Repository Tour](project/repository-tour.md): current directory map, including local backup,
  DRI/reference data, shared Epic 2 contracts, and cross-cutting mobile UI infrastructure.
- [Development Guide](project/development-guide.md): code ownership, configuration, current migration
  head, feature/backup/UI change paths, and change checklist.
- [GitHub Implementation Workflow](project/github-workflow.md): planning-to-delivery flow and GitHub
  artifact responsibilities for future work.
- [Implementation Lessons](project/implementation-lessons.md): retained engineering lessons from
  completed implementation work.
- [Future Product and Scalability Options](project/future-product-and-scale.md): non-roadmap idea register
  for deliberately deferred product, platform, accessibility, and scaling options.

## Current repository status

Version 2.0 is the current source-release line. Root `VERSION` is the canonical repository release authority, with current mobile, Expo, backend, and documentation metadata mirroring `2.0.0`. Qualification uses Node 24 and Python 3.12.

Version 1.1 and the technical Epic 2 program are complete. Subsequent implementation issue/PR work
represented before Epic 4 is also closed. Nutrition Label Capture Confidence is completed Epic 3.

Epic 4 — Nutrition History and Trends is complete. E4-01 through E4-15 delivered explicit date-owned
Complete state, bounded History evidence/shared projections, logging-first Daily Log and Daily
Nutrition surfaces, 7/30-day History analysis, Food-authoring refinements, and Complete durability.
E4-16 qualified local SQLite, physical PostgreSQL 16, shared-projection, failure, and target-iPhone
behavior. Separate #144 documentation-validation hardening, #147 Expo patch maintenance, and #148
30-day selected-date viewport alignment remain non-blocking follow-ups rather than unfinished Epic 4
acceptance scope.

Epic 5 — Recipe Reuse and Discovery remains planned and requires re-scope.

Current `main` includes substantial post-Epic-2 work: expanded nutrient coverage and qualified units,
serving reference/gram-authority fixes, improved Recipe serving/yield UX, personalized DRI-based
Targets and per-nutrient tracking preferences, safe local backup/restore, guided nutrition-label
camera capture, conservative OCR image-quality warnings, unsaved-draft protection, standardized
sticky/fixed route headers, and related accessibility/refinement work.

The remaining known maintenance constraint is dependency-security cleanup that requires
Expo-compatible upstream fixes. Version 2.0 currently carries three accepted Dependabot warnings in the Expo toolchain: two high-severity `image-size` alerts and one moderate `uuid` alert. Incompatible forced upgrades are not accepted remediation. Current documentation must not describe closed issues/PRs as the
active implementation backlog.

## Retained Version 1.2 Epic 4 planning and delivery records

Epic 4's frozen package records the approved plan and delivery sequence that produced the current
implementation. It is retained provenance, not the current behavior authority:

- [Epic 4 Planning and Delivery Index](project/version-1.2/epic-4/README.md).
- [Epic 4 Research Record](project/version-1.2/epic-4/planning.md).
- [Epic 4 Grill Decision Record](project/version-1.2/epic-4/accepted-decisions.md).
- [Epic 4 Feature PRD](project/version-1.2/epic-4/feature-prd.md).
- [Epic 4 Data and Runtime Contracts](project/version-1.2/epic-4/data-contracts.md).
- [Epic 4 Architecture Review](project/version-1.2/epic-4/architecture-review.md).
- [Epic 4 Implementation Backlog](project/version-1.2/epic-4/implementation-backlog.md).
- [GitHub Epic #113](https://github.com/MitCaine/Nutrition-App/issues/113): retained delivery index for E4-01–E4-17.

These artifacts preserve point-in-time scope, acceptance, and delivery provenance. Current feature,
architecture, project, and operations guides own what the application now does.

## Completed planning and implementation records

The Version 1.1 planning and local-first implementation program is complete. Its files remain
available as historical implementation/closure evidence rather than current planning state:

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
- [Issue #108 Sticky Navigation Header Inventory](project/version-1.1/issue-108-sticky-header-inventory.md).

These records preserve point-in-time plans, acceptance criteria, and closure evidence. A feature
mentioned there as proposed/future is not a current capability unless current implementation and
current guides say it exists. Conversely, post-program work may exist even when those historical
plans do not mention it.

## Architecture

- [Architecture Overview](architecture/overview.md): current implemented system, layer, persistence,
  runtime, local-backup/bootstrap, UI-infrastructure, and test boundaries.
- [Architecture Decision Index](architecture/decisions.md): accepted implemented decisions including
  explicit application-data authority, serving/reference authority, reference-derived Targets, and
  validated local backup replacement.
- [PostgreSQL Runtime-Authority Evolution](engineering/postgresql-runtime-authority.md): forward
  relation classification, exact privilege decisions, write-fence integration, and PG16 proof.

The default application-data authority is local SQLite. FastAPI/PostgreSQL remains a preserved
alternate/reference authority. The two application-data authorities do not synchronize, dual-write,
fail over, or silently mix. A local backup is a validated replacement artifact, not a second live
authority.

Epic 4's approved pre-implementation architecture remains versioned as closure provenance. The
current Architecture Overview and Decision Index describe the implemented Complete/History
boundaries.

## Feature guides

- [Foods and Nutrition](features/foods-and-nutrition.md): expanded nutrient catalog/qualified units,
  serving/reference measurements, Foods, USDA, discovery, DRI/FDA Targets, and per-nutrient tracking
  policy.
- [Recipes and Nutrition History](features/recipes-and-logging.md): authoring/yields/serving choices,
  immutable publication, revisions, projections, Daily Logs, explicit Complete state, bounded 7/30-
  day Nutrition History, shared projection semantics, and current guarded mobile behavior.
- [OCR, Search, Offline Behavior, and Local Backup](features/ocr-search-and-offline.md): guided native
  camera capture, Apple Vision recognition, conservative quality hints, parsing/provenance, search
  composition, local/remote offline boundaries, and validated local SQLite backup/restore.

## Operations

Use the [Operations Index](operations/README.md) for the mandatory session workflow, testing,
transfer qualification, preserved remote/PostgreSQL operations, control-plane material, and
reproducible historical release qualification. Operational documents remain authoritative for their
bounded areas but are not prerequisites for ordinary local-first feature work.

The [Testing Guide](operations/testing.md) includes current DRI/Target, local backup/restore,
serving/reference, OCR camera/quality, route-header/draft-guard, local/native SQLite, transfer,
PostgreSQL, and control-plane proof boundaries.

## Reference

- [Glossary](reference/glossary.md): canonical project vocabulary, including current authority,
  serving-reference, DRI/tracking, and local-backup terms.

## Historical knowledge and learning

Use the [Historical Knowledge Index](historical/README.md) for stage records,
production-hardening chronology, release evidence, manual QA evidence, and guided learning paths.
Historical records preserve their point-in-time assertions and are never the authority for current
repository state.

## Canonicality rules

- Implementation and migrations remain authoritative for implemented behavior/state.
- [Project Constitution](project/constitution.md) owns enduring purpose, scope, non-goals, and engineering priorities.
- [Current State](project/current-state.md) owns current release/product-line, runtime-authority,
  migration-head, completed-program, and deployment/maintenance-boundary summaries.
- [Current Product Roadmap](project/product-roadmap.md) owns current Epic numbering and product-Epic status.
- [Project Invariants](project/invariants.md) owns cross-cutting invariants and rationale.
- Current architecture, feature, and operations guides own their respective implemented guidance.
- An explicitly active versioned planning package may own approved implementation scope before a
  behavior exists; a completed frozen package remains provenance and does not override current
  guides about implemented behavior.
- Versioned completed planning directories and historical/evidence records preserve point-in-time context;
  correct present-day guidance in current docs rather than rewriting history.
- A closed historical issue/roadmap entry is not current unfinished work merely because its document remains.
- Prefer one canonical explanation and links from other documents.

## See also

- [Project README](../README.md)
- [Contributing](../CONTRIBUTING.md)
- [Repository Session Contract](operations/session-contract.md#repository-session-contract)
