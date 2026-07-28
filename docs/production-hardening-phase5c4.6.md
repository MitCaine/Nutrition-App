# Phase 5C4.6: target-activation authorization admission

Phase 5C4.6 admits one purpose-specific, short-lived Ed25519 authorization into the independent
control database. It does not activate a target and it does not consume the authorization.
Application schema revision `0020_immutable_provenance_enforcement` and all application runtime
privileges remain unchanged.

## Authority boundary

The executable contract is
`phase5c4_target_activation_authorization_v2`. The detached signature covers this exact message:

```text
ASCII("nutrition-app/phase5c4/authorization/v1") || NUL ||
uint64_be(length(canonical_statement_bytes)) || canonical_statement_bytes
```

The canonical statement contains the pinned algorithm, contract version, public-key ID, exact
activation payload, and payload digest. JSON must already be in the repository canonical form and
must use the contract's ASCII-only strings, integer profile, exact UUID/digest/base64url forms, and
six-microsecond UTC timestamps. The CLI never canonicalizes a noncanonical input into acceptance.

The signing key remains outside the repository, CLI, application database, and control database.
Only canonical DER Ed25519 public keys are admitted. The key ID is the lowercase SHA-256 digest of
the exact SubjectPublicKeyInfo DER bytes.

Control revision `ops_0008_phase5c4_authorization` replaces the three empty authorization
placeholders with immutable:

- public-key trust and key-revocation records;
- authorization-specific revocations, including revocation before admission;
- admitted target-activation authorizations and durable changed-input conflicts;
- an intentionally empty future consumption table.

The migration first counts all three old placeholder tables and aborts transactionally if any is
nonempty. It never translates or deletes legacy rows.

## Role and migration sequence

The verifier login is an external bootstrap responsibility because the control migrator has no
`CREATEROLE` authority. Use this order:

1. Qualify control revision `ops_0007_recovery_validation`.
2. As the PostgreSQL bootstrap superuser, run
   `manage_phase5c4_control_roles.py provision-authorization-verifier`.
3. Run the control Alembic upgrade as `nutrition_control_migrator`.
4. Run `qualify-authorization-verifier` and
   `phase5c4_api.qualify_control_plane_v6()` through the audit identity.
5. Bootstrap or rotate public keys only through the migrator-only append API.

`nutrition_control_authorization_verifier` has `CONNECT`, `USAGE` on `phase5c4_api`, and execute
authority on exactly:

- `phase5c4_api.read_authorization_key_v1(text)`;
- `phase5c4_api.admit_target_activation_authorization_v2(bytea)`.

It has no base-table access, memberships, owner assumption, trust mutation, revocation,
qualification, workflow transition, target, application-database, or consumption authority.
The v6 catalog manifest records the final functions, tables, constraints, indexes, triggers,
roles, database ACL, schema ACL, and grants.

## Operator CLI

`scripts/manage_phase5c4_authorization.py` provides:

- `export`: validate a canonical payload and write the canonical statement and framed message;
- `assemble`: combine the statement with one raw 64-byte detached signature;
- `verify`: retrieve the trusted public key and perform real Ed25519 verification;
- `admit`: verify and submit the exact canonical envelope;
- migrator-only public-key bootstrap/rotation and revocation append operations.

Output files are exclusive, regular, bounded, mode `0600`, and never overwritten. The CLI has no
sign command and accepts no private key, seed, PEM private material, or caller-supplied verification
key. JSON output contains only safe IDs, digests, results, and stable reason codes.

Admission runs in a fresh serializable transaction, uses control-database time, locks the trusted
key row, and acquires sorted advisory locks for authorization ID, nonce, and activation command ID.
Serialization failures and deadlocks receive bounded fresh-transaction retries. Exact committed
replay is idempotent. Changed authorization-ID, nonce, or activation-command input commits an
immutable conflict and returns `authorization_conflict`.

## Rollback and the 5C4.7 boundary

An empty ops-0008 schema can downgrade exactly to ops-0007; the bootstrap superuser must then remove
the verifier role before v5 qualification. Downgrade refuses once any key, revocation,
authorization, conflict, or consumption row exists. Operational recovery after use is restore or
forward correction, never deletion of authority history.

Every authorization admitted by this stage remains unused. Phase 5C4.6 provides no consumption
routine, workflow transition, production-open authority, target grant, route mutation, provider
orchestration, cutback, or emergency-close behavior. Phase 5C4.7a separately defines preactivation
promotion and closed-target evidence binding.
[Phase 5C4.7b](production-hardening-phase5c4.7b.md) separately defines target-activation consumption
and the `TARGET_ACTIVATION_REQUESTED` execution-schema boundary; it does not retroactively broaden
Phase 5C4.6 authority.
