# Phase 5C4.7b: target-activation execution

> **Document role: Operational Reference.**

Phase 5C4.7b introduces the separately authorized boundary from a qualified,
closed schema-0020 target to schema 0021 and controlled runtime-write
activation. It consumes Phase 5C4.7a evidence without modifying it. Promotion
Authorization still authorizes route switching only, and the existing
schema-0020 Target Activation Authorization still authorizes activation only;
neither authorizes application migration 0021.

## Authority and schema boundary

The executable schema authority is
`phase5c4_execution_schema_authorization_v1`. Its detached Ed25519 signature
covers:

```text
ASCII("nutrition-app/phase5c4/execution-schema-authorization/v1") || NUL ||
uint64_be(length(canonical_statement_bytes)) || canonical_statement_bytes
```

The authorization binds the exact environment, attempt, source, target,
deployment, Phase 5C4.7a preactivation chain, admitted Target Activation
Authorization, recovery and provenance evidence, manifests, runtime
identities, fence requirements, current schema
`0020_immutable_provenance_enforcement`, intended schema
`0021_target_activation_execution`, migration identity and digest, activation
and emergency-close policies, signer, nonce, and validity interval. Canonical
bytes and digests are reconstructed independently; caller-projected values do
not replace authoritative control rows.

The current active application migration head is `0029_expand_nutrient_catalog`; the
target-activation procedure remains pinned to its approved `0021_target_activation_execution`
boundary.

Control revision `ops_0010_phase5c4_activation` installs the immutable
execution trust, authorization, migration, activation, emergency-close,
conflict, observation, and final-evidence records. Control qualification v8
checks the exact catalog and privilege manifest. The application migration is
`0021_target_activation_execution`; it changes no nutrition-domain row and is
PostgreSQL-only and forward-only.

## Roles and privilege boundary

`nutrition_control_execution_authorization_verifier` may read one execution
public key and admit one execution authorization. It cannot migrate, consume
authority, activate, close, reconcile, or read base tables. Public-key
bootstrap, rotation, and revocation remain migrator-only operations.

`nutrition_control_emergency_closer` may request and finalize emergency close
through its two fixed-purpose control functions. It has no activation,
migration, verifier, collector, audit, or base-table authority. Admission of
migration, activation, and emergency-close observations uses the existing
collector boundary. Normal control execution uses `nutrition_control_executor`.

On the application database, `nutrition_ops` alone may invoke the
schema-0021 `open_runtime_writes_v1` and
`emergency_close_runtime_writes_v1` maintenance routines. Those routines
grant or revoke only the established production runtime-write policy; they do
not grant migration, ownership, control-plane, verifier, recovery, or operator
authority to `nutrition_runtime`.

## Execution sequence

Use this order:

1. Qualify the Phase 5C4.7a control database and complete its authoritative
   activation-evidence binding while schema 0020 remains installed, the route
   resolves to the target, the source is frozen, and the target is
   maintenance-closed.
2. Provision the execution-verifier and emergency-closer roles, upgrade the
   control database to `ops_0010_phase5c4_activation`, then qualify both roles
   and control qualification v8.
3. Bootstrap or rotate only public Ed25519 key material through the control
   migrator. Export the canonical statement and framed message, sign outside
   Nutrition App, assemble the raw detached signature, verify, and admit the
   execution authorization.
4. Request schema migration. This stores a durable migration intent before any
   application-database operation; it does not consume the Target Activation
   Authorization.
5. Run application migration `0021_target_activation_execution` against the
   closed and drained target with the exact admitted authority and migration
   bindings. The migration installs the application emergency-close routine;
   it must qualify before any target-opening operation is requested.
6. Collect and record an authoritative schema-migration observation. Only an
   `installed` observation for the exact schema, migration, target, deployment,
   role manifest, runtime privileges, closed fence, and absent runtime-write
   admission satisfies the activation precondition.
7. Request target activation once. The serializable control transaction
   validates the complete chain, consumes the schema-0020 Target Activation
   Authorization once, stores the durable target-open intent, and advances to
   `TARGET_ACTIVATION_REQUESTED`.
8. Outside the control transaction, execute the exact target-open command
   against the application database. A command return is not proof that writes
   are open.
