# Why this exists

This guide answers the architectural questions that are easy to forget when returning to the
project. It describes the problem each invariant solves, not the implementation history.

## Why immutable Recipe revisions?

An authored Recipe is expected to change: ingredients, yields, and source Foods evolve. A logged
meal is expected not to change. If Logs referenced only the current Recipe, editing tomorrow's
Recipe would rewrite yesterday's nutrition.

Publication therefore creates an immutable revision with exact content, amount definitions, and
nutrient totals. The mutable Recipe points to the active revision; historical Logs point to the
revision they actually used.

## Why a Recipe Food projection?

Foods already participate in ingredient selection, serving resolution, search, logging, ownership,
and nested composition. A managed Food projection lets a published Recipe reuse those workflows
without weakening revision identity or building a parallel “loggable thing” hierarchy.

The projection is compatibility state, not the historical authority. Its revision link is.

## Why immutable nutrition history?

People correct Food definitions. Historical reports must still describe what the system resolved
when the item was logged. Each Daily Log stores nutrient snapshots of the consumed amount, and
daily totals aggregate those snapshots only.

Editing a Log deliberately rebuilds that Log's snapshots because the user is changing the
historical event. Editing the source Food alone does not.

## Why distinguish unknown from zero?

“The label says 0 mg” and “the data source did not provide sodium” support different conclusions.
Treating both as zero produces false confidence. The domain carries known, estimated, zero, and
unknown status through resolution and aggregation so summaries can expose incomplete inputs.

## Why explicit serving identities and gram weights?

Labels such as “1 cup” are not universal mass conversions. Serving definitions record exact
quantity/unit semantics and optional measured gram weight. Recipe ingredients retain the exact
serving they reference, preventing a later default-serving change from silently altering the
Recipe.

Ambiguous serving remaps fail atomically because guessing would corrupt both authored Recipes and
future publication revisions.

## Why revision-backed logging?

The Recipe compatibility Food is useful for selection, but it can advance to a newer publication.
The Daily Log therefore records both the immutable revision and its exact amount definition. That
pair answers “which recipe state and which serving meaning did this log use?” even after another
publication.

## Why bounded OCR correction provenance?

OCR is probabilistic and parser rules evolve. Keeping structured suggestions, source observation
IDs, and confirmation actions makes a future parser regression explainable and testable.

Storing the image or unbounded raw OCR response would increase privacy and retention risk without
being necessary for nutrition resolution. The persisted trace is deliberately bounded,
append-only, versioned, and separate from the Food's authoritative nutrients.

## Why ownership enforcement in several layers?

An authenticated user ID in a route is not enough. Queries, service operations, and relationship
constraints all need the same owner boundary so a guessed UUID cannot connect one user's Food to
another user's Recipe, revision, Log, or target.

Service checks produce understandable errors. Composite database constraints protect against
implementation mistakes and races. Both are necessary.

## Why payload-bound idempotency?

Mobile networks can lose a successful response. Blind retry could create duplicate Foods, Recipes,
Logs, publications, or confirmations. A request UUID is useful only when bound to the exact
operation and canonical payload.

Exact replay returns the committed response. Payload-changing reuse conflicts. Receipts are kept
indefinitely because expiring an accepted request ID would eventually grant permission to create a
duplicate.

## Why an online-first design?

The server owns nutrition calculation, ownership, immutable history, and transactional graph
changes. A durable offline queue would need conflict rules for each of those domains. The current
application provides in-session caching, explicit errors, and safe retry without pretending that a
local mutation is committed.

On-device OCR is a privacy and platform choice, not an offline synchronization architecture. Its
structured output still goes to the backend parser and confirmation service.

## Why read-only offline snapshots for migration evidence?

Historical inventory, qualification, and source-observation collectors must describe one coherent
database state without becoming another writer. They therefore use explicit read-only transactions,
usually at repeatable-read isolation, and record bounded snapshot, timeline, LSN, and server-time
anchors where the contract requires them.

