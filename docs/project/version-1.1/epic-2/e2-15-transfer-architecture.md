# E2-15 Architecture Approval — One-Time PostgreSQL-to-SQLite Personal Data Transfer

Issue: [GitHub #61](https://github.com/MitCaine/Nutrition-App/issues/61)
Repository state reviewed: `main` at `02deb788ab12effb1582160a65ee8b463bc393ca`
Application head: `0025_immutable_validator_head`
Control head: `ops_0011_phase5c4_recovery_audit`

## A. Overall assessment

**APPROVED FOR CODEX IMPLEMENTATION**

The approved design is:

- One owner-explicit, read-only PostgreSQL export.
- One stable PostgreSQL snapshot obtained with `SERIALIZABLE READ ONLY DEFERRABLE`.
- One bounded canonical JSON transfer file.
- One pre-bootstrap import into a migrated-but-semantic-empty SQLite database.
- One exclusive SQLite transaction containing all inserts and all acceptance qualification.
- No PostgreSQL transfer schema, table, or data state; the bounded prerequisite
  validator repair migration `0025_immutable_validator_head` is required at the
  application head. No control-plane participation, synchronization metadata,
  merge, or retry journal.
- No SQLite migration for transfer and no immutability bypass.
- Generated Recipe Food projections and immutable history are copied with their existing identities.
- Canonical nutrients are reconstructed from the existing SQLite seed and verified by digest.

The design follows the existing deep-module boundaries: a narrow exporter, package contract, importer, and local-start import gate. It does not create a generic migration framework.

No architecture-stop condition is presently triggered.

### E2-15 prerequisite repair at application head 0025

The original 0020 immutable-provenance validator froze both the schema-0020
application head and schema-0020 runtime authority. Migration 0021 legitimately
added `public.phase5c_local_admission_v4()` to the exact runtime execution
surface. Migrations 0022 and 0023 changed profile columns without changing any
validator-owned protection or runtime-authority predicate. Migration 0024
replaced the Daily Log guard and rebuilt the historical validator around the
new guard hash, but retained the stale 0020 head and runtime execution set.

Migration `0025_immutable_validator_head` is therefore a current-state
validator repair discovered during E2-15 qualification. Its sole database
mutation is `CREATE OR REPLACE FUNCTION` for
`public.phase0020_immutable_provenance_integrity_valid()`. It changes no table,
trigger, guard, role, grant, application row, or transfer state. The repaired
validator accepts only the runtime authority already established by migrations
0021–0024, including retained v1/v2/v3 admission, snapshot replacement, and v4
activation authority. Historical exact-0020 and exact-0024 definitions remain
frozen and replayable.

Authoritative evidence included the live implementation plus [Current State](</Users/mipoo/Nutrition App/docs/project/current-state.md>), [Epic 2 backlog](</Users/mipoo/Nutrition App/docs/project/version-1.1/epic-2/implementation-backlog.md>), [E2-02 contract](</Users/mipoo/Nutrition App/docs/project/version-1.1/epic-2/e2-02-exact-value-contract.md>), [E2-03 schema](</Users/mipoo/Nutrition App/docs/project/version-1.1/epic-2/e2-03-sqlite-schema.md>), and the runtime/schema implementations.

## B. PostgreSQL table inclusion/exclusion matrix

Legend:

- **A** — Include in personal transfer.
- **B** — Exclude: operational/control-plane.
- **C** — Exclude: canonical or deterministically reconstructible.
- **D** — Exclude: obsolete, unsupported, or authority-specific.
- **E** — Requires architecture decision.

No table remains in E.

### Application semantic tables

| Table/model | Class | Owner/reachability | Mutability | Dependencies | SQLite counterpart | Transfer decision |
|---|---:|---|---|---|---|---|
| `users` / `User` | A | Exact `id = --owner-id`; exactly one | Mutable identity metadata | None | Direct | Copy selected row verbatim |
| `user_profiles` / `UserProfile` | A | `user_id = owner`; exactly one required | Mutable profile/calendar state | `users` | Direct | Copy verbatim |
| `nutrients` / `Nutrient` | C | Global canonical catalog | Canonical policy data | Self-parent relation | Direct seed | Do not package; require exact 16-row source and target digests |
| `food_items` / `FoodItem` | A | Every row with `user_id = owner`, including soft-deleted rows and Recipe projections | Mutable/soft-deleted; projections managed | `users`, optional publication revision | Direct | Copy all columns and IDs verbatim |
| `food_sources` / `FoodSource` | A | Parent Food must be owner-reachable | Mutable provenance child | `food_items` | Direct | Copy verbatim, including USDA raw payload/metadata as canonical JSON text |
| `food_nutrients` / `FoodNutrient` | A | Parent Food must be owner-reachable | Mutable current Food generation | Food, canonical nutrient | Direct | Copy exact current rows; never recalculate |
| `serving_definitions` / `ServingDefinition` | A | Parent Food must be owner-reachable | Mutable current Food generation | Food | Direct | Copy exact rows and identities |
| `food_favorites` / `FoodFavorite` | A | Both `user_id` and Food resolve to owner | Mutable | User, Food | Direct | Copy verbatim |
| `recipes` / `Recipe` | A | `user_id = owner`, including soft-deleted rows | Mutable authoring state | User, active revision, projection Food | Direct | Copy verbatim after bounded link staging during insertion |
| `recipe_ingredients` / `RecipeIngredient` | A | Recipe and referenced Food must both belong to owner | Mutable authoring graph | Recipe, Food, optional serving | Direct | Copy verbatim |
| `recipe_publication_revisions` / `RecipePublicationRevision` | A | `user_id = owner`; parent Recipe must belong to owner | Append-only/immutable | Recipe, User | Direct | Copy exact row and ID |
| `recipe_publication_amount_definitions` / `RecipePublicationAmountDefinition` | A | Reachable through included revision | Immutable | Revision | Direct | Copy exact row and ID |
| `recipe_publication_nutrients` / `RecipePublicationNutrient` | A | Reachable through included revision | Immutable | Revision, nutrient | Direct | Copy exact row and ID |
| `daily_logs` / `DailyLog` | A | `user_id = owner`; Food and publication references must remain in the owner graph | Immutable identity/nutrition with approved metadata/snapshot replacement | User, Food, serving, revision and amount | Direct | Copy exact current row |
| `daily_log_nutrient_snapshots` / `DailyLogNutrientSnapshot` | A | Reachable through owner Daily Log; referenced Food must be owner-owned | Immutable except established complete replacement semantics | Log, Food, optional nutrient/serving provenance, nutrient | Direct | Copy exact historical rows; do not recompute |
| `ocr_nutrition_confirmation_traces` / `OcrNutritionConfirmationTrace` | A | Direct owner plus owner Food | Append-only/immutable | User, Food | Direct | Copy established bounded trace verbatim after privacy validation |
| `nutrition_targets` / `NutritionTarget` | A | `user_id = owner` | Mutable | User, nutrient | Direct | Copy exact override rows |
| `create_operation_idempotency` / `CreateOperationIdempotency` | A/D by operation | Direct owner; `resource_id` may refer to a later-deleted resource | Reservation-to-terminal application state | User; operation-specific resource semantics | Direct | Apply the explicit policy in section K |

There is **no current `recipe_publication_ingredients` table**. Mutable ingredients are represented by `recipe_ingredients`; publication persistence consists of the immutable revision header, amount definitions, nutrients, and content digest. E2-15 must not invent a revision-ingredient table.

### Migration-owned tables in the application database

| Table | Class | Reason and semantics | Owner/dependencies | SQLite counterpart | Decision |
|---|---:|---|---|---|---|
| `nutrient_reference_values` | C | Retained global reference data; current target behavior is code-owned and seed-qualified | Global nutrient references | None | Exclude; verify canonical nutrient/target behavior instead |
| `ocr_scans` | D | Legacy raw OCR payload, full text, and image metadata violate current bounded provenance/privacy contract | Direct user | None | Exclude completely |
| `parse_results` | D | Legacy parser output tied to excluded OCR scans | OCR scan, optional Food | None | Exclude completely |
| `parser_corrections` | D | Legacy correction history tied to excluded raw scan/result graph | User, scan, parse result | None | Exclude completely |
| `phase5c_conversion_metadata` | B | Historical conversion/operator evidence | Operational archive identity | None | Exclude |
| `phase5c_conversion_runs` | B | Conversion execution state | Conversion metadata | None | Exclude |
| `phase5c_conversion_outcomes` | B | Conversion outcomes/evidence | Conversion run | None | Exclude |
| `phase5c_promotion_target_identity` | B | Promotion identity | Operational deployment state | None | Exclude |
| `phase5c_write_fence_state` | B | Mutable operational fence state | Deployment authority | None | Exclude |
| `phase5c_write_fence_events` | B | Fence event evidence | Fence state | None | Exclude |
| `phase5c_activation_schema_evidence` | B | Activation qualification evidence | Operational activation | None | Exclude |
| `phase5c_activation_runtime_commands` | B | Runtime activation command evidence | Operational activation | None | Exclude |
| `phase5c_conversion_clone_marker` | B | Optional Phase 5C conversion-clone isolation evidence, created and retained by the approved Issue 17 workflow | Operational clone identity; exactly one immutable row when present | None | Never package; admit only as the one exact optional public relation and qualify its structure, semantics, protections, and read-only authority |
| `alembic_version` | B | Application migration bookkeeping | Schema lifecycle | SQLite has independent ledger | Exclude |

Any registered Phase 5 archive schema and every relation within it are also B. The exporter operates only on fully qualified `public` relations and never traverses archive schemas.

### Independent control database

`phase5c4_alembic_version` and all 113 current `phase5c4_control` tables are B.

For every name below: the rows are keyed by operational environments, attempts, artifacts, evidence, authorizations, or audit identities rather than the personal owner graph; lifecycle semantics are a mixture of mutable workflow state and append-only/immutable evidence; dependencies remain entirely within the control database; there is no SQLite application counterpart; no row is transferred or queried.

```text
phase5c4_activation_authorization_evidence_bindings
phase5c4_activation_execution_conflicts
phase5c4_activation_executions
phase5c4_activation_runtime_observations
phase5c4_admission_decision_artifacts
phase5c4_admission_decisions
phase5c4_artifact_bindings
phase5c4_artifact_identity_conflicts
phase5c4_artifact_logical_identities
phase5c4_artifact_object_bindings
phase5c4_artifact_set_members
phase5c4_artifact_sets
phase5c4_artifacts
phase5c4_attempts
phase5c4_audit_deliveries
phase5c4_audit_delivery_attempts
phase5c4_audit_messages
phase5c4_audit_sink_receipts
phase5c4_authorization_admission_conflicts
phase5c4_authorization_consumptions
phase5c4_authorization_envelope_bindings
phase5c4_authorization_key_revocations
phase5c4_authorization_keys
phase5c4_authorization_revocations
phase5c4_authorizations
phase5c4_backup_evidence
phase5c4_bridge_metadata_evidence
phase5c4_candidate_seal_bindings
phase5c4_candidate_seals
phase5c4_clone_origins
phase5c4_constraint_manifests
phase5c4_contract_types
phase5c4_cutback_authorization_conflicts
phase5c4_cutback_authorization_consumptions
phase5c4_cutback_authorization_key_revocations
phase5c4_cutback_authorization_keys
phase5c4_cutback_authorization_revocations
phase5c4_cutback_authorizations
phase5c4_cutback_consumption_conflicts
phase5c4_cutback_route_conflicts
phase5c4_cutback_route_observation_vantages
phase5c4_cutback_route_observations
phase5c4_cutback_safety_conflicts
phase5c4_cutback_safety_observations
phase5c4_database_instance_observations
phase5c4_database_instances
phase5c4_database_physical_components
phase5c4_deployment_descriptors
phase5c4_emergency_close_executions
phase5c4_emergency_close_observations
phase5c4_environments
phase5c4_events
phase5c4_execution_authorization_conflicts
phase5c4_execution_authorization_key_revocations
phase5c4_execution_authorization_keys
phase5c4_execution_authorization_revocations
phase5c4_execution_authorizations
phase5c4_external_action_conflicts
phase5c4_external_action_intents
phase5c4_external_action_observations
phase5c4_external_action_status
phase5c4_final_activation_evidence
phase5c4_final_cutback_evidence
phase5c4_function_manifests
phase5c4_immutable_provenance_admissions
phase5c4_performance_admission_epochs
phase5c4_performance_component_rows
phase5c4_performance_contract_revocations
phase5c4_performance_contracts
phase5c4_performance_scan_rows
phase5c4_performance_structural_rules
phase5c4_post_cutover_verification_checks
phase5c4_post_cutover_verification_receipts
phase5c4_principals
phase5c4_promotion_authorization_consumptions
phase5c4_promotion_authorization_key_revocations
phase5c4_promotion_authorization_keys
phase5c4_promotion_authorization_revocations
phase5c4_promotion_authorizations
phase5c4_qualification_observations
phase5c4_qualification_v2_catalog_manifest
phase5c4_qualification_v3_catalog_manifest
phase5c4_qualification_v4_catalog_manifest
phase5c4_qualification_v5_catalog_manifest
phase5c4_qualification_v6_catalog_manifest
phase5c4_qualification_v7_catalog_manifest
phase5c4_qualification_v8_catalog_manifest
phase5c4_qualification_v9_catalog_manifest
phase5c4_qualification_v9_domain_manifest
phase5c4_quarantine_acceptances
phase5c4_quarantine_reason_counts
phase5c4_quarantine_subjects
phase5c4_reconciliation_roots
phase5c4_recovery_validations
phase5c4_request_conflicts
phase5c4_resource_membership_admissions
phase5c4_restore_checks
phase5c4_restore_receipts
phase5c4_route_observation_conflicts
phase5c4_route_observation_vantages
phase5c4_route_observations
phase5c4_run_admissions
phase5c4_schema_migration_executions
phase5c4_schema_migration_observations
phase5c4_source_dimension_observations
phase5c4_source_reconciliations
phase5c4_source_restore_conflicts
phase5c4_source_restore_intents
phase5c4_source_restore_observations
phase5c4_transition_requests
phase5c4_verification_checks
phase5c4_verification_runs
phase5c4_zero_block_receipts
```

PostgreSQL roles, grants, role settings, routines, views, policies, canary state, qualifier manifests, and bootstrap state are also B even though they are not application tables.

## C. Source-owner selection contract

The exporter requires one mandatory `--owner-id` argument:

- Lowercase, canonical, hyphenated UUID.
- Email, display name, token identity, or “first user” selection is forbidden.
- `public.users` must contain exactly one matching row.
- Exactly one matching `user_profiles` row is required; E2-15 must not synthesize missing source profile state.

The exported graph is:

1. Direct owner rows: user, profile, Foods, Recipes, publication revisions, Daily Logs, Favorites, OCR traces, Targets, and eligible idempotency rows.
2. Child rows selected only through included parents: Food sources/nutrients/servings, Recipe ingredients, publication amounts/nutrients, and Daily Log snapshots.
3. Soft-deleted owner rows remain included because Recipes, Logs, provenance, and receipts may retain their identities.
4. Every referenced Food, Recipe, revision, amount, serving, nutrient, or owner must exist in the approved graph.

Exporter anti-join checks must prove:

- No included child belongs to an excluded or other-owner parent.
- No owner-direct row is omitted.
- Recipe ingredients reference only owner Foods and servings belonging to that Food.
- Daily Logs reference owner Foods and paired owner publication records.
- Favorites and OCR traces reference owner Foods.
- Manual duplicate `source_id` UUIDs resolve to same-owner Foods.
- Recipe projection `source_id`, revision link, and Recipe backlink are coherent.

Unexpected cross-owner or missing references reject the whole export. They are never silently dropped.

The global nutrient catalog is not packaged. The exporter requires the exact 16-row canonical source catalog and records its canonical digest. The importer requires the exact target seed digest before mutation.

## D. Source schema/version qualification

The production exporter accepts only:

- PostgreSQL major version 16.
- `public.alembic_version` containing exactly `0025_immutable_validator_head`.
- Codec version `e2-02.v1`.
- Source contract identifier `e2-15.pg-0025.v1`.
- The exact required 31 ordinary `public` tables: 18 semantic, 12 migration-owned, and `alembic_version`.
- Either no additional ordinary `public` relation, or exactly one additional relation named `public.phase5c_conversion_clone_marker`. No other optional or unexpected relation is admitted.
- When the optional marker is present, its exact established 15-column structure, one-row authoritative Phase 5C clone-marker contract, immutable row/truncate guards, qualifier `SELECT` authority, and qualifier mutation denial are required. It remains operational evidence and is never packaged or imported into SQLite.
- No missing, renamed, or structurally altered required relation, and no structural drift of the optional marker when present.
- The expected columns, PostgreSQL types, nullability, defaults, PKs, FKs, unique/check constraints, required indexes, and relevant immutable-provenance triggers/routines.
- A true result from the current immutable-provenance integrity validator repaired by migration 0025.

Implementation must freeze a narrow source-schema descriptor under the E2-15 shared contract and compare `pg_catalog` output against it. The digest binds both the exact required 31-relation descriptor and the single optional marker descriptor/presence policy. This is a fixed compatibility gate, not a generic migration framework.

Extension-owned catalog objects may exist but may not shadow expected application objects. Non-public Phase 5 archive schemas are ignored and never traversed.

Older, newer, partial, multiple-head, structurally drifted, or protection-tampered sources fail before row export.

## E. Exact freeze/quiescence procedure

### Correctness preconditions

1. Resolve or explicitly abandon every pending remote mobile mutation/recovery prompt.
2. Close remote clients.
3. Stop every FastAPI/backend instance and any writer/operator process connected to the application database.
4. Drain pooled sessions.
5. Using an existing privileged operator connection, verify no sessions remain for write-capable application roles such as `nutrition_runtime`, `nutrition_migrator`, `nutrition_owner`, or `nutrition_ops`, excluding the checking session itself.
6. Do not close a write fence or mutate control/application state merely for E2-15.

### Export transaction

The exporter connects as the existing `nutrition_qualifier` role and verifies:

- `current_user = 'nutrition_qualifier'`.
- `default_transaction_read_only=on`.
- SELECT authority on required relations.
- No DML/DDL authority.

The validator itself remains owner-only. The privileged Issue 17 source
preflight requires its direct result to be exactly `TRUE`. Inside the qualifier
transaction, the exporter independently verifies the exact validator
definition/manifest and every catalog-visible current input to that validator,
including relation privileges, runtime EXECUTE routines, v4 ACL, protected
ownership, and runtime role restrictions. It does not grant the qualifier
direct validator execution or bypass any validator predicate.

It then opens one connection and executes the equivalent of:

```sql
BEGIN ISOLATION LEVEL SERIALIZABLE READ ONLY DEFERRABLE;
```

All schema qualification, owner selection, graph reads, counts, source aggregate calculations, and export timestamp acquisition occur in that transaction. The transaction is explicitly rolled back after the complete package has been constructed and validated in memory.

A stable PostgreSQL snapshot prevents internally inconsistent export even if another transaction existed. The service stop is nevertheless required for cutover completeness: without it, a later commit could be absent from the package.

### Evidence

Retain separately:

- Backend/service stop evidence.
- Zero write-capable session query.
- Exporter-reported role, isolation, read-only, and deferrable settings.
- Source head and source-contract digest.
- Export transaction timestamp.
- Section counts and package digest.

The package need not contain hostnames, roles, LSNs, database names, or session details.

Remote operation may resume only if import is abandoned or fails while SQLite remains empty. After a successful local cutover, remote writes must remain stopped; otherwise the two authorities immediately diverge.

## F. Transfer-package and canonical-codec contract

### Chosen form

One UTF-8 canonical JSON document:

- Extension: `.nutrition-transfer.json`.
- Maximum file size: **64 MiB**.
- No BOM or trailing newline.
- No ZIP, archive traversal, cursors, tombstones, journal entries, or continuation sequences.
- If the real package exceeds 64 MiB, stop. Do not add chunking under #61.

### Top-level shape

```text
format: "nutrition-personal-transfer"
format_version: "1"
codec_version: "e2-02.v1"
source:
  postgres_major: "16"
  alembic_revision: "0025_immutable_validator_head"
  schema_contract: "e2-15.pg-0025.v1"
  schema_contract_digest: <sha256>
target:
  sqlite_schema_version: 1
  migration_ids: ["001_initial_runtime_schema"]
exported_at: <canonical instant>
owner_id: <canonical UUID>
nutrient_catalog_digest: <sha256>
idempotency_policy:
  version: "e2-15.idempotency.v1"
  copied_portable_count: <safe integer>
  translated_log_update_count: <safe integer>
  reconstructed_log_create_count: <safe integer>
  excluded_log_delete_count: <safe integer>
sections: [...]
qualification:
  daily_totals: {name, count, digest, records}
overall_digest: <sha256>
```

Unknown top-level keys, section names, record keys, or duplicate keys are rejected.

### Fixed section order

1. `users`
2. `user_profiles`
3. `food_items`
4. `food_sources`
5. `food_nutrients`
6. `serving_definitions`
7. `food_favorites`
8. `recipes`
9. `recipe_ingredients`
10. `recipe_publication_revisions`
11. `recipe_publication_amount_definitions`
12. `recipe_publication_nutrients`
13. `daily_logs`
14. `daily_log_nutrient_snapshots`
15. `ocr_nutrition_confirmation_traces`
16. `nutrition_targets`
17. `create_operation_idempotency`

Records use exact target column names and contain every column for that table. Arrays are sorted by canonical primary-key tuple in Python after retrieval, independent of PostgreSQL collation. UUID/string key ordering uses Unicode code-point order.

### Section digests

For section `S`, digest input is:

```text
UTF8(E2_02_CANONICAL_JSON({
  "count": S.records.length,
  "name": S.name,
  "records": S.records
}))
```

The section object adds lowercase hexadecimal `digest` afterward.

`qualification.daily_totals` uses the same preimage rule.

The overall digest is:

```text
SHA256(UTF8(E2_02_CANONICAL_JSON(document with only overall_digest omitted)))
```

The final file is the E2-02 canonical serialization of the document with `overall_digest` present. The importer must:

1. Parse the JSON.
2. Re-serialize it canonically and require byte-for-byte equality with the file.
3. Recompute every section digest.
4. Recompute the overall digest.

### Value representation

| Value | Package representation |
|---|---|
| UUID | Lowercase canonical 36-character string |
| Instant | UTC `Z`; no fraction for zero microseconds, otherwise exactly six digits |
| Date | `YYYY-MM-DD` |
| IANA time zone | Trimmed validated key, preserving aliases |
| Boolean | JSON `true`/`false`; importer binds SQLite `0`/`1` |
| `NUMERIC(14,6)` | Fixed six-place string |
| `NUMERIC(8,3)` | Fixed three-place string |
| `NUMERIC(5,4)` | Fixed four-place string |
| Derived aggregate decimal | E2-02 response-decimal string; never JavaScript `Number` |
| JSON database column | String containing an E2-02 canonical JSON document; SQL NULL remains outer JSON `null` |
| Nullable scalar | JSON `null` |
| Integer | Safe JSON integer, validated against its column bounds |
| Enum/status | Exact approved case-sensitive string; no normalization |

Python and TypeScript must consume shared E2-15 parity fixtures covering Unicode, JSON-number spellings, escaping, nullable JSON versus JSON `null`, decimals, timestamps, record sorting, and digest preimages. If an existing JSON value cannot round-trip through both E2-02 canonicalizers without semantic loss, export stops.

## G. Privacy and data-minimization approval

The file contains sensitive personal information:

- Email/display identity.
- Birth date, height, weight, biological-sex reference field, activity level, energy context, and time zone.
- Foods, brands, notes, servings, nutrients, USDA provenance/raw response data, Favorites.
- Recipes, notes, ingredient graph, publication history, and projection data.
- Daily Log dates, meals, notes, amounts, immutable nutrition, and derived qualification totals.
- Nutrition target overrides.
- Bounded OCR suggestions/corrections and request identifiers.
- Portable application mutation receipts.

It excludes:

- `ocr_scans.image_metadata`.
- OCR source images.
- Image paths or URIs.
- Complete raw OCR text and raw OCR engine payloads.
- `parse_results` and `parser_corrections`.
- Tokens, bearer credentials, USDA credentials, database URLs/passwords, environment variables, or request headers.
- Control-plane, Phase 5, role, promotion, canary, qualifier, audit, backup, or WORM evidence.
- Host/database/session/LSN metadata.

Included OCR confirmation traces must pass the existing bounded-trace contract. A legacy or malformed trace containing forbidden image/path/full-text material rejects export rather than being stripped.

The exporter:

- Requires an explicit output path in an existing, personally controlled, non-cloud-synced directory.
- Creates an exclusive temporary sibling with mode `0600`.
- Publishes atomically without overwriting an existing destination.
- Removes its temporary file on failure.
- Emits only format/version, byte count, section counts, and digest—never row contents, email, notes, JSON snippets, credentials, or full paths.

The file is plaintext. The operator must use an encrypted local volume and a local Finder/AirDrop/“On My iPhone” handoff, not email, cloud storage, or upload.

The mobile importer may copy the selected file into app cache. It deletes only that cache copy, best effort, after success or failure. It must never delete the operator’s original file automatically; manual deletion after successful import is documented.

Tests use synthetic data and must not snapshot or log full packages.

## H. SQLite empty-target definition

The target must already be migrated to:

- `PRAGMA user_version = 1`.
- Ledger row `(1, "001_initial_runtime_schema")`.
- Exact expected schema/index/trigger contract.
- Exact 16 canonical nutrient seed rows.
- `PRAGMA foreign_keys = 1`.

Permitted preexisting state:

- `nutrition_schema_migrations`.
- The 16 `nutrients` rows.
- An empty `nutrition_daily_log_snapshot_replacement_scopes` table.
- SQLite internal objects.

Required absent state:

- Zero rows in every semantic table except `nutrients`, including `users` and `user_profiles`.
- Zero snapshot replacement-scope rows.

A placeholder `local-owner@local.invalid` row means the target is no longer empty and import must fail. E2-15 does not delete or rewrite it.

The importer must therefore run after `openNutritionDatabase()` applies migrations and seeds but before `bootstrapLocalRuntimeFoundation()` invokes `ensureLocalOwner()`.

The PostgreSQL user UUID becomes the local `users.id` unchanged. Existing E2-04 behavior will reuse that single owner and derive authority identity `local:<owner_uuid>` without rewriting foreign keys.

Existing rows, extra nutrient rows, altered seeds, schema drift, multiple owners, or any scope row cause rejection. There is no merge, overwrite, reset, or “import anyway” path.

## I. Import dependency order and transaction design

All file-size, syntax, canonicalization, version, digest, count, shape, ownership, privacy, and graph validation occurs before acquiring the write transaction.

The validated package is then deeply immutable in memory. Import uses one existing `withExclusiveSQLiteTransaction` call with foreign keys and immutable triggers left enabled.

Insertion order:

1. Recheck schema, nutrient digest, and emptiness inside the transaction.
2. Insert the selected `users` row.
3. Insert `user_profiles`.
4. Insert non-projection `food_items`.
5. Insert their `food_sources`, `food_nutrients`, and `serving_definitions`.
6. Insert all `recipes` with both publication-link columns temporarily `NULL`; every other value is exact.
7. Insert all immutable `recipe_publication_revisions`.
8. Insert projection `food_items`, now that their revision rows exist.
9. Insert projection Food sources, nutrients, and servings.
10. Insert immutable publication amount definitions and publication nutrients.
11. Update each staged Recipe once to its exact packaged `published_food_item_id` and `active_publication_revision_id`.
12. Insert `recipe_ingredients`, including nested-Recipe projection references.
13. Insert `daily_logs`.
14. Insert immutable Daily Log snapshots.
15. Insert Favorites.
16. Insert OCR confirmation traces.
17. Insert nutrition targets.
18. Insert copied/translated/reconstructed application idempotency receipts.
19. Run every qualification check in section L.
20. Return from the transaction callback only if every check passes.

The temporary Recipe link staging is necessary because `recipes.published_food_item_id` has an immediate Food FK while the projection Food has an immediate revision dependency. Both the all-null staged state and final paired state satisfy existing checks.

No foreign-key pragma is disabled. No `defer_foreign_keys` override is added. No trigger is dropped or bypassed. Immutable tables allow INSERT, so no import scope is required. The Daily Log replacement-scope table remains empty.

## J. Verbatim-versus-reconstructed decisions

| Entity/artifact | Decision |
|---|---|
| User/profile | Copy every persisted value and UUID |
| Nutrient catalog | Exclude package; reconstruct from exact existing seed and verify digest |
| Manual/USDA/legacy Foods | Copy all current and soft-deleted rows and children |
| Food JSON provenance | Canonicalize semantically to E2-02 JSON text and copy |
| Recipe drafts and ingredients | Copy exact current authoring graph |
| Publication revision rows | Copy exact immutable rows and content digests |
| Publication amount/nutrient rows | Copy exact immutable rows |
| Generated Recipe Food projection | Copy exact Food ID, revision link, child IDs, nutrients, servings, timestamps, and deletion state |
| Recipe projection nutrition | Never recompute; verify copied projection semantically matches the active revision |
| Daily Log headers | Copy exact current values |
| Daily Log snapshots | Copy exact immutable rows and nullable historical provenance links |
| Daily totals | Do not persist separately; recompute independently and compare with package qualification records |
| OCR confirmation traces | Copy only the established bounded trace |
| Target overrides/profile | Copy exact rows; effective defaults remain code-derived |
| Idempotency rows | Apply section K’s explicit operation policy |
| Migration/Phase 5/control data | Exclude |

Historical IDs are never regenerated except the explicitly reconstructed `log.create` receipt ID. Nutrition amounts, publication nutrients, and Daily Log snapshots are never recalculated for storage.

## K. Idempotency/recovery inclusion decisions

The package section contains target-ready receipt rows, not a blind dump of every source receipt.

### Copy verbatim after contract validation

- `food.create_manual`
- `food.duplicate`
- `food.add_serving`
- `recipe.create`
- `recipe.publish`

The response snapshot is converted from PostgreSQL JSON to E2-02 canonical JSON text without changing its semantic document.

### Translate deterministically

`log.update` receipts are portable but the local receipt envelope differs. Convert the remote snapshot:

```text
remote:
  DailyLog response fields
  _source_logged_date
  _destination_logged_date

local:
  kind: "log.update"
  source_logged_date
  destination_logged_date
  result: <DailyLog response without the two private keys>
```

Copy the receipt ID, owner, request identity, fingerprint, resource ID, creation time, and completion time.

### Reconstruct deterministically

PostgreSQL stores `log.create` idempotency on the Daily Log row rather than in `create_operation_idempotency`. For every transferred Daily Log with a non-null request ID/fingerprint, create one local `log.create` receipt:

- `user_id`, request ID, fingerprint, and `resource_id` come from the Daily Log.
- Response snapshot is the canonical local Daily Log response reconstructed from the imported header and snapshots.
- `created_at` and `completed_at` use the Daily Log’s canonical `created_at`.
- Receipt UUID is UUIDv5 using standard DNS namespace `6ba7b810-9dad-11d1-80b4-00c04fd430c8` and name:

```text
nutrition-app:e2-15:log.create:<owner_uuid>:<client_request_uuid>
```

Any collision rejects import.

### Exclude

Completed `log.delete` receipts are not transferred. The deleted row and its source date no longer exist, so the local receipt envelope cannot be reconstructed exactly. Remote recovery storage remains isolated and will not be consulted in local mode. The excluded count is recorded in package metadata.

### Reject

- Incomplete receipt pairs.
- Unsupported/unknown operation names.
- Unexpected source `log.create` receipt rows.
- Malformed response snapshots.
- Ownership/fingerprint/resource inconsistencies.

The importer never copies AsyncStorage recovery entries. Remote entries remain under the original remote scope; local recovery begins under `local:<owner_uuid>`. No automatic cross-authority retry occurs.

## L. Post-import qualification matrix

Every mandatory check occurs inside the exclusive transaction before commit.

| Area | Mandatory check |
|---|---|
| Package | Recompute canonical file, section, qualification, and overall digests |
| Counts | Target-ready row count equals each section count |
| Exact rows | Reconstruct every target section from SQLite and reproduce the package section digest |
| Owner | Exactly one user/profile; all directly scoped rows use the package owner |
| Isolation | No row reachable from another owner; no unexpected owner |
| Schema | Version, ledger, schema objects, indexes, triggers, and seed contract unchanged |
| Foreign keys | `PRAGMA foreign_key_check` returns zero rows |
| Nutrients | Exact 16-row digest and parent/order/unit fields |
| Foods | PK uniqueness, child membership, default-serving uniqueness, active source uniqueness, duplicate provenance |
| Recipes | Ingredient owner/Food/serving integrity; positions and graph constraints |
| Publications | Revision numbers, row sets, amount/nutrient uniqueness, immutable content digest |
| Projections | One coherent projection per published Recipe; exact Recipe/revision/Food links; projection values match active revision |
| Daily Logs | Owner Food, serving, revision, and amount links are coherent and paired |
| Snapshots | Exact per-log counts and section digest; valid nutrient/status/amount combinations |
| Daily totals | Recompute from imported snapshots with existing exact local arithmetic and match every source qualification record |
| OCR | Owner/Food link, unique request/Food constraints, canonical bounded trace, forbidden-data absence |
| Targets | Exact profile and override rows; nutrient/unit/basis/source contract |
| Idempotency | Exact copied operations; translated `log.update`; one deterministic `log.create` receipt where required; zero imported `log.delete` receipts |
| Exclusions | Only the approved SQLite semantic/ledger/scope objects exist; scope table is empty; no Phase 5/control/legacy OCR tables or package sections |

No success-affecting qualification is deferred until after commit. Any check may be repeated read-only afterward for evidence, but the success decision is already complete inside the atomic transaction.

## M. Failure and reimport semantics

| Failure | Result |
|---|---|
| File over 64 MiB, truncated, malformed, duplicate-key, noncanonical, or BOM/newline drift | Reject before transaction |
| Unsupported format/codec/schema/target version | Reject before transaction |
| Overall/section/qualification digest mismatch | Reject before transaction |
| Count mismatch or duplicate table primary-key tuple | Reject before transaction |
| Invalid scalar, decimal, timestamp, date, JSON, enum, or privacy field | Reject before transaction |
| Owner/profile/graph inconsistency | Reject before transaction |
| Existing target application row or seed/schema drift | Reject before mutation or at transactional recheck |
| FK, uniqueness, check, or immutable-trigger failure | Throw and roll back |
| Injected importer-stage or qualification failure | Throw and roll back |
| Process interruption before commit | SQLite rollback; reopening shows migrations/seeds only |
| Process interruption after commit but before UI response | Reopening shows the complete, already-qualified graph; never a partial graph |
| Reimport into the populated target | Reject as `target_not_empty` |
| Retry after a pre-commit failure | Permitted only because the target still satisfies the exact empty contract |

There is no resume position, merge behavior, package application history, cursor, or incremental mode.

## N. PostgreSQL read-only proof strategy

Production guarantees:

- Existing `nutrition_qualifier` login.
- `default_transaction_read_only=on`.
- SELECT-only grants.
- Explicit `SERIALIZABLE READ ONLY DEFERRABLE`.
- Fully qualified SELECT/catalog statements only.
- Explicit transaction rollback.
- No ORM service calls that can flush.
- No Alembic, `create_all`, DML, DDL, `CALL`, mutation routine, temporary application table, sequence use, advisory mutation, or control database connection.

Focused PostgreSQL tests must:

1. Provision the representative schema and two-owner fixture.
2. Capture canonical row counts/digests for every expected `public` table.
3. Run export as the qualifier role.
4. Recompute and require identical full-table counts/digests.
5. Assert the qualifier cannot execute INSERT, UPDATE, DELETE, TRUNCATE, or DDL.
6. Record executed SQL and require only transaction control, `SET LOCAL`/`SHOW`, catalog reads, and SELECT.
7. Verify the control database is never connected.
8. Verify no package output is published when source qualification fails.

## O. Recommended operator flow

1. Confirm the source is at the exact supported head and the qualifier role already exists.
2. Resolve pending remote recovery state.
3. Close remote clients; stop backend and writer processes.
4. Run the privileged current-source preflight and require
   `phase0020_immutable_provenance_integrity_valid() = TRUE`.
5. Verify zero write-capable application sessions.
6. Run the exporter solely as `nutrition_qualifier`, with canonical owner UUID,
   explicit output path, and explicit frozen-writes acknowledgment. The
   exporter must not execute the owner-only validator.
7. Inspect the redacted count/byte/digest summary.
8. Move the file locally to the simulator or device using Finder/AirDrop/“On My iPhone”.
9. Start the app explicitly in local mode on a new database.
10. At the pre-bootstrap gate, select the transfer file.
11. Validate, import, and qualify atomically.
12. Display success only after transaction commit, including counts and overall digest.
13. Bootstrap the normal local runtime; it reuses the imported owner UUID.
14. Keep remote writes stopped.
15. Manually delete the exporter file and external device copy after independent confirmation; the app deletes only its cache copy.

The local first-start screen may also offer “Start with an empty local profile.” That explicit choice creates the normal placeholder owner and permanently makes this database ineligible for import.

## P. Bounded changes required

E2-15 required one prerequisite PostgreSQL repair migration:
`0025_immutable_validator_head`. That migration repairs only the existing
immutable-provenance validator. The transfer feature itself adds no
PostgreSQL transfer schema, table, or data state.
No SQLite migration.
No transfer table.
No FK or trigger weakening.
No import scope.

Required bounded implementation surfaces:

- Shared E2-15 package/schema/parity fixtures.
- Pure backend source qualifier/exporter module.
- Thin `argparse` exporter script under `apps/backend/scripts`.
- Mobile package parser, validator, importer, and qualification module.
- A local-only pre-bootstrap coordinator that opens/migrates SQLite before owner bootstrap.
- A minimal accessible first-start import/file-selection screen.
- `expo-document-picker`, installed at the Expo-compatible version and lazily loaded only in local mode.
- Focused documentation/runbook updates.

Remote startup must continue to avoid opening SQLite or loading the file-picker/import modules.

## Q. Testing strategy

Required focused tests:

- Shared Python/TypeScript canonical package and digest fixtures.
- Every E2-02 scalar/decimal/JSON boundary used by the package.
- PostgreSQL exact schema/head/role qualification.
- Two-owner inclusion and anti-join rejection.
- Missing profile, extra nutrient, malformed OCR trace, and cross-owner rejection.
- Representative graph export containing soft deletion, USDA raw JSON, duplicates, nested Recipes, multiple publications, projection refresh, Daily Log edits/moves, unknown nutrients, OCR trace, Targets, and receipts.
- Portable, translated, reconstructed, excluded, incomplete, and unknown idempotency cases.
- Tampered metadata, records, counts, section digests, qualification totals, and overall digest.
- 64 MiB and nested/string bounds.
- Exact empty-target checks and reimport rejection.
- Failure injection after every insertion section and every qualification group.
- Reopen after each injected failure and prove all semantic tables except nutrient seeds are empty.
- Exact imported row/count/digest comparisons.
- `PRAGMA foreign_key_check`.
- Recipe content/projection qualification.
- Daily Log per-log snapshot counts and exact aggregate parity.
- Privacy scan proving excluded tables/fields do not enter the package.
- PostgreSQL before/after unchanged proof.
- Local/remote recovery authority isolation.
- Remote bootstrap spy proving no SQLite/import/file-picker access.
- Minimal UI accessibility, progress, failure, retry, and success presentation.
- One focused end-to-end PostgreSQL fixture → transfer file → SQLite import test.

Full owner data and physical-device qualification remain owner-coordinated and part of E2-16. If PostgreSQL/native prerequisites are unavailable, report the exact skip; do not present skipped checks as passing.

## R. Risks and unresolved decisions

There are no unresolved architecture decisions.

Controlled risks:

- **Package size:** 64 MiB must be confirmed against the real owner dataset. Exceeding it is an architecture stop, not permission to add streaming/chunking.
- **Cross-language JSON:** shared fixtures must prove Python/TypeScript canonical parity, including JSON-number spelling.
- **Plaintext sensitivity:** operator handling and manual deletion are mandatory.
- **Qualifier availability:** E2-15 must not create or repair production roles. A missing qualifier is an operational blocker.
- **Source inconsistencies:** missing profile, incomplete receipts, cross-owner references, or malformed provenance block export.
- **Remote `log.delete` receipts:** deliberately excluded because exact local reconstruction is impossible and remote recovery scope is not migrated.
- **Mobile memory/device behavior:** the bounded document must receive owner-coordinated physical-device validation in E2-16.

Architecture stops remain mandatory if implementation discovers a need for PostgreSQL writes, control-plane authority, merge/reconciliation, immutable-history rewriting, lossy value conversion, excluded OCR retention, protection weakening, or silent source repair.

Review closeout:

- Repository remained clean; no files changed, committed, or pushed.
- `session-end.sh`: exit 0.
- Focused audit tooling: 39 passed.
- `git diff --check`: passed.
- Warning: audit boundary scanner reported the established `daily_logs` token in `ops_0004_phase5c4_admission.py`.
- Warning: pytest could not write its cache under the restricted environment.
- Session-start toolchain warnings: Python 3.9.6 versus expected 3.12; Node 26.7.0 versus expected 24.
- PostgreSQL concurrency/control, MinIO, Docker/restart, and Phase 5 performance suites were intentionally not run because this was a read-only architecture review.

## S. Bounded implementation sequence

1. Freeze `e2-15.v1` shared contract, source-schema descriptor, JSON/section/digest fixtures, and privacy allowlists.
2. Implement pure backend qualification, owner graph selection, transformations, package construction, and read-only CLI.
3. Prove PostgreSQL immutability and package parity with focused tests.
4. Implement the mobile parser and all pre-transaction validation.
5. Implement the single-transaction importer, staging order, idempotency transformation, and in-transaction qualification.
6. Add the local-only pre-bootstrap gate and minimal file-selection UI.
7. Run the representative end-to-end fixture and complete focused failure/privacy/authority tests.
8. Update E2-15 documentation and report exact tests, skips, warnings, changed files, and intentional non-changes.
9. Stop before owner data/device qualification; that remains E2-16.

## T. Final Codex implementation prompt

```text
Model: gpt-5.6-sol
Reasoning effort: max

Work in:
/Users/mipoo/Nutrition App

Implement GitHub #61:
E2-15 — Deliver one-time PostgreSQL-to-SQLite personal data transfer

Run ./scripts/session-start.sh first. Read AGENTS.md, GitHub #61, the Epic 2
backlog, E2-02 through E2-14 contracts, and treat as binding:
docs/project/version-1.1/epic-2/e2-15-transfer-architecture.md

Treat the approval as binding. Do not make new architecture decisions during
implementation. If a stated stop condition is encountered, stop and report it.

Core boundary:
- one read-only, owner-explicit, point-in-time PostgreSQL export;
- one canonical JSON package;
- one atomic import into a migrated-but-semantic-empty SQLite database;
- no synchronization, merge, incremental mode, backup system, replication,
  control-plane authority, PostgreSQL mutation, or immutable-protection bypass.

Implement these exact decisions:

1. Package contract
- format "nutrition-personal-transfer", format_version "1";
- codec "e2-02.v1";
- source contract "e2-15.pg-0025.v1";
- target SQLite version 1 / migration "001_initial_runtime_schema";
- one canonical UTF-8 .nutrition-transfer.json file, no BOM/newline;
- hard maximum 64 MiB;
- fixed section order:
  users, user_profiles, food_items, food_sources, food_nutrients,
  serving_definitions, food_favorites, recipes, recipe_ingredients,
  recipe_publication_revisions,
  recipe_publication_amount_definitions,
  recipe_publication_nutrients, daily_logs,
  daily_log_nutrient_snapshots,
  ocr_nutrition_confirmation_traces, nutrition_targets,
  create_operation_idempotency;
- canonical primary-key ordering;
- section digest preimage is canonical JSON of {count,name,records};
- overall digest is canonical JSON of the complete document with only
  overall_digest omitted;
- exact E2-02 UUID, instant, date, timezone, boolean, decimal, response-decimal,
  JSON-document, null, enum, and safe-integer representations;
- JSON database columns are package strings containing canonical E2-02 JSON;
- add shared Python/TypeScript parity fixtures, including Unicode, escaping,
  JSON-number spellings, null distinctions, sorting, and digest preimages.

2. PostgreSQL exporter
- add a pure exporter/qualification module and thin argparse script under
  apps/backend/scripts;
- require canonical --owner-id and explicit non-existing output path;
- require PostgreSQL 16, exact Alembic head
  0025_immutable_validator_head, exact fixed schema descriptor, and valid
  immutable-provenance protection;
- connect as current_user nutrition_qualifier with read-only settings and
  SELECT-only authority;
- use one SERIALIZABLE READ ONLY DEFERRABLE transaction for schema checks,
  owner graph reads, counts, aggregates, and exported_at;
- explicitly roll back; never call mutation services, Alembic, create_all,
  DML, DDL, sequences, control-plane code, or the control database;
- require exactly one owner User and one UserProfile;
- include all same-owner application rows, including soft-deleted rows;
- select child rows only through included parents;
- reject missing/cross-owner/incoherent references;
- validate the exact 16-row source nutrient catalog and package only its digest;
- exclude every Phase 5/control/migration ledger table, nutrient reference
  table, legacy ocr_scans, parse_results, and parser_corrections;
- validate bounded OCR traces and reject forbidden image/path/full-text data;
- write a 0600 sibling temporary file and publish atomically without overwrite;
- emit only redacted counts, byte size, versions, and digest.

3. Idempotency policy
- copy completed canonical receipts for:
  food.create_manual, food.duplicate, food.add_serving,
  recipe.create, recipe.publish;
- translate log.update response snapshots into the local
  {kind,source_logged_date,destination_logged_date,result} envelope;
- synthesize one log.create receipt for each imported Daily Log with request
  identity, using UUIDv5 DNS namespace
  6ba7b810-9dad-11d1-80b4-00c04fd430c8 and name
  nutrition-app:e2-15:log.create:<owner_uuid>:<client_request_uuid>;
- use the Daily Log created_at for reconstructed receipt creation/completion;
- exclude completed log.delete receipts and report only their count;
- reject incomplete, unknown, malformed, or unexpected source log.create
  receipt rows;
- never migrate AsyncStorage recovery state or remote authority scopes.

4. SQLite target/importer
- add no schema migration, table, trigger, or protection bypass;
- run after openNutritionDatabase migrations/seeds but before
  ensureLocalOwner/bootstrapLocalRuntimeFoundation;
- define empty as exact version/ledger/schema, exact 16 nutrient seeds, zero
  rows in every other semantic table, and zero replacement-scope rows;
- reject existing placeholder owner or any application data;
- preserve the PostgreSQL owner UUID so local authority becomes
  local:<owner_uuid>;
- validate file size, syntax, canonical bytes, versions, keys, shapes, privacy,
  counts, digests, owner graph, and duplicate primary-key tuples before the
  write transaction;
- use exactly one existing withExclusiveSQLiteTransaction call;
- keep foreign keys and immutable triggers enabled;
- insert in the approved order:
  owner/profile;
  non-projection Foods and children;
  Recipes staged with both publication links NULL;
  revisions;
  projection Foods and children;
  publication amounts/nutrients;
  final Recipe publication links;
  ingredients;
  Daily Logs;
  snapshots;
  Favorites;
  OCR traces;
  Targets;
  target-ready receipts;
- do not use the Daily Log replacement-scope helper during import.

5. Mandatory in-transaction qualification
- recheck target emptiness and nutrient digest;
- recompute package/section digests;
- reproduce each target section count and digest from SQLite;
- prove one-owner isolation;
- PRAGMA foreign_key_check must return zero rows;
- verify Food source/default-serving uniqueness and duplicate provenance;
- verify Recipe graph, revision content digests, active links, and generated
  projection parity without recomputing stored nutrition;
- verify Daily Log references, per-log snapshot counts, exact snapshot rows,
  and source-versus-target daily aggregate totals with existing exact arithmetic;
- verify OCR links/privacy, profile/Targets, and the idempotency policy;
- prove the replacement-scope table is empty and no excluded operational data
  exists;
- any failure must throw before commit.

6. Local operator UI
- add the narrowest local-only first-start import gate;
- use an Expo-compatible expo-document-picker dependency, lazy-loaded only
  after local authority is selected;
- offer Import transfer file and explicit Start with empty local profile;
- show accessible validating/importing/qualifying/success/failure states;
- delete only the importer-controlled cache copy, best effort;
- document manual deletion of the original file;
- do not expose import after application data exists;
- preserve remote startup’s no-SQLite/no-import behavior.

7. Tests
- shared Python/TypeScript canonical/digest fixtures;
- exact PostgreSQL schema/head/role checks;
- two-owner and cross-owner rejection;
- representative full graph including soft deletion, USDA JSON, nested and
  republished Recipes, projections, Daily Log history and unknown nutrients,
  OCR, Targets, and receipts;
- tampered/truncated/unsupported/duplicate/count/digest/privacy cases;
- source-before/after unchanged proof and qualifier mutation denial;
- failure injection after every import section and qualification group;
- reopen after failure and prove only migrations/nutrient seeds remain;
- exact target row/digest/aggregate/projection/idempotency qualification;
- reimport rejection;
- local/remote recovery isolation and remote bootstrap access spies;
- focused UI/accessibility tests;
- focused end-to-end PostgreSQL fixture -> file -> SQLite import.

Do not add chunking, an archive, migration cursors, import journals, receipt
tables, sync APIs, background jobs, or permanent generic migration
infrastructure. Stop if the package exceeds 64 MiB on owner-coordinated data,
JSON cannot round-trip losslessly, source data is inconsistent, or any approved
architecture stop is encountered.

Run proportional focused checks, TypeScript, backend lint/tests for affected
modules, documentation validation, git diff --check, and ./scripts/session-end.sh.
Report every test result, skip, warning, changed file, and intentional
non-change. Do not commit or push.
```
