# Production Hardening Phase 5C4: promotion, cutover, and recovery

## 1. Status, purpose, and authority

This specification is the implementation contract for deciding when an independently qualified
Phase 5C conversion may serve production traffic and for keeping the system safe if cutover fails.
It consumes the existing Phase 5C1, 5C2, 5C3a, 5C3b, 5C2.1, and 5C2.2 contracts. It does not
change conversion decisions, plan v2, execution authorization, checkpoint behavior, qualification
receipt v1, or historical data.

Promotion is a new authorization domain. A conversion plan says what to convert, an execution
attestation permits that conversion, a qualification receipt proves the resulting clone, and a
performance manifest measures a disposable workload. None of those artifacts permits a production
endpoint switch. Phase 5C4 adds a signed, one-use promotion authorization after correctness,
lineage, freshness, backup, restore, block, quarantine, and performance admission all pass.

The design makes these decisions:

1. The final production candidate must be cloned from the source **after** the source write barrier
   is established. Phase 5C4 provides no delta copier. A candidate created while the source was
   still accepting writes is inadmissible, even if its conversion is internally correct.
2. Source, target, and endpoint-switch state are coordinated by a dedicated PostgreSQL operations
   control database that is neither endpoint being switched. Evidence is also copied to immutable
   object storage. State held only in a process, source database, target database, or JSON file is
   not authoritative.
3. The application runtime database role must be separate from database/schema owners and migration
   roles. Maintenance uses database privileges, connection denial, and session draining as the
   authoritative write barrier; the Phase 5C advisory maintenance lock is not reused as one.
4. Both databases remain write-disabled while the endpoint is switched and post-cutover checks run.
   The transition that begins enabling target writes durably sets divergence to `possible`; from
   that point onward, switching back to the retired source is prohibited.
5. Conversion and restart remain locked to `0017_phase5c_indexes`. After they complete, a bounded
   PostgreSQL-only `0018_phase5c_promotion_prerequisites` adds target identity, a server-side write
   fence, and immutability hardening without changing any domain/archive row. Independent
   qualification then runs again through a v2 admission implementation that emits the unchanged
   `phase5c_conversion_qualification_receipt_v1` shape. Promotion control has a separate Alembic
   stream and database.

These choices favor a longer, bounded maintenance window over an unproven synchronization or
rollback claim.

## 2. Preserved invariants and safety rules

Phase 5C4 preserves:

- immutable Daily Log nutrition history and nutrient snapshots;
- immutable Recipe publication revisions and their canonical content digests;
- generated Recipe FoodItems as compatibility projections;
- logging and Recipe resolution against immutable revisions;
- immutable OCR correction and confirmation provenance;
- server-side ownership enforcement and historical nutrition immutability;
- exact plan-v2, archive, inventory, marker, and execution-authorization binding;
- checkpoint and restart guarantees;
- qualification receipt version 1 and independent qualification;
- archive reconciliation and clone isolation; and
- fail-closed, database-backed, bounded operator behavior.

The following rules are unconditional:

- At most one database may be write-enabled. During maintenance, neither is write-enabled.
- The source remains frozen from `SOURCE_FROZEN` until either `CUTBACK_COMPLETED` or permanent
  retirement after successful target activation.
- The target remains isolated through endpoint switch and post-cutover verification.
- Unknown or split routing forces maintenance, readiness 503, and both databases write-disabled.
- A missing, unsupported, stale, tampered, or inconsistent artifact blocks promotion.
- Correctness qualification is evaluated before performance. Performance can never waive a
  correctness, lineage, block, quarantine, backup, or restore failure.
- Any planned or observed `block` disposition prevents promotion. There is no block override.
- Terminal failure never releases maintenance or a database write barrier automatically.
- No dual write, reverse replication, or archive cleanup is introduced.

## 3. Control-plane and trust boundaries

### 3.1 Placement

The authoritative promotion ledger lives in a dedicated PostgreSQL operations database reached by
an immutable direct service identity, not by the application database alias. It must remain
available when either source or target is unavailable. Secret-free canonical artifact bytes are
ingested once and retained immutably in that database; a second copy is anchored in versioned,
immutable object storage. The database records the content digest, byte count, and exact object
version, so neither a path nor the recoverability of one storage system is the sole evidence.

The control database is not a user-facing application dependency for nutrition reads. A
maintenance-aware release reads only its environment gate for readiness and mutation admission.
If that gate cannot be read, readiness and mutations fail closed. The database privilege barrier
still protects the source if an application process has stale state or misses the gate change.

### 3.2 Roles

Use separate authenticated roles:

| Role | Allowed authority |
| --- | --- |
| evidence collector | Read source/target and register immutable evidence; cannot authorize or switch |
| data owner | Accept an exact quarantine set; cannot switch or enable writes |
| performance ratifier | Ratify a versioned performance contract; cannot run promotion |
| promotion approver | Sign an exact promotion authorization; cannot execute it |
| promotion executor | Invoke state transitions and deployment adapters; cannot sign approvals |
| activation approver | Authorize the irreversible target-write release after verification |
| audit reader | Read control ledger and immutable objects only |
| break-glass recovery | Explicitly authenticated recovery actions; every action is externally anchored |
| application runtime | No access to promotion evidence; read-only gate access and ordinary data grants only |

The application runtime role must be `NOSUPERUSER`, `NOBYPASSRLS`, non-owner, and not a member of
any migration or operator role. Operator identity comes from mTLS/OIDC/workload-identity claims;
caller-supplied labels are audit references, not authority.

### 3.3 Write barrier and readiness

`MAINTENANCE_REQUESTED` first makes the maintenance gate durable and changes `/api/v1/ready` to a
safe 503 while `/api/v1/health` remains a liveness-only 200. Mutating requests return a bounded 503.
The deployment stops new work and drains request and job queues. The database operator then:

1. revokes source application `CONNECT`, DML, sequence, and executable mutator-function privileges;
   on the target it denies DML/mutators while allowing only the explicitly read-only canary/runtime
   connection needed for post-switch smoke;
2. blocks source reconnects and unapproved target sessions at the pooler/firewall;
3. waits for bounded in-flight transactions, then terminates remaining application sessions;
4. proves no prepared transaction, replication writer, background job, or application session can
   write; and
5. performs a denied-write probe as the application runtime role.

Only then may the ledger say `WRITES_DRAINED` and `SOURCE_FROZEN`. Revocation cannot safely freeze
an application role that owns the affected objects; role separation is therefore a hard preflight
requirement. Advisory locks continue to serialize Phase 5C offline commands but are not access
control.

## 4. Immutable artifact admission and digest binding

### 4.1 Canonical artifact set

Promotion consumes `phase5c_promotion_artifact_set_v1`. Each member is the exact canonical byte
sequence ingested into immutable storage, not a filename or caller-provided digest. Each entry has
`artifact_type`, `contract_version`, `logical_id`, `sha256_digest`, `byte_count`, and immutable
storage object/version identifiers. Entries are sorted by `(artifact_type, logical_id, digest)`.

The artifact-set digest is:

```text
SHA-256(canonical_json({
  "artifact_set_version": "phase5c_promotion_artifact_set_v1",
  "environment": ...,
  "deployment_digest": ...,
  "source_database_incarnation_digest": ...,
  "target_database_incarnation_digest": ...,
  "members": sorted_members
}))
```

Unknown fields, duplicate singleton types, unsupported versions, non-canonical JSON, size-limit
violations, symlinks, mutable object references, and digest mismatches fail admission.

The complete required set is:

| Artifact | Required binding |
| --- | --- |
| `historical_database_inventory_v1` | Frozen source inventory, source schema, and its canonical digest |
| `phase5c_safe_database_identity_v1` | Existing safe source identity used by Phase 5C1 |
| `phase5c_database_incarnation_identity_v1` for source and target | Direct safe endpoint, managed resource ID when available, PostgreSQL system identifier, database OID/name, timeline, clone marker, environment |
| `phase5c_clone_origin_receipt_v1` | Frozen source incarnation/timeline/snapshot LSN or provider token to the newly created clone incarnation |
| clone marker and bridge metadata evidence | Inventory, source/clone distinction, archive identity, schema signature, source/archive roots, planning attestation |
| `phase5c_conversion_plan_v2` | Exact inventory, marker, archive, source roots, decisions, plan digest |
| planning/operator attestation v1 | Exact marker and planning scope |
| execution attestation v2 | Exact plan digest, archive, roots, marker, and execution scope |
| persisted conversion run/outcomes admission receipt | Exact database run, plan, execution attestation, complete/verified checkpoints |
| `phase5c_execution_receipt_v1` | Exact run and per-subject outcome evidence |
| `phase5c_conversion_qualification_receipt_v1` | `qualified=true`, exact run, plan, execution receipt, archive/source/Daily Log/OCR/outcome roots |
| `phase5c_qualification_observation_v1` | Fresh server-timed invocation, target incarnation, qualification digest, start/end time, read-only snapshot anchor |
| `phase5c_candidate_state_seal_v1` | Full protected target logical root after final 0018 qualification, schema revision, incarnation, fence-event binding, snapshot/timeline/LSN anchor |
| `phase5c_source_candidate_reconciliation_v1` | Frozen source to target equivalence under the allowed-difference contract |
| `phase5c_performance_qualification_manifest_v1` | Exact measured T0 evidence and raw metrics; the existing manifest is not modified |
| `phase5c_performance_contract_ratification_v1` | Exact ratified rules, tier, measured manifest digest, component versions, approver signature |
| `phase5c_backup_evidence_v1` (two roles) | Frozen source cutback backup and promoted-target recovery seed |
| `phase5c_restore_test_receipt_v1` (two roles) | Successful disposable restore of each exact admitted backup |
| `phase5c_quarantine_acceptance_v1` | Required only when quarantine count is nonzero; exact subject set/root, reasons, plan, ledger, policy, data-owner signature |
| `phase5c_zero_block_receipt_v1` | Plan, outcome ledger, and candidate query all prove zero blocks |
| `phase5c_promotion_policy_v1` | Freshness, schema, tier, backup, restore, route, sample, and recovery rules |
| deployment/routing descriptor | Environment, application build digest, target direct identity, provider revision, endpoint adapter contract |

