# Production Hardening: immutable historical provenance

> **Document role: Operational Reference.**

Status: **frozen design and operating contract for application revision
`0020_immutable_provenance_enforcement` and control revision
`ops_0006_immutable_provenance`**

When this retained schema-0020 boundary requires independent requalification, run
`apps/backend/scripts/qualify_immutable_provenance.py` from `apps/backend` with
`.venv/bin/python` and an explicit `NUTRITION_DATABASE_URL`. Admission additionally requires the
separate control-database authority and the CLI's `--admit` flag. This is specialist operations
qualification, not part of ordinary local-first development.

This stage closes a specific enforcement gap. At revision 0019 the PostgreSQL runtime role could
only insert Recipe publication rows and OCR confirmation traces, and the normal repositories did
not expose mutation methods for them. Those were useful least-privilege and service conventions,
but they did not make the rows immutable to a table owner, a test running as owner, or a SQLite
session. Runtime also retained table-wide `DELETE` on Daily Log snapshots so an approved Log edit
could replace the snapshot set. That grant could delete one historical value independently.

Revision 0020 adds row guards at the database boundary and narrows snapshot replacement without
making the mutable Daily Log aggregate append-only. It neither changes an existing nutrition value
nor adds an OCR feature. The frozen implementation names and identity surface live in
`app/operators/immutable_provenance_contracts.py`; this document explains that contract and must
not become a second source of executable constants.

## Classification vocabulary

The inventory uses these classifications precisely:

- `fully_enforced`: enabled database protection rejects update, direct delete, and bulk truncate;
  ordinary writers lack alteration or bypass authority.
- `partially_enforced`: immutable payload is protected, but a bounded lifecycle operation may
  replace or remove the row as part of its owning aggregate.
- `service_only`: normal service code preserves the rule, but a permitted direct database write
  can violate it.
- `test_identity_bypass`: a test connection owns or can alter the protection and therefore does
  not model the production runtime identity by itself.
- `migrator_only_exception`: a fenced, reviewed migration may deliberately change a protected
  structure or row; there is no standing runtime repair path.
- `historical_legacy_exception`: retained legacy evidence remains outside the current application
  writer and has its own historical qualification boundary.
- `not_actually_immutable`: the row is a mutable projection or state machine even if some identity
  or terminal fields never change.

“Immutable” always means immutable after the successful insert/confirmation. A transaction may
construct and flush a new graph before commit, and a failed transaction may roll the entire new
graph back.

## Proven 0019 deficiencies and bounded corrections

| Proven deficiency | Property at risk | Smallest 0020 correction | Deliberately unchanged |
| --- | --- | --- | --- |
| Publication rows and OCR traces were insert-only for `nutrition_runtime`, but had no row guard. The absence is visible in the 0019 schema and owner-level direct SQL can therefore mutate them. SQLite had neither roles nor an equivalent guard. | A mistaken owner/migrator/test write could rewrite or remove historical payload while normal API tests still passed. | Add the exact shared row/truncate rejectors to four enumerated tables and SQLite behavioral triggers. Preserve runtime `INSERT` and valid transaction rollback. | No generalized trigger framework, ownerless security model, or new repository layer. |
| Snapshot immutability relied on service behavior while runtime held relation-wide `DELETE` for delete-and-reinsert Log edits. | Direct SQL could remove one nutrient snapshot and leave a valid-looking but incomplete Log. | Revoke direct runtime snapshot `DELETE`; route complete owned-set replacement through one exact routine; guard every update/delete/truncate and allow only real nullable FK provenance loss. | Daily Log edit and whole-Log delete remain supported; no permanent Log retention or edit event sourcing. |
| Owner-backed and SQLite test sessions could exercise paths unavailable to production runtime. | Passing tests could prove service convention while missing a production privilege failure. | Keep owner setup separate and execute PostgreSQL rejection tests as a runtime-equivalent login; use SQLite triggers only as regression guards. | Test owner remains available for migrations and controlled fixture setup. |
| The Daily Log table keeps broad runtime `UPDATE`, while the 0019 constraints validate only the resulting owner/membership shape. | Direct runtime SQL could repoint a historical Recipe Log to another valid same-owner revision/amount or change amount headers without replacing snapshots. | Add one bounded Daily Log guard: permanently freeze identity, owner, Food, historical name, request identity, creation time, and publication revision; require the exact replacement capability for nutrition-header transitions; retain metadata edit, complete Log delete, and FK-driven serving nulling. | Do not make all Daily Logs append-only or add a general mutation routine. |

