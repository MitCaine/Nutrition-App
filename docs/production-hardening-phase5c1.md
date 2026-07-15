# Production Hardening Phase 5C1: historical bridge and conversion planning

## Purpose and boundary

Phase 5C1 preserves populated pre-0004 Recipe tables on an operator-created PostgreSQL conversion
clone and produces a deterministic answer to “what exactly would be converted?” It performs no
Recipe conversion. It does not create current Recipes, publication revisions, projections, Daily
Log links, OCR records, execution checkpoints, quarantine records, or execution receipts.

The bridge and planner are offline operator commands. They are not imported by API routers and
must never run against a database serving application traffic. A command-line confirmation is not
sufficient admission evidence: destructive bridging requires a pre-existing clone marker created
by a separate, non-destructive preflight.

## Supported source admission

Marker preflight and bridging admit only a source that proves all of the following:

- Alembic revision is exactly `0003_usda_source_identity`;
- a current `historical_database_inventory_v1` document exactly matches the locked clone;
- inventory classification is `legacy_conversion_required` with no limitations;
- the legacy Recipe structure matches `legacy_recipe_pre0004_v1`, including exact columns,
  primary keys, unique constraints, foreign keys, nullability, and defaults;
- required supporting Food, serving, nutrient, source, and owner columns exist; and
- current Recipe-domain tables or columns are not active.

Similar-looking, manually stamped, partially migrated, or unknown schemas are rejected. The bridge
does not broaden admission through heuristic matching.

## Clone identity and session isolation

The operator first captures the source-production safe identity. Its versioned document contains
only driver family, host, port, database name, schema, and a canonical digest. It never contains a
username, password, full URL, or query values. The clone attestation records the distinct clone
identity digest, the source-production identity digest, inventory and schema evidence, conversion
rules version, a bounded non-secret operator attestation identifier, scope, and digest. If the safe
source and clone identities are equal, Phase 5C refuses to proceed; an operator must use a clone
whose distinct identity is provable.

The marker preflight verifies the exact unbridged 0003 state and then creates only
`phase5c_conversion_clone_marker`. It does not move a table, alter a domain row, change the Alembic
revision, or create conversion output. Bridge and planner invocations revalidate the marker,
attestation, current clone identity, source/clone distinction, inventory evidence, schema
signature, versions, and command scope on every run, including restarts.

For database-level isolation, each admitted Phase 5C process holds a marker-derived shared
PostgreSQL advisory lock for its entire operation. Before taking the normal Phase 5C operation lock,
and again immediately after acquiring it, the command inspects `pg_stat_activity` and `pg_locks`.
Every other client session connected to the clone database must hold that exact shared maintenance
lock. The mechanism does not trust `application_name`, SQL text, database usernames, network
addresses, or operator assertions. General application, migration, psql, and inspection sessions
are therefore rejected. The ordinary Phase 5C operation lock still serializes bridge/planner work;
the maintenance lock is an admission credential for known Phase 5C sessions, not a permanent
application lock-hierarchy rule.

This check complements, but cannot create, infrastructure isolation. The operator remains
responsible for snapshot/cutover correctness, disabling application access, provisioning a
disposable clone database, and preventing reconnects. Run these commands with no unrelated
connections to that database.

## Operator sequence

Capture the safe identity from the actual source before operating on its clone:

```bash
cd apps/backend
NUTRITION_DATABASE_URL='<source-production-url>' \
  .venv/bin/python -m scripts.capture_phase5c_database_identity \
  > phase5c-source-identity.json
```

Provision an offline PostgreSQL clone under a different database identity. With no application or
operator sessions connected, create the Phase 5B inventory while it is still at migration 0003:

```bash
NUTRITION_DATABASE_URL='<conversion-clone-url>' \
  .venv/bin/python -m scripts.inventory_historical_database --format json \
  > phase5b-inventory.json
```

Create deterministic operator attestation evidence against that clone, then establish the marker
in a separate non-destructive preflight:

```bash
NUTRITION_DATABASE_URL='<conversion-clone-url>' \
  .venv/bin/python -m scripts.create_phase5c_operator_attestation \
  --inventory phase5b-inventory.json \
  --source-production-identity phase5c-source-identity.json \
  --operator-attestation-id '<non-secret-operator-or-change-id>' \
  --scope bridge_and_planning \
  --clone-marker-id '<non-secret-marker-id>' \
  --conversion-clone-id '<non-secret-clone-id>' \
  > phase5c-operator-attestation.json

NUTRITION_DATABASE_URL='<conversion-clone-url>' \
  .venv/bin/python -m scripts.establish_phase5c_clone_marker \
  --inventory phase5b-inventory.json \
  --attestation phase5c-operator-attestation.json \
  --clone-marker-id '<non-secret-marker-id>' \
  --conversion-clone-id '<non-secret-clone-id>'
```

Only after marker preflight succeeds may the destructive bridge run:

```bash
NUTRITION_DATABASE_URL='<conversion-clone-url>' \
  .venv/bin/python -m scripts.bridge_historical_recipes \
  --inventory phase5b-inventory.json \
  --attestation phase5c-operator-attestation.json \
  --clone-marker-id '<non-secret-marker-id>' \
  --conversion-clone-id '<non-secret-clone-id>' \
  --format human
```

After the bridge succeeds, run normal Alembic migrations and then the planner with the same exact
evidence:

```bash
NUTRITION_DATABASE_URL='<conversion-clone-url>' alembic upgrade head

NUTRITION_DATABASE_URL='<conversion-clone-url>' \
  .venv/bin/python -m scripts.plan_historical_recipe_conversion \
  --inventory phase5b-inventory.json \
  --attestation phase5c-operator-attestation.json \
  --clone-marker-id '<non-secret-marker-id>' \
  --conversion-clone-id '<non-secret-clone-id>' \
  --format json \
  > phase5c-conversion-plan.json
```

Use `--archive-schema` consistently when the default `nutrition_phase5c_archive` is unsuitable.
The three identifiers above are audit labels, not secrets. Do not put credentials in identity,
inventory, attestation, marker, bridge, or plan artifacts.

## Bridge and archive behavior

Within one serializable PostgreSQL transaction, the bridge acquires access-exclusive locks on the
two legacy tables, repeats admission checks, computes source checksums, and moves `recipes` and
`recipe_ingredients` into the archive schema. Moving the tables preserves rows, identifiers,
constraints, and foreign keys. Empty, structurally equivalent placeholders let unchanged migration
0004 follow its normal empty-table path.

The archive's single `bridge_metadata` row binds archive identity to safe database components,
source/archive schemas, source revision, inventory and schema contracts, checksums, conversion
rules, clone marker, source/clone identity digests, isolation-evidence contract, and operator
attestation. The bounded, explicitly non-secret marker and attestation identifiers are persisted;
the raw conversion-clone label is reduced to a digest. Credentials, URL query values, execution
timestamps, and execution history are excluded.

The planning-source checksum covers every legacy Recipe and ingredient plus all owners, Food rows,
servings, nutrients, and Food source rows that can influence classification. Any change to covered
source evidence causes planning to fail. A restart succeeds only when the full marker, attestation,
archive metadata, structure, checksums, and current migration state still match.

## Planner and manifest

The planner runs only at `0015_phase5c_conversion_control`. It verifies the original inventory,
bridge/archive evidence, source checksum, unchanged marker and attestation, session isolation, and
absence of current Recipe or immutable revision rows. It classifies every archived Recipe exactly
once as `convert`, `quarantine`, or `block` under the unchanged Phase 5C1 rules.

The canonical `phase5c_conversion_plan_v2` JSON adds the complete versioned isolation-evidence
binding to the v1 planning contract: marker format and digest, distinct source/clone database
identity digests, conversion-clone digest, operator attestation identity/scope/version/digest, and
the isolation contract version. It retains deterministic ordering, source checksums, dispositions,
and a digest over the complete preceding manifest. No execution timestamp or user-authored content
appears. Repeating an identical plan is a no-op; different evidence for the archive is rejected.

## Migration and deferred work

The uncommitted migration `0015_phase5c_conversion_control` creates only the metadata table needed
to bind future execution to the immutable v2 plan and its isolation evidence. It does not inspect
the archive or modify domain data. Migration 0004 and its Phase 5A admission guard remain unchanged.

Actual Recipe conversion, immutable revision creation, compatibility projection changes,
checkpointed execution, quarantine persistence, execution receipts, post-conversion verification,
Daily Log enrichment, and OCR changes remain deferred to Phase 5C2 or later bounded phases.
