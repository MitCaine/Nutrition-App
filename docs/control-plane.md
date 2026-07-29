# Control Plane guide

> **Optional advanced reading.** You do not need the Control Plane to understand or modify Foods,
> Recipes, Daily Logs, USDA, OCR, Search, or Targets. Read this guide when working on historical
> database conversion, PostgreSQL role separation, write fencing, immutable operational evidence,
> canary admission, or production-like promotion.

## What it is

The Phase 5 control architecture is a safety system for moving a populated historical application
database through legacy Recipe conversion and, eventually, into production service. It separates
four questions that ordinary deployment scripts often blur:

1. **What data exists?** Read-only inventory and source identity.
2. **What conversion is authorized?** A deterministic plan plus execution authority.
3. **Is the result correct?** Independent qualification, reconciliation, and performance evidence.
4. **May this exact candidate serve traffic?** Independent promotion admission and workflow state.

Success at one layer never grants authority at the next. A conversion receipt is not a promotion
authorization; a performance pass cannot waive correctness; a process exit code is not durable
evidence.

## Why a personal deployment can ignore most of it

Normal application development uses one PostgreSQL database and the FastAPI/mobile stack described
in the [Architecture Guide](architecture.md). A fresh database does not need legacy Recipe
conversion. Local development does not need an independent promotion ledger or WORM evidence store.

The Control Plane exists for controlled production-like exercises where the cost of an ambiguous
source, incomplete conversion, stale candidate, privilege leak, or unsafe cutback is high. Its
complexity matches that operational risk rather than the complexity of nutrition tracking.

## Evolution of Production Hardening

| Phase | Purpose | Where to read |
| --- | --- | --- |
| Phase 1 | Explicit deployment modes, caller identity, fail-closed production auth | `production-hardening-phase1.md` |
| Phase 5A | Stop destructive upgrade of populated legacy Recipe tables | `production-hardening-phase5a.md` |
| Phase 5B | Read-only, privacy-safe historical database inventory | `production-hardening-phase5b.md` |
| Phase 5C1 | Isolated clone bridge, archive, deterministic conversion plan | `production-hardening-phase5c1.md` |
| Phase 5C2 | Authorized checkpointed conversion with restart-safe outcomes | `production-hardening-phase5c2.md` |
| Phase 5C3a | Independent PostgreSQL-only correctness qualification | `production-hardening-phase5c3a.md` |
| Phase 5C3b / 5C2.2 | Deterministic performance fixtures, evidence, and bounded optimization | `production-hardening-phase5c3b.md`, `production-hardening-phase5c2.2.md` |
| Phase 5C4.0 | Freeze the controlled portfolio deployment profile and trust decisions | `production-hardening-phase5c4.0.md` |
| Stage 5C4.1 | Versioned canonical promotion contracts and tamper validation | Contract modules and tests |
| Stage 5C4.2 | Least-privilege application roles, local target identity/write fence, canary prerequisites | `production-hardening-phase5c4.2a.md`, migration 0018 |
| Stage 5C4.3 | Independent control DB, immutable evidence/events, leases/outbox, MinIO anchoring, gate API | ops migrations 0001–0003 |
| Stage 5C4.4 | Collector-authored source observations and semantic admission/performance decisions | ops migration 0004 and admission modules |
| Resource membership 0019 | Database-enforced ownership/membership, read-only corruption inventory, and distinct current-schema admission | `production-hardening-resource-membership.md`, application migration 0019, ops migration 0005 |
| Immutable provenance 0020 | Database-enforced historical immutability and exact current-schema admission | `production-hardening-immutable-provenance.md`, application migration 0020, ops migration 0006 |
| Stage 5C4.5 | Idempotent local restore execution, atomic restored-database qualification, and immutable recovery evidence | `production-hardening-phase5c4.5.md`, ops migration 0007 |
| Stage 5C4.6 | Purpose-specific Ed25519 target-activation authorization admission; no consumption or activation | `production-hardening-phase5c4.6.md`, ops migration 0008 |
| Stage 5C4.7a | Purpose-specific promotion admission, one-use route intent, closed-target route/post-cutover evidence, and activation-evidence binding; no activation or opening | `production-hardening-phase5c4.7a.md`, ops migration 0009 |
| Stage 5C4.7b | Separate schema-0021 execution authority, forward-only target migration, one-use activation, runtime observation/reconciliation, and emergency close | `production-hardening-phase5c4.7b.md`, application migration 0021, ops migration 0010 |
| Stage 5C4.8 (bounded recovery qualification) | Purpose-specific executable preactivation cutback, crash/reconciliation correction, cumulative recovery qualification, and read-only postactivation PITR qualification | `production-hardening-phase5c4.8.md`; ops 0011 installs the cutback authority lifecycle, v9, and the audit snapshot |