Performance fixture subjects do not belong to the production candidate. A block deliberately
present in a benchmark fixture does not violate the candidate's zero-block rule.

### 4.2 Cross-artifact binding graph

Admission validates the full graph, not isolated digests:

```text
frozen source identity + inventory
        -> clone-origin receipt -> clone marker -> bridge/archive metadata
        -> plan v2 -> execution authorization -> run/outcomes -> execution receipt
        -> qualification receipt + fresh observation -> candidate state seal
        -> source/candidate reconciliation

performance manifest -> performance-contract ratification
plan + qualified outcome ledger -> zero-block receipt + quarantine acceptance
source/target seals -> two backup artifacts -> exact restore receipts

all preceding digests + policy + environment + deployment -> artifact-set digest
artifact-set digest -> signed promotion authorization -> one consumption -> one attempt
```

Every repeated inventory, archive, plan, marker, source/clone identity, execution-attestation,
schema, run, outcome-ledger, and qualification digest must be byte-for-byte equal. Promotion also
re-queries the target conversion metadata, run, and outcomes; external receipt counts are never
trusted alone.

### 4.3 Freshness and database drift

Qualification receipt v1 is deterministic and intentionally has no timestamp. Freshness is proven
without changing it: rerun the independent qualifier after the source is frozen and final clone is
converted, then create a server-timed `phase5c_qualification_observation_v1` and a read-only
`phase5c_candidate_state_seal_v1`.

The candidate seal contract enumerates every application, archive, Phase 5C conversion, and target
identity table, sequence, constraint/index fingerprint, extension/collation requirement, row count,
and canonical logical root. It includes Alembic revision
`0018_phase5c_promotion_prerequisites`. The mutable write-fence projection and append-only fence
events are outside the qualified domain root but are bound by their own exact event-chain digest;
the independent control ledger is in another database. LSN is recorded only as a recovery and
temporal anchor: PostgreSQL WAL is cluster-wide and LSN movement alone neither proves nor disproves
application-data drift.

Before authorization, switch, and activation, the target root is recomputed in a read-only
repeatable snapshot and must equal the seal. Any target content change after qualification fails
closed. Recommended `phase5c_promotion_policy_v1` limits are:

- qualification observation and candidate seal no more than 24 hours old;
- both exact backup completions and both exact restore receipts no more than 24 hours old;
- all evidence from the same uninterrupted source-freeze epoch; and
- promotion authorization lifetime no more than 30 minutes.

Age never overrides equality. Reopening source writes invalidates the freeze epoch and every
candidate, reconciliation, backup, restore, and promotion authorization derived from it.

### 4.4 Source/candidate reconciliation

The final clone is created from the already frozen source. `phase5c_source_candidate_reconciliation_v1`
proves:

- all pre-0004 tables, sequences, and rows common to source and clone are identical at clone origin;
- archived legacy Recipes and ingredients equal the frozen source roots;
- Foods, servings, nutrients, sources, users, Daily Logs, nutrient snapshots, OCR, idempotency, and
  other non-conversion data remain identical;
- current Recipe, immutable revision, projection-link, archive, migration, Phase 5C control, and
  Phase 5C4 target-fence differences are exactly those authorized by plan v2 and the migration
  fingerprint; and
- no unexpected table, column, constraint, index, extension, owner, grant, or sequence difference
  exists.

There is no "close enough" or operator exception. A mismatch requires a new frozen-source clone and
new Phase 5C1-C3 evidence; Phase 5C4 does not copy deltas or repair history.

## 5. Performance-contract ratification

The existing `phase5c_performance_budgets_v1` and all three T0 manifests remain immutable. Phase
5C4 introduces `phase5c_performance_contract_ratification_v1`, whose first ratified rules document
is `phase5c_performance_contract_t0_v2`.

For the deterministic T0 full path, it records both the required proof-obligation floor and
admission ceiling:

| Structural metric | Required floor | Ceiling | Margin |
| --- | ---: | ---: | ---: |
| global source passes | 25 | 25 | 0 |
| archive/support relation scans | 68 | 68 | 0 |
| Daily Log relation scans | 20 | 20 | 0 |
| OCR relation scans | 37 | 37 | 0 |
| per-subject source / Daily Log / OCR full scans | 0 / 0 / 0 | 0 / 0 / 0 | 0 |

Zero margin is intentional. These are deterministic structural obligations, not noisy latency
measurements: fewer scans would require proof that a correctness obligation was not removed, and
more scans would be a structural regression. Existing v1 wall-time, memory, total-query,
subject-query, and artifact-size ceilings remain unchanged; their ample existing headroom is not
recalibrated in 5C4.

The contract binds the requalified manifest digest, T0 fixture generator/seed/blueprint/logical
digests, plan/converter/qualifier/receipt versions, PostgreSQL major version, raw measurements, and
the exact metric evaluator. It acknowledges that the source manifest's historical
`overall_result = performance_failed` was correct under v1; v2 evaluates the same raw evidence
under a new signed contract without editing that evidence.

Performance applies by tier. Promotion derives the smallest required tier whose Recipe, Food,
Daily Log, OCR, ingredient-distribution, serving/nutrient, and graph dimensions cover the frozen
source. The first ratification authorizes only T0. A candidate exceeding any T0 dimension is blocked
until the corresponding T1/T2/T3 workload has independently passed correctness and restart checks
and a new immutable contract version is ratified. No tier is extrapolated.

Later evidence may add a contract version; it may not update or reinterpret a consumed version.
T1/T2 ratification requires reproducible raw manifests, an explicit proof-obligation ledger, and
the same architecture/operations policy authority plus release-safety approval. Revocation is a
separate signed artifact. Promotion authorization binds the exact active contract version and
digest, so a revoked or superseded contract cannot be silently substituted.

## 6. Backup, restore, and lineage evidence

### 6.1 Required recovery assets

Promotion requires two distinct backups from the same freeze epoch:

1. `frozen_source_cutback`: the exact legacy source after the write barrier. It supports safe
   pre-activation cutback and incident analysis.
2. `promoted_target_recovery_seed`: the exact qualified, reconciled, sealed target while target
   writes remain disabled. It is the base for target PITR and forward recovery after activation.

The backup used to create the final clone also produces `phase5c_clone_origin_receipt_v1`, but it
does not replace either final recovery role. Backup creation is not proof of restorability. Each
exact admitted backup must be restored into a new isolated disposable PostgreSQL environment and
must produce a passing restore receipt before promotion authorization.

A physical base backup plus complete WAL/PITR coverage, or a reviewed managed-service equivalent,
is required. A logical `pg_dump` may be retained as a supplemental export but is not sufficient: it
does not alone prove cluster/global-object restoration or provide the target's WAL recovery path.
For `pg_basebackup`, require all tablespaces, streamed or otherwise proven required WAL, a backup
manifest with SHA-256 checksums, and `pg_verifybackup`; verification is necessary but a real restore
is still mandatory.

### 6.2 `phase5c_backup_evidence_v1`

The strict contract contains:

- evidence ID, attempt ID, freeze epoch ID, and role (`frozen_source_cutback` or
  `promoted_target_recovery_seed`);
- provider/tool and bounded version, immutable backup ID, method, and consistency class;
- safe database identity and database-incarnation digests, PostgreSQL system identifier, database
  name/OID, server version, timeline, start/end LSN, and start/end server timestamps;
- required WAL range, archive-confirmed-through LSN/time, and timeline-history digest;
- Alembic revision and the applicable frozen-source or candidate-state-seal digest;
- target qualification, plan, archive, run, and artifact-set component digests where applicable;
- backup-manifest version/digest and file-checksum policy;
- immutable storage object/version, region/class, encryption status and non-secret key-reference
  digest;
- retention-policy ID/version/digest, retain-until time, and immutability/legal-hold capability;
- completion result, evidence collector identity, and canonical artifact digest.

Reject mutable "latest" identifiers, missing or unarchived WAL, wrong system/timeline/database,
failed completion, mutable retention, a backup taken before the write fence, or a state-root change
across the backup window. An LSN is meaningful only with the cluster system identifier and timeline.