“Offline” in this operational context means isolated from live application mutation and promotion
authority; it does not mean a mobile offline cache. A snapshot lets every count, root, and binding
refer to the same observed state. Read-only credentials and rollback-on-exit prevent the act of
qualification from repairing or changing the candidate it is supposed to judge.

## Why fail-closed release configuration?

Development convenience must not become accidental production authentication. Deployment mode is
required. Private single-user mode requires an explicit shared credential and configured identity.
Public production startup is rejected until a real identity provider exists.

Failing at configuration time is safer than silently creating or trusting a development user.

## Why database-enforced write fencing?

An application-level “maintenance” flag cannot stop stale processes, unknown sessions, or code
paths that fail to check it. Application migration 0018 adds local target identity, append-only
fence history, projection validation, and trigger enforcement in PostgreSQL. Role separation and
privilege withdrawal provide additional operational barriers.

The local fence is defense in depth. It does not replace the independent promotion authority.

## Why a Control Plane?

Historical Recipe conversion and production cutover are high-risk operations with several
independent facts: source identity, clone lineage, conversion plan, execution, qualification,
performance, backup/restore evidence, quarantine, and authorization.

Keeping authority only in the source, candidate, a process, or a JSON file creates circular trust:
the system being replaced could also rewrite the evidence that approves its replacement. The
independent control PostgreSQL database records immutable evidence and workflow state outside both
application endpoints.

Personal local development does not need this machinery. It exists for controlled production-like
promotion of historical data.

## Why WORM evidence?

Database rows prove what the control plane accepted, while object-lock storage preserves the exact
canonical bytes and object version independently. Digest, byte count, bucket, key, version, and
COMPLIANCE retention are bound together.

This does not create a cryptographic identity signature. In the implemented collector boundary,
authority comes from the dedicated read-only observation credential, collector-only registration
credential, canonical bytes, and immutable object binding.

## Why qualification?

A command succeeding is not proof that the surrounding database, roles, functions, triggers,
grants, or immutable projections are the expected ones. Qualification independently inventories
the security-critical surface and emits a deterministic result.

Tests intentionally tamper with qualified objects to ensure qualification fails. This guards
against a manifest that merely checks its happy path or forgets a newly authoritative routine.

## Why two migration streams?

Application data and promotion authority have different owners, credentials, lifecycles, and
failure modes. Application Alembic migrations must never acquire implicit authority over the
control ledger, and control migrations must not become feature-table migrations. Separate streams
make that boundary explicit and testable.

## Application requirement or production infrastructure?

| Concern | Needed to understand normal features? | Purpose |
| --- | --- | --- |
| Foods, servings, nutrients | Yes | Core nutrition definitions |
| Recipe revisions and Log snapshots | Yes | Correct application history |
| Ownership and create idempotency | Yes | Correct API behavior and retry safety |
| Apple Vision and parser provenance | Only for OCR work | Privacy-aware label capture |
| Application migration 0018 local fence | Usually no | Production-like target prerequisite |
| Historical Phase 5C conversion | No | Safe migration of populated legacy Recipe data |
| Independent control database | No | Promotion evidence and workflow authority |
| MinIO WORM evidence | No | Immutable operational artifact copy |
| Control roles, leases, outbox, admission | No | Least-privilege production operations |

For the operational overview, continue with the [Control Plane Guide](control-plane.md).

## Next reading

- Use the [Architecture Decision Index](architecture-decisions.md) when you need a shorter lookup.
- Read the [Architecture Guide](architecture.md) to map these reasons to system responsibilities.
- Choose a domain guide—[Foods](foods-and-nutrition.md),
  [Recipes and Logs](recipes-and-logging.md), or
  [OCR, Search, and Offline](ocr-search-and-offline.md)—for execution flows.

## See also

- [Development Guide](development-guide.md) for code ownership
- [Testing Guide](testing.md) for the proof behind each invariant
- [Control Plane Guide](control-plane.md) for advanced operational decisions
