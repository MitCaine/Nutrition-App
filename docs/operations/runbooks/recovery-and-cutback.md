# Phase 5C4.8: bounded crash and recovery qualification

> **Document role: Operational Reference.** The Phase 5C4.9 Version 1.0 gate is preserved as a
> historical release record.

Status: **executable preactivation cutback and bounded recovery qualification
implemented at control revision `ops_0011_phase5c4_recovery_audit`;
local disposable infrastructure qualification is opt-in and vendor-neutral**

Phase 5C4.8 qualifies recovery at the irreversible target-activation boundary.
The original Phase 5C4 roadmap names crash injection across every transition,
concurrent controllers, mixed routing, safe preactivation cutback,
postactivation target PITR, and control-plane failure behavior. The implemented
Phase 5C4.7a and 5C4.7b stages provide route intent and observation,
post-cutover evidence, target activation, reconciliation, and emergency close,
but deliberately do not provide cutback or source-reopen authority.

This record refines that roadmap into bounded work that can be implemented and
reviewed without adding a generic deployment or recovery framework. The
repository contains the pure cutback contract and observation parsers, the
ops-0011 cumulative qualifier and audit snapshot, the two forward
reconciliation corrections, a signerless cutback authorization export,
assembly, verification and admission CLI, the executable database authority
lifecycle, and a read-only postactivation PITR evidence validator. External
route and source-restoration effects remain operator work reconstructed from
durable intent and proven by independent observations.

## Existing boundary

Phase 5C4.8 starts from:

The current active application migration head is now `0027_serving_reference_measurement`; the historical
cutback boundary below remains intentionally pinned to `0021_target_activation_execution`.

- application schema `0021_target_activation_execution`;
- control revision `ops_0010_phase5c4_activation`;
- the immutable Phase 5C4.7a route, post-cutover, and activation-evidence
  chain;
- the Phase 5C4.7b execution authorization, target-migration evidence,
  target-open intent and observation, final activation evidence, and
  emergency-close protocol;
- the Phase 5C4.5 operator-restored database validator and immutable recovery
  receipt; and
- the established rule that a provider acknowledgement or command return is
  never proof of an external effect.

The application migration stream remains at schema 0021. Phase 5C4.8 must not
change nutrition-domain rows, immutable history, Recipe revisions or
projections, OCR provenance, ownership, or the historical archive.

`TARGET_ACTIVE` and its immutable final activation evidence are the current
implemented successful-activation result. Older design prose that uses
`PROMOTION_COMPLETED` does not by itself authorize a new lifecycle transition.
Any change to that state contract must be separately justified and frozen
before fault qualification begins.

The authoritative control head is
`ops_0011_phase5c4_recovery_audit`. It installs qualifier v9 and the audit-only
recovery snapshot while leaving the application schema at 0021.

## Frozen contract surface

The implemented pure contract surface is:

- authorization contract
  `phase5c4_preactivation_cutback_authorization_v2`;
- purpose `production_preactivation_cutback`;
- safety observation `phase5c4_cutback_safety_observation_v1`;
- route observation `phase5c4_cutback_route_observation_v1`; and
- source-restoration observation
  `phase5c4_source_restore_observation_v1`.

The Ed25519 signing message is exactly:

```text
ASCII("nutrition-app/phase5c4/preactivation-cutback-authorization/v1")
+ NUL
+ uint64_be(canonical_statement_byte_length)
+ canonical_statement_bytes
```

The contract accepts no private key. It enforces exact canonical JSON,
purpose, signer, validity, environment, attempt, prior-authority, route,
source, target, fence and command bindings. The older
`phase5c_cutback_authorization_v1` shape remains non-executable historical
contract material.

The role-policy scaffolding also freezes the dedicated login identity
`nutrition_control_cutback_authorization_verifier`. Its intended callable
surface is only:

- `phase5c4_api.read_cutback_authorization_key_v1(text)`; and
- `phase5c4_api.admit_cutback_authorization_v1(bytea)`.

