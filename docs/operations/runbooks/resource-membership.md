# Production Hardening: database-enforced resource membership

> **Document role: Operational Reference.**

Status: **frozen application schema contract for revision
`0019_resource_membership_integrity`**

This bounded stage moves selected ownership and child-membership rules from application-only
validation into database constraints. It does not change nutrient values, rewrite Daily Log
snapshots, replace published Recipe revisions, introduce row-level security, or remediate legacy
rows. PostgreSQL is authoritative for the production migration. SQLAlchemy metadata carries the
portable constraint subset used by supported SQLite development and test schemas.

The frozen contract names, corruption categories, lock order, constraint definitions, and version
boundaries live in `app/operators/resource_membership_contracts.py`. Do not duplicate or silently
reinterpret them in another operator.

## Before migration: read-only corruption inventory

Run the inventory against the exact application revision
`0018_phase5c_promotion_prerequisites`, using an approved read-only operator or qualifier
credential:

```bash
cd apps/backend
NUTRITION_DATABASE_URL='postgresql+psycopg://…' \
  .venv/bin/python -m scripts.preflight_resource_membership
```

The command refuses non-PostgreSQL databases and any schema head other than exact 0018. It opens
one `REPEATABLE READ`, `READ ONLY` transaction, runs all frozen
`resource_membership_preflight_v1` categories, emits one canonical JSON document to standard
output, and rolls the transaction back. Output is deterministic and contains only category data
and whitelisted row identifiers; it does not expose names, nutrition values, OCR content, or
cross-owner data through an ordinary runtime API.

Exit behavior is stable:

- `0`: the canonical report was emitted and contains no blocking rows;
- `2`: the canonical report was emitted and contains at least one blocking row; and
- `1`: configuration, connection, transaction, database-engine, or schema admission failed; the
  command emits only a bounded operator error.

The report binds its version, required and observed schema revisions, read-only state, ordered
category counts, ordered findings, and a canonical `report_digest`. A zero result is evidence from
that snapshot, not permission to omit the migration's own preflight.

### Corruption classifications and remediation

Every reported row blocks 0019. `impossible_invariant` means the row contradicts an invariant that
valid application behavior should never have produced. `remediable_legacy_corruption` identifies a
legacy relationship whose correction may be possible without changing historical nutrition. The
classification is not itself a repair authorization. Legacy-compatible nullable or soft-deleted
states that remain valid are excluded from the blocking result.

The preflight performs no mutation. When it reports findings:

1. retain the exact report and digest as operator evidence;
2. investigate the identified rows outside runtime APIs;
3. prepare a separate, reviewed remediation plan that explains historical-integrity effects;
4. execute only explicitly approved repairs under an appropriate write fence and audit boundary;
   and
5. rerun the entire preflight and require a new zero-finding report.

Do not make the migration delete, re-own, relink, or rewrite a corrupt row. In particular, do not
recompute Daily Log nutrient snapshots or mutate publication revisions to make a constraint pass.
An impossible-invariant result should be treated as an incident investigation, not normalized as
routine legacy cleanup.

## Migration runbook

Migration 0019 is PostgreSQL-only and must run through the separate migrator identity. Before
invoking Alembic, the operator must:

- confirm the application database is still at exact revision 0018;
- place the deployment candidate in a canary-eligible closed mode
  (`closed_prequalification` or `closed_cutover`);
- stop new application and background work, drain in-flight requests and jobs, and prove that no
  `nutrition_runtime` database session remains;
- retain a restorable pre-0019 backup and the successful preflight artifact; and
- leave migration execution separate from application startup.

Revision 0018 deliberately has no production principal that can reopen an
`open_production` target, and `closed_incident` cannot return to a canary-eligible mode. Therefore
0019 is deployable only to a target already in `closed_prequalification` or `closed_cutover` under
the established promotion workflow. An already-open production upgrade is blocked until a
separately reviewed maintenance/activation authority exists; this migration does not smuggle in
that authority. Incident-state observation remains useful for recovery diagnosis, but it cannot
produce a deployable 0019 qualification or control admission.

Then run the application migration with the explicit migrator URL:

```bash
cd apps/backend
NUTRITION_DATABASE_URL='postgresql+psycopg://…' \
  alembic upgrade 0019_resource_membership_integrity
```

The migration verifies the closed fence and drained runtime itself. It sets a five-second lock
timeout and a fifteen-minute statement timeout, then acquires `SHARE ROW EXCLUSIVE` locks in this
frozen order:

1. `daily_logs`
2. `food_items`
3. `recipes`
4. `recipe_publication_revisions`
5. `recipe_publication_amount_definitions`
6. `serving_definitions`
7. `food_nutrients`
8. `recipe_ingredients`
9. `daily_log_nutrient_snapshots`
10. `ocr_nutrition_confirmation_traces`

The first three locks preserve the established runtime edge
`DailyLog -> Food -> Recipe`; the remaining tables are acquired only afterward in this one order.
Table locks begin only after the write fence is stable under the shared advisory transaction lock
and the real `nutrition_runtime` login has drained, so no live runtime row-lock transaction can
invert this migration sequence. The fence and drain are therefore correctness requirements, not
optimizations. A lock that cannot be acquired within five seconds aborts the transaction and
leaves revision 0018 intact; there is no automatic DDL retry.

