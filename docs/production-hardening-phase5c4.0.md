# Production Hardening Phase 5C4.0: deployment and provider decision record

Status: **accepted for Stage 5C4.1**
Decision date: 2026-07-16
Decision owner: repository owner, acting as `portfolio_owner_v1`
Selected profile: `phase5c4_controlled_portfolio_demo_v1`

This record closes the infrastructure and policy choices required by Section 20 of
[Production Hardening Phase 5C4](production-hardening-phase5c4.md). It makes no application,
database, provider, or Phase 5C4 runtime change. Stages 5C4.1 through 5C4.9 remain implementation
work with their own exit gates.

The graph-restart/idempotency and Alembic schema-authority blockers were corrected before this
record. Migration 0018 may therefore be designed against an explicit runtime-plus-retained schema
authority graph.

## 1. Decision summary

The first release is a **controlled production-like portfolio demonstration**.

It is not:

- a public multi-user service;
- a private service distributed to multiple independent users;
- a publicly reachable backend;
- an App Store or generally distributed TestFlight release; or
- a claim of highly available, regional, or independently operated production infrastructure.

The environment has one human operator, one pre-provisioned application user, operator-controlled
devices, private TLS ingress on a trusted local network, and synthetic or repository-owner data.
Reviewers observe the application through a supervised demonstration, screenshots, video, or a
screen share. They do not receive the mobile binary, bearer credential, database access, signing
keys, or network access to the backend.

This scope is selected because it matches the repository's implemented `private_single_user`
boundary and its explicit refusal to start public production without a real identity provider.
Calling the release public production would be false. Calling it merely local development would
also omit the production-like cutover, recovery, role, signing, and evidence behavior that Phase
5C4 is intended to demonstrate.

Any of the following invalidates this decision and returns Phase 5C4.0 to `blocked pending
user/provider choice`:

- public Internet exposure;
- credentials or builds issued to another independent user;
- storage of another person's nutrition/OCR data;
- a public-production, multi-user, SLA, or high-availability claim; or
- migration from the selected local providers to a managed/cloud deployment.

## 2. Normative policy and adapter identities

Later contracts use these exact identifiers. Renaming or changing their meaning requires a new
version rather than mutating v1:

| Contract | Identifier |
| --- | --- |
| Deployment scope | `phase5c4_controlled_portfolio_demo_v1` |
| Authentication | `phase5c4_private_single_user_auth_policy_v1` |
| Local provider profile | `phase5c4_local_docker_provider_profile_v1` |
| Database roles | `phase5c4_postgresql_role_policy_v1` |
| Database incarnation | `phase5c4_database_incarnation_v1` |
| Signing/trust | `phase5c4_local_ed25519_trust_policy_v1` |
| Endpoint switching | `phase5c4_docker_compose_switch_contract_v1` |
| Backup/recovery | `phase5c4_pgbackrest_minio_recovery_policy_v1` |
| Maintenance window | `phase5c4_t0_four_hour_window_policy_v1` |
| Performance admission | `phase5c4_t0_performance_ratification_v2` |
| Read-only canary | `phase5c4_private_canary_policy_v1` |
| Qualifier admission | `phase5c_qualifier_v2` |
| Operating roles | `phase5c4_single_operator_role_assignment_v1` |

Exact image digests, generated operation UUIDs, database OIDs, LSNs, nonces, public-key
fingerprints, object-version IDs, and timestamps are per-environment evidence. Omitting them from
this ADR is not a provider placeholder: the providers and algorithms are fixed here, while those
values must be observed from the actual exercise and cannot be invented in advance.

## 3. Section 20 closure table

Each row has exactly one current classification.

| Item | Decision | Classification | Gate carried forward |
| --- | --- | --- | --- |
| Deployment claim | Controlled production-like portfolio demonstration; one operator and one user; no public or multi-user access | resolved | Any scope expansion requires a new ADR before code or deployment |
| Authentication | Existing `private_single_user` bearer boundary with stricter issuance, rotation, pre-provisioning, and network restrictions below | resolved | Public production remains impossible and intentionally fails configuration |
| Control/audit placement | Separate PostgreSQL 16 control cluster plus separate single-node MinIO evidence service; distinct projects, credentials, networks, and volumes | resolved | Loss of either service stops the exercise; single-host failure-domain limitation is disclosed |
| Signing authority | Local Ed25519 approval key, pinned public trust anchor, offline trust/revocation key, purpose-bound promotion and activation artifacts | resolved | Key custody and tamper/revocation drills must pass before Stage 5C4.6 exits |
| Runtime role separation | Fixed owner/migrator/runtime/canary/qualifier/operations model; current owner-runtime arrangement is ineligible | requires a production-like exercise | Rehearse ownership transfer, privilege revoke, session drain, reconnect denial, and restoration |
| Endpoint switch | Stable private Caddy ingress plus Docker Compose backend process replacement; CAS/idempotency/status are emulated durably through the control DB and container labels | requires a production-like exercise | Crash/readback, old-pool drain, and two-vantage identity checks must pass |
| Database incarnation | PostgreSQL control data, database OID, Docker resource evidence, target nonce, backup label, restore operation, and clone lineage form one fail-closed identity | requires a production-like exercise | Every selected field must be observable on source, candidate, and both restores |
| Backup/WAL/PITR | pgBackRest with continuous WAL archive to versioned MinIO; encrypted repository; two same-attempt backups and exact restores | requires a production-like exercise | Prove archive health, restore correctness, RPO, RTO, and post-activation PITR |
| Maintenance window | Two consecutive complete rehearsals must finish within 180 minutes; hard window is 240 minutes with 30 minutes reserved for safe pre-activation exit | requires a production-like exercise | Exceeding the gate aborts or revises this ADR; no stale clone or delta copy |
| Production tier | T0 is the only permitted first-release tier, subject to a fresh frozen inventory meeting every T0 ceiling | requires a production-like exercise | Any exceeded dimension requires T1 fixture evidence and a new ratification |
| Read-only canaries | Pre-provisioned synthetic user/data, separate read-only database role and canary process, GET-only bounded suite, no bootstrap or cache writes | requires a production-like exercise | Database-denied write probe and before/after logical roots must prove zero mutation |
| Qualifier v2 | Admit only exact 0018 with a closed target fence; preserve independent queries and qualification receipt v1 shape; bind fence history separately | resolved | Compatibility proof obligations in Section 14 must pass during Stage 5C4.2 |
| Operational ownership | All named roles are assigned to authenticated principal `portfolio_owner_v1`; every separation exception is explicit | resolved | The assignment is invalid for public or independently used private deployment |

