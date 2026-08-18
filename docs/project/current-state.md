# Current state

> **Document role: Current Guide.** This is the single authoritative starting point for the current repository state. Update it when the active product line, runtime authority, roadmap status, migration heads, operational availability, or supported deployment boundary changes.

## Release and product status

Version 1.2 is the current product line.

Version 1.0 established the maintained production baseline. The Version 1.1 planning and implementation program is complete, including the Daily Logging Flow work, the complete Epic 2 local-first SQLite program, transfer tooling, accessibility qualification, remote/PostgreSQL isolation qualification, and Epic 2 release closure. Subsequent work on `main` added substantial nutrition-model, OCR, backup/restore, serving, target, and mobile UX refinements.

At this repository state, there is no open feature implementation issue or pull request. Epic 4 now has a frozen Version 1.2 planning package—research/Grill, Feature PRD, architecture/data contracts, and a bounded implementation backlog—but application implementation has not started. The package remains gated on repository documentation validation and project audit before GitHub implementation issues or code changes are authorized. Epic 5 remains planned and requires re-scope. The remaining known maintenance constraint is dependency-security cleanup that cannot be completed safely until compatible Expo/upstream dependency fixes are available. Dependency automation is intentionally constrained to Expo-compatible updates rather than forcing incompatible major versions.

The [Current Product Roadmap](product-roadmap.md) owns the canonical Epic numbering used going forward:

| Epic | Product area | Status |
| --- | --- | --- |
| Epic 1 | Daily Logging Flow | Complete |
| Epic 2 | Local-First SQLite Runtime | Complete |
| Epic 3 | Nutrition Label Capture Confidence | Complete; absorbed by Epic 2 OCR and subsequent OCR/camera work |
| Epic 4 | Nutrition History and Trends | Planning package complete; validation gate pending; implementation not started |
| Epic 5 | Recipe Reuse and Discovery | Planned; requires re-scope because substantial adjacent Recipe work already landed |

The historical Version 1.1 product roadmap predates this canonical numbering. In that record, Nutrition History and Trends was product Epic 2, Recipe Reuse and Discovery was product Epic 3, and Nutrition Label Capture Confidence was product Epic 4. Current planning maps those product areas to Epics 4, 5, and 3 respectively. Historical documents retain their point-in-time numbering rather than being rewritten as if the current sequence had existed when they were authored.

The Version 1.1 roadmap, PRDs, architecture reviews, implementation backlogs, and closure records are retained as historical implementation evidence. They are not the current planning state. Current Version 1.2 Epic 4 planning is indexed separately and remains planning evidence until implementation/qualification promotes behavior into current feature and architecture guides.

## Current application architecture

The primary application runtime is the iOS-first local authority selected through `NutritionRuntime`. In normal use, on-device SQLite is authoritative for Foods, Recipes, Daily Logs, Targets, OCR confirmation/provenance, USDA imports, favorites/recents, idempotency state, and related local application data.

The preserved FastAPI/PostgreSQL implementation remains available as an alternate remote/reference authority. Exactly one application-data authority is selected for a running context. There is no synchronization, fallback, dual write, background replication, automatic failover, or silent authority mixing.

Local backup/restore is a replacement workflow for the selected SQLite authority, not synchronization. It exports a validated coherent SQLite snapshot and validates/stages a selected backup before activation on a later local-runtime bootstrap. It does not create a second live authority or a cloud replica.

The separate control-plane/operations architecture is retained for remote/PostgreSQL migration, promotion, evidence, qualification, activation, and recovery work. It is not part of ordinary local application requests and is not a second application backend.

The [Architecture Overview](../architecture/overview.md) owns the full current system/layer model; the [Architecture Decision Index](../architecture/decisions.md) owns accepted structural choices.

## Current user-facing capabilities

