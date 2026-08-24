# Current state

> **Document role: Current Guide.** This is the single authoritative starting point for the current repository state. Update it when the active product line, runtime authority, roadmap status, migration heads, operational availability, or supported deployment boundary changes.

## Release and product status

Version 2.0 is the current product line. Root `VERSION` is the canonical
repository release authority with exact value `2.0.0`; current mobile, Expo,
backend, and documentation metadata mirror it. Version 2.0 qualification uses
Node 24 and Python 3.12.

The finalized [Version 2.0 release record](../historical/releases/version-2.0-release.md)
preserves the qualified integration commit, annotated tag, and GitHub Release
publication evidence.

Epic 4 — Nutrition History and Trends is implemented and qualified.
Epic 5 remains planned and requires re-scope. The
[Current Product Roadmap](product-roadmap.md) owns canonical Epic numbering and
the complete current planning-status table.

Completed Version 1.1 and Version 1.2 planning, implementation, qualification,
and closure packages are historical provenance. They do not define current
feature state.
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
- Explicit date-owned Complete assertions for non-empty Daily Log dates. Complete is never inferred; nutrition-changing Log mutations invalidate it atomically, while exact snapshot-preserving and metadata-only edits preserve it.
- Nutrition History and Trends for 7-day and 30-day calendar ranges ending yesterday, with honest Complete-day/Logged-day denominators, four macro overview cards, grouped Nutrition Details, focused nutrient History, exact daily values, and navigation to the authoritative Daily Log date.
- Local-first SQLite persistence for the normal personal workflow.
- Validated local SQLite backup export plus staged restore with restart-time activation, rollback protection, and retained success/failure evidence.
- Native Apple Vision nutrition-label OCR on iOS, app-owned guided camera capture, structured review/confirmation, conservative pre-recognition capture-quality warnings, and immutable bounded correction provenance.
- Direct USDA FoodData Central search/import in local mode with secure request-time on-device credential handling and expanded nutrient mapping.
- Daily target comparison with per-nutrient tracking preferences, manual overrides, DRI recommendations where supported, FDA Daily Value fallback/reference data, neutral amount-only tracking when no goal is established, and explicit unavailable states.
- Personalized DRI recommendations for supported adult reference profiles, including supported pregnancy/lactation life stages; calorie estimation remains a separate general-adult Mifflin–St Jeor calculation.
- Accessibility-focused navigation, shared fixed/sticky route headers, focus restoration, mutation/recovery semantics, unsaved-draft protection, and light/dark presentation.
- One-time [PostgreSQL-to-SQLite personal transfer](../operations/postgresql-to-sqlite-transfer.md) tooling for installations migrating from the preserved remote authority.

History derives from immutable Daily Log snapshots rather than current Foods or Recipes. No-Log dates remain gaps, explicit zero remains a usable zero, and unknown-only nutrient evidence remains unavailable. Current Targets are a presentation lens only; the app does not reconstruct historical target configuration. See [Recipes and Nutrition History](../features/recipes-and-logging.md) for the feature contract and the retained [Version 1.2 Epic 4 package](../historical/programs/version-1.2/epic-4/README.md) for planning and closure provenance.

## Remote/reference migration heads

These heads describe the preserved PostgreSQL/control-plane streams. They do not govern the local SQLite schema-version migration engine.

The current preserved remote application runtime requires PostgreSQL already provisioned and qualified at `0033_complete_runtime_authority`.

Schema `0020_immutable_provenance_enforcement` is retained only as the `LIMITED_PREACTIVATION_OPERATIONS_SANDBOX`; it is not current feature-parity remote startup. The target-activation procedure remains pinned to `0021_target_activation_execution`, an operations-only boundary. Ordinary development must not use an unqualified `alembic upgrade head` to cross that procedure boundary.

| Authority | Current head |
| --- | --- |
| Remote application PostgreSQL migration | `0033_complete_runtime_authority` |
| Control PostgreSQL migration | `ops_0011_phase5c4_recovery_audit` |

Revision `0021_target_activation_execution` remains an authorized target-activation migration, not an ordinary development upgrade. Use the applicable runbook rather than advancing to it through a convenience startup path.

## Operational state

Target activation and emergency close, purpose-specific preactivation cutback, evidence-driven recovery, cumulative recovery qualification, role separation, and disposable infrastructure qualification remain implemented for the preserved remote/operations path. The [Operations Index](../operations/README.md) is the canonical entry point for exact authority, commands, validation, and limitations.

Historical Version 1.0 and Version 1.1 release/closure evidence remains available for provenance and regression context; it is not current product planning guidance.

## Current documentation entry points

The [Documentation Index](../README.md) owns current-document navigation.
Use that index rather than maintaining a second routing table here.
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
- The repository currently has three open Dependabot alerts in the Expo/toolchain dependency graph: two high-severity `image-size` alerts and one medium-severity `uuid` alert. Compatible upstream remediation remains deferred; incompatible forced upgrades are not treated as valid remediation.
- Version 2.0 is a source/GitHub release boundary. No iOS `buildNumber` or Android `versionCode` is introduced by this release, and no App Store or Play Store binary publication is implied.

## Authority and maintenance

When sources disagree, use this order:

1. implementation and migrations;
2. this Current State document and current architecture, feature, and operations guides;
3. accepted architecture decisions and technical invariants; and
4. completed versioned planning records, historical documents, and evidence records for provenance only.

The Version 1.2 Epic 4 package preserves the approved point-in-time scope and delivery provenance. Current implementation, migrations, and current guides—not frozen planning prose—own the now-implemented capability.

Report drift instead of silently reconciling contradictory documents in working memory. Keep this page concise by linking to canonical detail rather than copying every feature inventory, rationale, or runbook instruction.