There are no unresolved provider names in this profile. Items classified `requires a
production-like exercise` have a selected provider and policy but still require measured evidence;
they are not placeholders.

## 4. Mandatory versus deferred controls

### Mandatory for the first demonstration

Deployment scope does not weaken data correctness. The following remain mandatory:

- immutable Daily Log history, Recipe revisions, and OCR provenance;
- generated Recipe Food compatibility and logging against immutable revisions;
- server-side ownership and cross-owner denial checks;
- exact plan-v2, execution authorization, checkpoints, restart, and receipt bindings;
- independent qualification and unchanged qualification receipt v1;
- archive reconciliation, clone isolation, and freeze-before-clone;
- independent control state and append-only/WORM evidence;
- zero block tolerance and explicit quarantine acceptance;
- target identity, closed write fence, role separation, and database immutability enforcement;
- signed, one-use promotion, activation, and pre-activation cutback authorizations;
- exact backup/restore evidence, continuous WAL, PITR, and measured recovery;
- provider readback, process/pool replacement, and no mixed routing;
- read-only post-switch verification; and
- activation as the irreversible divergence boundary.

### Scope-based deferrals

The following are intentionally deferred because their threat model does not exist in the selected
release:

| Deferred item | Classification | Why safe in this scope | Re-entry trigger |
| --- | --- | --- | --- |
| Public OIDC provider and multi-user account lifecycle | intentionally deferred because it is outside the selected deployment scope | No public access, no independent users, and no credentials/builds issued to reviewers | Any public or multi-user plan |
| Per-user refresh tokens, device sessions, and self-service revocation/deletion | intentionally deferred because it is outside the selected deployment scope | Exactly one operator-owned user and environment-level teardown | A second independent user or generally distributed build |
| Two-human approval and verifier separation | intentionally deferred because it is outside the selected deployment scope | One-person portfolio project; purpose, key, credential, and artifact separation still applies | Production/private service used by another person |
| Managed KMS/HSM | intentionally deferred because it is outside the selected deployment scope | Encrypted local key custody and FileVault are accepted only on the operator-controlled host | Cloud deployment or non-owner data |
| Multi-zone control plane and regional disaster recovery | intentionally deferred because it is outside the selected deployment scope | Demonstration stops safely on host/control failure and makes no availability claim | SLA, remote operation, or production claim |
| Physically independent WORM failure domain | intentionally deferred because it is outside the selected deployment scope | MinIO is process/credential/volume independent but shares one host | Production claim or evidence survival requirement after host loss |
| Customer support/on-call/public status communications | intentionally deferred because it is outside the selected deployment scope | There are no customers; observers receive direct maintenance notice | External users or scheduled public availability |
| Legal/compliance retention regime | intentionally deferred because it is outside the selected deployment scope | Synthetic or owner-controlled data only; no organizational/legal hold exists | Regulated data, third-party data, or an actual hold notice |

No archive deletion, cleanup, compaction, or shortened historical retention is authorized by these
deferrals.

## 5. Authentication decision

Authentication policy is `phase5c4_private_single_user_auth_policy_v1`.

### Boundary

- Backend mode is exactly `private_single_user`.
- The backend is reachable only through private TLS from operator-controlled devices on a trusted
  local network. Host firewall rules deny untrusted interfaces and the public Internet.
- The mobile build is installed only on devices controlled by the repository owner.
- Reviewers receive no build or credential.
- Data is synthetic or belongs to the repository owner. Third-party health, nutrition, image, or
  OCR data is prohibited.

### Credential lifecycle

- The bearer value is 32 cryptographically random bytes encoded base64url, not merely a human
  password satisfying the existing minimum length.
- One credential exists per environment/build. Development, rehearsal, and demonstration values
  are never reused.
- The secret is injected through backend and build environments and is never committed, printed,
  placed in an evidence artifact, or copied into screenshots.
- Rotate before every formal rehearsal/demonstration, at least every 30 days while an environment
  remains active, and immediately on suspected exposure.
- Compromise response is: enter maintenance, revoke ingress, replace the backend secret, rebuild
  and reinstall the mobile application, prove the old token is rejected, then issue a new
  environment authorization.

The token remains extractable from the mobile binary. That is accepted only because every device
and binary is controlled by the same operator. It is not accepted for independent users.

### User bootstrap and deletion

- Exactly one application user is pre-provisioned by an authenticated operator before the canary
  and before source freeze.