The 0019 composite ownership/resource-membership constraints were not deficient and are retained
unchanged. Runtime already lacked update/delete on publication and OCR tables; 0020 adds defense in
depth rather than broadening runtime. Current Recipe/Projection links, the Daily Log row itself,
mutable Foods, and retained legacy OCR tables are not made append-only merely because they contain
historically relevant information.

## Current enforced application inventory

### Domain history

| Row class | Identity and lifecycle | Permitted writers | Database protection at 0020 | Classification |
| --- | --- | --- | --- | --- |
| `recipe_publication_revisions` | `id`; unique `(recipe_id, revision_number)`; immutable from publication commit forever | Runtime publication and the reviewed historical converter may insert; no ordinary update/delete | Owner-aware FKs and checks from 0019; 0020 rejects `UPDATE`, `DELETE`, and `TRUNCATE`; runtime remains `INSERT`-only | `fully_enforced`; `migrator_only_exception` for a reviewed forward migration |
| `recipe_publication_nutrients` | `id`; unique `(revision_id, nutrient_id, basis)`; lifetime equals immutable revision history | Inserted only with a new revision | `RESTRICT` parent/nutrient FKs plus 0020 row and truncate guards; no runtime update/delete | `fully_enforced` |
| `recipe_publication_amount_definitions` | `id`; revision membership and per-revision order/semantic uniqueness | Inserted only with a new revision | `RESTRICT` parent FK, shape/partial-unique rules, and 0020 row and truncate guards; no runtime update/delete | `fully_enforced` |
| `daily_logs` | `id`, owned by `user_id`; one current user-visible Log aggregate | The service may insert, edit approved metadata/nutrition selection, and delete the complete owned Log. Runtime retains bounded table-level insert/update/delete | Owner/resource FKs and paired revision links plus the 0020 update guard. Permanent identity/revision fields are frozen; metadata remains editable; nutrition headers require the owned replacement capability | `partially_enforced`; the row is intentionally not append-only, but revision pinning and header/snapshot transition boundaries are database guarded |
| `daily_log_nutrient_snapshots` | `id`, bound to `(daily_log_id, source_food_item_id)`; one immutable calculated value inside the current Log generation | Runtime inserts a complete set. It may remove only the owned Log's whole set through the bounded replacement routine before an approved edit or Log delete | Immutable numeric/linkage guard; only verified FK-driven nulling of nullable source nutrient/serving IDs is accepted; truncate rejected; direct runtime `DELETE` revoked | `partially_enforced` because an explicit Log edit replaces the generation and whole-Log deletion removes it |
| `ocr_nutrition_confirmation_traces` | `id`; unique owner request and one trace per created Food; immutable from confirmation commit | Runtime confirmation transaction may insert; idempotent replay reads the existing row | Composite `(food_item_id,user_id)` ownership FK plus 0020 row and truncate guards; runtime remains `INSERT`-only | `fully_enforced` |

There are no other Recipe revision child tables. Compatibility `food_items`, their
`food_nutrients`, `serving_definitions`, and `food_sources` are mutable projections or ordinary
Food state, not publication history. A Recipe republish inserts a new revision graph and may replace
the projection children; it never rewrites the old revision. `recipes.active_publication_revision_id`
and the projection's revision pointer are mutable current-state links, not historical payload.

The normal writer changes Daily Log header columns such as amount, unit, gram amount,
amount-definition selection, date, meal, and notes only through the established owner-scoped Log
edit. That edit deletes the prior snapshot set and inserts a newly resolved set in the same
transaction. This is version replacement, not in-place snapshot editing. The system does not
retain every user edit as a separate Log version, and 0020 does not claim that it does. Food,
serving, projection, or Recipe changes without an explicit Log edit cannot recalculate an existing
snapshot.

The 0020 Daily Log guard permanently freezes identity, owner, Food, request/fingerprint,
food-name snapshot, creation time, and the publication revision originally logged. Date, meal,
notes, and update time remain directly editable. Amount, unit, serving, amount-definition, gram,
and package fields may transition only after the owner-scoped replacement routine has removed the
old snapshot set in the same transaction. The exact FK-driven serving non-null-to-null action is
also admitted without opening a general update path. This enforces revision pinning and prevents a
header-only nutrition rewrite while preserving the existing product edit/delete lifecycle.

