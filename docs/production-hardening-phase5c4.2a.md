# Production Hardening Stage 5C4.2a: PostgreSQL Role Boundary

Status: implemented for disposable/local PostgreSQL 16 exercises only.

Deployment scope: `phase5c4_controlled_portfolio_demo_v1`  
Role policy: `phase5c4_postgresql_role_policy_v1`  
Privilege manifest: `phase5c4_postgresql_privilege_manifest_v1`

This stage adds no Alembic revision. Alembic head remains `0017_phase5c_indexes`. It adds no write
fence, target identity, qualifier v2, control plane, provider switch, backup adapter, FastAPI route,
or public API change. The qualification document is exercise evidence and is not admitted to the
Stage 5C4.1 promotion artifact set.

## Current-state root cause inventory

The local Compose profile initially uses `nutrition_app` for database creation, Alembic, and the
backend. That role is a login, superuser, database/role creator, replication-capable,
`BYPASSRLS`, database owner, and owner of the migration-created application objects. This is the
root cause: an application connection can exercise ownership rather than a bounded DML grant.

At migration 0017 the reviewed PostgreSQL surface is:

- 18 runtime ORM tables, seven migration-retained/history/control tables, and
  `alembic_version` in `public`;
- 59 indexes on a fresh database; indexes and table row types follow their table owner;
- no application sequence, view, materialized view, procedure, trigger, policy, RLS table, or
  pre-existing application routine;
- no application default ACL entries;
- default database `PUBLIC CONNECT,TEMPORARY` and public-schema `PUBLIC USAGE`;
- exact extension set `plpgsql` 1.0 in `pg_catalog` plus `pgcrypto` 1.3 in `public`; and
- optional `phase5c_conversion_clone_marker` plus zero or more metadata-bound archive schemas,
  each containing exactly `recipes`, `recipe_ingredients`, and `bridge_metadata`.

The provisioner pins that extension set, schema, and version; preserves extension membership and
ownership; and rejects any additional extension. Extension-member functions are not mistaken for
application routines and are not rewritten. It transfers only enumerated application schemas and
objects; it never uses `REASSIGN OWNED`.

At the time of this stage's root-cause inventory, the development `start-backend.sh` ran Alembic
and the backend with one URL. That was convenient for unqualified development but was not an
eligible 5C4.2a launch sequence. The current script implements only the qualified runtime half: it
requires the `nutrition_runtime` identity and never runs Alembic. Apply migrations separately with
the migrator credential.

## Final topology

| Role | Exact attributes | Membership/authority |
| --- | --- | --- |
| `nutrition_owner` | `NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS` | Owns the database, application/archive/maintenance schemas, and enumerated objects |
| `nutrition_migrator` | `LOGIN NOINHERIT` plus all safety attributes above | `nutrition_owner` membership with `SET=true`, `INHERIT=false`, `ADMIN=false` |
| `nutrition_runtime` | `LOGIN INHERIT` plus all safety attributes above | Only `nutrition_runtime_read` and `nutrition_runtime_write`, both with `INHERIT=true`, `SET=false`, `ADMIN=false` |
| `nutrition_canary` | `LOGIN INHERIT` plus safety attributes; `default_transaction_read_only=on` | Only `nutrition_canary_read`, with `INHERIT=true`, `SET=false`, `ADMIN=false` |
| `nutrition_qualifier` | `LOGIN NOINHERIT` plus safety attributes; `default_transaction_read_only=on` | No membership; direct exact SELECT/USAGE grants only |
| `nutrition_ops` | `LOGIN NOINHERIT` plus safety attributes | `pg_signal_backend` with `INHERIT=true`, `SET=false`, `ADMIN=false`; bounded metadata reads and maintenance-routine execution |
| three group roles | `NOLOGIN NOINHERIT` plus safety attributes | Exact grants below; no memberships except the edges above |

No login other than `nutrition_migrator` is a member of `nutrition_owner`. Runtime has no direct or
transitive path to owner or migrator. Login passwords are not created, rotated, accepted as CLI
arguments, or emitted by this implementation; the local operator supplies them through the
existing external PostgreSQL/bootstrap secret boundary.

`nutrition_ops` inherits `pg_signal_backend` because the normative portfolio profile requires it.
PostgreSQL defines that built-in role broadly enough to signal any non-superuser backend. The
single-operator profile accepts that denial-of-service radius; it does not grant row mutation,
owner assumption, or migrator assumption. A multi-operator/public deployment requires a narrower
separate operational design.

## Exact privilege manifest

The canonical manifest and SHA-256 digest are produced by
`app/operators/phase5c4_roles.py`. Serialization and every digest reuse the single canonical
implementation in `phase5c_contracts.py`.