- `NUTRITION_PRIVATE_USER_CREATE_IF_MISSING` is false for every rehearsal and demonstration.
- Startup fails if the configured user is missing. An authenticated GET never creates it.
- The canary user is separate, synthetic, and also pre-provisioned.
- There is no self-service account deletion because there is no account service. Environment
  deletion is an operator action: revoke ingress and secrets, destroy databases after retention
  gates, and allow locked backup/evidence versions to expire under policy.

Public OIDC/JWT issuer, audience, provider subject binding, refresh sessions, JWKS rotation, and
provider account deletion are intentionally deferred, not partially simulated.

## 6. Concrete local provider profile

Provider profile is `phase5c4_local_docker_provider_profile_v1`.

| Capability | Selected provider/equivalent | Isolation and acceptance rule |
| --- | --- | --- |
| Application PostgreSQL | PostgreSQL 16 source, candidate, and restore containers; exact patch image pinned by digest in the exercise manifest | Source and candidate use different containers, credentials, networks, and named volumes |
| Independent control DB | Separate PostgreSQL 16 container/cluster in Compose project `nutrition-5c4-control` | Never shares the source/candidate PostgreSQL cluster, role catalog, volume, or application credentials |
| Evidence/object store | Single-node MinIO service in project `nutrition-5c4-evidence`, pinned by digest | Separate credentials/network/volume; loss stops promotion; same-host limitation disclosed |
| WORM audit sink | MinIO bucket `nutrition-5c4-audit-v1`, versioning plus COMPLIANCE object lock | Default 180-day retention; legal hold only for an actual incident/hold |
| Immutable evidence | MinIO bucket `nutrition-5c4-evidence-v1`, versioning plus COMPLIANCE object lock | Canonical artifact bytes and event anchors retained at least 180 days and never shorter than archive lifetime |
| Backup repository | MinIO bucket `nutrition-5c4-backup-v1`, versioned S3 repository used by pgBackRest | Separate least-privilege backup credentials; backup manifests and final receipts copied to WORM evidence |
| Backup/WAL engine | pgBackRest 2.58 series, pinned by artifact/image digest | `archive-push`, `archive-get`, backup, restore, check, info, and repository verify are the only adapter surface |
| Private ingress | Caddy 2 private TLS endpoint with a private CA trusted only by operator devices | Stable API name; no public DNS or public listener; firewall is part of admission evidence |
| Process switch | Docker Compose V2 service recreation with an immutable config/image digest | Provider effect is reconciled with Docker inspection and live database identity, never exit status alone |
| Local key custody | Encrypted Ed25519 PEM outside the repository; passphrase in macOS Keychain; trust root offline | No private key or passphrase enters containers, Git, logs, or control tables |

Image digests and installed versions must be captured during Stage 5C4.1 contract fixtures and
frozen before the first rehearsal. Floating `latest` or major-only tags are inadmissible evidence.

### Availability and backup of the control plane

The control DB and MinIO are single-node services on the operator host. They have no HA claim.
The control DB has its own pgBackRest stanza and continuous WAL archive. A control service outage
causes immediate maintenance and prevents new state transitions. Safe automatic resume requires
zero acknowledged control-event loss. If the restored control state cannot prove that, the attempt
is terminal/manual-recovery; commands do not infer state from application databases.

## 7. Signing and authorization model

Trust policy is `phase5c4_local_ed25519_trust_policy_v1`.

The signed-artifact issuer is exactly
`portfolio_owner_v1@phase5c4_local_ed25519_trust_policy_v1`. The authenticated local principal
`portfolio_owner_v1` may invoke the signer only after interactive Keychain approval; the issuer
string by itself conveys no authority.

### Keys and custody

- Promotion, activation, and pre-activation cutback artifacts use Ed25519 signatures.
- `key_id` is the SHA-256 digest of the canonical DER public key.
- The active approval private key is an encrypted PEM stored outside the repository with mode
  `0600`; its passphrase is stored in macOS Keychain and requires interactive operator approval.
- The public trust anchor and its fingerprint are versioned with the policy and copied to the WORM
  evidence bucket.
- A separate offline trust/recovery Ed25519 private key is stored on encrypted removable media. It
  alone signs trust-store rotations and revocation lists.
- Rotation creates a new policy version and key ID. Existing attempts stay bound to their original
  key; new attempts cannot use a retired key.
- Revocation is fail-closed. A revoked key invalidates unconsumed authorizations. An already
  consumed authorization remains immutable incident evidence but cannot authorize a later step.

### Authorization purposes

Promotion, activation, and cutback are three different signed envelope types. Each binds its
purpose, environment, attempt, nonce, artifact-set digest, source/candidate incarnations, provider
operation/config digest, expected state version, issuer, approver principal, issue time,
`not_before`, and expiry. Cross-purpose replay fails.

- Promotion authorization lifetime: at most 30 minutes.
- Activation authorization: issued only after complete post-switch verification; at most 10
  minutes.
- Cutback authorization: pre-activation only; at most 10 minutes and bound to continuous target
  fence proof.
- Authorization and nonce consumption occur with the control-plane state transition in one
  serializable transaction using control-database time.

### Separation-of-duty exception

`portfolio_owner_v1` is promotion approver, executor, activation approver, and recovery authority.
This is an explicit portfolio-only exception. It does not remove separate keys/credentials,
purpose-bound signed artifacts, interactive approval, independent qualifier execution, or immutable
audit events. It is invalid under any public or independently used private deployment.

## 8. PostgreSQL role and privilege model

Role policy is `phase5c4_postgresql_role_policy_v1`.