9. The target-local command immediately inspects the application database and
   writes a canonical runtime observation. Admit it through the separate
   control collector, then reconcile it against authoritative control rows.
   Only the exact schema-0021 target and deployment, expected runtime
   identities, admitted runtime writes, frozen source, target route, and
   absence of conflicting emergency close may advance to `TARGET_ACTIVE`.
10. Inspect the immutable final activation evidence. Do not infer completion
    from an external command result or from workflow state alone.

All control transition requests use explicit canonical UUIDs and the current
environment generation, environment state version, attempt identifier, and
attempt state version. Refresh status after every committed transition rather
than reusing a stale compare-and-swap value.

## Target-local command boundary

`manage_phase5c4_target_activation.py` reconstructs every target-local action
from its durable control-plane intent. It does not accept caller-supplied
authority, identity, manifest, or evidence digests. Use separate audit,
migration, and operations URLs:

```bash
NUTRITION_PHASE5C4_CONTROL_AUDIT_DATABASE_URL='<control audit URL>' \
NUTRITION_PHASE5C4_TARGET_MIGRATION_DATABASE_URL='<target migrator URL>' \
NUTRITION_PHASE5C4_TARGET_OPS_DATABASE_URL='<target nutrition_ops URL>' \
NUTRITION_PHASE5C4_TARGET_QUALIFIER_DATABASE_URL='<target qualifier URL>' \
  python scripts/manage_phase5c4_target_activation.py migrate-target \
  --action-id '<schema-migration action UUID>' \
  --observation-out schema-migration-observation.json

NUTRITION_PHASE5C4_TARGET_OPS_DATABASE_URL='<target nutrition_ops URL>' \
  python scripts/manage_phase5c4_target_activation.py inspect-target \
  --output target-state.json

NUTRITION_PHASE5C4_CONTROL_AUDIT_DATABASE_URL='<control audit URL>' \
NUTRITION_PHASE5C4_TARGET_OPS_DATABASE_URL='<target nutrition_ops URL>' \
  python scripts/manage_phase5c4_target_activation.py open-target \
  --action-id '<target-open action UUID>' \
  --observation-out activation-runtime-observation.json

NUTRITION_PHASE5C4_CONTROL_AUDIT_DATABASE_URL='<control audit URL>' \
NUTRITION_PHASE5C4_TARGET_OPS_DATABASE_URL='<target nutrition_ops URL>' \
  python scripts/manage_phase5c4_target_activation.py emergency-close-target \
  --action-id '<emergency-close action UUID>' \
  --observation-out emergency-close-observation.json
```

Observation files are exclusive, bounded, mode `0600`, and never overwritten.
Creating a file does not admit its contents into the control plane; record it
through the matching collector command and reconcile through the matching
fixed-purpose transition. A successful target-local command means the local
routine completed, the target was inspected, and the observation file was
written; it does not mean control reconciliation completed. If the command
fails after an external action may have occurred, retain the same action ID,
inspect the target, and reconcile that durable action rather than creating a
new authority or command.

Each committed target-local mutation records the fixed
`target_local_postgresql_v1` mechanism, attempt count `1`, database timestamp,
canonical request digest, fence event digest, and immutable result document.
Retries use new transactions around the same command identity; exact committed
replay returns that stored row and changed-input reuse conflicts.

Internally, application migration 0021 receives all of these exact bindings in
addition to the target migrator URL:

```text
NUTRITION_PHASE5C4_EXECUTION_AUTHORIZATION_ID
NUTRITION_PHASE5C4_EXECUTION_AUTHORIZATION_DIGEST
NUTRITION_PHASE5C4_SCHEMA_MIGRATION_COMMAND_ID
NUTRITION_PHASE5C4_SCHEMA_MIGRATION_ACTION_ID
NUTRITION_PHASE5C4_ENVIRONMENT_ID
NUTRITION_PHASE5C4_ATTEMPT_ID
NUTRITION_PHASE5C4_TARGET_DATABASE_INSTANCE_ID
NUTRITION_PHASE5C4_TARGET_IDENTITY_DIGEST
NUTRITION_PHASE5C4_DEPLOYMENT_DESCRIPTOR_DIGEST
```