- Personal Food creation, editing, collision-aware duplication, favorites, recents, search, serving definitions, and exact decimal nutrition handling.
- Expanded canonical nutrient coverage spanning macros, vitamins, minerals, fatty acids, total Omega-3, ALA, EPA, DHA, and linoleic acid/Omega-6, including nutrient-specific canonical units where required.
- Serving authoring with explicit gram authority and optional reference-measurement metadata so unit changes preserve physical equivalence rather than silently changing amount meaning.
- Recipe authoring, nested published Recipe use, immutable publication revisions, generated Food compatibility projections, explicit serving/yield authoring, and draft-preserving navigation guards.
- Daily Logs with immutable nutrient snapshots so later Food or Recipe edits cannot rewrite historical nutrition.
- Local-first SQLite persistence for the normal personal workflow.
- Validated local SQLite backup export plus staged restore with restart-time activation, rollback protection, and retained success/failure evidence.
- Native Apple Vision nutrition-label OCR on iOS, app-owned guided camera capture, structured review/confirmation, conservative pre-recognition capture-quality warnings, and immutable bounded correction provenance.
- Direct USDA FoodData Central search/import in local mode with secure request-time on-device credential handling and expanded nutrient mapping.
- Daily target comparison with per-nutrient tracking preferences, manual overrides, DRI recommendations where supported, FDA Daily Value fallback/reference data, neutral amount-only tracking when no goal is established, and explicit unavailable states.
- Personalized DRI recommendations for supported adult reference profiles, including supported pregnancy/lactation life stages; calorie estimation remains a separate general-adult Mifflin–St Jeor calculation.
- Accessibility-focused navigation, shared fixed/sticky route headers, focus restoration, mutation/recovery semantics, unsaved-draft protection, and light/dark presentation.
- One-time PostgreSQL-to-SQLite transfer tooling for installations migrating from the preserved remote authority.

Nutrition History and Trends is **not** listed above as a current capability because Epic 4 remains unimplemented. Its accepted planned behavior is documented in the [Version 1.2 Epic 4 planning package](version-1.2/epic-4/README.md).

## Remote/reference migration heads

These heads describe the preserved PostgreSQL/control-plane streams. They do not govern the local SQLite schema-version migration engine.

| Authority | Current head |
| --- | --- |
| Remote application PostgreSQL migration | `0030_total_omega_3_nutrient` |
| Control PostgreSQL migration | `ops_0011_phase5c4_recovery_audit` |

Revision `0021_target_activation_execution` remains an authorized target-activation migration, not an ordinary development upgrade. Use the applicable runbook rather than advancing to it through a convenience startup path.

## Operational state

Target activation and emergency close, purpose-specific preactivation cutback, evidence-driven recovery, cumulative recovery qualification, role separation, and disposable infrastructure qualification remain implemented for the preserved remote/operations path. The [Operations Index](../operations/README.md) is the canonical entry point for exact authority, commands, validation, and limitations.

Historical Version 1.0 and Version 1.1 release/closure evidence remains available for provenance and regression context; it is not current product planning guidance.

## Current documentation entry points

| Need | Canonical document |
| --- | --- |
| Current product line and supported boundaries | This document |
| Current product Epic numbering and planning status | [Current Product Roadmap](product-roadmap.md) |
| Version 1.2 Epic 4 frozen planning package | [Epic 4 Planning Index](version-1.2/epic-4/README.md) |
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
- Local backup/restore covers the local SQLite application database. It is not automatic cloud backup, cross-device synchronization, remote PostgreSQL backup, or conflict reconciliation. USDA credentials and other secrets are not included in exported local backups.
- Native Apple Vision label recognition and image-quality inspection require an iOS development or release build. Expo Go cannot load the native project module. Capture-quality checks are advisory/best-effort and do not replace user review of OCR results.
- Local USDA search requires network access to FoodData Central and a configured personal credential stored through the app's secure credential path.
- DRI recommendations support adults age 19 and older where the canonical dataset has an established recommendation and required profile inputs. Pregnancy/lactation are supported for female reference profiles age 19–50. Pediatric and specialized-medical target models remain unsupported. The Mifflin–St Jeor maintenance-calorie estimate is narrower: general-adult context, required profile inputs, and supported ages 19–78.
- Some nutrients intentionally have no established DRI/FDA goal and therefore default to amount-only presentation instead of inventing a target. Per-nutrient preferences can also explicitly select amount-only or ignored tracking.
- The independent control gate is not consumed by ordinary local application requests. Remote provider routing, infrastructure backup/restore, and readback remain bounded operator/provider responsibilities distinct from the local user backup feature.
- Local infrastructure qualification proves only its documented disposable topology/provider stand-ins; it is not production-vendor certification.
- Known dependency vulnerabilities that require versions outside the currently supported Expo compatibility envelope remain deferred until compatible upstream fixes are available; incompatible forced upgrades are not treated as a valid remediation.

## Authority and maintenance

When sources disagree, use this order:

1. implementation and migrations;
2. this Current State document and current architecture, feature, and operations guides;
3. accepted architecture decisions and technical invariants; and
4. completed versioned planning records, historical documents, and evidence records for provenance only.

The Version 1.2 Epic 4 planning package governs only the planned Epic 4 scope until implementation is completed and reconciled into current guides.

Report drift instead of silently reconciling contradictory documents in working memory. Keep this page concise by linking to canonical detail rather than copying every feature inventory, rationale, or runbook instruction.