| Role | Attributes and membership | Authority |
| --- | --- | --- |
| `nutrition_owner` | `NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS` | Owns application schemas, objects, and fixed-search-path security-definer routines |
| `nutrition_migrator` | `LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`; may `SET ROLE nutrition_owner` | Alembic only; no runtime credential reuse |
| `nutrition_runtime` | `LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`; member only of `nutrition_runtime_read` and `nutrition_runtime_write` | Normal application DML through the documented surface; never owner/migrator/archive/control authority |
| `nutrition_canary` | `LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`; member only of `nutrition_canary_read`; `default_transaction_read_only=on` | Bounded pre-activation API verification; no sequences, DML, receipts, caches, or favorites |
| `nutrition_qualifier` | `LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`; `default_transaction_read_only=on` | SELECT on required public/archive/evidence relations and control functions only |
| `nutrition_ops` | `LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`; member of `pg_signal_backend`; execute-only maintenance routines | Revoke/restore bounded runtime grants, terminate sessions, observe role/fence state; cannot mutate domain rows directly |
| bootstrap administrator | Local PostgreSQL administrative credential, never supplied to the app or normal CLI | Creates roles and performs the one-time ownership transfer; sealed after provisioning |

`PUBLIC` receives no schema create privilege. Runtime receives no `USAGE` on any Phase 5C archive
schema, no control-plane connection, no role-admin option, and no membership path to owner or
migrator. Qualifier and canary credentials are different from runtime and from one another.

`nutrition_runtime_read`, `nutrition_runtime_write`, and `nutrition_canary_read` are exact
`NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS` group roles.
The first two receive only the relation, sequence, and routine grants in the versioned application
privilege manifest. `nutrition_canary_read` receives only the canary GET allowlist's SELECT and
read-routine grants. The migrator's owner membership has `SET` true, `INHERIT` false, and `ADMIN`
false; no other login role is a member of `nutrition_owner`.

### Proof obligations

Admission captures bounded queries over `pg_roles`, `pg_auth_members`, schema/table/sequence
privileges, ownership, and database settings proving:

- runtime is not owner, superuser, bypass-RLS, replication, create-role, or create-database;
- no direct or transitive membership reaches owner or migrator;
- runtime can perform only expected application operations before maintenance;
- runtime cannot access archives or control tables;
- canary and qualifier transactions are read-only and cannot call mutating routines;
- `max_prepared_transactions = 0` and `pg_prepared_xacts` is empty; and
- every security-definer routine pins `search_path`, validates expected state, and is not executable
  by `PUBLIC`.

### Current-owner migration and rehearsal

The current local Compose database uses the application credential as initial database owner and
is not Phase 5C4 eligible. On a disposable copy, the bootstrap administrator must:

1. create the roles above with exact attributes;
2. transfer database, schema, table, sequence, function, and type ownership to `nutrition_owner`;
3. revoke `CREATE` from `PUBLIC` and all owner/admin memberships from the runtime identity;
4. grant runtime, canary, qualifier, and operations privileges from an exact manifest;
5. rotate the application connection to `nutrition_runtime` and the migration connection to
   `nutrition_migrator`;
6. run all application, migration, ownership, archive-denial, and cross-owner tests; and
7. rehearse maintenance: stop the backend, revoke runtime writes/connect, terminate its sessions,
   reject reconnects and a write probe, wait for a quiet interval, and later restore only the
   documented grants.

The same manifest is then applied to the real demonstration source before freeze. No `REASSIGN
OWNED` or broad privilege repair is first attempted during the cutover window.

## 9. Endpoint-switch contract

Switch contract is `phase5c4_docker_compose_switch_contract_v1`.

The public/private API name remains on Caddy. The switch replaces the only backend process behind
that ingress; it does not change DNS and does not run source- and target-writing backends together.

### Required request

The durable switch request contains:

- attempt UUID and immutable operation UUID;
- expected control-state version and route generation;
- expected current container/config/database incarnation;
- desired image digest, Compose config digest, candidate direct endpoint digest, and candidate
  incarnation digest;
- source and target fence-event digests; and
- request fingerprint and expiry.

### CAS and idempotency emulation

Docker Compose has no transactional compare-and-swap API. The independent control DB supplies it:

1. a serializable transaction locks the environment route row;
2. expected generation/current incarnation must match;
3. operation UUID and request fingerprint are inserted uniquely;
4. desired state is persisted before Docker is called; and
5. the container is created with attempt, operation, config, image, and candidate-incarnation digest
   labels.

An exact same-operation retry reads control state and Docker state and returns the existing result.
A changed fingerprint conflicts. An unknown result is never retried blindly.

### Effect and readback

1. Both source runtime writes and target writes are database-fenced.
2. Caddy serves maintenance; liveness remains available and public readiness stays non-ready.
3. The old backend is stopped gracefully, its container/process/pool identity is recorded, and all
   application database sessions are drained/terminated.
4. Compose recreates the backend from the exact image/config digest with the candidate endpoint.
5. Readback collects Docker engine ID, container ID, image digest, labels, health, start time, and
   Compose project/service identity.
6. The backend's operator-only identity probe and a direct database observation must agree on the
   candidate incarnation, schema 0018, role, and closed fence.
7. Database session census proves no old process or source connection remains.
8. Host-local and physical-device/private-ingress vantage points must agree on deployment and
   candidate identity before the switch is marked confirmed.

Provider exit status, Caddy reachability, Docker labels, or database LSN alone is never sufficient.
A partial/mixed/unknown observation fences both sides and retains maintenance.

## 10. Database-incarnation and clone-lineage evidence

The canonical `phase5c4_database_incarnation_v1` record contains:

- environment, purpose (`source`, `candidate`, `source_restore`, `target_restore`, or
  `promoted_target`), attempt, and observation UUID;
- Docker engine ID digest, Compose project/service, container ID, exact image digest, and immutable
  volume/incarnation label;
- safe direct-endpoint digest, PostgreSQL server version, database name, and database OID;
- `pg_control_system().system_identifier`;
- checkpoint timeline, previous timeline, checkpoint/redo LSN, current/replay LSN as applicable,
  recovery state, and database server time;
- schema revision and schema-authority digest;
- migration-0018 target nonce/identity row and digest;
- clone marker, source state seal, pgBackRest backup label, backup repository/object version,
  restore operation UUID, and parent incarnation digest;
- captured role/fence epoch/event digest; and
- canonical record digest.

PostgreSQL exposes system identifier and checkpoint/timeline control data through its control
functions. Physical clones may deliberately retain the source system identifier, so that value is
not unique authority. Candidate identity requires the complete provider/resource tuple plus a new
0018 target nonce and bound restore operation.

The local provider has no managed-cloud resource UUID. The selected equivalent is the tuple of
Docker engine ID, container ID, immutable image/config digests, volume incarnation label,
PostgreSQL control identity, database OID, target nonce, and lineage operation. Absence or
disagreement of any required field fails closed.

## 11. Backup, WAL, PITR, restore, RPO, and RTO policy

Recovery policy is `phase5c4_pgbackrest_minio_recovery_policy_v1`.

### Technology and encryption

- pgBackRest archives WAL using `archive-push` and restores it using `archive-get`.
- Backups and WAL are written to the versioned MinIO S3 repository.
- Repository encryption is pgBackRest AES-256-CBC with a random passphrase held in macOS Keychain;
  MinIO credentials are separate and least privilege.
- Host storage is protected by FileVault. This is the portfolio equivalent of managed KMS and is
  not represented as an HSM/KMS claim.
- Backup/WAL credentials cannot write WORM evidence/audit buckets. The evidence writer cannot
  delete or administer the backup bucket.

### Recovery objectives

| State | RPO | RTO | Failure behavior |
| --- | --- | --- | --- |
| Frozen source before activation | Zero accepted writes after the recorded freeze | 120 minutes | Restore the exact frozen-source backup or authorized pre-activation cutback |
| Promoted target after activation | At most 5 minutes of acknowledged writes, measured from WAL archive lag | 120 minutes | Target maintenance plus forward repair/PITR; source is never a rollback target |
| Independent control state | Zero acknowledged event loss for safe automatic resume | 120 minutes | Any uncertainty makes the attempt terminal/manual-recovery; no inferred continuation |

`archive_timeout`, archive monitoring, and exercise workload must demonstrate the five-minute data
RPO; configuration alone is not evidence.

### Retention

- Continuous WAL and ordinary rolling backups: 30 days.
- Exact frozen-source cutback backup and target recovery seed: 90 days.
- Canonical promotion/recovery evidence and audit anchors: at least 180 days and never shorter than
  the retained historical archive.
- Incident/legal hold, when explicitly declared, is indefinite until the repository owner clears
  it; no legal hold is assumed by default.
- Expiry never authorizes archive deletion or mutation.

The application PostgreSQL containers are dedicated to this app. Unrelated databases are
prohibited because physical backup and PITR operate at cluster scope and would otherwise copy
unrelated data.

### Same-attempt backups and exact restores

During the frozen window:

1. create a full frozen-source backup after source seal and WAL confirmation;
2. verify the repository and backup manifest;
3. restore it to a new disposable source-restore container/volume, assign a restore nonce, start it
   fenced, and verify schema, roots, system/timeline/LSN lineage, backup label, and source seal;
4. after conversion, 0018, and final qualification, create the target recovery-seed backup;
5. restore it to a different disposable target-restore container/volume with a new nonce; and
6. verify the exact qualified roots, target identity/fence/event binding, archive, and artifact
   digests.

Both restore receipts must be created in the same attempt before promotion authorization. Evidence
older than 24 hours is inadmissible, although the selected window normally makes it less than four
hours old. Backup creation without a successful exact restore is a failure.

After activation, a separate drill must restore/PITR through a known post-activation synthetic
write without consulting the retired source.

## 12. Maintenance-window rehearsal plan

Window policy is `phase5c4_t0_four_hour_window_policy_v1`.

- Target duration: at most 120 minutes.
- Acceptance: two consecutive complete rehearsals at at most 180 minutes each.
- Hard maintenance window: 240 minutes.
- The final 30 minutes are reserved for a pre-activation safe exit. New irreversible work may not
  begin after minute 210.
- Each exact restore must complete within 60 minutes; the complete recovery drill must meet the
  120-minute RTO.

| Phase | Budget | Required evidence |
| --- | ---: | --- |
| Maintenance ingress, app stop, source drain/freeze/seal | 20 min | denied-write/reconnect probes, zero mutating sessions, stable source root |
| Frozen-source clone and lineage | 20 min | clone operation, source/candidate identities, marker, backup/LSN lineage |
| Phase 5C1 inventory, bridge, plan, attestations | 15 min | exact plan-v2 and archive/source roots |
| Phase 5C2 conversion plus restart verification | 15 min | run/outcomes, receipt, checkpoints, unchanged preservation roots |
| Migration 0018 and final independent qualifier v2 | 15 min | schema/role/trigger/fence proof and receipt-v1-compatible qualification |
| Source/candidate reconciliation | 10 min | exhaustive permitted-difference receipt |
| Frozen-source backup and exact restore | 30 min | backup/version/manifest plus passing restore receipt |
| Target seed backup and exact restore | 30 min | backup/version/manifest plus qualified-root restore receipt |
| Authorization, switch, pool/readback, read-only canary | 20 min | consumed promotion auth, unanimous route/identity, zero-mutation smoke |
| Activation or authorized pre-activation cutback | 10 min | consumed purpose-specific auth and final fence/route state |
| Contingency/reserved exit | 55 min | incident timeline or normal completion evidence |