The role is provisioned before ops 0011 with `require_api=false`, then must
qualify with `require_api=true` after migration. It has API-schema usage and
only the two functions above; it has no base-table access or transition,
bootstrap, revocation, collection, or execution authority.

## Recovered bounded sequence

### 5C4.8a: purpose-specific preactivation cutback

The first bounded increment installs one purpose-specific,
preactivation-only cutback saga.

Cutback is eligible only while all of the following are authoritatively true:

- route switching and post-cutover verification belong to the same current
  environment generation and attempt;
- target activation has not been requested and divergence remains `none`;
- the source remains frozen and the target remains maintenance-closed;
- a fresh observation proves the exact target fence and absence of target
  runtime-write admission;
- the exact route/provider identity and both database incarnations match the
  immutable preactivation evidence;
- no conflicting activation, emergency-close, cutback, or recovery action
  exists; and
- a short-lived purpose-specific Ed25519 cutback authorization is valid,
  unrevoked, unused, and bound to the current state versions and continuous
  target-fence proof.

The external saga is strictly ordered:

1. consume the cutback authorization and commit an immutable route-to-source
   intent in the control database;
2. let the operator perform the exact external route operation;
3. collect an independent route observation;
4. accept only a unanimous observation of the exact source route with no
   split, unknown, stale-pool, or replaced-identity result;
5. inspect both database fences again; and
6. restore source runtime-write admission last through a fixed-purpose,
   source-local operation reconstructed from durable control intent.

“Restore source runtime-write admission last” does not mean restoring or
rewriting the source database. The frozen source must remain the exact sealed
source incarnation. A route result that is partial, split, unknown, stale, or
unavailable leaves both databases write-disabled and the attempt in
maintenance for exact reconciliation.

The route operation remains operator/provider work outside the database
transaction. Phase 5C4.8 must not introduce automatic Caddy, Docker Compose,
DNS, load-balancer, or multi-provider execution. The control plane records
intent and independently observed effect; it does not infer the effect.

### 5C4.8b: crash and reconciliation qualification

The second increment qualifies the Phase 5C4.7a, Phase 5C4.7b, and
preactivation-cutback boundaries with deterministic failure injection.
Injection points include immediately before and after:

- authoritative control state, event, current-row, conflict, and outbox
  commits;
- authorization admission and one-use consumption;
- route, migration, target-open, emergency-close, and cutback intents;
- external command invocation and acknowledgement loss;
- provider, route, target-fence, and source-fence observation admission;
- target activation and emergency-close reconciliation;
- source runtime-write restoration; and
- final activation, cutback, and recovery evidence finalization.

Every case must prove either complete transaction rollback or exact resume from
durable intent plus newly inspected state. Missing acknowledgement, process
exit, timeout, connection loss, or an enum value alone must never be treated as
success.

The existing target-local `inspect-target` operation remains read-only.
Phase 5C4.8 may add fixed-purpose inspection and reconciliation commands only
where needed to bind a durable action to a fresh authoritative observation.
It must not add a generic resume command. Target-open and emergency-close
failure paths must always preserve enough deterministic output or durable
unresolved state for the operator to inspect and reconcile the original action
instead of issuing unrelated authority.

Concurrency qualification must cover identical retries, changed-input reuse,
stale compare-and-swap versions, two controllers, lost controller leases,
authorization-consumption races, route-observation races, and activation
versus cutback races. PostgreSQL must select one authoritative outcome without
two consumptions, two active attempts, mixed writes, or deadlock-dependent
behavior.

### 5C4.8c: cumulative recovery qualification

The third increment adds a read-only cumulative recovery snapshot and
qualification result. The snapshot must be collected at one explicit
qualification boundary and bind:

- the current environment generation, attempt and state versions, route,
  source/target write modes, divergence state, and maintenance state;
- the immutable event chain, action ledger, authorization consumptions,
  conflicts, final activation or cutback evidence, and pending audit outbox;
- exact source, target, deployment, route/provider, runtime-role, schema,
  fence, and runtime-admission identities;