Deleting a source `FoodNutrient` or `ServingDefinition` may set the corresponding nullable
diagnostic pointer on a snapshot to null. The guard accepts only the exact old-non-null to null
transition after the referenced parent has disappeared, with every authoritative snapshot column
unchanged. `source_food_item_id`, `daily_log_id`, `nutrient_id`, calculated values, units, consumed
amounts, and calculation metadata cannot be reassigned. Food soft deletion does not delete a
snapshot or OCR trace. Publication parents and OCR Foods are protected from physical deletion by
their `RESTRICT`/`NO ACTION` relationships; Recipe and Food retirement remains soft deletion.

### Other application receipts and retained history

| Row class | Actual lifecycle | Enforcement and classification |
| --- | --- | --- |
| `create_operation_idempotency` | Reserved, then completed with a response snapshot; it is a mutable two-state coordination receipt, not historical nutrition | `not_actually_immutable`; service and checks constrain completion, but it is outside 0020 |
| `phase5c_conversion_metadata` | One immutable binding of archive, clone, inventory, checksums, attestation, and converter manifest | Existing 0018 row/truncate triggers: `fully_enforced` |
| `phase5c_conversion_runs` | Binding fields immutable; execution and verification state advance until terminal | Existing guarded state machine: `partially_enforced`; terminal rows cannot regress |
| `phase5c_conversion_outcomes` | Plan/binding/result identities immutable; checkpoint and verification state advance until terminal | Existing guarded state machine: `partially_enforced`; terminal rows cannot regress |
| `phase5c_promotion_target_identity`, `phase5c_conversion_clone_marker`, `phase5c_write_fence_events` | Immutable target/clone identity and append-only fence event evidence | Existing 0018 row/truncate guards: `fully_enforced` |
| `phase5c_write_fence_state` | Current fence projection advanced only by the bounded fence API | `not_actually_immutable`; guarded mutable operational state |
| Registered archive schema `bridge_metadata`, `recipes`, `recipe_ingredients` | Frozen source archive used by conversion qualification | Existing archive row/truncate guards: `fully_enforced`; no application-runtime access |
| Public legacy `ocr_scans`, `parse_results`, `parser_corrections` | Retained pre-current-schema OCR records included in Phase 5 conversion/qualification digests; no current ORM or runtime writer | `historical_legacy_exception`; runtime has no privileges, but these are not newly reclassified as current 0020 OCR persistence |
| `food_sources`, `food_nutrients.original_*`, and serving/nutrient source fields | Diagnostics attached to a mutable Food generation | `not_actually_immutable`; runtime Food update/replacement may update or delete them, so they are not a substitute for a confirmation trace or Log snapshot |
| `nutrients` and `nutrient_reference_values` | Migration-owned catalog/reference data, with reference rows carrying `source_version` | Runtime read-only but no historical-row guard; `not_actually_immutable` for this contract. Stored revision/snapshot units and values, not a live reference row, preserve user history |

The historical converter may insert a missing transition-baseline revision while operating under
its frozen pre-0020 execution contract. Its source archive, Daily Log digest, OCR digest, plan, run,
and outcome bindings prevent it from rewriting unrelated history. After 0020, it receives no new
ability to update an existing revision, child, snapshot, or OCR confirmation trace.

### Exact application writer surfaces

- `RecipeService.publish` builds a new graph with `build_revision` and persists it through
  `RecipePublicationRepository.add`. That repository exposes add and owner-scoped reads only; it
  has no update or delete method. Republish calls the same insert path with a new revision number.
- `execute_historical_recipe_conversion` is the separately controlled legacy insertion path. It
  binds writes to its plan/run/outcome evidence and is not a user-facing repair endpoint.
- `LogService.create_log` inserts one Daily Log plus its new snapshots. `LogService.update_log`
  locks the Log, resolves an immutable revision or locked mutable Food, removes the complete prior
  snapshot set through the bounded repository/routine boundary, and inserts the replacement in one
  transaction. `LogService.delete_log` deletes the complete owned aggregate; there is no service
  operation for editing or deleting one snapshot.
- `OcrConfirmationService.confirm` creates the Manual Food and confirmation trace in one
  transaction. It returns an existing trace only for an owner-scoped request ID with the same
  fingerprint. `get_trace` is owner-scoped read-only; no OCR trace mutation repository exists.

### Control-plane evidence inventory

The application control database is a separate authority. The following tables installed by
`ops_0001` through `ops_0003` are append-only and already protected by the shared control-plane
row and truncate rejector:

- registry and artifact identity: `phase5c4_principals`, `phase5c4_contract_types`,
  `phase5c4_database_instances`, `phase5c4_artifacts`,
  `phase5c4_artifact_logical_identities`, `phase5c4_artifact_identity_conflicts`,
  `phase5c4_artifact_object_bindings`, `phase5c4_artifact_bindings`,
  `phase5c4_artifact_sets`, and `phase5c4_artifact_set_members`;
- database and candidate evidence: `phase5c4_database_instance_observations`,
  `phase5c4_database_physical_components`, `phase5c4_candidate_seals`,
  `phase5c4_candidate_seal_bindings`, `phase5c4_performance_contracts`,
  `phase5c4_performance_structural_rules`, `phase5c4_performance_scan_rows`,
  `phase5c4_performance_component_rows`, `phase5c4_performance_contract_revocations`,
  `phase5c4_qualification_observations`, `phase5c4_source_reconciliations`,
  `phase5c4_reconciliation_roots`, `phase5c4_quarantine_acceptances`,
  `phase5c4_quarantine_subjects`, `phase5c4_quarantine_reason_counts`,
  `phase5c4_zero_block_receipts`, `phase5c4_backup_evidence`,
  `phase5c4_restore_receipts`, `phase5c4_restore_checks`, `phase5c4_clone_origins`,
  `phase5c4_bridge_metadata_evidence`, `phase5c4_run_admissions`,
  `phase5c4_deployment_descriptors`, and `phase5c4_authorization_envelope_bindings`;
- command and audit evidence: `phase5c4_transition_requests`,
  `phase5c4_request_conflicts`, `phase5c4_external_action_intents`,
  `phase5c4_external_action_observations`, `phase5c4_external_action_conflicts`,
  `phase5c4_function_manifests`, `phase5c4_constraint_manifests`,
  `phase5c4_authorizations`, `phase5c4_authorization_consumptions`,
  `phase5c4_verification_runs`, `phase5c4_verification_checks`, `phase5c4_events`,
  `phase5c4_audit_messages`, `phase5c4_audit_delivery_attempts`, and
  `phase5c4_audit_sink_receipts`.

`ops_0004` adds immutable `phase5c4_source_dimension_observations`,
`phase5c4_admission_decisions`, `phase5c4_admission_decision_artifacts`, and
`phase5c4_qualification_v2_catalog_manifest`. `ops_0005` adds immutable
`phase5c4_resource_membership_admissions` and
`phase5c4_qualification_v3_catalog_manifest`. The 0020 control migration must likewise retain its
qualification admission bytes and current catalog manifest as new append-only evidence; it must
not edit any earlier row or definition in place.

Control projections are intentionally different: `phase5c4_environments`, `phase5c4_attempts`,
`phase5c4_external_action_status`, and `phase5c4_audit_deliveries` are guarded, routine-owned state
machines with immutable identity/terminal states, while `phase5c4_performance_admission_epochs` is
a mutable serialization counter. They are `not_actually_immutable` as whole rows.

Control identities receive no base-table DML. Collector, executor, outbox, and gate actions cross
only their exact control API routines; audit and gate logins are read-only where applicable.
`nutrition_control_owner` is non-login and owns the schema/protections.
`nutrition_control_migrator` alone may explicitly assume it for a control migration. Thus accepted
evidence is insert-only through a validated routine, mutable projections advance only through
their guarded routines, and no application runtime/canary identity can mutate control evidence.

## Identity and mutation matrix

The table shows direct database authority after 0020. `I` means valid insert, `R` the exact owned
snapshot replacement routine, `G` a database guard rejects the mutation, and `A` that an identity
can alter protection only through the reviewed migration exception.