### 6.3 `phase5c_restore_test_receipt_v1`

The strict receipt contains:

- exact backup evidence ID/digest, backup provider ID, and manifest digest;
- restore-test ID, fresh disposable restore identity, isolation attestation, and proof its safe
  endpoint differs from live source and target;
- restored system identifier and source/recovered timelines, requested target LSN, observed replay
  LSN, and explicit proof the requested target was reached;
- PostgreSQL major/tool versions and current Alembic revision;
- expected and observed logical state-seal roots plus archive/plan/run/qualification digests;
- check-set version and results for manifest/WAL, startup, schemas, extensions, collations,
  constraints/indexes, privileges, archives, conversion outcomes, Daily Logs, OCR, and bounded
  read-only smoke tests;
- completion time, measured restore duration/RTO, `passed`, and receipt digest.

The existing Phase 5C3a qualifier must not be tricked into accepting the restore by rewriting clone
identity. Its identity binding should fail on a different endpoint. A restore-specific read-only
verifier transfers the already qualified state by proving exact logical-root equality and adds
bounded semantic checks. Full historical requalification on the disposable restore is therefore
neither necessary nor claimed.

After activation, recovery also requires continuous WAL archiving, monitored archive lag, a stated
production RPO/RTO, and a proven ability to restore the target recovery seed and replay the target
timeline through the required recovery point. The frozen source backup cannot recover writes made
to the target.

## 7. Quarantine and block policy

Each plan subject retains exactly one disposition:

- `convert`: must have a completed, verified outcome and all qualified immutable domain rows.
- `quarantine`: must have a completed, verified non-convert outcome and no current Recipe,
  revision, or managed projection link.
- `block`: must have a completed, verified blocked outcome, but **any** block prevents promotion.

`phase5c_zero_block_receipt_v1` binds plan digest, run ID, qualification receipt, outcome-ledger
digest, aggregate count zero, and a target-database query proving no planned or observed block was
omitted or relabeled. Discovery of a block at any later gate invalidates authorization.

When quarantine count is nonzero, a data owner signs `phase5c_quarantine_acceptance_v1`. It contains
the plan and qualification digests, exact sorted subject UUID set digest, count, reason-code/count
digest, archive identity, policy version, intended environment, approver identity, issued/expiry
times, and signature. Ordinary summaries show counts and reason codes, not subject IDs. A different
set, plan, ledger, or reason requires new acceptance.

Quarantined legacy records remain in the immutable archive. The application runtime receives no
archive-schema privilege and exposes no legacy-record endpoint after cutover. A later narrowly
authorized repair tool may read a quarantined record, create new current immutable provenance and
publication rows, and record a repair receipt; it may not update/delete the archive, rewrite a Daily
Log snapshot, or pretend the original conversion succeeded.

## 8. Promotion and activation authorization

### 8.1 `phase5c_promotion_authorization_v1`

Do not extend execution attestation v2. Promotion uses a distinct signed artifact with:

- authorization UUID, cryptographically random one-use nonce, and purpose fixed to
  `production_historical_conversion_promotion`;
- promotion attempt and freeze epoch IDs;
- source and target database-incarnation digests;
- exact artifact-set digest and all promotion/performance/quarantine policy versions;
- candidate seal, source reconciliation, qualification observation/receipt, performance
  ratification, both backup, both restore, zero-block, and quarantine-acceptance digests;
- exact environment, deployment/build digest, endpoint provider/revision and intended destination;
- authenticated approver subject, issuer, audience, key ID, change reference, and separation-of-duty
  evidence;
- `issued_at`, `not_before`, `expires_at` with at most 30 minutes validity;
- canonical payload digest and detached asymmetric signature.

The trust policy pins issuer, audience, algorithms, and active public keys outside operator-writable
source/target tables. The signing key stays in the IAM/deployment approval system. A self-computed
SHA-256 digest is integrity evidence, not approval authenticity.

Authorization admission and consumption run in one `SERIALIZABLE` control-database transaction.
Authorization ID and nonce are globally unique; consumption is unique per authorization and bound
attempt. Exact replay of the same request ID and attempt is idempotent. Any reuse for a different
attempt, database, clone, environment, deployment, artifact set, or state is persisted and rejected
as `authorization_replayed`. Expiry, revocation, candidate seal, state version, and environment
fencing generation are rechecked in that transaction.

### 8.2 Irreversible target activation

Endpoint switching occurs while both databases are write-disabled and is covered by the promotion
authorization. After `phase5c_post_cutover_verification_receipt_v1` passes, a distinct
`phase5c_target_activation_authorization_v1` binds that receipt, the original promotion
authorization, route observations, target identity, attempt/generation, and a validity of at most
15 minutes.

Before any external grant is changed, the control database atomically records
`TARGET_ACTIVATION_REQUESTED` and `divergence_state = possible`. This is the conservative point of
no return. A crash after this commit but before target grants are enabled may cause unnecessary
forward-only handling, but can never cause unsafe source cutback. The executor then grants target
runtime access, confirms every application pool uses the target, and reconciles
`PROMOTION_COMPLETED`. There is no automatic source re-enable path after activation is requested.

Cutback requires a separate `phase5c_cutback_authorization_v1`; promotion authorization cannot be
replayed for it.

## 9. Promotion state machine

### 9.1 Authoritative state tuple

A single enum cannot represent partial external effects. Each attempt persists:

```text
workflow_state
source_write_mode = active | draining | frozen | retired
target_write_mode = isolated | maintenance | active | quarantined
route_state = source | target | split | unknown
divergence_state = none | possible | confirmed
maintenance_required = true | false
environment_generation
state_version
```

The current projection is mutable only through fixed-search-path security-definer transition
routines. Every accepted or rejected command appends an immutable hash-chained event in the same
transaction. External backup, restore, deployment, and route changes use an intent/effect saga:
persist desired action and idempotency key, call the provider, then persist independently observed
outcome. No external acknowledgement is treated as a distributed database commit.

### 9.2 Normal path

```text
CREATED
  -> PREFLIGHT_PASSED
  -> MAINTENANCE_REQUESTED
  -> WRITES_DRAINING
  -> WRITES_DRAINED
  -> SOURCE_FROZEN
  -> CANDIDATE_PREPARING
  -> FINAL_SOURCE_VERIFIED
  -> BACKUP_COMPLETED
  -> RESTORE_EVIDENCE_ADMITTED
  -> PROMOTION_AUTHORIZED
  -> SWITCH_REQUESTED
  -> ENDPOINT_SWITCHED
  -> POST_CUTOVER_VERIFYING
  -> POST_CUTOVER_VERIFIED
  -> TARGET_ACTIVATION_REQUESTED
  -> PROMOTION_COMPLETED
```

`CANDIDATE_PREPARING` creates the final clone from the frozen source, runs the unchanged Phase
5C1/5C2 flow and restart verification at 0017 with their existing separate attestations, applies
schema-only 0018 with the target fence closed, runs final independent qualification at 0018, and
seals the candidate. The source remains frozen throughout.

Safety holds and terminal branches are:

```text
SWITCH_OUTCOME_UNKNOWN
RECOVERY_HOLD
CUTBACK_INITIATED -> CUTBACK_SWITCH_REQUESTED -> CUTBACK_ROUTE_CONFIRMED
                  -> SOURCE_WRITES_RESTORED -> CUTBACK_COMPLETED
FORWARD_RECOVERY_REQUIRED
FAILED_TERMINAL
```

### 9.3 Transition contract

| Transition | Authority / effect | Transactional | Retry / restart | Irreversible |
| --- | --- | --- | --- | --- |
| create -> preflight | automatic strict evidence/tooling/role/provider checks | control DB | exact rerun; close on deterministic mismatch | no |
| preflight -> maintenance requested | promotion executor with change window | control DB intent first | idempotent | no |
| maintenance -> writes draining/drained | automatic deploy drain and bounded session drain | external saga | retry until deadline; timeout holds maintenance | no |
| writes drained -> source frozen | automatic after privilege/reconnect denial and freeze receipt | source effect, then control reconciliation | inspect grants/sessions/root on restart | no |
| source frozen -> candidate preparing | executor starts unchanged Phase 5C commands on fresh clone | checkpointed external work | existing restart guarantees | no |
| candidate preparing -> final source verified | automatic read-only qualification, seal, and reconciliation | snapshot-local | deterministic rerun; mismatch requires new attempt | no |
| final verified -> backups complete | automatic provider requests after persisted intents | external saga | same idempotency key; ambiguous result reconciled | no |
| backup -> restore admitted | automatic exact disposable restores and validation | external saga | fresh restore identity per retry | no |
| restore -> promotion authorized | signed approver artifact and one-use consumption | serializable control DB | new authorization if expired; no timestamp refresh | no |
| authorized -> switch requested | executor; provider CAS intent persisted first | external saga | observe route before retry | no |
| switch -> endpoint switched | automatic only after all route/pool identity observations | external saga | unknown/split goes to safe hold | no, while target fenced |
| endpoint switched -> verified | automatic bounded read-only suite | target snapshot + control event | discard partial output and rerun | no |
| verified -> activation requested | distinct signed activation approval | control DB before grants | reconcile target grants on restart | **yes: simple cutback ends** |
| activation requested -> completed | automatic grant/readiness/route reconciliation | external saga | forward-only reconciliation | yes |
| pre-activation -> cutback initiated | separate signed cutback approval | control DB | idempotent | no |
| cutback route -> source writes restored | source revalidation, route confirmation, source grant last | external saga | inspect actual grants and route | ends attempt |