- the admitted backup, restore, recovery, qualification, provenance, and
  artifact-set evidence; and
- every unresolved, unknown, stale, partial, split, or intervention-required
  condition.

Snapshot collection performs no control transition, provider operation,
application migration, fence change, or data mutation. It uses control-database
time for control freshness, emits canonical deterministic output, redacts
credentials and private connection details, and fails closed when any required
view cannot be collected. A qualification result is evidence, not authority to
activate, cut back, reopen, close, route, or recover.

The cumulative view must distinguish at least:

- safe preactivation cutback eligibility;
- activation requested or divergence possible, for which source cutback is
  permanently forbidden;
- active target with no unresolved control or audit action;
- safely completed preactivation cutback;
- emergency-closed target requiring forward recovery;
- mixed or unknown routing requiring maintenance; and
- insufficient evidence requiring manual inspection.

## Read-only postactivation PITR qualification

After activation, Phase 5C4.8 must qualify a disposable target restore/PITR
through a known postactivation synthetic write without consulting the retired
source. The exercise may reuse the Phase 5C4.5 restore execution, database
inspection, and immutable recovery-receipt boundaries, but it must use a new
disposable database incarnation and independent operation identity.

The qualification proves:

- the configured WAL/archive lag and recovered target meet the approved RPO
  and RTO;
- the requested timeline and recovery target were reached;
- the known postactivation write is present;
- application schema 0021, target identity, role policy, fence evidence,
  immutable history, ownership, provenance, archive, and protected roots are
  valid;
- the restored database starts maintenance-closed and does not admit runtime
  writes; and
- the retired source was neither queried nor used as a rollback target.

This is a read-only qualification of a disposable restored target. It does not
replace the live target, route traffic, grant runtime writes, perform a live
PITR cutover, or authorize a new production activation. Any future live
replacement requires a separate purpose-specific architecture and authority.

This is a qualification contract over a restore performed outside the control
transaction. It is not permission for the application or control plane to
perform a restore.

The repository includes one destructive, opt-in local infrastructure
qualifier:

```bash
NUTRITION_PHASE5C4_QUALIFICATION_CONFIRM=phase5c4_infrastructure_destroy_disposable \
NUTRITION_PHASE5C4_QUALIFICATION_RETAIN_EVIDENCE=1 \
  ./scripts/qualify-phase5c4-infrastructure.sh
```

Each run creates a generated `nutrition-p5c4q-*` Compose project containing
PostgreSQL 16 source/restored/control databases, pgBackRest 2.58.0, TLS-enabled
MinIO with COMPLIANCE retention, and a persistent local routing-provider
stand-in. Credentials and the MinIO TLS key are generated per run; the key is
held in a temporary directory and removed even when evidence is retained.
All published service ports bind only to loopback.

The executable scenarios prove command/readback separation, operation-bound
replay and changed-input rejection, provider restart reconciliation, partial
and conflicting provider observations, source-last restoration ordering, full
and differential backup, WAL archiving, exact-LSN PITR,
latest-durable-LSN restore, unreachable-LSN fail-closed behavior, read-only
restored history, MinIO duplicate/conflict behavior, COMPLIANCE deletion
refusal and restart persistence, and selected cutback/activation/cumulative
PostgreSQL authority tests. RPO and RTO use database timestamps and WAL
positions; a positive subsecond RPO rounds up rather than reporting zero.

The canonical summary is retained only when requested under
`.project-runtime/phase5c4-qualification/<project>/qualification-summary.json`.
It includes scenario status and digests, provider operation/readback
documents, backup and LSN identities, protected root, WORM receipt, measured
timings, selected control-test digest, skipped scenarios, and cleanup result.
Raw command output, credentials, TLS keys, and host-specific container IDs are
not evidence.

This local run deliberately does not install schema 0021 through the live
activation migrator or restore representative application-domain tables.
Raw Alembic advancement would bypass the established closed-fence activation
protocol, so `application_schema_and_domain_restore` remains an explicit
skipped scenario. The provider process exercises and the selected control
authority tests run in the same qualification but are not one cross-bound
control saga; `control_provider_end_to_end_binding` is therefore also skipped.
The run is not certification of a production routing vendor, and a local
Docker administrator can physically destroy the MinIO volume despite
object-level COMPLIANCE enforcement.