| Identity or path | Revision root/children | OCR trace | Snapshot value row | Daily Log row | Protection bypass/alteration |
| --- | --- | --- | --- | --- | --- |
| `nutrition_runtime` | `SELECT`, `I`; update/delete/truncate `G` | `SELECT`, `I`; update/delete/truncate `G` | `SELECT`, `I`, `R`; direct update/delete/truncate `G` | Table-level insert/update/delete; owner scoping and transition semantics are service-enforced | None; no table ownership, `ALTER`, `TRIGGER`, role assumption, superuser, replication, or `BYPASSRLS` |
| `nutrition_canary` | Read only | Read only | Read only | Read only | None; transaction default is read only |
| `nutrition_qualifier` | Read/catalog qualification only | Read/catalog qualification only | Read/catalog qualification only | Read/catalog qualification only | None; transaction default is read only |
| application control roles | No application-table grant | No application-table grant | No application-table grant | No application-table grant | Control API authority does not cross into the application database |
| `nutrition_owner` | `I`; enabled guards reject row mutation | `I`; enabled guards reject row mutation | `I`; guard or `R` | Owner DML subject to application guards/fence | `A`: owns relations/routines and can deliberately alter them; it is not a login role |
| `nutrition_migrator` | No ordinary runtime path; may `SET ROLE nutrition_owner` for an approved migration | Same | Same | Same | `A` only in a fenced, drained migration; no standing repair routine |
| PostgreSQL runtime test identity | Same grants and failures as `nutrition_runtime` | Same | Same | Same | None; these are the security assertions that count |
| PostgreSQL test owner | Setup/DDL and reviewed migration behavior | Same | Same | Same | `test_identity_bypass`; owner-only success is not evidence of runtime safety |
| SQLite test session | Valid service insert; update/delete rejected by SQLite triggers | Same | Insert and explicitly scoped set replacement; other mutation rejected | Approved service edit/delete | No role isolation; schema owner can drop triggers, so this is behavioral regression protection only |
| ORM mutation, Core SQL, or bulk SQL under runtime | Database guard/ACL applies equally | Same | Same | Normal ownership/service rules | No ORM escape from database enforcement |
| historical converter | May insert a new transition-baseline graph under its frozen operator contract | No current trace writes | No snapshot mutation | No Daily Log mutation | Migrator identity remains the explicit exception boundary |
| Alembic | May install a new protection version or perform an explicitly reviewed repair | Same | Same | Same | Runs as migrator/owner under fence, locks, evidence, and requalification |

Trigger functions execute for direct SQL, ORM flushes, bulk operations, and owner DML while the
triggers remain enabled. They do not make a true database owner powerless: PostgreSQL ownership
necessarily includes alteration authority, and a superuser can bypass any in-database control.
Separation of login roles, exact ownership, catalog qualification, and operational evidence make
that exception visible rather than pretending it does not exist.

## Exact 0020 enforcement boundary

PostgreSQL installs one shared row rejector and one shared truncate rejector for the four fully
append-only tables. Each table receives an exact `BEFORE UPDATE OR DELETE FOR EACH ROW` trigger and
an exact `BEFORE TRUNCATE FOR EACH STATEMENT` trigger. The snapshot table instead receives
`phase0020_snapshot_mutation_guard` and its own truncate trigger. The exact trigger set is frozen in
`POSTGRES_TRIGGER_CONTRACTS`; adding a table requires a new contract version, not a wildcard or
general trigger framework.

| Table | Row trigger | Truncate trigger |
| --- | --- | --- |
| `recipe_publication_revisions` | `phase0020_revision_immutable_row` | `phase0020_revision_immutable_truncate` |
| `recipe_publication_nutrients` | `phase0020_revision_nutrient_immutable_row` | `phase0020_revision_nutrient_immutable_truncate` |
| `recipe_publication_amount_definitions` | `phase0020_revision_amount_immutable_row` | `phase0020_revision_amount_immutable_truncate` |
| `ocr_nutrition_confirmation_traces` | `phase0020_ocr_trace_immutable_row` | `phase0020_ocr_trace_immutable_truncate` |
| `daily_log_nutrient_snapshots` | `phase0020_snapshot_mutation_guard` | `phase0020_snapshot_immutable_truncate` |
| `daily_logs` | `phase0020_daily_log_update_guard` | none; complete Log deletion remains product behavior |

The shared trigger functions are `phase0020_reject_immutable_row_mutation()`,
`phase0020_reject_immutable_truncate()`, `phase0020_guard_snapshot_mutation()`,
`phase0020_guard_daily_log_mutation()`, and
`phase0020_require_snapshot_replacement_completion()`. Current
qualification is computed through the independent
`phase0020_resource_membership_integrity_valid()`,
`phase0020_immutable_provenance_integrity_valid()`, and
`phase5c_local_admission_v3()` definitions; none is an unqualified mutation helper.

`phase0020_guard_snapshot_mutation` rejects numeric, unit, status, calculation, source-Food,
nutrient, Log, and ownership/linkage changes. It admits only the two existing nullable provenance
FK actions when the referenced serving or FoodNutrient has actually gone away. Snapshot-set
deletion is performed by
`phase0020_delete_log_snapshots_for_replacement(uuid, uuid)`, a narrow
`SECURITY DEFINER` routine that verifies the owning user and target Log, pins its `search_path`, and
opens the guard only for that set in the current transaction. Runtime loses relation-level
snapshot `DELETE` and gains execute on this one routine. `PUBLIC` has no execute. This routine is
used for both an approved edit replacement and removal of the snapshot set immediately before the
complete owned Log is deleted; it is not an arbitrary repair API.