At most one nonterminal attempt exists per environment. Each command supplies attempt ID, expected
state version, environment generation, request ID, and relevant authorization digest. Stale
callbacks from an older generation are recorded and ignored. Advisory locks may reduce contention
but never replace these durable constraints.

### 9.4 Crash interpretation

- Before source freeze, inspect the ledger and actual service state; normal traffic may resume only
  through an explicit aborted/cutback transition.
- During drain/freeze, grants, pooler rules, and live sessions are authoritative, not the last enum.
- From source freeze through activation, the safe default is maintenance with both databases
  write-disabled; evidence work may resume on the exact attempt.
- During switch, route is `unknown` until configured and live observations agree. Never blindly
  repeat a switch after an acknowledgement timeout.
- During verification, partial results have no authority; rerun the bounded suite.
- During activation, a durable `divergence_state = possible` or observed target grants forces
  forward recovery even if control-plane acknowledgement was lost.
- During cutback, source writes are restored last. Any ambiguous route leaves both databases frozen.

## 10. Database schema and migration design

### 10.1 Migration boundary

Keep the converter, restart path, and performance harness locked to `0017_phase5c_indexes`. Only
after conversion and restart verification complete, apply the PostgreSQL-only application revision
`0018_phase5c_promotion_prerequisites`. It must not update a domain, archive, or conversion-evidence
row. It adds target identity, a closed write fence, and immutability enforcement. Run independent
qualification again at 0018 before producing the candidate seal.

The qualifier implementation becomes `phase5c_independent_qualifier_v2` solely to admit and verify
the exact 0018 promotion schema and closed fence. Its independent queries and
`phase5c_conversion_qualification_receipt_v1` shape remain unchanged. A receipt produced before
0018 is not promotion evidence. The performance harness remains at 0017 and keeps its existing
manifest; the ratification binds a reviewed v1-to-v2 qualifier compatibility contract because 0018
does not alter the measured conversion path.

Create a separate Alembic configuration and version table for the operations control database:

1. `ops_0001_phase5c4_evidence` creates digest/identifier domains, immutable artifact/evidence
   tables, and `pgcrypto` in the control database for database-enforced digest/event checks.
2. `ops_0002_phase5c4_workflow` creates environments, attempts, transition requests, external
   actions, authorizations/consumption, and append-only events.
3. `ops_0003_phase5c4_enforcement` creates immutable-row triggers, fixed-search-path transition
   routines, grants, partial unique indexes, and audit anchoring/outbox support.

Migrations run as a `NOLOGIN` schema owner. Direct DML is revoked from collectors, approvers,
executors, and the application. Executors receive only `EXECUTE` on narrowly scoped routines;
readers receive explicit views. Production downgrade is disallowed once evidence exists. Empty
test databases may downgrade in dependency order.

The application and control databases cannot have PostgreSQL foreign keys to one another.
Cross-plane integrity is enforced by canonical digest binding plus live application-database
re-query at authorization, switch, and activation. The specification must not claim a cross-database
FK.

### 10.2 Application data-plane tables and hardening

Revision `0018_phase5c_promotion_prerequisites` creates:

| Table | Essential columns and constraints | Lifecycle / ownership / indexes |
| --- | --- | --- |
| `phase5c_promotion_target_identity` | Singleton key `CHECK = 1`; identity version; unique target instance ID and nonce; archive identity; unique conversion run ID; marker and clone-identity digests; initialized time; unique identity digest. Composite `ON DELETE RESTRICT` FKs bind metadata `(archive_identity, marker digest, clone identity)` and run `(id, archive identity, marker digest)`. | Insert once through a fixed-search-path routine; no update/delete/truncate. Owned by `NOLOGIN` owner, unreadable/unwritable by clients. Unique digest and binding indexes. |
| `phase5c_write_fence_state` | Target-instance PK/FK; monotonic epoch; mode in `closed_prequalification`, `closed_cutover`, `open_production`, `closed_incident`, `retired`; attempt/auth/artifact digests with mode-shape checks; last-event digest; server time. | Sole mutable target projection, only through transition routine. Runtime may read mode through a safe function, never update. |
| `phase5c_write_fence_events` | PK `(target_instance_id, epoch)`; unique event and command IDs; attempt; from/to modes; authorization/artifact-set digests; previous/event digests; server time; target FK RESTRICT. | Append-only. Index event/command/attempt. Transition routine locks state, checks expected epoch/mode, appends event, and updates projection atomically. |

A statement-level gate trigger covers every table on which the application role has
`INSERT`, `UPDATE`, or `DELETE`. Missing identity/fence rows or any mode other than
`open_production` raises a stable maintenance error. A migration assertion and recurring test fail
if an application-DML-granted table lacks the trigger. DDL, ownership, superuser, bypass, archive,
and promotion-control privileges are absent from the runtime role.

The fence is initialized `closed_prequalification`, remains closed through final 0018
qualification, endpoint switch, and read-only smoke, and opens only after control-plane divergence
is durably marked possible. Fence state/events are bound separately from the qualified domain root.

The same migration hardens existing terminal evidence:

- clone marker, conversion metadata, target identity, and archive bridge metadata become immutable;
- run binding fields are always immutable and a completed/verified or failed run cannot regress;
- outcome plan/binding fields are immutable and completed/verified or failed outcomes cannot regress;
- archived Recipes and ingredients in every registered archive schema reject update/delete/truncate;
- Daily Logs are not blanket-frozen because normal product semantics may edit/delete them; their
  historical snapshots and qualified roots keep the existing invariants.

The 0018 downgrade succeeds only when identity/fence/event tables are empty and hardening has never
been initialized; otherwise it fails explicitly. A qualified or promoted target is forward-only.

### 10.3 Common constraints

All UUIDs are server-generated. All time is `timestamptz` from control-database time. SHA-256
columns use a domain/check matching exactly 64 lowercase hexadecimal characters. Bounded identity,
type, reason, and version strings use restrictive checks; arbitrary exception text is not stored.
Every foreign key uses `ON DELETE RESTRICT`. Immutable tables reject `UPDATE`, `DELETE`, and
`TRUNCATE` through privileges and triggers. Every canonical artifact has a unique digest and byte
count; typed evidence tables reference that artifact so cross-artifact relations are enforced by
foreign keys and repeated digest columns are not free-form copies.

### 10.4 Control-plane tables