The phases are sequential where their evidence depends on prior state; backups/restores are not
quietly overlapped in a way that weakens exact bindings.

If a rehearsal exceeds 180 minutes, it does not qualify. If the real attempt projects beyond the
hard window before switching, discard the candidate, verify the source seal, restore source grants,
and schedule a new freeze-before-clone attempt. After switching but before activation, keep target
fenced and execute authorized cutback, enabling source writes last. After activation, cutback is
forbidden; use target maintenance and forward/PITR recovery.

The only acceptable remedies for an oversized window are faster measured infrastructure, bounded
non-semantic optimization with new evidence, or a newly approved larger window. Stale-clone reuse,
dual write, CDC, delta copy, reverse replication, and informal synchronization remain prohibited.

## 13. Performance tier decision

The first release is capped at T0.

T0 ceilings are 50 Recipes, 250 Foods, 5,000 Daily Logs, 1,000 OCR records, at most four servings
per Food, at most 25 nutrients per Food, Recipe ingredient p50/p95 at most 4/10, and graph
depth/breadth at most 3/2. The ratified structural proof vector is exactly 25 global, 68
archive/support, 20 Daily Log, and 37 OCR scans with zero per-subject source/Daily/OCR full scans.

A read-only observation of the current local database found five Recipes, six authored Recipe
ingredients, 45 Foods, 14 Daily Logs, and one OCR confirmation trace. That database is at migration
0012 rather than current head 0017, so the inventory classified it `inventory_inconclusive` and did
not authoritatively measure servings, nutrients, or graph shape. Those counts demonstrate that the
workspace is small; they do not authorize promotion.

Before every rehearsal and real attempt, a frozen aggregate inventory must prove every dimension
at or below the T0 ceiling. T0 fixture evidence and v2 ratification must be generated on the exact
selected hardware/provider profile. If any dimension exceeds T0, promotion is blocked until the
T1 fixture and performance contract are run and separately ratified. No dimension is averaged or
waived to remain in T0.

## 14. Read-only canary design

Canary policy is `phase5c4_private_canary_policy_v1`.

### Seeded data

Stage 5C4.2 provisions one fixed synthetic canary user before freeze, with:

- one manual Food with serving and nutrient data;
- one published Recipe, immutable revision, and compatibility projection;
- one Daily Log bound to immutable revision nutrition plus nutrient snapshots;
- one OCR confirmation/provenance trace containing synthetic observations only;
- deterministic favorites/recents expectations; and
- ownership-isolation fixtures owned by the primary application user but inaccessible to canary.

The canary seed has a canonical manifest and logical root. Seeding is never part of post-switch
verification.

### Execution boundary

- Private-user auto-create is disabled and startup fails if either required user is absent.
- A separate canary backend process uses `nutrition_canary`, not `nutrition_runtime`.
- The database role has SELECT/execute-read privileges only and
  `default_transaction_read_only=on`.
- The canary suite performs only an exact GET allowlist. USDA calls, OCR parse/import, mutation,
  favorite changes, log recents updates, idempotency paths, cache warming, and background tasks are
  disabled or excluded.
- Application caches remain disabled for the canary process. No cache table, filesystem cache, or
  mutable external cache is permitted.
- A denied SQL write and denied API mutation are required negative probes.
- Before/after domain roots, row counts, sequence values, idempotency receipts, favorites, logs,
  revision state, OCR state, and fence events must be identical.

Only after the canary succeeds does the normal target process become eligible for activation. The
normal runtime write group remains revoked and the target fence remains closed during the canary.

## 15. Qualifier-v2 compatibility decision

`phase5c_qualifier_v2` changes admission, not historical semantics or receipt shape.

It must:

- admit only exact Alembic revision `0018_phase5c_promotion_prerequisites`;
- verify target incarnation/nonce, exact role and trigger contract, closed
  `closed_prequalification` fence, and the initial append-only fence event;
- run its own read-only repeatable snapshot through `nutrition_qualifier`;
- preserve the independent queries, comparison rules, roots, reason classifications, and canonical
  `phase5c_conversion_qualification_receipt_v1` field set;
- exclude the mutable current fence projection and identity observation timestamps from every
  historical/domain root; and
- compute a separate append-only fence-event-chain digest and bind it through the candidate state
  seal, artifact set, and promotion authorization rather than inserting it into receipt v1.

### Compatibility proof obligations

Later implementation review must prove:

1. the receipt-v1 validator accepts v2 output without modification;
2. v2 emits exactly the existing receipt-v1 keys and contract versions;
3. with identical historical/domain/archive/run inputs, v1-at-0017 and v2-at-0018 produce identical
   planned/observed counts, reason counts, source roots, Daily Log/OCR roots, outcome ledger, and
   receipt digest;
4. 0018 identity/fence/event rows cannot change any protected root;
5. missing/wrong identity, open/wrong fence, broken event chain, wrong runtime/qualifier role,
   missing trigger, or schema drift fails before qualification;
6. qualifier queries remain independent of converter/control-plane cached results;
7. a receipt created before 0018 is rejected for promotion even if otherwise valid; and
8. concurrent fence mutation is impossible under the closed fence and read-only qualification
   boundary; any observation mismatch fails closed.