The routine creates an owner-only temporary transaction capability for the exact owner/Log pair;
runtime cannot forge it by setting a session variable. Snapshot and Daily Log guards consult that
capability. A `DEFERRABLE INITIALLY DEFERRED` constraint trigger rejects a naked helper call at
commit: the parent must have been deleted, a replacement snapshot must exist, or the guarded
nutrition-header transition must have completed. The last case deliberately permits an explicit
edit to resolve to zero snapshots because the established Food resolver may validly have no
nutrient rows. This is the narrow unavoidable runtime capability, not permission to delete one
snapshot or rewrite an existing value in place. SQLite cannot provide equivalent deferred
constraint security and remains a service/trigger regression boundary.

All protection and validation routines are owned by `nutrition_owner`, with exact signatures,
language/properties, `search_path`, definitions, and ACLs included in the stage qualification. At
revision 0020, runtime and canary may execute the v3 local admission routine; runtime additionally
may execute the snapshot replacement routine. Frozen pre-0020 routine grants remain independently
qualified. Owner-only validator/rejector functions do not grant an ordinary caller a mutation
path. The resource-membership validator independently proves that the complete 0019 constraint
contract is still validated before immutable provenance can qualify.

The migration uses the established advisory lock, five-second lock timeout, fifteen-minute
statement timeout, closed write fence, and drained runtime requirement. It acquires
`SHARE ROW EXCLUSIVE` locks in this exact order:

1. `daily_logs`
2. `recipe_publication_revisions`
3. `recipe_publication_amount_definitions`
4. `recipe_publication_nutrients`
5. `daily_log_nutrient_snapshots`
6. `ocr_nutrition_confirmation_traces`

The order starts with the mutable owning Log and then advances through immutable roots/children.
The migration changes no domain row. Transactional failure removes every new trigger, routine,
grant, and admission object and leaves 0019 usable. After commit, the revision is forward-only:
an old runtime would attempt direct snapshot deletes and is not schema-compatible.

## PostgreSQL and SQLite boundary

PostgreSQL is the production authority. It combines role separation, relation/routine ACLs,
non-login object ownership, row and statement triggers, a security-definer snapshot routine,
transactional DDL, fence/drain checks, catalog qualification, and versioned admission.

SQLite has no production roles, `SECURITY DEFINER`, `TRUNCATE`, PostgreSQL catalog, or independent
control admission. SQLAlchemy metadata installs `BEFORE UPDATE` and `BEFORE DELETE` SQLite triggers
for the four append-only tables. Snapshot triggers reject all in-place value/linkage changes except
real FK-driven nulling, and reject direct child deletion while the owning Log remains. The
repository opens a process-local, context-scoped SQLite UDF guard only around the approved complete
snapshot-set replacement. A Daily Log update trigger freezes permanent/revision fields and requires
the same scope for nutrition headers while allowing metadata and exact FK-driven serving nulling.
Deleting the owning Log may remove its snapshots without turning Daily Logs into permanent records.

That UDF is explicitly not authorization: a process controlling the SQLite connection or schema
can replace functions or drop triggers. SQLite tests prove accidental application/test mutation is
caught and approved workflows still behave; they do not prove production identity isolation or
PostgreSQL migration/locking behavior.

## Reviewed migrator repair exception

There is no always-available “repair immutable history” function, configuration flag, owner API,
or runtime grant. Discovery of corrupt protected data blocks promotion and starts a separate
incident/review. Do not change a historical value merely to make qualification green.

When a repair is justified and its historical meaning can be defended, use a new forward migration
with all of the following:

1. identify exact row IDs, columns, before-digests, reason, approvers, and expected after-digests;
2. retain a restorable backup and the failed qualification/preflight evidence;
3. close the established fence, stop background writers, and prove `nutrition_runtime` drained;
4. run only as `nutrition_migrator`, explicitly assuming non-login `nutrition_owner` for the
   migration transaction;
5. take the shared advisory lock and the frozen table locks in owner-before-child order;
6. alter or disable only the named immutable-row trigger on the exact target relation and, because
   the closed fence intentionally rejects DML, that relation's exact `phase5c_write_fence_gate`;
   record both definitions/enabled states and restore them in the same transaction. Never use
   `session_replication_role`, `DISABLE TRIGGER ALL`, runtime owner grants, or a generic bypass;
7. perform the exact mutation, install the same or a new versioned protection definition, and
   verify it is enabled before commit;
