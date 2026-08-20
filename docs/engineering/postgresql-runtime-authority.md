# PostgreSQL runtime-authority evolution

> **Document role: Current Guide.** This page governs forward changes to the
> preserved FastAPI/PostgreSQL runtime authority. PostgreSQL 16 is the physical
> qualification authority.

## Rule

A new ORM/runtime relation is incomplete until its schema, role authority,
write-state behavior, and PostgreSQL qualification agree.

Historical Phase 5C contracts are revision evidence. Do not expand an old
migration, manifest, or validator to make it describe a later application
head. Add a forward migration and update an explicitly revision-scoped current
runtime-authority contract.

For every new mutable runtime relation, record and review:

1. Exact owner (normally `nutrition_owner`).
2. Runtime `SELECT` decision.
3. Exact runtime mutations; do not infer these from ORM code.
4. Explicit denials from `UPDATE`, `TRUNCATE`, `REFERENCES`, and `TRIGGER` where
   those privileges are not required.
5. Qualifier `SELECT` decision.
6. Canary `SELECT` decision, justified by an already-admitted canary route.
7. Canonical write-fence trigger coverage.
8. Closed-state revocation and sanctioned open-state restoration.
9. A forward Alembic migration preserving one application head.
10. A physical PostgreSQL 16 test proving the exact effective privileges,
    owner, close/open behavior, application operation, and negative cases.

Use relation-specific grants. Do not use `ALTER DEFAULT PRIVILEGES`, `GRANT
ALL`, grants on all tables, ownership changes, superuser bypasses, or trigger
disabling to add runtime authority.

## Mechanical guardrail

The current contract must explicitly classify every table in SQLAlchemy
`Base.metadata`. An executable test compares those sets so a future live ORM
relation cannot be entirely absent from role policy.

That test detects missing classification only. Exact read/write, qualifier,
canary, and write-fence decisions remain reviewed contract data.

Migration-owned/control-plane relations remain governed by the existing schema-authority boundary and are excluded from the ORM runtime-relation equality check explicitly, not implicitly.

A Python manifest or unit test is not sufficient physical qualification; current runtime-authority changes must be exercised against a disposable PostgreSQL 16 database through the repository-supported migration path.

## Daily Log Complete example

Revision `0033_complete_runtime_authority` classifies
`daily_log_day_completions` with:

- runtime: `SELECT`, `INSERT`, `DELETE`;
- qualifier: `SELECT` only;
- canary: `SELECT` only, because `/api/v1/logs/daily-summary` reads completion
  state;
- canonical Phase 5C gate and ACL close/open integration; and
- no `UPDATE`, `TRUNCATE`, `REFERENCES`, or `TRIGGER` authority.