| Table | Essential columns and database rules | Lifecycle and indexes |
| --- | --- | --- |
| `phase5c4_database_instances` | instance UUID, role, environment, safe/physical/provider identity fields and digests, target nonce when applicable, system identifier, database OID, marker/archive/run bindings | Immutable. Unique physical identity digest; indexes environment/role and marker. Endpoint identity is routing evidence, not incarnation identity. |
| `phase5c4_artifacts` | `id`, type, version, canonical `bytea`, DB-computed digest, byte count, immutable object ID/version, ingest actor/time, signature metadata, optional database-instance FK; unique `(type, version, digest)` and object version; bounded sizes | Immutable. Index type/version and ingest time. Object deletion forbidden by retention policy. |
| `phase5c4_artifact_bindings` | artifact FK + binding name PK; exactly one typed digest/UUID/text/integer/time value by CHECK | Immutable. Indexed by binding name/value. Finalization compares normalized plan/inventory/marker/run/receipt/schema/root bindings in SQL. |
| `phase5c4_artifact_sets` | `id`, set version, environment, source/target incarnation digests, deployment digest, set digest; unique set digest | Immutable. Index environment/target. |
| `phase5c4_artifact_set_members` | set FK, artifact FK, logical role, ordinal; PK `(set_id, logical_role, ordinal)`, unique `(set_id, artifact_id)` | Immutable. Singleton-role uniqueness enforced with partial unique indexes. |
| `phase5c4_candidate_seals` | artifact FK/PK, target incarnation, qualification artifact FK, schema revision, protected-root version/digest, snapshot anchor, timeline, LSN, observed time | Immutable. Unique `(target_incarnation_digest, protected_root_digest)`. Index observation time. |
| `phase5c4_performance_contracts` | artifact FK/PK, contract version, tier, rules digest, source manifest FK, component-set digest, ratifier/issuer, effective time; unique contract version/digest | Immutable. Revocation is a new row in `phase5c4_contract_revocations`; active lookup indexed by version. |
| `phase5c4_quarantine_acceptances` | artifact FK/PK, plan artifact FK, qualification FK, outcome-ledger digest, subject-set digest/count, reason-count digest, policy, expiry, approver/signature | Immutable. Unique plan+ledger+set; count > 0. Index expiry. Zero quarantine needs no row. |
| `phase5c4_quarantine_subjects` | acceptance FK, source Recipe UUID, reason code, source checksum; PK `(acceptance, source_recipe_id)` | Immutable. Finalizer checks child count and canonical set/reason digest. No ordinary summary access. |
| `phase5c4_backup_evidence` | artifact FK/PK, attempt FK, role, database incarnation, system ID, timeline, native `pg_lsn` start/end/archive positions, state-seal FK, provider/backup unique ID, completed time, result fixed to passed | Immutable. Unique provider/backup ID and `(attempt, role, artifact)`. Index attempt/role/time. Failures are events, not passing evidence rows. |
| `phase5c4_restore_receipts` | artifact FK/PK, backup FK, restore identity, requested/achieved `pg_lsn`, timeline, observed root, check-set version, completed time, result fixed to passed | Immutable. Restore identity must differ from live identities. Unique test ID and backup+restore identity. |
| `phase5c4_environments` | environment PK, fencing generation, maintenance flag, route state, source/target write modes, divergence state, active deployment digest, state version | Mutable current projection only through routines. Checks reject dual-write tuples and `maintenance=false` with unknown/split route. Row locked for every transition. |
| `phase5c4_attempts` | attempt ID, environment FK, generation, workflow state, source/target incarnations, artifact-set FK, policy version, current authorization FK nullable, state version, created/terminal times | Mutable projection only through routines. Partial unique indexes allow one nonterminal attempt per environment and per target. Terminal rows cannot reopen. |
| `phase5c4_transition_requests` | request UUID, attempt FK, command, request digest, expected/observed state versions, result/reason/retryable, actor, timestamps | Append-once result. Unique request ID; same ID with a different digest is a conflict. Index attempt/time. |
| `phase5c4_external_actions` | action ID, attempt FK, kind, idempotency key, expected provider revision, request digest, provider operation ID, status, observation digest/time | Status advances monotonically by routine. Unique `(kind, idempotency_key)` and provider operation ID. Index pending/unknown actions for restart reconciliation. |
| `phase5c4_authorizations` | artifact FK/PK, auth type, authorization ID, nonce, bound attempt/environment/generation/artifact set, source/target/deployment, issued/not-before/expires, issuer/audience/key/signature | Immutable. Globally unique authorization ID and nonce. Strict auth-type checks. Index expiry and bound attempt. |
| `phase5c4_authorization_consumptions` | authorization FK/PK, attempt FK, request FK, state/version at consumption, consumed time/actor | Immutable one-row consumption. A second attempt cannot reference the authorization. |
| `phase5c4_verification_runs` / `phase5c4_verification_checks` | run binds attempt, verifier, schema, endpoint/fence/root and final result; child PK `(run, check_name)` with exact check-name allowlist and evidence digest | Immutable after finalization. Finalizer requires every required check exactly once and passing before post-cutover-verified state. |
| `phase5c4_events` | attempt FK, sequence, event ID, prior/new state tuple, request/actor, evidence digest, result/reason, previous-event digest, event digest, database time | Append-only. PK `(attempt, sequence)`, unique event ID and event digest. Trigger verifies sequence and hash chain. Index environment/time and reason. |
| `phase5c4_audit_outbox` | event FK/PK, immutable anchor payload digest, delivery state, sink receipt/digest | Delivery projection may advance monotonically; event/payload never change. Unique sink receipt. Undelivered index. |

Typed tables for clone-origin, qualification observation, source reconciliation, zero-block, route,
post-cutover verification, activation, cutback, and recovery receipts use the common artifact registry
and artifact-set membership. Their decision fields are also projected into attempts/events and
validated before the transition, avoiding a second family of loosely synchronized mutable tables.

Database transition routines enforce the allowed state graph, expected state version, environment
generation, evidence FKs, freshness, authorization consumption, and event append in one transaction.
The application cannot write `maintenance_required` or any promotion state.

### 10.5 Data-plane role migration

The deployment also needs a separately reviewed role/grant migration before the first exercise:

- a `NOLOGIN` owner/migration role owns schemas and objects;
- a non-owner runtime login receives only required table, sequence, and function privileges;
- a read-only verifier role cannot execute user-creating or mutating functions;
- an operations role may change runtime grants and inspect sessions but cannot alter evidence;
- archive-schema privileges are absent from the runtime role; and
- default privileges preserve this split for later migrations.

The role migration must inventory and reproduce every existing grant and ownership before changing
anything. Preflight rejects a source on which the runtime login still owns objects or can inherit a
write-capable owner role.

## 11. Operator command and API contract

Phase 5C4 uses a CLI plus narrow authenticated adapters for backup/restore and deployment routing.
It adds no public or internal promotion route to FastAPI. If remote orchestration is later needed,
it must be a separate mTLS/OIDC operator service invoking the same database routines.

One module, `scripts.manage_phase5c_promotion`, exposes bounded subcommands:

| Command | Contract |
| --- | --- |
| `ingest-evidence` | Atomically ingest canonical bytes once, validate strict shape/digest, register immutable object/version |
| `preflight` | Read-only artifact graph, role/grant, provider, tier, auth, route, RPO/RTO, and drill admission; optional audited dry run |
| `request-maintenance` | Persist maintenance intent/gate with request ID and expected state version |
| `drain-writes` | Observe deployment queues/pools/transactions and persist a bounded drain receipt |
| `freeze-source` | Revoke/fence runtime writes, terminate sessions, denied-write probe, capture freeze epoch/root |
| `prepare-candidate` | Clone frozen source; run existing conversion/restart at 0017; apply schema-only 0018; run final independent qualification with fence closed |
| `verify-final-source` | Create candidate seal, zero-block receipt, and exhaustive source/candidate reconciliation |
| `create-backup` / `verify-restore` | Invoke approved adapter, then independently admit exact evidence |
| `admit-authorization` | Verify signed promotion/activation/cutback artifact; signer is external |
| `switch-endpoint` | Persist intent, call provider CAS with idempotency key, then observe route/pools |
| `verify-post-cutover` | Run bounded, explicitly read-only suite and emit its receipt |
| `activate-target` | Consume activation authorization, mark divergence possible, then enable/reconcile target runtime |
| `cutback` | Only pre-activation; keep target fenced, route source, reverify, enable source last |
| `recover-forward` | Record and reconcile separately authorized PITR/forward-repair actions |
| `status` / `resume` | Show safe state or reconcile external actions; never infer success from intent |
| `export-evidence` | Export manifest/digests and WORM anchor receipts without secrets or authored content |

Mutating commands require `--attempt-id`, `--request-id`, and `--expected-state-version` and derive
operator identity from the authenticated session. Database URLs, credentials, bearer tokens, and
private keys come from workload identity/secret manager or protected environment/file descriptors,
never command arguments or artifacts. TLS verification is mandatory. Local artifact output is
atomic mode 0600, no-overwrite, regular-file-only, and size-bounded.

Machine output is strict canonical JSON with `contract_version`, command, attempt, prior/current
state, result, bounded reason code, retryable flag, maintenance-required flag, and safe evidence
digests. Human output is derived from it. Raw SQL, URLs, exceptions, authored Recipe text, user
identity data, and OCR content are excluded.

Stable exits are:

| Exit | Meaning |
| ---: | --- |
| 0 | success or exact idempotent replay |
| 2 | usage or unsupported contract |
| 3 | evidence/admission/freshness failure |
| 4 | authentication, signature, expiry, revocation, or authorization failure |
| 5 | replay, stale version, concurrent attempt, or provider conflict |
| 6 | retryable infrastructure/provider failure with safety state retained |
| 7 | verification failure; maintenance remains active |
| 8 | unsafe/terminal condition requiring manual or forward recovery |
| 9 | bounded unexpected internal failure; no automatic safety release |

Dry run performs reads and validation only, never consumes authorization or calls a mutating
provider. It still creates an audit event in the control database. Exact idempotent repeats return
the original result; changed parameters under the same request ID fail with `request_conflict`.

## 12. Post-cutover verification

Endpoint switch is performed with source and target runtime roles fenced. Application processes are
replaced so the process-global SQLAlchemy engine and all connection pools use the target direct
identity. Configured route state is insufficient: every instance/pool and multiple ingress
vantage points must report the same target incarnation and deployment digest.

`phase5c_post_cutover_verification_v1` is bounded and read-only. It verifies:

1. route provider revision, live target identity, database incarnation, Alembic revision 0018, and
   application build digest;
2. liveness 200 and expected maintenance readiness 503;
3. availability and digests of the complete immutable artifact set;
4. candidate state root still equal to the qualification seal;
5. conversion metadata/run/outcome cardinality and qualification/receipt bindings;
6. a deterministic sample of converted Recipes covering nested dependencies, `needs_republish`,
   first/last/hash-selected subjects, immutable revision digests, and compatibility projections;
7. deterministic Daily Log reads across owners/dates/authority types, including immutable nutrient
   snapshots and Recipe resolution against the recorded revision;
8. deterministic OCR parse/correction/confirmation provenance reads;
9. ownership isolation through direct anomaly checks and authenticated cross-owner denial;
10. runtime denial of archive-schema access and all target writes;
11. no runtime connection to the retired source and unchanged source frozen root; and
12. target endpoint and connection routing confirmation from all instances.

