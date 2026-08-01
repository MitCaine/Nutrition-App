# Production Hardening Phase 5C4.5: recovery validation

> **Document role: Historical Record.**

Status: **implemented; production activation remains unavailable**

This stage proves that an operator-restored PostgreSQL 16 database is the
intended, qualified target. It does not create backups, select retention,
route traffic, authorize activation, or open the application write fence.

## Transaction and failure boundaries

Recovery has three deliberately separate boundaries:

1. `manage_phase5c4_recovery.py execute` records an exclusive local operation
   intent, invokes the configured Docker Compose pgBackRest restore service,
   starts the PostgreSQL service, and records immutable completion evidence.
2. `validate` connects as `nutrition_qualifier` and collects database identity,
   PostgreSQL metadata, immutable-provenance qualification, exact role policy,
   runtime privileges, target identity, and fence state in one read-only,
   repeatable-read transaction under the shared migration advisory lock.
3. Optional `--admit` sends the canonical receipt to the independent control
   database in one serializable transaction.

A repeated completed execute returns the existing completion record only when
the current canonical provider request exactly matches the immutable intent and
completion journals. Operation-ID reuse with any changed execution input is
classified `provider_request_conflict`. An exact matching intent without
completion is classified `recovery_interrupted` and is never automatically
re-executed. The operator must reconcile the external target and use a
separately reviewed operation identifier for any retry.

Validation and admission can be retried without repeating restore execution.
An admission failure grants no authority and leaves no partial control row.

## Provider boundary

`DockerComposePgBackRestRecoveryProvider` is the only provider. The referenced
absolute Compose file must define:

- a restore service with pgBackRest repository and PostgreSQL data-volume
  configuration;
- a PostgreSQL service using the restored data volume;
- credentials through the Compose secret/environment boundary, not command
  arguments.

The adapter issues only an exact `pgbackrest ... --type=lsn
--target-action=promote restore` command followed by `docker compose up
--detach <postgres-service>`. One canonical request document drives intent
creation, command construction, and replay validation. Its digest binds:

- provider version and operation ID;
- the Compose file's resolved absolute path, byte count, and content digest;
- Compose project, restore/PostgreSQL services, and pgBackRest stanza;
- repository 1, provider backup ID, recovery type `lsn`, target LSN, and target
  action `promote`;
- the exact restore and startup argument vectors.

Both immutable journals retain that request digest. The completion also binds
the exact command digests and separate SHA-256 digests and byte counts for
restore stdout/stderr and startup stdout/stderr. Output is read in 64 KiB
chunks, hashed, and discarded; each stream is limited to 32 MiB and each
command retains the 30-minute timeout. Raw output and secrets are never written
to a journal or receipt.

The request object contains:

- `operation_id` and an existing absolute `operation_directory`;
- an existing absolute `compose_file`;
- `compose_project`, `restore_service`, `postgres_service`, and `stanza`;
- `provider_backup_id` and `recovery_target_lsn`.

## Evidence and admission

The `phase5c4_recovery_validation_v1` receipt separates expected values from
observed values. It binds:

- recovery/request, environment, attempt, and target database instance IDs;
- backup and restore artifact IDs and immutable digests;
- safe and physical database identity plus system identifier, database OID/name;
- PostgreSQL server revision, timeline, recovery state, and observed/requested LSN;
- target identity, schema 0020, immutable qualification and provenance digests;
- exact role-manifest and role-qualification state;
- runtime privilege and fence-chain digests;
- operator identity, provider request digest, bounded provider execution
  metadata, outcome, and bounded reason.

Intent and completion journals are canonical JSON, exclusive-created mode
`0600`, no more than 1 MiB, symlink-rejected, and atomically published only
after the complete file has been written. A completion is never accepted
without its canonical matching intent, and journal timestamps must order intent
creation, execution start, and completion.

`ops_0007_recovery_validation` installs immutable
`phase5c4_recovery_validations`, a narrow executor-only admission routine, an
audit-only read routine, and control qualification v5. Successful evidence is
accepted only when existing environment/attempt/target, backup, restore, and
immutable-provenance control rows agree. Failed evidence may be retained, but
it is not counted as a passing recovery prerequisite.

Rows reject update, delete, and truncate. Exact canonical replay is
idempotent. Conflicting recovery or request identifiers fail closed. Downgrade
is allowed only while the recovery table is empty and is forward-only after
first use.

The application schema remains `0020_immutable_provenance_enforcement`.
`nutrition_runtime` receives no new privilege, and its frozen runtime
privilege manifest is unchanged. This stage adds control authority only.

## Operator commands

From `apps/backend`:

```bash
python scripts/manage_phase5c4_recovery.py execute \
  --request /absolute/private/restore-request.json \
  --evidence-out /absolute/private/provider-evidence.json
```

Then validate without re-executing the restore:

```bash
NUTRITION_DATABASE_URL='<nutrition_qualifier URL>' \
NUTRITION_PHASE5C4_CONTROL_DATABASE_URL='<control executor URL>' \
python scripts/manage_phase5c4_recovery.py validate \
  --expectation /absolute/private/recovery-expectation.json \
  --provider-evidence /absolute/private/provider-evidence.json \
  --receipt-out /absolute/private/recovery-receipt.json \
  --admit
```

Audit readback requires the control audit identity:

```bash
NUTRITION_PHASE5C4_CONTROL_DATABASE_URL='<control audit URL>' \
python scripts/manage_phase5c4_recovery.py audit \
  --recovery-id '<uuid>'
```

All exported files are exclusive-create, mode `0600`, bounded, and refuse
symlink replacement.

## Exit boundary

This stage is complete when PostgreSQL 16 migration, qualification, provider,
replay/concurrency, binding-tamper, rollback, immutable-evidence, and audit
tests pass with the existing Phase 5C and backend suites.

The next stage may consume a passing recovery receipt as one prerequisite for
post-restore readiness. It must not infer activation authority from the
existence of a restore or a failed validation.

Phase 5C4.8 may reuse this evidence boundary to qualify a separately restored
postactivation target in a read-only transaction. That later qualification
does not mutate a 5C4.5 receipt, replace the live target, route traffic, grant
runtime writes, or make the retired source a rollback target. The provider
restore and measured RPO/RTO exercise remain separate evidence and must not be
inferred from a parser or qualification result.