Normal database `CONNECT` is granted directly to migrator, runtime, canary, qualifier, and ops.
During maintenance it is absent only from runtime. `PUBLIC` receives no database privilege.

Schema grants are:

- `public`: `USAGE` to runtime-read, canary-read, qualifier, and ops;
- each metadata-bound archive schema: `USAGE` to qualifier only;
- `phase5c4_maintenance`: `USAGE` to ops only; and
- no `CREATE` grant to any non-owner role or `PUBLIC`.

`nutrition_runtime_read` receives SELECT on the 18 runtime ORM relations. It receives no retained
Phase 5C, archive, or Alembic access. `nutrition_qualifier` receives SELECT on all 26 required public
relations, the optional clone marker when present, and all three relations in every bound archive
schema. `nutrition_canary_read` receives SELECT on the read-probe relations except
`create_operation_idempotency` and `food_favorites`; it receives no retained, archive, or Alembic
access. Daily Log relations remain readable because the seeded canary GET proof reads immutable log
state. The separate exact HTTP allowlist that excludes the recent-food route belongs to Stage
5C4.2b; relation ACLs cannot distinguish two SELECT statements over the same table.

Ops receives SELECT only on `alembic_version` and `phase5c_conversion_metadata`. Those reads let
the maintenance precheck bind exact head and archive names without exposing archive/domain rows;
ops remains denied every other application, retained, and archive relation.

Runtime write grants are exact:

| Relation | Privileges |
| --- | --- |
| `users` | INSERT |
| `user_profiles` | INSERT, UPDATE, DELETE |
| `food_items` | INSERT, UPDATE |
| `food_sources`, `food_nutrients`, `serving_definitions` | INSERT, UPDATE, DELETE |
| `daily_logs` | INSERT, UPDATE, DELETE |
| `daily_log_nutrient_snapshots` | INSERT, DELETE |
| `recipes` | INSERT, UPDATE |
| `recipe_ingredients` | INSERT, UPDATE, DELETE |
| three `recipe_publication_*` relations | INSERT only |
| `ocr_nutrition_confirmation_traces` | INSERT only |
| `nutrition_targets` | INSERT, UPDATE, DELETE |
| `food_favorites` | INSERT, DELETE |
| `create_operation_idempotency` | INSERT, UPDATE |

There are no application sequences or application read-only routines at 0017, so their manifest
sections are intentionally empty. No `GRANT ALL`, blanket present/future function grant, column
grant, or implicit schema-wide relation grant is used.

PostgreSQL's PUBLIC-executable large-object mutators are explicitly revoked in this database. The
policy verifies that those routines are unavailable to every managed role and that
`pg_largeobject_metadata` is empty. This closes durable-state mutation even if a canary or
qualifier changes its user-settable transaction-read-only default.

Owner default privileges are fail-closed. Table and sequence defaults are asserted for `public`,
maintenance, and every archive schema. PostgreSQL's hard-wired PUBLIC defaults for functions and
types can only be revoked globally (per-schema default rules can add but cannot subtract them), so
the owner receives one global PUBLIC EXECUTE/USAGE revocation for those object classes. Future
tables, sequences, routines, and types therefore receive no non-owner or `PUBLIC` privilege. A
future migration must update the versioned manifest and apply explicit object grants in the same
reviewed change. This avoids making an unknown new object automatically reachable.

## Provisioning and ownership transfer

The split model is deliberate:

- Alembic remains the only schema authority and keeps the existing migration history;
- the role tool is a separately reviewed PostgreSQL-16 bootstrap boundary; and
- once the database owner is `nutrition_owner`, Alembic calls `SET ROLE nutrition_owner` only when
  `session_user` is exactly `nutrition_migrator`; every other login is rejected. A sealed
  superuser/bootstrap path is accepted only while that session still owns the bootstrap database.

Provisioning requires an explicitly configured bootstrap-administrator URL and an exact database
name confirmation:

```text
export NUTRITION_DATABASE_URL=<bootstrap administrator URL for disposable database>
python scripts/manage_phase5c4_roles.py provision --confirm-database <exact database name> \
  --acknowledge-disposable
```

The transaction:

1. requires explicit disposable acknowledgement, exclusive database access, PostgreSQL 16, and
   the singleton Alembic revision 0017;
2. creates missing roles or verifies every attribute and role setting;
3. rejects unexpected membership edges and adds only missing expected edges;
4. discovers archives from catalog structure and verifies them against retained metadata;
5. rejects unknown schemas, relation kinds, standalone/composite types, routines, extensions,
   non-internal triggers, RLS/policies, owners, column/default ACLs, grant options, or grants;