The migration acquires the established application migration advisory lock,
requires exactly one schema-0020 target in `closed_cutover`, rejects active
`nutrition_runtime` sessions, requalifies the schema-0020 maintenance role
policy, and records the exact binding in immutable
`phase5c_activation_schema_evidence`. It leaves runtime writes closed. A
pre-commit failure leaves schema 0020 in place and consumes no Target
Activation Authorization. Once installed, application downgrade is refused;
recover by restore or forward correction.

## State and reconciliation semantics

The normal activation path is:

```text
POST_CUTOVER_VERIFIED
→ TARGET_ACTIVATION_REQUESTED
→ TARGET_ACTIVATION_RECONCILING
→ TARGET_ACTIVE
```

An authoritative passing observation may reconcile directly from
`TARGET_ACTIVATION_REQUESTED` to `TARGET_ACTIVE`. A failed, partial, stale, or
unknown observation remains immutable and leaves activation unresolved in
`TARGET_ACTIVATION_RECONCILING`. A later separate observation may reconcile
the same durable action when it satisfies the exact contract.

The ops-0010 action-status guard does not fully realize the last sentence for
an action already recorded `observed_failed`: it treats that status as
terminal. Phase 5C4.8 owns the narrowly scoped forward correction that permits
the same migration or target-open action to reconcile from failed or unknown
observation to later authoritative success. Until that migration exists,
operators must not describe an ops-0010-only installation as supporting that
reconciliation.

Exact committed request retries return the stored result. Reuse with changed
bytes, identifiers, nonces, commands, observations, or compare-and-swap
versions fails closed and records conflict evidence where the contract defines
it. Serialization failures and deadlocks use bounded fresh-transaction
retries. No database transaction remains open during external migration,
target-opening, or observation work.

## Emergency close

Emergency close is a separate two-step protocol and needs no new activation
authority:

```text
TARGET_ACTIVATION_REQUESTED, TARGET_ACTIVATION_RECONCILING,
TARGET_ACTIVE, POST_CUTOVER_VERIFIED, or ACTIVATION_INTERVENTION_REQUIRED
→ EMERGENCY_CLOSE_REQUESTED
→ EMERGENCY_CLOSED
```

The control request first stores an immutable close intent. The external
application-database routine then moves the local fence to `closed_incident`
and revokes runtime-write admission. The target-local command inspects that
result and emits a canonical observation for separate collector admission.
The observation must prove that the target is closed and runtime writes are
not admitted before finalization reaches `EMERGENCY_CLOSED`. A partial or
unknown result reaches `ACTIVATION_INTERVENTION_REQUIRED` and remains
maintenance-required.

Emergency close never deletes or invalidates prior activation evidence. It
does not switch the route, reopen the source, or perform a general rollback.
When the external result is ambiguous, keep the environment closed or
unresolved and reconcile the stored action; do not issue an unrelated new
command.

Ops 0010 also cannot finalize later authoritative closure evidence after the
same emergency-close action has advanced to
`ACTIVATION_INTERVENTION_REQUIRED`. Phase 5C4.8 owns the same-action
reconciliation correction. It does not authorize a new close command, route
change, source reopen, or rollback.

## Operator command boundary

The signed-material CLI must never accept a private key or provide a sign,
migrate, activate, open, or emergency-close command. Operational commands must
load authoritative bindings from the control plane and require explicit
environment, attempt, authorization, request, action, observation, and
compare-and-swap identifiers where applicable.

The signerless authorization sequence is:

```bash
python scripts/manage_phase5c4_execution_authorization.py export \
  --payload execution-payload.json \
  --key-id '<trusted public-key digest>' \
  --statement-out execution-statement.json \
  --message-out execution-message.bin

python scripts/manage_phase5c4_execution_authorization.py assemble \
  --statement execution-statement.json \
  --signature-file detached-signature.bin \
  --execution-authorization-out execution-authorization.json

NUTRITION_PHASE5C4_EXECUTION_AUTHORIZATION_VERIFIER_DATABASE_URL='<verifier URL>' \
  python scripts/manage_phase5c4_execution_authorization.py verify \
  --execution-authorization execution-authorization.json

NUTRITION_PHASE5C4_EXECUTION_AUTHORIZATION_VERIFIER_DATABASE_URL='<verifier URL>' \
  python scripts/manage_phase5c4_execution_authorization.py admit \
  --execution-authorization execution-authorization.json

NUTRITION_PHASE5C4_CONTROL_AUDIT_DATABASE_URL='<control audit URL>' \
  python scripts/manage_phase5c4_execution_authorization.py status \
  --authorization-id '<execution authorization UUID>'
```