The broad [Phase 5C4 design record](production-hardening-phase5c4.md) describes later promotion,
cutover, recovery, and authorization goals as well as implemented foundations. Do not read every
future design statement as a claim that provider adapters or runtime cutover are active today.

## Architecture

```mermaid
flowchart LR
    Source[("Frozen source DB")]
    Target[("Candidate DB")]
    Collector["Read-only evidence collector"]
    Object["MinIO WORM objects"]
    Control[("Independent control PostgreSQL")]
    Executor["Promotion executor"]
    Outbox["Leased outbox worker"]
    Audit["Read-only audit role"]
    Gate["Read-only gate role"]
    Runtime["Application runtime"]

    Source --> Collector
    Target --> Collector
    Collector --> Object
    Collector --> Control
    Executor --> Control
    Control --> Outbox
    Control --> Audit
    Control --> Gate
    Gate -.->|future runtime consumption| Runtime
    Runtime --> Target
```

The control database must be independent of both application endpoints. Evidence remains available
even if the source or candidate is unhealthy. MinIO preserves the exact canonical object version;
the control database preserves the digest, byte count, binding, typed projection, event history,
and workflow authority.

## Authority boundaries

### Application database roles

The production-like role topology separates:

- `nutrition_owner`: non-login object owner;
- `nutrition_migrator`: the only login allowed to assume owner for Alembic;
- `nutrition_runtime`: ordinary bounded read/write API access;
- `nutrition_canary`: read-only allowlisted application access;
- `nutrition_qualifier`: independent read-only qualification;
- `nutrition_ops`: bounded maintenance authority.

The role provisioner is not an application feature. It verifies exact PostgreSQL version, object
surface, grants, default privileges, memberships, routine safety, extensions, and prepared
transaction state.

### Control database roles

The independent database has its own non-overlapping role family:

- `nutrition_control_owner` and `nutrition_control_migrator`;
- `nutrition_control_collector` for immutable evidence registration;
- `nutrition_control_executor` for workflow/admission requests;
- `nutrition_control_outbox` for leased delivery;
- `nutrition_control_audit` for read-only evidence review;
- `nutrition_control_gate` for the minimal environment gate.
- `nutrition_control_authorization_verifier` for trusted-public-key reads and exact authorization
  admission only.

Possessing more than one credential operationally does not merge their PostgreSQL authority. The
collector cannot admit or advance attempts; the executor cannot author registered source evidence.

## Application-side prerequisites

Application migration `0018_phase5c_promotion_prerequisites` adds target identity, append-only fence
events, a validated fence projection, database write-fence triggers, schema/role admission readers,
and immutability hardening without changing domain data.

Application migration `0019_resource_membership_integrity` retains those historical prerequisites
and adds database-enforced ownership and child-membership constraints. Its operator preflight,
closed-fence and drained-runtime requirements, qualification boundary, and forward-only recovery
rules are in [Database-Enforced Resource Membership](production-hardening-resource-membership.md).

Application migration `0020_immutable_provenance_enforcement` carries that exact constraint
contract forward and adds immutable publication/OCR guards, guarded Daily Log snapshot replacement,
current local admission v3, and independent immutable-provenance qualification. Control revision
`ops_0006_immutable_provenance` admits only that exact versioned artifact. See
[Immutable Historical Provenance](production-hardening-immutable-provenance.md).

The local database fence is defense in depth. It prevents ordinary runtime DML unless the target is
in the allowed production state and turns its SQLSTATE into a bounded API 503. It does not decide
that promotion is authorized.

Canary process mode performs a local startup admission through a read-only repeatable snapshot and
mounts only a frozen GET allowlist. It validates application-database prerequisites, not the
independent control gate.