6. transfers the enumerated database, schemas, relations, indexes/row types, and retained objects;
7. preserves extension-member ownership;
8. applies explicit owner, database, schema, relation, routine, and fail-closed default privileges;
9. creates the two bounded maintenance routines; and
10. commits only if the final canonical eligibility check passes.

An initial database must be wholly bootstrap-owned with PostgreSQL-default ACLs. A previously
provisioned database is classified before any role mutation and must already qualify in normal
state. Missing roles/grants, a maintenance-state database, or any other drift is rejected rather
than repaired. DDL is transactional, so a failed first pass rolls back the database-local
ownership and ACL changes as one unit. The command is restart-safe only from the exact initial
state or exact final normal state.

After external secret creation/rotation, process configuration is separated:

- Alembic: `NUTRITION_DATABASE_URL` authenticates as `nutrition_migrator`;
- normal backend: authenticates as `nutrition_runtime`;
- later read-only canary process: authenticates as `nutrition_canary`;
- independent qualification: authenticates as `nutrition_qualifier`; and
- maintenance close/restore: authenticates as `nutrition_ops`.

Do not supply the bootstrap administrator credential to the application, ordinary CLI, or Alembic
after provisioning. Run `alembic upgrade head` before starting the runtime process; the existing
application settings and API do not need a new configuration field.

For each process, verify `SELECT session_user, current_user`: Alembic must report
`nutrition_migrator,nutrition_owner` after its explicit role assumption, while backend connections
must report `nutrition_runtime,nutrition_runtime`. Revoke/seal the bootstrap secret only after this
readback and normal qualification succeed. Credentials must be distinct per login role.

## Eligibility evidence and reason codes

Read-only qualification is:

```text
export NUTRITION_DATABASE_URL=<qualifier URL>
python scripts/manage_phase5c4_roles.py qualify --expected-state normal
```

`phase5c4_source_role_eligibility_v1` is deterministic and contains no timestamp, connection URL,
password, authored data, or OCR payload. It binds the deployment, role policy, manifest digest,
safe database-name digest, expected normal/maintenance state, archive-name digests, sorted check
results, bounded reasons, decision, and self-digest. It is Stage 5C4.2a exercise evidence pending a
later artifact-admission contract.

Bounded failure reasons are:

- `postgresql_version_unsupported`, `alembic_revision_unsupported`;
- `ambient_authority_drift`, `extension_surface_drift`;
- `role_attribute_mismatch`, `role_setting_mismatch`, `membership_graph_mismatch`,
  `runtime_authority_escalation`;
- `unexpected_object`, `object_owner_mismatch`;
- `database_privilege_drift`, `schema_privilege_drift`, `relation_privilege_drift`,
  `column_privilege_drift`, `routine_privilege_drift`, `default_privilege_drift`;
- `runtime_archive_access`, `readonly_role_mutation_capability`, `security_definer_unsafe`; and
- `prepared_transactions_enabled`, `prepared_transactions_present`.

Qualification checks exact ACLs including grantability, managed-role grants on system and ambient
PostgreSQL object classes, effective durable-state read-only authority, exact transitive paths,
per-database role-setting overrides, object ownership/type/RLS/trigger/policy surface, exact
extensions, routine body/search path/owner/ACL, `max_prepared_transactions=0`, and empty prepared
transaction and large-object catalogs. A failing document is evidence only; it never repairs state.
Database-wide role settings are also prohibited, and the effective
`session_replication_role` must be `origin`.

## Maintenance rehearsal

The caller must first stop or isolate new backend work. Stage 5C4.2a does not implement readiness,
ingress maintenance, process switching, or the later write-fence table/trigger.

Close as operations:

```text
export NUTRITION_DATABASE_URL=<operations URL>
python scripts/manage_phase5c4_roles.py close-maintenance \
  --confirm-database <exact database name> \
  --quiet-period-seconds 2 --drain-timeout-seconds 30
```

The CLI first runs the complete canonical policy inspection. The owner-owned security-definer
routine independently validates `session_user=nutrition_ops`, a non-null exact manifest digest,
the singleton head/archive binding, prepared/replication state, and the exact relation/database/
routine/column ACL plus effective runtime write/connect surface that it changes, both before and
after the change. It rejects grant-option, direct, PUBLIC, and transitive runtime privilege drift.
It then revokes each enumerated runtime write privilege and runtime `CONNECT`. After that commits,
`nutrition_ops` repeatedly terminates runtime sessions until it observes zero for the bounded quiet
interval. Reconnect pressure resets that interval; deadline expiry leaves maintenance closed.
Database ACL/session state—not process memory—is authoritative.
Before closure and throughout the drain, the CLI also rejects any client session authenticated as
an identity other than runtime, canary, qualifier, or ops. A backend using the bootstrap,
migrator, or an unknown login therefore prevents a successful quiet result instead of escaping the
runtime-only termination filter.