`bootstrap-key`, `revoke-key`, and `revoke-authorization` require
`NUTRITION_CONTROL_MIGRATION_DATABASE_URL`; they are manual control-migrator
operations. The CLI accepts only a public SubjectPublicKeyInfo DER file for key
bootstrap.

Run control migrations only against the independent control database:

```bash
NUTRITION_CONTROL_MIGRATION_DATABASE_URL='<bootstrap superuser control URL>' \
  python scripts/manage_phase5c4_control_roles.py \
  provision-execution-authorization-verifier \
  --confirm-database '<control database name>'

NUTRITION_CONTROL_MIGRATION_DATABASE_URL='<bootstrap superuser control URL>' \
  python scripts/manage_phase5c4_control_roles.py \
  provision-emergency-close \
  --confirm-database '<control database name>'

NUTRITION_CONTROL_MIGRATION_DATABASE_URL='<control migrator URL>' \
  python -m alembic -c alembic-control.ini \
  upgrade ops_0010_phase5c4_activation

NUTRITION_CONTROL_MIGRATION_DATABASE_URL='<bootstrap superuser control URL>' \
  python scripts/manage_phase5c4_control_roles.py \
  qualify-execution-authorization-verifier \
  --confirm-database '<control database name>'

NUTRITION_CONTROL_MIGRATION_DATABASE_URL='<bootstrap superuser control URL>' \
  python scripts/manage_phase5c4_control_roles.py \
  qualify-emergency-close \
  --confirm-database '<control database name>'
```

Request the schema migration through the control executor:

```bash
NUTRITION_PHASE5C4_CONTROL_DATABASE_URL='<control executor URL>' \
  python scripts/manage_phase5c_promotion.py request-schema-migration \
  --request-id '<request UUID>' \
  --environment-id '<environment UUID>' \
  --expected-environment-generation '<generation>' \
  --expected-environment-state-version '<environment version>' \
  --attempt-id '<attempt UUID>' \
  --expected-attempt-state-version '<attempt version>' \
  --execution-authorization-id '<execution authorization UUID>'
```

Run `migrate-target` with the stored migration action, then admit its exact
observation through the collector:

```bash
NUTRITION_PHASE5C4_CONTROL_DATABASE_URL='<control collector URL>' \
  python scripts/manage_phase5c_promotion.py \
  record-schema-migration-observation \
  --file schema-migration-observation.json
```

After refreshing the compare-and-swap versions, request activation and execute
the stored target-open action:

```bash
NUTRITION_PHASE5C4_CONTROL_DATABASE_URL='<control executor URL>' \
  python scripts/manage_phase5c_promotion.py request-target-activation \
  --request-id '<signed activation request UUID>' \
  --environment-id '<environment UUID>' \
  --expected-environment-generation '<generation>' \
  --expected-environment-state-version '<environment version>' \
  --attempt-id '<attempt UUID>' \
  --expected-attempt-state-version '<attempt version>' \
  --execution-authorization-id '<execution authorization UUID>' \
  --schema-migration-observation-id '<migration observation UUID>'
```

Record the target-local observation and reconcile it with fresh versions:

```bash
NUTRITION_PHASE5C4_CONTROL_DATABASE_URL='<control collector URL>' \
  python scripts/manage_phase5c_promotion.py \
  record-activation-runtime-observation \
  --file activation-runtime-observation.json

NUTRITION_PHASE5C4_CONTROL_DATABASE_URL='<control executor URL>' \
  python scripts/manage_phase5c_promotion.py reconcile-target-activation \
  --request-id '<reconciliation request UUID>' \
  --environment-id '<environment UUID>' \
  --expected-environment-generation '<generation>' \
  --expected-environment-state-version '<environment version>' \
  --attempt-id '<attempt UUID>' \
  --expected-attempt-state-version '<attempt version>' \
  --activation-request-id '<signed activation request UUID>' \
  --runtime-observation-id '<runtime observation UUID>'

NUTRITION_PHASE5C4_CONTROL_DATABASE_URL='<control audit URL>' \
  python scripts/manage_phase5c_promotion.py activation-status \
  --environment-id '<environment UUID>'
```

