# Current state

> **Document role: Current Guide.** This is the single authoritative starting point for the current repository state. Update it when the active product line, runtime authority, roadmap status, migration heads, operational availability, or supported deployment boundary changes.

## Release and product status

Version 1.2 is the current product line.

Version 1.0 established the maintained production baseline. The Version 1.1 planning and implementation program is complete, including the Daily Logging Flow work, the local-first SQLite runtime, transfer tooling, accessibility qualification, remote/PostgreSQL isolation qualification, and Epic 2 closure. The current main branch has moved beyond that program and includes subsequent personalized general-adult nutrition targets and UI refinements.

The Version 1.1 roadmap, PRDs, architecture reviews, implementation backlogs, and closure records are retained as historical implementation evidence. They are not the current planning state. New scope should be documented deliberately rather than inferred from those completed planning artifacts.

## Current application architecture

The primary application runtime is the iOS-first local authority selected through `NutritionRuntime`. In normal use, on-device SQLite is authoritative for Foods, Recipes, Daily Logs, Targets, OCR confirmation/provenance, USDA imports, favorites/recents, idempotency state, and related local application data.

The preserved FastAPI/PostgreSQL implementation remains available as an alternate remote/reference authority. Exactly one application-data authority is selected for a running context. There is no synchronization, fallback, dual write, background replication, automatic failover, or silent authority mixing.

The separate control-plane/operations architecture is retained for remote/PostgreSQL migration, promotion, evidence, qualification, activation, and recovery work. It is not part of ordinary local application requests and is not a second application backend.

The [Architecture Overview](../architecture/overview.md) owns the full current system/layer model; the [Architecture Decision Index](../architecture/decisions.md) owns accepted structural choices.

## Current user-facing capabilities

- Personal Food creation, editing, duplication, favorites, search, serving definitions, and exact decimal nutrition handling.
- Recipe authoring, nested published Recipe use, immutable publication revisions, and generated Food compatibility projections.
- Daily Logs with immutable nutrient snapshots so later Food or Recipe edits cannot rewrite historical nutrition.
- Local-first SQLite persistence for the normal personal workflow.
- Native Apple Vision nutrition-label OCR on iOS, structured review/confirmation, and immutable bounded correction provenance.
- Direct USDA FoodData Central search/import in local mode with secure on-device credential storage.
- Daily target comparison with manual overrides, personalized general-adult targets where supported, FDA Daily Value fallbacks/references, and explicit unavailable states.
- Personalized calories plus general-adult recommendations for protein, carbohydrate, total fat, saturated fat, iron, calcium, vitamin D, potassium, magnesium, and fiber where the required profile inputs are available.
- Accessibility-focused navigation, focus restoration, mutation/recovery semantics, and light/dark presentation.
- One-time PostgreSQL-to-SQLite transfer tooling for installations migrating from the preserved remote authority.

## Remote/reference migration heads

These heads describe the preserved PostgreSQL/control-plane streams. They do not govern the local SQLite schema-version migration engine.

| Authority | Current head |
| --- | --- |
| Remote application PostgreSQL migration | `0026_food_nutrient_integrity` |
| Control PostgreSQL migration | `ops_0011_phase5c4_recovery_audit` |

Revision `0021_target_activation_execution` remains an authorized target-activation migration, not an ordinary development upgrade. Use the applicable runbook rather than advancing to it through a convenience startup path.

## Operational state

Target activation and emergency close, purpose-specific preactivation cutback, evidence-driven recovery, cumulative recovery qualification, role separation, and disposable infrastructure qualification remain implemented for the preserved remote/operations path. The [Operations Index](../operations/README.md) is the canonical entry point for exact authority, commands, validation, and limitations.

Historical Version 1.0 and Version 1.1 release/closure evidence remains available for provenance and regression context; it is not current product planning guidance.

## Current documentation entry points

| Need | Canonical document |
| --- | --- |
| Current product line and supported boundaries | This document |
| Enduring purpose, scope, and priorities | [Project Constitution](constitution.md) |
| Technical truths that changes must preserve | [Project Invariants](invariants.md) |
| Minimum implementation or review context | [Project Onboarding](onboarding.md) |
| Current system boundaries | [Architecture Overview](../architecture/overview.md) |
| Accepted structural choices | [Architecture Decision Index](../architecture/decisions.md) |
| Code ownership and change checklist | [Development Guide](development-guide.md) |
| Testing, qualification, transfer, release, and recovery | [Operations Index](../operations/README.md) |
| Completed Version 1.1 planning/implementation records | [Version 1.1 Product Roadmap](version-1.1/version-1.1-roadmap.md) |
| Historical provenance and learning | [Historical Knowledge Index](../historical/README.md) |

The [Documentation Index](../README.md) remains the authoritative navigation map for the full knowledge system.

## Known limitations and boundaries

- Public multi-user production deployment is intentionally unsupported. There is no production identity provider or multi-tenant trust model; private single-user authentication in the remote path is not a scalable account system.
- The selected mobile application-data authority is either local SQLite or remote FastAPI/PostgreSQL. There is no synchronization, fallback, dual write, background sync, or shared recovery/cache authority.
- Native Apple Vision label recognition requires an iOS development or release build. Expo Go cannot load the native project module.
- Local USDA search requires network access to FoodData Central and a configured personal credential stored through the app's secure credential path.
- General-adult personalized nutrition targets intentionally do not silently cover pregnancy, lactation, pediatric profiles, specialized medical nutrition, or athletic-program targets. Unsupported cases retain appropriate FDA references or unavailable states.
- The independent control gate is not consumed by ordinary local application requests. Provider routing, backup, restore, and readback remain bounded operator/provider responsibilities.
- Local infrastructure qualification proves only its documented disposable topology/provider stand-ins; it is not production-vendor certification.

## Authority and maintenance

When sources disagree, use this order:

1. implementation and migrations;
2. this Current State document and current architecture, feature, and operations guides;
3. accepted architecture decisions and technical invariants; and
4. completed versioned planning records, historical documents, and evidence records for provenance only.

Report drift instead of silently reconciling contradictory documents in working memory. Keep this page concise by linking to canonical detail rather than copying every feature inventory, rationale, or runbook instruction.