## Canonical evidence flow

```mermaid
sequenceDiagram
    participant Source as Source or candidate DB
    participant Collector
    participant MinIO
    participant Control as Control PostgreSQL
    participant Executor

    Collector->>Source: Observe with approved read-only credential
    Source-->>Collector: Snapshot-bound facts
    Collector->>Collector: Build one canonical byte sequence and SHA-256 digest
    Collector->>MinIO: PUT exact bytes with COMPLIANCE retention
    MinIO-->>Collector: Bucket, key, version, retention receipt
    Collector->>Control: Register artifact and exact object binding
    Control->>Control: Parse immutable typed projection from canonical bytes
    Control-->>Collector: Safe artifact reference
    Executor->>Control: Request admission using artifact UUIDs
    Control->>Control: Lock, validate server-time freshness and semantic graph
    Control-->>Executor: Immutable accepted or rejected decision
```

There is one canonical JSON serialization implementation shared by digest-producing contracts.
Artifact digests are computed from bytes, not trusted from caller input.

Stage 5C4.4's `phase5c4_source_dimensions_v1` illustrates the boundary: the collector directly
observes the source and registers WORM-bound bytes; PostgreSQL derives a typed immutable projection;
the executor references its UUID. The executor-facing admission APIs do not accept competing raw
authoritative dimensions.

## Evidence, workflow, and event integrity

The control migration stream builds three related surfaces:

- immutable registered artifacts and object bindings;
- an immutable chained event ledger plus atomic outbox entries;
- mutable workflow projections whose changes are authorized only through controlled routines.

Request IDs bind to canonical request bytes. Exact replay returns the original result. Reusing an ID
with a different request creates bounded conflict evidence rather than another transition.

Terminal mismatch handling cannot rewrite earlier evidence. Projection mutations and immutable
event/outbox inserts occur in the same transaction.

## Lease authority

Outbox delivery uses database leases. Acknowledgement, failure, retry scheduling, release, reclaim,
lost-PUT reconciliation, and terminal mismatch paths validate exact message identity, current lease
token, leased state, and unexpired server-time lease under the same row lock immediately before
mutation.

PostgreSQL server time—not worker wall-clock time—is authoritative. Reclaim establishes a new token;
a stale worker cannot acknowledge after that authority changes.

## Admission

Preflight and final-source admission run inside SERIALIZABLE transactions. They lock environment,
attempt, source/target instances, evidence artifacts, object bindings, performance authority, and
typed projections in deterministic order. After potentially blocking locks are acquired, they
capture control PostgreSQL time and repeat freshness/retention validation before inserting an
immutable decision and mutating the attempt projection.

Admission checks the entire evidence graph rather than isolated “valid” documents: environment,
source/candidate identity, freeze epoch, archive, plan, run, marker, inventory, schema authority,
reconciliation, qualification, performance tier, WORM object version, and retention must agree.

Dry-run follows the same validation and state-decision path but omits projection mutation. A changed
artifact under the same request ID is a request conflict.

## Qualification and migration safety

Control qualification inventories every authoritative table, function, trigger, index, constraint,
owner, grant, registry row, and immutable projection. Tamper tests alter parser/projector routines,
grants, or seed data and require qualification to fail.

Control downgrades are empty-only. They are for qualification of an uncommitted/empty schema path,
not rollback of a live ledger. A nonempty database fails closed because removing a control revision
would destroy evidence or authority that cannot be reconstructed safely.

The application and control Alembic streams use different configuration files, environment
variables, credentials, databases, and ownership assumptions.

## Current runtime boundary

The independent environment gate API exists as a minimal read-only control projection, but normal
application runtime does **not** consume it per request. Phase 5C4.6 and 5C4.7a provide
purpose-specific signature verification, admission, route intent, and preactivation evidence.
Phase 5C4.7b adds the separately authorized schema-0021 migration and fixed-purpose target-open,
runtime-observation, reconciliation, and emergency-close boundaries. It does not supply a generic
provider executor, automatic route cutback, source reopening, or deployment orchestrator. Phase
5C4.5's bounded Docker Compose/pgBackRest recovery adapter still does not create backups, route
traffic, or authorize activation.