The sample contract is versioned and selected only from qualified ledger identities. It uses at
least 20 and at most 50 converted subjects when available, plus up to 20 Daily Log and 20 OCR chains,
while explicitly including each relevant authority/edge category. Empty categories are reported,
not fabricated. These checks do not replace or rerun full historical qualification.

Smoke requests use a database role proven read-only and set private-user auto-creation off. In the
current application, authenticated GET handling may create the configured private user, so an
ordinary authenticated client is not presumed read-only until this behavior is disabled or the
canary identity already exists and database writes are impossible.

Any failed or incomplete check leaves maintenance active and target writes denied. Only a complete
receipt may be used by activation authorization. After activation, readiness must become 200 and
all instances must still report the target; this reconciliation does not re-open cutback.

## 13. Cutback, restore, forward recovery, and incidents

### 13.1 Simple cutback

Simple cutback means routing back to the unchanged frozen source and re-enabling its runtime role.
It is permitted only when all of the following are proven:

- `divergence_state = none` and `TARGET_ACTIVATION_REQUESTED` has never committed;
- target writes were continuously denied by the database/infrastructure barrier;
- source remains frozen and its logical root equals the freeze receipt;
- both databases are currently write-disabled;
- the endpoint adapter can compare-and-swap target/unknown to the exact source identity;
- a signed cutback authorization binds the attempt, route observation, source/target seals, and
  cutback policy.

Cutback persists intent, switches the route, replaces/drains target-connected processes, proves
all pools use the source, rechecks the source root, and restores source privileges **last**. A
crash or ambiguous route leaves both databases disabled. Cutback does not delete the candidate or
its evidence.

### 13.2 After target activation

Once `TARGET_ACTIVATION_REQUESTED` commits, divergence is conservatively `possible` even if no
business write has yet been observed. Simple source cutback is rejected and recorded as a security
incident. The old source is forensic/cutback evidence, not a production recovery target.

A post-activation failure immediately returns the target deployment to maintenance and blocks new
writes. Recovery choices are:

1. **Forward repair:** deploy a bounded corrective application/schema/configuration change against
   the target while preserving all committed target data.
2. **Target PITR/restore:** restore the promoted-target recovery seed to a new isolated incarnation,
   replay the target WAL on the correct timeline through the policy recovery point, verify all
   acknowledged writes and invariants, issue new recovery/promotion evidence, and forward-switch.
3. **Manual incident response:** when completeness, acknowledged-write recovery, identity, WAL,
   or ownership cannot be proven, remain in maintenance and require incident command, data-owner,
   database, security, and release-safety approval. No automated destructive action is permitted.

Restoring only the pre-cutover target image loses production writes and is not recovery unless the
declared RPO explicitly permits that loss and every acknowledgement after the recovery point is
accounted for. The design should normally require zero acknowledged-write loss.

### 13.3 Partial promotion and restart

Every external action has a durable desired state, idempotency key, provider operation identifier,
and independently observed result. `resume` first reads source/target grants, sessions, route,
deployment revision, backup/restore jobs, and control state. It never repeats a switch, grant, or
restore request solely because the prior process did not record an acknowledgement.

Evidence retained for every incident includes the complete artifact set, authorization and
consumption, state/event chain and external WORM anchors, database identities/seals, session/grant
censuses, backup/restore manifests, WAL/timeline evidence, route/deployment observations, smoke
receipts, bounded errors, monitoring snapshots, communications timeline, and attempted unsafe
commands. Retention is at least as long as the historical archive and any legal/incident hold.

## 14. Archive lifecycle boundary

Phase 5C4 never deletes, compacts, rewrites, anonymizes, or changes privileges to enable ordinary
runtime access to the archive. Every completion receipt carries `archive_hold_required = true`.
Promotion success is not archive-deletion eligibility.

A later archive-lifecycle phase may only **consider** cleanup after it has all of:

- Phase 5C4 promotion completion and post-cutover stabilization evidence;
- the policy-defined soak interval and repeated reconciliation/retention audits;
- no unresolved incident, legal hold, blocked subject, or unaccepted quarantine;
- an explicit disposition for every quarantine and proof no current read or repair path still
  depends on the archive;
- successful target backup/PITR restoration including the archive;
- immutable Daily Log, Recipe revision/projection, OCR provenance, ownership, and archive checksum
  audits after the soak;
- a records-retention/legal policy and data-owner approval;
- a separate versioned cleanup plan, dry-run manifest, authorization, backup, restore, and rollback
  design; and
- independent qualification of the cleanup result.

Those facts merely admit a later design review. They do not authorize deletion in Phase 5C4.

## 15. Failure matrix

In this table, “maintenance” means readiness 503 and both databases write-disabled unless the row
explicitly occurs before the maintenance request.

| Failure | Detection and persisted state | Retryability / operator action | Maintenance / resume |
| --- | --- | --- | --- |
| Required artifact missing | Strict artifact-role cardinality fails; admission event `evidence_missing` | Add exact immutable artifact; create a new set digest | Before window: normal service. After freeze: maintenance; resume preflight on same attempt if artifact predates freeze appropriately |
| Unsupported version/shape | Strict parser rejects unknown field/version | Implement/review support or regenerate with supported producer; no manual edit | State unchanged; no promotion resume until new artifact set |
| Digest/cross-binding disagreement | Canonical digest or graph FK/equality check fails; terminal evidence event | Investigate tampering/wrong bundle; ingest new canonical set/new attempt | Maintenance if already requested; never waive |
| Stale qualification/backup/restore | Control DB time exceeds policy or freeze epoch differs | Requalify/reseal or create and restore fresh exact backups; never alter timestamps | Remains frozen; may resume only with new bound evidence/authorization |
| Target drift after qualification | Recomputed protected root differs from candidate seal | Quarantine candidate, investigate, create fresh frozen clone and evidence | Maintenance; current attempt terminal |
| Source mutation after freeze | Source root/session/audit evidence changes | Incident; re-establish freeze, discard candidate and all derived evidence | Maintenance; new freeze epoch/attempt required |
| Maintenance gate fails | Gate read/write or readiness negative test fails | Repair control/readiness path; do not drain | Service may remain source-active only if source barrier was never changed; otherwise maintenance |
| Writes do not drain | Active transaction/session/reconnect exceeds deadline | Find owner, stop worker/pool, retry bounded drain or cut back/abort | Maintenance once requested; resume drain only |
| Runtime role owns objects | Preflight ownership/grant inventory | Complete separately reviewed role migration | Before window only; promotion blocked |
| Backup provider failure | Failed/unknown provider action event; no passing evidence row | Reconcile unknown ID; retry with same key or new immutable backup attempt | After freeze, maintenance; resume backup step |
| WAL gap/manifest tamper | Archive/manifest/verify failure | Repair pipeline and create a new backup; same backup permanently inadmissible | Maintenance; no authorization |
| Restore test infrastructure failure | Restore attempt fails before content conclusion | Retry exact immutable backup in a fresh isolated identity | Maintenance; resume restore step |
| Restore content/identity/LSN failure | Root, system/timeline, manifest, or target-LSN mismatch | Investigate backup chain; create new backup | Maintenance; failing evidence never reused |
| Authorization expires before switch | Database-time check fails; no consumption | Approver issues a new exact authorization after all freshness checks | Maintenance; resume authorization |
| Promotion authorization expires after switch | Activation cannot use it; route remains target but fenced | Revalidate state and issue distinct activation authorization | Maintenance; cutback still eligible before activation |
| Concurrent promotion | Partial unique index/state-version conflict; loser event recorded | Loser stops; inspect winning attempt | Winning state governs maintenance; loser cannot resume |
| Preflight process crash | Durable request absent/partial artifact ingestion reconciled by digest | Repeat exact preflight/request | Normal service unless maintenance already requested |
| Crash during maintenance request | Gate/ledger inspected; never infer from client result | Reissue same request ID or reconcile | If gate durable, maintenance; otherwise source-active |
| Crash during drain/freeze | Inspect actual grants, pools, sessions, denied-write probe, roots | Continue drain or explicit abort; never mark frozen from enum alone | Fail-safe maintenance |
| Crash during candidate conversion | Existing Phase 5C checkpoints and exact execution authorization inspected | Resume unchanged converter/qualifier or fail candidate | Source remains frozen; same attempt only |
| Crash during backup/restore | Query provider by immutable operation ID | Reconcile result, then same-key retry if provider proves no completion | Maintenance |
| Crash after authorization consumption | Consumption/state event in same transaction decides | Continue exact attempt; authorization cannot be re-consumed elsewhere | Maintenance; resume switch if still fresh |
| Crash during endpoint switch | Route becomes `unknown`; inspect provider, instances, pools, connections | Same-key reconcile; never blind switch replay | Both DBs fenced; maintenance |
| Split routing/old pools | Config/live identity observations disagree | Stop/restart instances, fence both, reconcile CAS | Maintenance; verify only after unanimous target/source route |
| Switch succeeded, verification failed | Complete/partial smoke result; partial never authorizes | Before activation, signed simple cutback or fix and rerun read-only suite | Maintenance; cutback eligible only with continuous fence proof |
| Crash during post-cutover verification | No complete receipt exists | Discard partial results and rerun entire bounded suite | Maintenance; cutback remains eligible |
| Target write observed before activation | Root/grant/audit mismatch; `FORWARD_RECOVERY_REQUIRED` | Incident and forward recovery; investigate privilege breach | Maintenance; simple cutback forbidden |
| Crash during activation | Durable divergence flag and actual target grants inspected | If activation requested/grants possible, forward-only reconciliation | Maintenance until target state proven; no simple cutback |
| Late blocked subject | Plan/outcome/qualification/target queries disagree or count > 0 | Terminal candidate rejection; no override/relabel | Maintenance; new candidate/plan as separately allowed |
| Quarantine set changes/unaccepted | Acceptance set/count/reasons/expiry mismatch | New data-owner acceptance for exact qualified set | Maintenance; no promotion resume until accepted |
| Incompatible schema | Conversion is not exact 0017 or promotion target is not exact 0018; schema fingerprint differs | Restore/rebuild correct candidate; no stamping | Maintenance; current candidate inadmissible |
| Artifact/signature tampering | Digest/signature/issuer/key/revocation/anchor check fails | Security incident; preserve bytes; new trusted artifact/attempt | Maintenance; never retry altered artifact |
| Attempted authorization replay | Unique nonce/ID or bound-context check fails | Security review; use a newly signed authorization if legitimate | State unchanged; replaying caller cannot resume |
| Cutback attempted after divergence possible | Transition routine rejects and records incident | Forward recovery/manual response only | Maintenance; source stays retired/frozen |
| Control database unavailable | Gate/ledger/transition cannot be read/committed | Restore control service; no state-changing operator action | Readiness/mutations fail closed; resume from durable ledger |
| Audit anchor unavailable | Outbox remains undelivered and policy alert fires | Restore sink; policy decides bounded wait before switch | Maintenance at authorization/switch boundary; no silent loss |
| Endpoint provider lacks CAS/readback | Preflight adapter capability failure | Implement supported adapter/change provider | Before window; promotion blocked |
| Performance tier unratified | Frozen dimensions exceed active contract | Run/ratify required tier under a new contract | Maintenance should not be opened if preflight was complete; otherwise abort/cutback |
| Production auth unavailable | Release configuration/provider and ownership smoke preflight fail | Install and qualify real production authentication or limit to explicitly approved private deployment | Public production promotion blocked |
| Crash during cutback | Observe both routes/grants; source enable never assumed | Continue same cutback key; source enable last | Both DBs fenced until route/source seal proven |
| Post-activation target failure | Readiness/alerts fail with divergence possible | Fence target, forward repair or target PITR preserving writes | Maintenance; promotion resumes only as a new forward-recovery operation |