Test harnesses must create isolated databases, containers, volumes, operation
directories, and credentials and must clean up only resources they created.
Immutable receipts and required journals remain evidence; cleanup, archive
deletion, retention shortening, or reuse of a restore identity is not
authorized.

## CLI inventory

The executable inventory is intentionally split by responsibility. Paths are
repository-relative.

**Operator CLIs**

- `apps/backend/scripts/manage_phase5c4_promotion_authorization.py` manages
  signerless promotion-authorization material;
- `apps/backend/scripts/manage_phase5c4_execution_authorization.py` manages
  signerless schema-execution authorization material;
- `apps/backend/scripts/manage_phase5c4_cutback_authorization.py` provides the
  cutback export/assemble/verify/admit/status flow plus migrator-only public-key
  and revocation operations;
- `apps/backend/scripts/manage_phase5c4_target_activation.py` performs only
  target migration, read-only target inspection, target opening, and emergency
  close from durable control actions;
- `apps/backend/scripts/manage_phase5c4_recovery.py` executes, validates, and
  audits an explicitly identified disposable restore; and
- `apps/backend/scripts/manage_phase5c4_roles.py` and
  `apps/backend/scripts/manage_phase5c4_control_roles.py` provision, inspect,
  and qualify the bounded application/control role policies.

**SQL authority**

Control revision `ops_0011_phase5c4_recovery_audit` owns the fixed
security-definer APIs for cutback intent, route observation,
source-restoration intent and observation, exact reconciliation, terminal
completion, cumulative qualification, and audit-only recovery status. The
Python module `apps/backend/app/operators/phase5c4_control.py` is a typed client
for bounded control calls; there is no standalone
`manage_phase5c4_control.py`, generic resume CLI, source-reopen CLI, or
cumulative-snapshot CLI.

**Infrastructure qualification**

`scripts/qualify-phase5c4-infrastructure.sh` is the operator entry point. It
validates its environment and invokes
`apps/backend/scripts/qualify_phase5c4_infrastructure.py` for the disposable
PostgreSQL 16/pgBackRest/MinIO/provider-stand-in exercise.

**Evidence generation and validation**

The authorization CLIs emit their bounded canonical artifacts. Existing
evidence helpers such as `apps/backend/scripts/create_phase5c_operator_attestation.py`
and `apps/backend/scripts/capture_phase5c_database_identity.py` retain their
specific earlier-stage responsibilities; they are not Phase 5C4.8 control
executors. `scripts/project-audit.sh`, `scripts/validate-docs.py`, and the
named pytest qualification suites validate repository and installed authority;
they do not grant authority.

**Provider responsibilities**

Production route changes, source-write operations, backup/restore/PITR work,
and independent provider readback remain operator/provider responsibilities
outside the control transaction. The local infrastructure qualifier supplies
only a disposable provider stand-in and does not create a production-provider
CLI or certify a vendor.

No command accepts or loads a private key. No command accepts caller-authored
authority digests in place of control readback. Command output and exit codes
must be deterministic, bounded, canonical where persisted, and free of secrets.
There is no generic provider command, arbitrary SQL command, automatic retry of
an ambiguous external effect, general resume, postactivation source reopen, or
live recovery command.

The cutback contract versions, purpose, signing preimage, control revision,
SQL routines, role grants, state transitions, lock namespace, command IDs, and
idempotency keys are frozen by ops 0011 and its PostgreSQL tests. SQL, Python,
CLI, qualification, and tests share those values without translation.

## Control-plane failure boundary

Control-database unavailability blocks every state-changing operation. Local
restart or restoration may resume only from the durable ledger after event
chain, current projection, authorization consumption, action, conflict, and
outbox integrity have been requalified. Any uncertainty keeps maintenance
enabled and requires manual recovery.