After the locks are held—and before its first schema mutation—the migration reruns the exact shared
preflight classifier in the Alembic transaction. It then backfills the new
`recipe_ingredients.user_id` only from the owning Recipe, adds supporting uniqueness and indexes,
installs the new foreign keys and paired-link check as PostgreSQL `NOT VALID`, validates them, makes
the owner column non-null, and installs the unique publication-projection index and current local
admission routine. `NOT VALID` limits initial installation work; validation still completes inside
this single migration and is not deferred to a later deployment.

The frozen 0018 write-fence trigger rejects migration DML while writes are closed. Under the held
table locks and in the same PostgreSQL transaction, 0019 therefore disables only
`recipe_ingredients.phase5c_write_fence_gate`, performs the owner-only backfill, and immediately
re-enables that same trigger. It does not add an owner-population trigger or permit runtime implicit
backfill. Success and injected-failure tests prove the trigger definition and enabled state are
unchanged; transactional rollback also restores it if failure occurs between disable and re-enable.

Fence failure, an undrained runtime session, lock timeout, preflight finding, validation error, or
any later statement failure aborts the PostgreSQL transaction. No partial 0019 schema is admitted.
Keep the fence closed after the migration until qualification and current-schema admission pass.

## Forward-only recovery boundary

The application downgrade for 0019 always refuses. Before commit, PostgreSQL transactional DDL
provides rollback of the failed attempt. After commit, recovery is fix-forward or restore of the
exact pre-0019 backup into a separately validated environment. Do not manually drop the composite
constraints, mark Alembic back to 0018, or start an older runtime that does not populate
`recipe_ingredients.user_id` against schema 0019.

Control revision `ops_0005_resource_membership` may downgrade only while its new
admission table is empty. Once a current-schema qualification has been admitted, the control
revision is forward-only as well, because removing it would discard immutable operational
evidence.

## Qualification and admission boundaries

This stage adds a new current-schema evidence line without rewriting Phase 5C4 history:

| Boundary | Stage contract |
| --- | --- |
| Frozen historical application evidence | `0018_phase5c_promotion_prerequisites` and its existing signed v1 evidence remain unchanged |
| Stage application schema | `0019_resource_membership_integrity` |
| Preflight | `resource_membership_preflight_v1` |
| Constraint manifest | `resource_membership_constraint_manifest_v1` |
| Stage qualification artifact | `resource_membership_qualification_v1` |
| Local application admission | `phase5c_local_admission_v2()` returning `resource_membership_local_admission_v1` |
| Stage control schema | `ops_0005_resource_membership` |
| Control admission | `phase5c4_api.admit_resource_membership_v1(bytea)` |
| Stage control qualification | `phase5c4_api.qualify_control_plane_v3()` returning `resource_membership_control_admission_v1` |

The stage application qualification must prove exact 0019 constraint, index, owner-column,
preflight, fence/identity, and runtime-privilege state. At revision 0019, runtime readiness and
canary startup consume the v2 local admission routine; the previous local routine and signed 0018
evidence remain historical contracts and are not recomputed as 0019 evidence.

Generate the stage qualification artifact with the independent application-database qualifier
credential:

```bash
cd apps/backend
NUTRITION_DATABASE_URL='postgresql+psycopg://…' \
  .venv/bin/python -m scripts.qualify_resource_membership
```

This mode reads the exact 0019 application database in a read-only transaction and emits the
canonical `resource_membership_qualification_v1` artifact to standard output. It does not register
evidence or mutate either database. Retain the exact emitted bytes; reserializing parsed JSON is not
equivalent operational evidence.

Admission is an explicit second authority. To qualify the application database and then submit the
exact artifact through the control executor credential, provide the independent control URL and
opt in with `--admit`:

```bash
cd apps/backend
NUTRITION_DATABASE_URL='postgresql+psycopg://…' \
NUTRITION_PHASE5C4_CONTROL_DATABASE_URL='postgresql+psycopg://…' \
  .venv/bin/python -m scripts.qualify_resource_membership --admit
```

The application-database observation remains read-only. The only write in admitted mode is the
separate control-database call to `phase5c4_api.admit_resource_membership_v1(bytea)` after the
artifact has been built. Setting a control URL without `--admit` does not authorize that write, and
`--admit` without an explicit control URL fails closed. Never point the control URL at an
application endpoint or use the application migrator/runtime credential for control admission.

Control migration ops 0005 first verifies the exact ops 0004/v2 catalog baseline, then adds a new
immutable admission table and v3 catalog manifest. The control executor may invoke only the new
admission routine; the audit role may invoke only the v3 qualification routine. The application
runtime receives no new table, `REFERENCES`, trigger, truncate, ownership, or migration privilege.
Its only new operational surface is execute access to the bounded local v2 admission reader,
alongside canary.

Admission accepts exact canonical bytes, verifies the artifact's versions and digests, requires
zero blocking categories and rows, and is idempotent only for the identical qualification digest
and bytes. It does not open the write fence, start runtime processes, authorize a cutover, or
replace the independent promotion gate.

## Required operator evidence

Retain, without editing:

- the successful exact-0018 preflight JSON and digest;
- the migration start/end record and resulting exact application head;
- proof that the write fence remained closed and `nutrition_runtime` was drained;
- the current-schema qualification artifact and its constraint, preflight, identity/fence, and
  runtime-privilege digests;
- the immutable control admission result and current v3 control qualification result; and
- the explicit decision to reopen traffic only after application readiness and all independent
  environment gates required by the deployment profile pass.

SQLite `create_all` coverage is useful for portable metadata behavior, but it is not migration,
locking, role, `NOT VALID`, or qualification evidence for this stage.