8. recompute immutable/history digests, rerun resource-membership and immutable qualification,
   admit new control evidence, and reopen traffic only after canary success.

An error before commit rolls back both data and protection-object changes. After commit, recovery
is fix-forward or restoration into a separately qualified environment; do not mark Alembic back,
drop guards by hand, or start an older runtime. For an unrecoverable bad deployment, preserve the
candidate and evidence for investigation and restore/PITR the last known-good database under the
same promotion controls.

## Deployment and recovery runbook

1. On exact 0019/ops 0005, retain the successful resource-membership qualification and take a
   restorable backup. Verify historical revision, Log, snapshot, OCR, and conversion digests.
2. Enter `closed_prequalification` or `closed_cutover`, stop application/background writers, and
   drain the real runtime login. Migration startup is never delegated to application startup.
3. Apply application revision 0020 with the migrator credential. Require the exact trigger,
   routine, owner, ACL, definition-digest, enabled-state, and unchanged-row qualifications.
4. Deploy the 0020-aware runtime while the fence remains closed. An older runtime is incompatible
   because direct snapshot `DELETE` has been removed.
5. Apply control revision ops 0006 independently. Register only the exact canonical current-schema
   qualification through its bounded control API; retain ops 0004 and ops 0005 evidence unchanged.
6. Run the qualifier through its read-only identity, then run canary admission and valid insert,
   publication, Log edit/delete, OCR confirmation, and historical-read checks.
7. Reopen traffic only through the established promotion authority. Monitor immutable-guard
   failures as integrity signals rather than translating them into generic optimistic conflicts.

If application migration, qualification, control admission, or canary fails, keep the fence closed.
Before the application migration commits, retry only after correcting the cause; PostgreSQL DDL
rollback restores 0019. After commit, correct forward or restore the backup. Control downgrade is
permitted only if its new immutable admission storage is empty; once evidence is admitted it is
forward-only.

## OCR provenance readiness

### Current enforced state

The current immutable root is one `ocr_nutrition_confirmation_traces` row for one successful
confirmation transaction—not one transient camera or parsing attempt. `(user_id,
client_request_id)` is the retry identity and `request_fingerprint` binds the canonical request;
`food_item_id` is unique, owner-bound, and created atomically with the trace. Identical replay
returns the existing Food and trace; the same request ID with different content conflicts. A failed
Food/trace transaction leaves neither row.

The bounded `trace_snapshot` currently distinguishes:

- machine extraction: suggested values, parse status, confidence, selected source snippets,
  observation IDs, warning codes, comparison markers, and `parser_version`;
- normalization: canonical field/nutrient IDs and units, schema version, resolutions, and parser
  warnings;
- user correction: `accepted`, `edited`, or `omitted`, final confirmed value, and dismissed unknown
  nutrients;
- final confirmation: trace ID, owner, Food, image source class, schema/parser versions, request
  fingerprint, and confirmation timestamp;
- Food result: the atomically created Manual Food. Current confirmation does not update an existing
  Food;
- serving and nutrient derivation: final values are present in the bounded decisions, but there are
  no relational trace-to-`serving_definitions` or trace-to-`food_nutrients` child bindings.

The request validator caps decisions, strings, observation IDs, warnings, unknown nutrients, and
the complete trace at 48,000 bytes. It rejects local image/path references. The server persists no
image, image path, full raw OCR text, or unbounded parser response. Selected explanatory snippets
are sensitive and must remain limited to what is needed to understand a decision. The trace is
provenance only; nutrition resolution reads Food/Recipe/Log authorities, never OCR JSON.

Food editing or serving/nutrient replacement cannot change this trace. Food soft deletion retains
it, and the ownership FK prevents its silent reassignment. Parser upgrades remain interpretable
because each trace pins parser and trace-schema versions. The current contract does not explicitly
pin a separate OCR engine/version, normalization-rule version, image digest, correction-set ID, or
the exact mutable serving/nutrient row IDs.

### Proven deficiencies before OCR persistence expands

The existing confirmation trace is sufficient for the current on-device-extraction, bounded
confirmation flow, but it is not a general persisted OCR-attempt model:

- unconfirmed attempts and multiple attempts are deliberately absent;
- machine engine/version and normalization version are not separate relational identities;
- final Food values are explainable from the JSON, but output serving/nutrient row membership is
  not relationally bound;
- correction decisions form one confirmation snapshot, not an append-only sequence of review
  events or superseding correction sets;