This local fail-closed and restoration qualification is not a high-availability
control plane. Phase 5C4.8 does not add multi-zone failover, leader election,
replication orchestration, automatic disaster recovery, or an availability
claim.

## Required tests

The pure contract suite covers deterministic Ed25519 framing,
canonical JSON, signature and key substitution, validity boundaries, purpose
and resource binding, and strict safety, route, and source-restoration
observation shapes. The PostgreSQL suites exercise the installed v9 qualifier,
audit snapshot, exact role surface, admission, one-use consumption, bounded
failure reconciliation, concurrency, immutability, and empty-only downgrade.

Further operational qualification must additionally add:

- deterministic signing, canonical-byte, tamper, expiry, revocation,
  cross-purpose replay, and changed-input tests for cutback authority;
- PostgreSQL 16 migration, exact-role/grant, `PUBLIC` denial, direct-write
  denial, immutability, replay, conflict, concurrency, lock, empty-only
  downgrade, and qualification-tamper tests;
- crash injection before and after every database/external-effect boundary;
- mixed, unknown, stale-pool, wrong-incarnation, lost-acknowledgement, partial
  observation, and source-enable-ordering cases;
- activation-versus-cutback and duplicate-controller races proving one winner;
- target-open and emergency-close ambiguous-result reconciliation tests;
- cumulative snapshot determinism, read-only behavior, redaction, missing-view,
  stale-evidence, event-chain, outbox, and cross-binding tests;
- disposable postactivation PITR tests proving the known write, lineage,
  immutable historical integrity, maintenance-closed startup, and absence of
  source use; and
- resource-lifecycle tests proving that only harness-created disposable
  resources are cleaned and immutable evidence is retained.

Mocks may prove deterministic provider and crash behavior. The local
Docker/pgBackRest/MinIO/provider qualifier is a separate result and must be
reported as unavailable when its prerequisites are unavailable. It does not
replace application-domain restore qualification or vendor certification.

## Explicit exclusions

Phase 5C4.8 does not implement:

- source cutback or source reopening after target activation is requested;
- automatic route, Caddy, Docker Compose, DNS, load-balancer, backup, restore,
  or PITR provider work;
- live target replacement, live PITR routing, or a second activation;
- a generic approval, deployment, recovery, or provider framework;
- high availability, multi-zone control failover, or regional disaster
  recovery;
- archive cleanup, evidence deletion, retention shortening, or historical-data
  repair;
- application-database schema or nutrition-domain changes; or
- mobile, UI, OCR, or other product work.

## Exit criteria

The implementation is code-complete only when:

1. the executable preactivation cutback path is purpose-specific, signed,
   one-use, independently observed, source-last, and impossible after
   activation request;
2. every named control and external-effect boundary has deterministic
   before/after crash coverage and an exact reconciliation result;
3. concurrent controllers, stale state, changed-input replay, and mixed route
   observations fail closed with one authoritative outcome;
4. cumulative recovery qualification is read-only, canonical, complete,
   secret-free, and independently tamper-tested;
5. the read-only postactivation PITR qualifier rejects missing lineage,
   unknown recovery targets, absent known writes, source use, mutable-history
   drift, and write-enabled restored targets;
6. control loss and restoration preserve the ledger and never permit inferred
   continuation;
7. PostgreSQL 16 privilege, migration, downgrade, CLI and existing Phase 5C4
   suites pass; and
8. unavailable Docker, pgBackRest, routing, PITR, provider-fault or
   control-restoration exercises are reported as not run.

Operational qualification remains a separate gate for the production-like
provider and schema-0021 application-domain restore path. The local qualifier
produces measured evidence for its own disposable topology only; unit tests,
PostgreSQL control tests, or a local-provider pass do not substitute for
vendor and application-domain qualification.

Phase 5C4.9 closes the remaining bounded Version 1.0 release findings: fixture
cleanup, frozen migration-0001 seed data, operator-document synchronization,
and fresh qualification evidence from the exact clean release commit. It does
not introduce new recovery semantics.