Qualify maintenance separately through the qualifier credential:

```text
python scripts/manage_phase5c4_roles.py qualify --expected-state maintenance
```

The rehearsal must additionally prove runtime reconnect and DML denial, qualifier/canary read-only
availability, archive denial for runtime/canary, and unchanged domain state.

The executable rehearsal is the isolated PostgreSQL module below. It creates a random database,
migrates zero-to-head, binds a custom archive, provisions twice, uses distinct role credentials,
runs runtime service/API reads and writes plus negative probes, simulates a crash after ACL closure,
resumes the quiet drain, proves reconnect/write denial and qualifier/canary availability, restores,
runs a post-restore write, exercises Alembic check/downgrade/re-upgrade, drops the database/roles,
and fails rather than sharing pre-existing managed roles:

```text
export NUTRITION_TEST_POSTGRES_URL=<isolated PostgreSQL 16 bootstrap URL>
cd apps/backend
.venv/bin/pytest -q -rs tests/test_phase5c4_roles_postgres.py
```

Success is four passing tests with no skips. A skip means the required isolated PostgreSQL 16
administrator environment was not supplied and is not qualification evidence.

Restore as operations only after the catalog-only maintenance precheck passes:

```text
export NUTRITION_DATABASE_URL=<operations URL>
python scripts/manage_phase5c4_roles.py restore --confirm-database <exact database name>
```

Restoration requires zero runtime sessions and refuses any unexpected grant, owner, object,
membership, routine, schema, prepared transaction, or state. The second owner-owned routine
revalidates exact state and restores only enumerated runtime writes plus runtime `CONNECT`. A
repeated restore after a lost response classifies exact normal state and returns idempotent success;
it never restores from a captured live ACL or broadens from observed state.

Both routines are `SECURITY DEFINER`, owned by `nutrition_owner`, use the exact fixed
`search_path=pg_catalog, pg_temp`, schema-qualify every referenced application object, call catalog
helpers through `pg_catalog`, reject unauthorized callers and wrong digests, and are executable
only by `nutrition_ops`. They return one bounded status string and no row content.

## Failure and recovery behavior

- Provision failure: the transaction rolls back. Correct the rejected unknown state; do not run a
  broad grant repair or `REASSIGN OWNED`.
- Close failure before commit: normal grants remain. Re-inspect through the bootstrap/qualifier
  path before retrying the same exact command.
- Close success with incomplete session drain: keep maintenance and runtime `CONNECT`/writes
  revoked, then rerun the same `close-maintenance` command. It classifies exact maintenance and
  resumes the bounded quiet drain without replaying the ACL transition.
- Crash after close: actual ACLs and sessions reveal maintenance state. Rerun close to finish the
  drain, then obtain qualifier maintenance evidence; do not infer state from process memory.
- Restore rejection: remain in maintenance, remove the unexpected drift through separately
  reviewed operator action, requalify, then retry exact restore.
- Restore success: reconnect the normal runtime process, run ordinary read/write probes, and obtain
  a new normal-state eligibility document.

This portfolio profile has one human operator and requires a dedicated data-plane PostgreSQL
cluster (or equivalent HBA/database CONNECT isolation). PostgreSQL roles are cluster-global, while
this contract qualifies the named application database; without that deployment boundary the
managed credentials may inherit PUBLIC CONNECT to unrelated databases. Concurrent exercises must
therefore use isolated clusters or serialize role creation/password assignment. This is not a
public multi-tenant role design and does not claim row isolation for direct SQL
canary/qualifier access; server-side ownership enforcement continues to be the application/API
boundary.

`--acknowledge-disposable` is a single-operator attestation reinforced by exact head, bootstrap
ownership/ACL checks, and exclusive access; 2a has no database-incarnation marker and therefore
cannot cryptographically prove clone/disposable lineage. Incarnation admission remains separately
gated with 5C4.2b rather than being approximated here.

Alembic revision 0017 remains the column/constraint/index-definition authority. This 2a checker
independently pins object names and kinds, the four 0017 subject-lookup index requirements through
migration rehearsal, ownership, triggers/RLS/policies, extensions, and all privilege surfaces; it
does not duplicate the complete 0017 column/constraint/index signature inside the role manifest.
That assumption must be reviewed if qualification is ever run without the clean Alembic
zero-to-head/check rehearsal required by this stage.
