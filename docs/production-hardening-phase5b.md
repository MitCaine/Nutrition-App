# Production Hardening Phase 5B: historical database inventory

## Purpose

The historical database inventory is an offline operator command for determining which migration,
legacy Recipe, current publication, projection, Daily Log, OCR, idempotency, and retention states
exist before future conversion work is designed. It is not exposed through the API and does not
change runtime application behavior.

The command reports aggregate counts and consistency classifications only. It never emits emails,
display names, Recipe or Food names, notes, OCR text, image paths, request payloads, response
snapshots, authentication values, row identifiers, or database URLs.

## Running the inventory

Run from `apps/backend` with the canonical database setting explicitly present in the command
environment:

```bash
NUTRITION_DATABASE_URL='<explicit-sqlalchemy-database-url>' \
  .venv/bin/python -m scripts.inventory_historical_database --format human
```

Supported formats are:

- `human`: a sectioned operator summary.
- `json`: the stable `historical_database_inventory_v1` machine-readable contract intended for
  comparison and consumption by the separately reviewed Phase 5C planner and verifier tooling.

`historical_database_inventory_v1` is now the official machine admission contract for historical
inventory, planning, conversion, verification, and future repair tooling. Consumers must reject a
major version they do not explicitly support. Changes to classification meaning, required fields,
or safety decisions require a new major contract. Additive, non-decision metadata is permitted only
inside a documented extension namespace. Unknown classifications and decision-affecting fields
must fail closed. Phase 5C hashes the canonical complete v1 report; changing any report evidence
therefore requires a new plan.

On PostgreSQL, inspection uses one repeatable-read transaction, marks it `READ ONLY`, performs only
schema inspection and aggregate queries, and rolls the transaction back. It does not acquire write
locks, update timestamps, invoke Alembic, or alter Alembic revision state. Configuration and
connection errors are reported without echoing the configured URL.

## Report scope

The report includes:

- Alembic revision and migration 0004 admission state;
- legacy Recipe and Recipe Ingredient table presence and row counts;
- current Recipe, draft/publication, compatibility projection, and authored ingredient counts;
- immutable revision, amount-definition snapshot, nutrient snapshot, and orphan counts;
- mutable Food, immutable Recipe-revision, and unknown-authority Daily Log counts;
- OCR confirmation trace and legacy OCR table counts, plus only whether raw payload rows exist;
- create-operation and Daily Log request-identity counts;
- aggregate retention counts; and
- missing, mismatched, orphaned, inactive, and unexpected-ownership relationships.

The current immutable publication schema contains amount-definition and nutrient snapshots but no
revision-ingredient table. Accordingly, the v1 report marks revision-ingredient table presence as
false and its counts as `null`; it does not misrepresent an unavailable concept as zero.

## Classifications

- `empty_database`: no application or historical rows were detected in the inspected scope.
- `clean_current_database`: the database is at the expected current head and no covered historical
  consistency anomaly was detected.
- `legacy_conversion_required`: migration 0004 is pending and populated legacy Recipe tables make
  the Phase 5A admission guard block the upgrade.
- `historical_repair_required`: the current system contains a covered missing, mismatched, orphaned,
  inactive, or unexpected-ownership relationship.
- `mixed_legacy_current_state`: legacy and current Recipe schemas coexist.
- `inventory_inconclusive`: the Alembic revision or schema contract is missing, unknown, ambiguous,
  or otherwise cannot be classified with certainty.

Each report includes one stable reason code explaining the selected classification. A count or
classification is observation, not permission to modify data.

## No repair or conversion

Phase 5B deliberately contains no repair, conversion, deletion, rewriting, anonymization, migration,
or historical inference. Correct conversion requires separately proven mappings and belongs to a
later phase. When this inventory cannot establish a state with certainty, it reports
`inventory_inconclusive` instead of guessing.

The [Phase 5C1 bridge and planner](production-hardening-phase5c1.md) consume this contract but still
perform no semantic historical conversion.