Emergency close uses its dedicated control identity, the stored target-local
action, an independent collector observation, and a separate finalization:

```bash
NUTRITION_PHASE5C4_CONTROL_DATABASE_URL='<emergency closer URL>' \
  python scripts/manage_phase5c_promotion.py request-emergency-close \
  --request-id '<request UUID>' \
  --environment-id '<environment UUID>' \
  --expected-environment-generation '<generation>' \
  --expected-environment-state-version '<environment version>' \
  --attempt-id '<attempt UUID>' \
  --expected-attempt-state-version '<attempt version>' \
  --emergency-command-id '<emergency command UUID>' \
  --reason '<stable_reason_code>' \
  --change-reference '<reviewed change reference>'

NUTRITION_PHASE5C4_CONTROL_DATABASE_URL='<control collector URL>' \
  python scripts/manage_phase5c_promotion.py \
  record-emergency-close-observation \
  --file emergency-close-observation.json

NUTRITION_PHASE5C4_CONTROL_DATABASE_URL='<emergency closer URL>' \
  python scripts/manage_phase5c_promotion.py finalize-emergency-close \
  --request-id '<finalization request UUID>' \
  --environment-id '<environment UUID>' \
  --expected-environment-generation '<generation>' \
  --expected-environment-state-version '<environment version>' \
  --attempt-id '<attempt UUID>' \
  --expected-attempt-state-version '<attempt version>' \
  --emergency-command-id '<emergency command UUID>' \
  --observation-id '<emergency-close observation UUID>'
```

Do not invoke application Alembic directly for this transition. The
`migrate-target` command obtains the authoritative action from the control
audit surface and supplies the exact migration bindings to the subprocess.
After a successful subprocess return, it requires the target qualifier to
prove the exact schema-0021 maintenance-state role, grant, routine, trigger,
and runtime-admission policy, then uses `nutrition_ops` to inspect the committed
schema and fence. A normal migration failure writes a canonical failed
observation before returning failure; a timeout writes an unknown observation
and leaves the durable control action unresolved for an exact retry.
Use only the fixed-purpose CLIs for authorization admission, status,
observation, activation, reconciliation, and emergency close. Do not
substitute direct table writes or caller-authored digests. Qualification and
operator commands require their designated credentials; never reuse an
application runtime URL for a control operation.

## Qualification and rollback

After installing ops 0010, provisioned roles and schema 0021, run control
qualification v8 and the schema-0021 application role/local-admission
qualification through their designated audit and qualifier identities.
Qualification must prove exact roles, attributes, memberships, grants,
functions, tables, triggers, constraints, runtime fence behavior, absence of
`PUBLIC` execution, and absence of generic helper access.

```bash
psql '<control audit URL>' -X -v ON_ERROR_STOP=1 -Atc \
  'SELECT phase5c4_api.qualify_control_plane_v8();'

NUTRITION_DATABASE_URL='<target qualifier URL>' \
  python scripts/manage_phase5c4_roles.py qualify \
  --expected-state maintenance \
  --policy-revision 0021_target_activation_execution
```

After a target has been authoritatively reconciled active, repeat application
role qualification with `--expected-state normal`. Qualification output is
evidence to review; it is not itself an activation command.

An empty control ops-0010 schema may downgrade to the qualified v7 baseline.
Any execution key, revocation, authorization, conflict, migration, activation,
emergency-close, observation, or final-evidence row blocks downgrade.
Application migration 0021 is always forward-only. Never delete or rewrite
immutable evidence to force rollback.

Phase 5C4.7b does not implement automatic route cutback or source reopening.
Those remain separate authorities and operations. Ambiguous activation or
close outcomes require reconciliation or explicit intervention, not unsafe
automation.

This section intentionally records the historical ops-0010 qualifier and
downgrade boundary. The current control qualifier must always match the
installed control head. Phase 5C4.8 ops 0011 supplies qualifier v9 rather than
treating v8 as current.