Deterministic admission, tamper, replay, and impossible-state failures are not made retryable by
wrapping them in a new command. Transient provider failures are retryable only under their persisted
idempotency key and after actual-state reconciliation.

## 16. Test and operational qualification plan

### 16.1 Deterministic automated tests

**Contract/unit tests** cover strict shapes, canonical JSON/digests, exact version allowlists,
artifact slot cardinality, normalized cross-bindings, tier selection, the 25/68/20/37 equality
contract, freshness, state transitions, reason/exit codes, redaction, sample selection, and every
impossible state tuple.

**Migration tests** cover:

- empty 0001-to-head and 0017-to-0018 upgrades, one application head, and empty downgrade/reupgrade;
- completed populated 0017 candidate to 0018 with identical pre/post domain, archive, and conversion
  counts/roots, including custom archive schemas;
- the unchanged populated-0003 guard against destructive migration 0004;
- final qualification only at 0018 with the target fence closed; a pre-0018 receipt is not promotion
  evidence, while conversion/restart remains exact at 0017;
- introspection of every FK, uniqueness/check constraint, index, trigger, validated constraint, role,
  and grant;
- blocked downgrade after identity/fence/evidence initialization; and
- independent control-plane migration history and forward-only behavior after first evidence.

**PostgreSQL integrity tests** attempt invalid digest lengths/case, composite identity mismatches,
duplicate singletons/slots/nonces/commands, invalid time/LSN/state shapes, direct mutation/truncate
of immutable rows, terminal run/outcome regression, archive mutation, unauthorized table access,
and use of a source/target endpoint with a replaced database incarnation. PostgreSQL—not only the
Python validator—must reject them.

**Fence and maintenance tests** prove missing/closed fence fails writes, every app-DML table is
gated, open permits expected writes, transition compare-and-swap is atomic, source role revocation
survives reconnect attempts, maintenance readiness is 503 while liveness remains 200, and failure
to read the control gate fails closed. Two concurrent opens create one fence event. A schema test
fails whenever a newly writable table lacks a gate trigger.

**Concurrency/replay tests** run two promotions for one environment, two consumers for one
authorization, stale state versions/generations, duplicate provider callbacks, same command/same
digest idempotency, same command/different digest conflict, and replaced endpoint identities. The
database constraints must select one winner without two active attempts or two consumptions.

**Crash/restart tests** inject failure immediately before and after every state/event/current-row,
authorization-consumption, fence-transition, backup/restore intent, switch intent/effect, smoke
finalization, activation, and cutback boundary. Each proves transaction rollback or exact observed
resume; none infers external success from a missing acknowledgement.

**Tamper/security tests** cover modified/truncated/reordered/duplicated/substituted artifacts,
file replacement between preflight/use, unknown/revoked keys and algorithms, wrong issuer/audience,
expired/replayed authorization, cross-attempt/environment/clone/deployment reuse, candidate mutation
after authorization, direct promotion-table DML, advisory-lock impersonation, WORM anchor mismatch,
block relabeling, quarantine omission, and unsafe cutback after divergence.

**Backup/restore simulations** cover wrong/incomplete backup, checksum corruption, missing WAL or
timeline history, same LSN on another system, recovery target not reached, schema/root/FK mismatch,
different restore identity, provider timeout/acknowledgement loss, and successful exact restore.

**Endpoint and smoke simulations** use a fake CAS/readback provider to exercise no-op, partial,
split, lost-ack, stale callback, old-pool, target-unreachable, and switch-success/verification-fail
cases. The read-only suite proves it creates no user, cache, idempotency, or domain row.

**Cutback/recovery tests** demonstrate safe source cutback before activation, automatic refusal
after activation request, forward repair, and target PITR replay through post-promotion writes.

### 16.2 Environment-specific production exercises

The following cannot be replaced by mocks or ordinary pytest:

- production-like runtime role separation, grants, pooler/firewall fence, session drain, and
  reconnect denial;
- final-clone creation duration and the total maintenance window at the applicable data tier;
- exact managed backup, encryption/KMS/storage/retention, WAL archive, disposable restore, and
  measured RTO/RPO;
- real endpoint CAS/readback, propagation, instance replacement, pool drainage, and multi-vantage
  identity confirmation;
- production authentication/ownership isolation canaries and read-only smoke behavior;
- a pre-activation verification failure followed by safe cutback;
- an activation followed by simulated target failure and forward/PITR recovery without using the
  source;
- control-database loss/failover and WORM audit anchoring;
- incident command, customer/support communications, and break-glass tabletop.

Before first production use, crash injection or an equivalent controlled exercise must cover every
major transition. After promotion, perform a target restore/PITR drill using data written after
activation. Automated deterministic tests and production exercises produce separate receipts; one
cannot substitute for the other.

## 17. Operational runbook and go/no-go gates

### 17.1 Before the window

1. Deploy and qualify the control database, immutable store, maintenance-aware readiness, runtime
   role split, target 0018 migration capability, approved backup/restore adapter, and route adapter.
2. Measure current production dimensions conservatively, admit an active performance contract for
   that tier or a larger one, and complete the named-role rehearsal and recovery drill. Recompute
   the exact frozen dimensions after the barrier; a higher tier then blocks promotion.
3. Create the attempt and name the change commander, promotion/activation approvers, database and
   deployment executors, independent verifier, data owner, scribe, and backups.
4. Verify credentials, direct endpoints, database incarnation access, control/audit failover,
   monitoring, change window, abort criteria, and maintenance/incident communications.
5. Prepare but do not sign final promotion authorization. A provisional clone may be used to
   estimate duration, never as the final promotable candidate.

**Go to maintenance** only if role separation, write fencing, provider CAS/readback, tier, production
authentication, backup/PITR health, RPO/RTO, drills, and monitoring pass. Otherwise keep the source
serving normally.

### 17.2 Maintenance and candidate preparation

1. Announce maintenance; persist `MAINTENANCE_REQUESTED`; confirm readiness 503 and mutation denial.
2. Stop ingress/jobs, drain pools/transactions, block reconnects, establish the source privilege
   barrier, and capture a stable freeze receipt.
3. Create the final clone from the frozen source and capture physical/provider lineage.
4. Run unchanged inventory, bridge, plan, execution authorization, conversion, receipt, restart,
   and independent qualification at 0017.
5. Apply schema-only 0018, initialize target identity/fence closed, and rerun independent
   qualification with the v1 receipt shape.
6. Produce the candidate seal, exhaustive source reconciliation, zero-block receipt, and exact
   quarantine acceptance. Recheck the required tier.
