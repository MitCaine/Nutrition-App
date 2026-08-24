# PostgreSQL-to-SQLite personal transfer

> **Document role: Operational Reference.** This guide describes the currently
> supported one-time personal-data transfer from the preserved remote
> PostgreSQL authority into the local SQLite authority. It is not a
> synchronization, replication, merge, backup, or generic migration API.

## Current contract

The executable transfer boundary is the checked-in
`packages/shared-contracts/e2-15/transfer-contract.json`.

The current contract is:

- contract: `e2-15.v4`;
- package format: `nutrition-personal-transfer`, format version `4`;
- source database: PostgreSQL 16;
- source application head: `0033_complete_runtime_authority`;
- source schema contract: `e2-15.pg-0033.v3`;
- target SQLite schema version: `7`; and
- maximum package size: 64 MiB.

The target schema includes migrations
`001_initial_runtime_schema` through `007_daily_log_complete_state` as listed
by the machine-readable contract.

Historical E2-15 contract and representative-package versions remain checked in
for compatibility qualification. Do not silently reinterpret an older version
as the current contract.

## Authority boundary

The transfer moves one explicitly selected owner's supported application data
from the preserved remote authority into the local authority.

It does not:

- synchronize PostgreSQL and SQLite;
- keep either authority updated after transfer;
- transfer control-plane or Phase 5C operational state;
- create a dual-write or fallback path;
- replay PostgreSQL Alembic migrations into SQLite; or
- create a general-purpose import/export framework.

The detailed original architecture decision is preserved in the
[historical E2-15 architecture record](../historical/programs/version-1.1/epic-2/e2-15-transfer-architecture.md).
That record is point-in-time design provenance. The current executable contract
and current implementation own present compatibility.

## Export preconditions

The exporter is
`apps/backend/scripts/export_personal_transfer.py`.

Before export:

1. the source must be PostgreSQL 16 at the exact schema accepted by the current
   E2-15 contract;
2. the owner must be supplied explicitly by canonical owner UUID;
3. application writes must be frozen for the point-in-time cutover;
4. the operator must explicitly pass `--acknowledge-frozen-writes`; and
5. the destination path must not already contain an output artifact.

The exporter itself opens a `SERIALIZABLE READ ONLY DEFERRABLE` PostgreSQL
transaction, qualifies the source schema and source data, builds the canonical
package, rolls the read transaction back, and publishes the completed transfer
file without overwriting an existing destination.

## Export command

From `apps/backend` with the repository Python environment active:

```bash
NUTRITION_DATABASE_URL='postgresql+psycopg://...' \
  .venv/bin/python scripts/export_personal_transfer.py \
  --owner-id '00000000-0000-4000-8000-000000000001' \
  --output '/absolute/path/personal-transfer.json' \
  --acknowledge-frozen-writes
```

Replace the database URL, owner UUID, and output path with the qualified source
values. Do not commit the generated personal-data package to the repository.

Successful output reports the byte count, format version, overall digest,
schema contract, section counts, and `status: complete`.

## Local import boundary

The mobile import implementation lives under
`apps/mobile/src/transfer/e2_15/`. Package validation, local-start gating, and
the importer consume the versioned shared contracts rather than trusting
arbitrary JSON.

Import remains a one-time local-authority bootstrap/cutover operation. Do not
bypass the E2-15 validator or manually insert transfer rows into SQLite.

The current importer also retains explicit compatibility handling for older
versioned E2-15 packages. Those older fixtures are compatibility evidence, not
the current export format.

## Qualification

Current transfer coverage includes:

- backend package, source-schema, exporter, CLI, and current-source-projection
  tests;
- physical PostgreSQL exporter qualification where the PostgreSQL test
  environment is explicitly enabled;
- mobile package, validator, importer, local-start, and PostgreSQL-transfer E2E
  coverage; and
- versioned fixtures under `packages/shared-contracts/e2-15/`.

See the [Testing Guide](testing.md) for the current test-selection and
environment requirements.

Any schema or semantic change that affects this boundary must update the
implementation and create or deliberately revise the applicable versioned
transfer artifacts. Never edit historical E2-15 architecture prose to pretend
a later source head existed when that record was approved.