## 16. Operational ownership matrix

The authenticated principal is `portfolio_owner_v1`, bound in evidence to the active signing-key
fingerprint and local operating identity. Role names remain distinct even when one person fills
them.

| Operating role | Assigned principal | Duty | Separation exception |
| --- | --- | --- | --- |
| Change commander | `portfolio_owner_v1` | Window, stop/go, incident state, final completion | Same person as executor |
| Data owner | `portfolio_owner_v1` | Zero-block review and explicit per-subject quarantine acceptance | Same person owns the synthetic/owner data |
| Performance ratifier | `portfolio_owner_v1` | Admit exact T0 v2 contract and measured provider profile | No independent performance approver |
| Promotion approver | `portfolio_owner_v1` using approval key | Sign exact short-lived promotion authorization | Same human as executor; interactive signed artifact remains separate |
| Promotion executor | `portfolio_owner_v1` using operations credential | Execute durable commands/provider operations | Cannot sign non-interactively or bypass control FSM |
| Activation approver | `portfolio_owner_v1` using approval key | Sign post-verification activation authorization | Same human; different purpose/artifact and re-authentication |
| Independent verifier | `portfolio_owner_v1` using qualifier credential | Run separately packaged read-only qualifier/canary and admit output | Procedural/tool/credential independence, not human independence |
| Database operator | `portfolio_owner_v1` using operations/bootstrap credentials | Role provisioning, freeze, backup/restore, session drain | Bootstrap credential sealed outside normal operation |
| Recovery authority | `portfolio_owner_v1` using offline trust/recovery key | Trust rotation, revocation, terminal recovery decision | Same human; offline key is separately held |
| Communications owner | `portfolio_owner_v1` | Notify supervised observers of maintenance, success, cutback, or incident | No public/customer channel exists |
| Audit scribe | `portfolio_owner_v1`; machine event stream is primary | Maintain one UTC timeline and seal final evidence bundle | Same human; append-only control/WORM events are authoritative |

Every role combination above is an explicit separation-of-duty exception. It is acceptable only
for this disclosed portfolio profile. A second independent user or public/private service claim
requires at least separate approver/executor and independent activation/verifier assignments.

## 17. Threat model

### Protected assets

- historical nutrition, Daily Log, Recipe revision, OCR provenance, ownership, and archives;
- plan, authorization, conversion, qualification, backup, restore, route, and audit evidence;
- private bearer, database, MinIO, backup encryption, and signing credentials;
- source/candidate authority and the activation/no-cutback boundary; and
- the truthfulness of the portfolio production-like claim.

### In-scope threats

- application, migration, operator, or automation mistakes;
- stale or wrong database/container/volume selection;
- dependency restart, replay, duplicate command, or lost acknowledgement;
- source writes after freeze, target writes before activation, or mixed routing/pools;
- artifact, manifest, event-chain, backup, WAL, or restore tampering/corruption;
- leaked mobile bearer or compromised operator-controlled device;
- malicious/untrusted local process or container without host-admin authority;
- process crash, host restart, network interruption, partial provider effect, and lost control-plane
  response; and
- accidental exposure of authored/OCR data through logs or evidence.

### Out-of-scope threats and limitations

- hostile public clients or independent account holders;
- a malicious repository owner/host root destroying the machine, volumes, MinIO, and offline keys;
- regional/cloud-provider failure and high-availability failover;
- collusion-resistant two-person approval;
- managed-HSM guarantees; and
- legal/regulatory retention certification.

These limitations are disclosed, not mitigated through misleading names. The environment fails
closed on control/evidence loss but may lose availability and locally stored evidence after total
host destruction.

## 18. Stage 5C4.1 go/no-go

**Decision: GO for Stage 5C4.1 only.**

The GO is valid because deployment scope, authentication, providers, algorithms, roles,
thresholds, and scope-based deferrals are concrete. No Section 20 item remains a placeholder.
Items requiring an exercise are exit gates for the provider/application stages that implement and
rehearse them; they do not prevent writing the pure contract library against this frozen profile.

The GO becomes NO-GO immediately if:

- the intended scope is public, multi-user, or distributed to reviewers;
- a selected provider/algorithm cannot implement its exact contract;
- Stage 5C4.1 proposes generic provider abstractions instead of these one-at-a-time contracts;
- the migration/schema-authority or idempotency corrections regress;
- any invariant or receipt/plan version changes; or
- a later stage starts before its predecessor's tests and review pass.

No production-like promotion is authorized by this GO. Promotion remains blocked until every
exercise-dependent row in Section 3 has passing evidence.

## 19. Revised bounded implementation sequence

The original sequence remains structurally sound. This profile narrows it to one local provider
per capability and splits the risk-heavy database stage; it does not remove correctness work.