7. Create both exact backups, restore each into a fresh isolated environment, and admit both restore
   receipts. Keep the source and target fenced throughout.

**Stop** on any write after freeze, unexplained reconciliation difference, block, unaccepted
quarantine, schema/root drift, failed exact restore, missing WAL, or expired maintenance window.
There is no manual row-copy or exception path.

### 17.3 Authorization, switch, and verification

1. Finalize the artifact set, sign/admit one-use promotion authorization, and consume it in the
   exact attempt.
2. Persist route-switch intent; execute provider CAS; replace processes/pools; read back provider,
   instance, connection, and ingress identities.
3. Keep target fence closed and run the complete bounded post-cutover suite. Confirm source is
   unchanged and has no runtime connections.
4. On failure, keep maintenance and either repair/reverify while fenced or execute authorized simple
   cutback.
5. On success, issue/admit the short-lived activation authorization. Persist divergence possible,
   open the target fence/grants, confirm readiness 200 and target identity, and mark promotion
   complete. Source remains frozen and retired.

### 17.4 Stabilization and evidence closure

Monitor high-frequency route identity, readiness, write errors, ownership denials, source reconnect
attempts, target WAL/PITR, backup status, and immutable-history behavior. Record bounded checks at
15 minutes, one hour, 24 hours, and seven days (or stricter policy). Take and verify the first
post-cutover target recovery point. Seal the evidence bundle and communications timeline in WORM
storage. Do not release the archive hold.

The operational dashboard must expose safe IDs/digests, state/version/actor, write modes, route,
database incarnations, deployments/pools, active sessions/transactions, fence events, mutation
rejections, backup/restore/WAL health, verification checks, application errors/latency,
authentication/ownership results, quarantine counts, and audit-anchor delivery. Immediate alerts
fire for source writes after freeze, target writes before activation, mixed routing, evidence drift,
expired authorization, control/audit loss, WAL/backup failure, or readiness 200 during maintenance.

## 18. Bounded implementation sequence for Codex

Model guidance was checked against the current official catalog: GPT-5.6 Sol is the flagship for
complex reasoning/coding, while GPT-5.3-Codex is the specialized agentic coding model. Use the named
model only when available in the team's Codex surface; otherwise use the strongest available Codex
model at the same effort. [GPT-5.6 Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol),
[GPT-5.3-Codex](https://developers.openai.com/api/docs/models/gpt-5.3-codex).

Each stage is independently reviewable and must land only after its named tests pass:

| Stage | Bounded scope and exit | Recommended model / effort |
| --- | --- | --- |
| 5C4.0 Decisions and contracts | Resolve all blockers in section 20; freeze versioned artifact/root/state/role/provider contracts and threat model; no runtime changes | GPT-5.6 Sol / xhigh |
| 5C4.1 Pure contract library | Canonical parsers/digests, strict shapes, database-incarnation, artifact-set, policy, performance-v2, quarantine/block, authorization envelopes; exhaustive unit/tamper tests | GPT-5.3-Codex / high |
| 5C4.2 Application prerequisites | Role/grant migration, 0018 identity/fence/immutability migration, qualifier-v2 admission with receipt-v1 shape, maintenance-aware readiness/mutation denial; migration/PostgreSQL tests | GPT-5.3-Codex / xhigh |
| 5C4.3 Independent control plane | Separate Alembic graph, typed artifact/binding/evidence schema, FSM, event hash chain, procedures, replay/concurrency enforcement, WORM outbox | GPT-5.3-Codex / xhigh |
| 5C4.4 Admission and performance | Artifact ingestion/finalization, live DB re-query, candidate/root reconciliation, T0 v2 ratification evaluator, tier gating, zero-block/quarantine workflows | GPT-5.3-Codex / xhigh |
| 5C4.5 Backup and restore | One approved provider adapter, physical identity/LSN/timeline evidence, exact restore verifier, PITR/WAL checks, corruption/timeout simulations | GPT-5.3-Codex / xhigh |
| 5C4.6 Authorization and CLI | Trust store/signature verification, one-use promotion/activation/cutback authorization, stable CLI/JSON/exits, secret/redaction/idempotency/audit | GPT-5.3-Codex / xhigh |
| 5C4.7 Cutover and verification | Maintenance drain/freeze, one endpoint CAS adapter, route/pool readback, bounded read-only smoke, activation/cutback transitions | GPT-5.3-Codex / xhigh |
| 5C4.8 Crash and recovery qualification | Crash injection across every transition, concurrent controllers, mixed routing, safe prewrite cutback, postwrite forward/PITR recovery, control-plane failover | GPT-5.3-Codex / xhigh |
| 5C4.9 Operational release | Production-like rehearsal, measured maintenance/RTO/RPO, runbook/communications/tabletop, evidence retention and release gate; no new semantics | GPT-5.6 Sol / high |

No stage may opportunistically rewrite the converter or combine independent qualification with
conversion. Provider support is intentionally one adapter at a time; a generic orchestration
framework is not a prerequisite.

## 19. Explicit non-goals

Phase 5C4 does not:

- change plan-v2 classifications, conversion mapping, baseline revision capture, projection
  behavior, checkpoint semantics, receipt v1 shapes, or restart guarantees;
- mutate or clean historical archives, repair quarantines, enrich Daily Logs, or alter OCR history;
- introduce delta synchronization, CDC, dual write, reverse replication, or conflict merging;
- make benchmark success equivalent to correctness or promotion authorization;
- permit a block override or implicit quarantine acceptance;
- expose promotion state or commands to application clients;
- treat process memory, DNS configuration, file modification time, provider acknowledgement, WAL
  LSN alone, or a self-hashed operator label as authority;
- promise source cutback after target activation;
- make `pg_dump` alone the recovery mechanism;
- rerun the entire historical qualifier after endpoint switch;
- authorize archive lifecycle actions; or
- add a broad multi-provider deployment platform.

## 20. Decisions that must be resolved before implementation

The architecture above resolves freeze-before-clone, the external control plane, target 0018 fence,
zero-block policy, explicit quarantine acceptance, exact T0 scan vector, and activation as the
irreversible boundary.

**Phase 5C4.0 status update (2026-07-16):** these infrastructure-specific decisions are closed for
the narrowly defined `phase5c4_controlled_portfolio_demo_v1` profile by
[Production Hardening Phase 5C4.0](production-hardening-phase5c4.0.md). Exercise-dependent gates
remain unfulfilled, and public or independently used multi-user production remains blocked. The
following list is retained as the source requirements that the decision record answers:

1. **Deployment mode and authentication.** The repository currently has no supported production
   authentication provider. Public production promotion is blocked until one is implemented and
   ownership-isolation canaries pass. An explicitly approved private deployment must state that
   narrower scope.
2. **Control/audit placement.** Select the independent PostgreSQL control cluster/account,
   availability/backup policy, immutable object store, WORM audit sink, and retention/legal-hold
   duration.
3. **Signing authority.** Select IAM/deployment issuer, signature algorithm, trust-anchor
   distribution, key rotation/revocation, approver/executor separation, and whether independent
   activation approval requires a second human. Recommendation: two-person promotion and activation.
4. **Legacy-source barrier.** Prove the 0003 application runtime is a non-owner, non-superuser role
   whose connections and all DML/sequence/mutator privileges can be revoked while a separate
   verifier remains. If it owns objects, complete role separation before Phase 5C4.
5. **Endpoint adapter.** Select a provider primitive with compare-and-swap, immutable revision,
   idempotency key, queryable operation/result, pool/process replacement, and multi-vantage identity
   readback. DNS-only switching is insufficient.
6. **Database incarnation.** Confirm permission/adapter access to managed resource identity,
   PostgreSQL system identifier, database OID, timeline/LSN, target nonce, direct endpoint, and clone
   lineage. If the physical/provider identity cannot be proven, promotion fails closed.
7. **Backup and recovery.** Select physical/managed backup technology, cluster-wide data scope,
   encryption/KMS, retention, exact-restore environment, WAL/PITR monitoring, zero-loss or explicit
   RPO, RTO, and 24-hour evidence ages. Cluster-wide backups require an explicit privacy/security
   decision if unrelated databases share the cluster.
8. **Maintenance window.** Measure final frozen clone, conversion, 0018 qualification, two backups,
   and two exact restores at the required tier. If they do not fit the approved window, design a
   separately reviewed synchronization protocol; do not reuse a stale provisional clone.
9. **Production tier.** Measure real frozen dimensions. T0 ratification cannot authorize a T1/T2/T3
   candidate; obtain and ratify the required tier first.
10. **Read-only canaries.** Define pre-existing canary users/data and disable private-user
    auto-creation/caching side effects so post-switch smoke is provably read-only.
11. **0018 qualifier compatibility.** Independently review that qualifier v2 changes only promotion
    schema admission/verification and keeps independent query semantics and receipt-v1 shape.
12. **Operational ownership.** Name change commander, data owner for quarantine, performance
    ratifier, independent verifier, recovery authority, and customer/support communication path.

Implementation must not begin with placeholder answers to items 1-11. Stage 5C4.0 records each
decision as a versioned policy/adapter contract and a production-exercise acceptance criterion.