Phase 5C4.8 freezes a distinct Ed25519
preactivation-cutback contract plus safety, route, and source-restoration observation shapes. Ops
0011 installs the matching trust store, admission, one-use consumption, route intent and
reconciliation, source-last restoration evidence, terminal `CUTBACK_COMPLETED` evidence,
cumulative qualification, and audit-only recovery inspection. Provider route changes and source
runtime changes still occur outside database transactions and require authoritative observations.

Therefore:

- the application trigger introduced by 0018 remains the active local write-fence prerequisite;
- schema-0020 runtime readiness and canary startup continue to validate local admission v3;
- schema-0021 runtime readiness and canary startup validate local admission v4, including the
  execution-schema evidence and runtime-write admission state;
- authorization admission, migration intent, and external command return do not by themselves
  enable or prove production writes;
- only the schema-0021 maintenance routine can alter local runtime-write admission, and the control
  workflow reaches `TARGET_ACTIVE` only after an authoritative matching observation;
- cutback is executable only before target activation authority exists; it is not automatic route
  cutback, postactivation rollback, or a generic production deployment pipeline.

## Where to look

| Concern | Primary location |
| --- | --- |
| Historical inventory/bridge/plan/conversion/qualification | `app/operators/historical_*`, `scripts/*historical*` |
| Canonical contracts | `app/operators/phase5c*_contracts.py` |
| Application role policy | `phase5c4_roles.py`, `phase5c4_prerequisites.py`, role-management script |
| Application fence, membership, immutable provenance, and activation execution | migrations `0018_phase5c_promotion_prerequisites.py` through `0021_target_activation_execution.py` |
| Control role policy | `phase5c4_control_roles.py`, `manage_phase5c4_control_roles.py` |
| Evidence collection and WORM delivery | `phase5c4_control_evidence.py`, `phase5c4_minio.py` |
| Python control client | `phase5c4_control.py` |
| Control authority | `app/control_migrations/versions/ops_0001` through `ops_0011` |
| Admission rules | `phase5c4_admission.py`, `phase5c_performance_contracts.py`, ops 0004 |
| Current resource-membership operations | `resource_membership_*` operator modules, preflight script, and the 0019 runbook |
| Current immutable-provenance operations | `immutable_provenance_*` operator modules, qualification script, and the 0020 runbook |
| Recovery execution and evidence | `phase5c4_recovery.py`, `manage_phase5c4_recovery.py`, the 5C4.5 runbook, and ops 0007 |
| Activation execution and emergency close | `phase5c4_activation_execution.py`, `0021_target_activation_execution.py`, the 5C4.7b runbook, and ops 0010 |
| Cutback contracts and cumulative recovery qualification | `phase5c4_cutback.py`, `phase5c4_recovery_qualification.py`, ops 0011, the 5C4.8 runbook, and focused tests; no executable cutback SQL authority |
| Qualification | control migration routines, resource-membership and immutable-provenance qualification, and PostgreSQL qualification tests |

Always follow the SQL routine and role grant reached by a Python wrapper. The wrapper alone does not
prove the transaction or authority boundary.

## Before changing it

Read the governing phase record, then use the [Testing Guide](testing.md). A control-plane change
normally requires canonical/tamper tests, real PostgreSQL role tests, complete qualification,
migration round-trip and nonempty refusal, concurrency/failure injection, replay checks, and MinIO
integration if object identity changes.

Stop and revisit the architecture if a proposed change creates two authorities for the same fact,
trusts caller-provided digests, uses application credentials in the control database, depends on
process time for lease/freshness authority, mutates immutable evidence, or allows a downgrade to
discard a nonempty ledger.

## Next reading

- Read the [Testing Guide](testing.md#control-database-qualification) before changing control
  authority or qualification.
- Follow the stage links in [Evolution of Production Hardening](#evolution-of-production-hardening)
  for the exact governing design record.
- Use the [Architecture Decision Index](architecture-decisions.md#production-hardening-decisions) to
  refresh the specific operational decision first.

## See also

- [Why This Exists](why-this-exists.md#why-a-control-plane) for architectural rationale
- [Architecture Guide](architecture.md#runtime-and-canary-modes) for the current application boundary
- [Development Guide](development-guide.md#if-you-need-to-modify-the-control-plane) for code entry points
