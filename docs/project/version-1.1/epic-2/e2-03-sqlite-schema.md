# E2-03 — Native SQLite schema and migration stream

The mobile local runtime owns an independent SQLite stream. It uses the Expo
SQLite native driver and starts at schema version `1`; PostgreSQL Alembic
history is not replayed. `nutrition_schema_migrations` records each applied
version and SQLite `PRAGMA user_version` is the version gate.

The baseline creates the eighteen semantic application tables listed by
`SQLITE_SEMANTIC_TABLES`. Phase 5, control-plane, role, promotion, historical
bridge, OCR parser-history, and other migration-owned operational tables are
not part of this database. The nutrient catalog is seeded from the frozen
sixteen-row catalog in the baseline migration.

E2-02 storage mappings are applied at the column boundary: nutrition decimals
are `TEXT` fixed-scale strings, UUIDs, instants, dates, IANA zones, and JSON
documents are canonical `TEXT`, and booleans are checked SQLite integers
(`0`/`1`). Feature adapters remain out of scope for E2-03 and must use the
shared exact codecs before binding values.

Every connection enables foreign keys, a bounded busy timeout, WAL journaling,
and normal synchronous durability before migration. Composite owner keys,
deferred Recipe/publication relationships, the active-source partial unique
index, and the immutable revision/provenance triggers are installed in the
baseline. A transaction-local owner/log scope table is used by the internal
snapshot-replacement helper; it records the prior snapshot count and the
replacement header touch, then checks the final snapshot state so an
incomplete delete/recreate aborts. Snapshot UPDATEs require a real FK
provenance change and preserve only the existing nullable cleanup exception.
It does not disable guards globally and is removed before that transaction
commits.

Migrations execute atomically and forward-only. A failed migration rolls back
its DDL, seeds, ledger row, and version update; startup rejects a future
`user_version` and never deletes or resets the database. The local lifecycle is
opt-in: remote runtime startup does not import, open, or migrate SQLite.