- image content/digest/retention and erasure receipts do not exist because images are deliberately
  excluded; and
- the retained legacy `ocr_scans`, `parse_results`, and `parser_corrections` are historical input,
  not a supported schema to revive for the current feature.

These are scope boundaries, not defects in current nutrition resolution. They become correctness
requirements only if later work persists attempts, images, repeated correction rounds, updates an
existing Food, or needs relational output lineage.

### Required next schema before such expansion

Freeze the intended feature behavior first, then add only the relations it needs:

1. Keep the confirmation trace as the immutable confirmation/transaction root. If pre-confirmation
   attempts must be persisted, introduce a separate immutable attempt identity owned by the user;
   do not overload or update a confirmation row. Each later attempt may reference a prior attempt
   as superseded, while both remain immutable.
2. Represent suggestions/observations and correction decisions as versioned immutable children of
   exactly one attempt or confirmation. A later correction set inserts new rows and a supersession
   link; it never updates an earlier correction.
3. Store final confirmed Food, serving, and nutrient values in immutable provenance children. Any
   pointers to mutable `serving_definitions` or `food_nutrients` are diagnostic and nullable on
   replacement; the stored final values remain authoritative for interpretation.
4. Add composite ownership/membership keys for `(trace_id,user_id)`, `(food_item_id,user_id)`,
   `(serving_definition_id,food_item_id)`, and
   `(food_nutrient_id,food_item_id,nutrient_id)` wherever those identities are persisted. Bind every
   child to its immutable root. Do not create cyclic constraints that make legitimate Food child
   replacement impossible.
5. Pin extraction engine/version, parser version, normalization-rule version, trace schema, request
   identity/fingerprint, and confirmation transaction identity. Retry uniqueness remains owner
   scoped. A new semantic attempt gets a new request identity; only byte/meaning-equivalent replay
   returns the old result.
6. If raw media is ever retained, keep the blob outside the application tables. Persist only a
   bounded artifact identity, digest, media type/size, policy version, and opaque object reference.
   Separate immutable artifact identity from mutable availability. Expiry or privacy deletion
   removes the object and appends an erasure/retention receipt while retaining the non-content
   digest and confirmation lineage, subject to privacy review.

Database constraints should own identity, owner, root-child membership, uniqueness, and bounded
state shapes. Application validation should continue to own semantic equivalence between a
versioned parser result and Food payload, redaction policy, engine-specific interpretation,
normalization, and cross-aggregate workflows that would otherwise create cyclic constraints.

With that shape, old confirmations remain interpretable after Food edits, child replacement, Food
soft deletion, engine upgrades, and normalization changes because the immutable provenance stores
the final values and exact algorithm versions. Mutable row pointers improve diagnostics but never
become the only historical authority.

### Optional future enhancements

Optional, feature-driven additions include encrypted raw-artifact storage with an explicit
retention class, a persisted attempt/supersession graph, signed engine manifests, per-field
correction-set children, and privacy erasure receipts. Each needs its own threat model, bounded
migration, and retention decision. None is required to enforce the current confirmation trace.

### Rejected complexity and explicitly deferred work

This stage rejects RLS, event sourcing, a generalized temporal or trigger framework, a broad
security-definer data API, reviving legacy OCR tables, automatic history repair, and making every
Daily Log append-only. It also deliberately defers camera/vendor integration, extraction, parsing
changes, image upload or object storage, queue workers, OCR drafts/attempt persistence, correction
UI, review screens, per-field workflow tables, existing-Food OCR updates, and mobile changes.
Those features must not infer authorization from the presence of 0020 guards.

## Qualification and evidence expectations

Current qualification must prove exact application/control heads; the frozen append-only table
set; trigger events, orientation, enabled state, function identity and owners; exact function
definitions and pinned `search_path`; no `PUBLIC` execute; exact runtime relation/routine ACLs;
runtime rejection of row update/delete/truncate and protection alteration; approved publication,
Log replacement/delete, and OCR insert; the complete validated 0019 resource-membership contract;
and unchanged canonical digests for existing revisions, revision children, Daily Logs, snapshots,
OCR traces, conversion evidence, and 0019 ownership/business columns.

Only mutation rejection executed as the runtime-equivalent PostgreSQL login proves the production
boundary. Owner tests prove controlled setup or migration behavior, not least privilege. SQLite
tests prove behavioral guards and legitimate workflows, not PostgreSQL role security. Any change
to a protected function, trigger set, ACL, table set, local admission result, or control catalog
requires a new versioned manifest and qualification line rather than editing prior evidence.