| Stage | Bounded scope and exit | Recommended Codex model / effort | Permitted subagent work | Parent-agent responsibility |
| --- | --- | --- | --- | --- |
| 5C4.0 | This decision record only; no runtime work | GPT-5.6 Sol / xhigh | Read-only provider, security, operations, or consistency reviews | Deployment claim, provider/policy choice, threat model, final GO/NO-GO |
| 5C4.1 | Pure versioned contracts for the exact local profile; canonical shapes/digests, identity, artifact set, policies, T0 v2, auth envelopes; exhaustive tamper tests | GPT-5.3-Codex / high | Independent parsers, fixtures, tamper matrices, documentation checks | Shared contract semantics, versioning, cross-bindings, integration, no placeholders |
| 5C4.2a | Disposable/local role conversion and exact privilege manifest; owner/migrator/runtime/canary/qualifier/ops proof and drain/reconnect tests | GPT-5.3-Codex / xhigh | PostgreSQL role inspection, negative privilege tests, migration rehearsal | Role architecture, security-definer boundary, source eligibility decision |
| 5C4.2b | Migration 0018 identity/fence/immutability, maintenance-aware readiness/mutation denial, canary startup boundary, qualifier v2 with receipt v1 | GPT-5.3-Codex / xhigh | Migration test matrices, trigger coverage, qualifier compatibility fixtures | Migration architecture, root/receipt invariants, application transaction/auth semantics |
| 5C4.3 | Separate control PostgreSQL graph, FSM/events, typed evidence, replay/CAS, WORM outbox; MinIO evidence/audit integration for this profile only | GPT-5.3-Codex / xhigh | Control-schema tests, concurrency tests, MinIO test harness, outbox failure cases | Control authority, state machine, transaction boundaries, one-way trust boundary |
| 5C4.4 | Artifact admission/finalization, live candidate re-query, reconciliation, exact T0 v2 evaluator, zero-block and quarantine acceptance | GPT-5.3-Codex / xhigh | Contract/tamper tests, performance fixtures, reconciliation cases | Admission authority, root equivalence, policy decisions, final result semantics |
| 5C4.5 | One pgBackRest/MinIO adapter, WAL/archive monitoring, backup labels/manifests, exact restore verifier, PITR and corruption/timeout drills | GPT-5.3-Codex / xhigh | Provider harness, disposable restore tests, fault injection, documentation | Recovery policy, identity/lineage binding, RPO/RTO acceptance, secret boundary |
| 5C4.6 | Local Ed25519 trust store/signer verification, one-use purpose-specific authorizations, operator CLI, redaction/idempotency/audit | GPT-5.3-Codex / xhigh | Cryptographic vectors, CLI exit/JSON tests, replay/expiry tests | Trust model, key/revocation semantics, authorization consumption, shared contracts |
| 5C4.7 | Caddy maintenance ingress, Docker Compose CAS-emulation adapter, process/pool drain/readback, read-only canary, activation/cutback | GPT-5.3-Codex / xhigh | Docker/Caddy harness, vantage probes, canary cases, crash simulations | External-saga semantics, exact switch authority, irreversible boundary, integration |
| 5C4.8 | Crash/recovery qualification across every state, concurrent controllers, mixed routing, safe pre-activation cutback, target PITR after activation | GPT-5.3-Codex / xhigh | Independent fault campaigns and evidence verification | Recovery state machine, stop/go classification, no-cutback enforcement |
| 5C4.9 | Two measured full T0 rehearsals, four-hour policy, recovery/communications tabletop, sealed evidence and portfolio disclosure | GPT-5.6 Sol / high | Evidence audit, timing analysis, runbook review | Final release decision, exception acceptance, truthful deployment claim |

Current official model guidance identifies GPT-5.6 Sol as the flagship for complex reasoning and
coding, while GPT-5.3-Codex is optimized for agentic coding and supports high/xhigh reasoning.
Use the named model only when available in the team's Codex surface; otherwise use the strongest
available Codex model at the same effort and record the substitution.

No subagent may decide transaction semantics, migration ownership, canonical cross-contract
bindings, trust authority, activation/cutback policy, or final acceptance. Those remain with the
parent agent in every stage.

## 20. External technology basis

The selected local equivalents are grounded in the providers' documented capabilities:

- [PostgreSQL 16 continuous archiving and PITR](https://www.postgresql.org/docs/16/continuous-archiving.html)
  requires a base backup plus a continuous WAL sequence and recovers entire clusters.
- [`pg_basebackup` and backup manifests](https://www.postgresql.org/docs/16/app-pgbasebackup.html)
  document exact cluster backup and `pg_verifybackup`; Phase 5C4 selects pgBackRest as the single
  operational adapter rather than mixing backup authorities.
- [PostgreSQL control-data functions](https://www.postgresql.org/docs/current/functions-info.html)
  expose system identifier, checkpoint LSN, and timeline evidence.
- [pgBackRest's user guide](https://pgbackrest.org/user-guide.html) documents S3 repositories,
  encrypted repositories, WAL archive push/get, repository verification, restore, and PITR.
- [MinIO object locking](https://min.io/docs/minio/linux/administration/object-management/object-retention.html)
  provides versioned WORM retention, COMPLIANCE mode, and legal holds.
- [Docker Compose service recreation](https://docs.docker.com/reference/cli/docker/compose/up/)
  replaces processes/containers, but Phase 5C4 still requires durable CAS emulation and identity
  readback because recreation exit status is not authority.
- [OpenAI model guidance](https://developers.openai.com/api/docs/models) recommends GPT-5.6 Sol for
  complex reasoning/coding, and [GPT-5.3-Codex](https://developers.openai.com/api/docs/models/gpt-5.3-codex)
  is optimized for agentic coding work.

## 21. Final decision

Phase 5C4.0 is complete for `phase5c4_controlled_portfolio_demo_v1`.

- Stage 5C4.1 may begin against the exact contracts and providers in this record.
- Stages 5C4.2 through 5C4.9 remain unimplemented and must not be skipped or combined casually.
- Public or multi-user production remains blocked and requires a new Phase 5C4.0 decision,
  production identity provider, real human separation, managed infrastructure choices, and a
  different threat model.
- The first demonstration cannot be released until all exercise-dependent decisions have passing
  evidence and the final Stage 5C4.9 gate approves the truthful portfolio claim.
