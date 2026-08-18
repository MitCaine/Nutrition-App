# Project invariants and rationale

> **Document role: Current Guide.**

The [Project Constitution](constitution.md) defines enduring purpose and principles. This guide
translates those principles into technical truths that implementation changes must preserve. It
describes why each invariant exists, not the implementation history or current release state.

## Decision tradeoffs at a glance

This table is the canonical short-form tradeoff summary. The sections below explain the reasoning;
the [Architecture Decision Index](../architecture/decisions.md) points to implementation detail.

| Decision | Benefits | Tradeoffs | Why chosen here |
| --- | --- | --- | --- |
| Immutable Daily Log nutrition | Past totals remain explainable after Food edits or deletion. | Writes store duplicated nutrient snapshots, and explicit Log edits must rebuild them atomically. | Historical truth is more important than minimizing rows or recomputing from mutable Foods. |
| Immutable Recipe revisions and retained history | Logs and nested Recipes keep exact published content. | Publication stores another graph and requires revision-resolution code. | Mutable authoring cannot safely serve as historical authority. |
| Explicit publication workflow | Users can edit freely while “published” has one transactional meaning. | A Recipe may be stale and marked `needs_republish` until the user publishes again. | An explicit boundary is safer than silently changing every downstream consumer on save. |
| Generated compatibility Food projection | Published Recipes reuse Food search, serving, ingredient, and logging paths. | Projection state must be regenerated and cannot be treated as historical authority. | Reuse is preferable to a parallel loggable-item hierarchy when the exact revision link remains authoritative. |
| Explicit serving identity plus gram/reference authority | Serving labels and UI units can change while physical amount meaning remains stable. | Serving edits must carry complete reference metadata or require review instead of guessing. | Household labels are not universal mass conversions, and Recipe/log meaning must not drift with presentation. |
| Reference-derived Targets outside history | Profiles, DRI/FDA references, and tracking preferences can evolve without changing past consumption. | Daily comparison must resolve current target policy separately from immutable Log snapshots. | Goals are interpretation/configuration, not historical nutrition facts. |
| Validated local backup replacement | Local users can export/restore a coherent authority without a sync engine. | Restore requires validation, staging, restart-time activation, and rollback handling rather than simple file overwrite. | Recovery is needed, but merge/sync semantics would be a substantially different architecture. |
| Service-first, selective repositories | Transaction and ownership authority stay visible while complex queries are reusable. | Persistence access is not mechanically uniform across every service. | A repository per table would add indirection without clarifying responsibility. |
| No Repository Provider/Factory layer | Construction and transaction ownership remain direct and easy to trace. | Swapping an entire persistence backend is not a plug-in operation. | Each running context has one explicitly selected local or remote application-data authority; selective test seams provide enough substitution. |
| Layered ownership enforcement | Friendly service errors and race-resistant database integrity reinforce each other. | Owner predicates and constraints appear at several layers and require coordinated tests. | One missed route check must not permit a cross-user relationship. |
| PostgreSQL concurrency strategy | Row locks, deterministic ordering, constraints, and one transaction protect graph changes. | Lock-dependent claims require PostgreSQL tests and deliberate deadlock review. | In-process locks or SQLite behavior cannot protect concurrent API workers. |
| Explicit mobile application-data authority | Each running context has one clear persisted authority and no mixed state. | Local mode does not use the remote API; remote mode does not provide durable local writes. | A correct synchronization engine would need explicit rules for every graph, owner, and immutable-history conflict, so synchronization and fallback remain out of scope. |
| Bounded OCR provenance | Parser behavior and user corrections remain explainable with limited privacy exposure. | The trace cannot reproduce every detail of the original image or raw OCR response. | Structured evidence needed for diagnosis is worth retaining; sensitive, unbounded capture material is not. |

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

The repository currently retains this history for exact Daily Log and Recipe-revision behavior. A
separate longitudinal trends/analytics product is not implied by the presence of historical rows.

## Why distinguish unknown from zero?

“The label says 0 mg” and “the data source did not provide sodium” support different conclusions.
Treating both as zero produces false confidence. The domain carries known, estimated, zero, and
unknown status through resolution and aggregation so summaries can expose incomplete inputs.

## Why explicit serving identities and gram weights?

Labels such as “1 cup” are not universal mass conversions. Serving definitions record exact
quantity/unit semantics and optional measured gram weight. Recipe ingredients retain the exact
serving they reference, preventing a later default-serving change from silently altering the
Recipe.

Current serving authoring also permits a complete reference measurement: reference quantity,
reference unit, and reference gram weight. That triple records the physical anchor behind a serving
when the user changes how the serving is displayed. It is all-or-none because a partial reference
would claim equivalence without enough information to prove it.

Gram mass is the authority when crossing between mass and non-mass presentation. If an edit cannot
preserve physical equivalence unambiguously, the correct behavior is explicit review or failure,
not an inferred conversion. Active Recipe serving references likewise remap only to one successor
with equivalent semantics.

## Why revision-backed logging?

The Recipe compatibility Food is useful for selection, but it can advance to a newer publication.
The Daily Log therefore records both the immutable revision and its exact amount definition. That
pair answers “which recipe state and which serving meaning did this log use?” even after another
publication.

## Why target configuration stays outside immutable nutrition history?

A Daily Log answers what was consumed. A target answers how current configuration/reference data
interprets that consumption. Combining the two would make a profile edit or reference-data update
rewrite history.

Targets therefore resolve separately from snapshot-derived daily totals. Per-nutrient tracking
policy can mark a nutrient ignored or amount-only. Manual overrides take precedence over dynamic
recommendations. Calories can use the bounded general-adult Mifflin–St Jeor estimate, while other
nutrients can use the canonical DRI RDA/AI dataset and then FDA Daily Value reference where
applicable. Some nutrients intentionally have no established target and remain amount-only; missing
or unsupported profile/reference cases remain explicitly unavailable.

The important invariant is not a fixed list of target numbers. It is that changing a profile,
tracking preference, manual override, DRI dataset, FDA catalog, or target-resolution rule never
changes previously stored Recipe revisions or Daily Log nutrient snapshots.

## Why bounded OCR correction provenance?

OCR is probabilistic and parser rules evolve. Keeping structured suggestions, source observation
IDs, and confirmation actions makes a future parser regression explainable and testable.

Storing the image or unbounded raw OCR response would increase privacy and retention risk without
being necessary for nutrition resolution. The persisted trace is deliberately bounded,
append-only, versioned, and separate from the Food's authoritative nutrients.

Guided camera framing and image-quality inspection are acquisition aids. They may improve the input
or warn the user about a weak capture, but neither becomes persisted nutrition authority and neither
removes the need for explicit confirmation.

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

The heading is retained as a stable historical anchor; the active mobile architecture is now
local-first with explicit authority selection.

Mobile startup explicitly selects exactly one `local` or `remote` application-data authority before
runtime construction. Local mode uses the composed SQLite adapters; remote mode preserves the
FastAPI/PostgreSQL API and authentication boundary. The selected runtime is the sole authority for
persisted nutrition totals in that running context.

Selection never implies fallback, dual writes, synchronization, cache sharing, recovery sharing,
or data migration. TanStack Query may cache authority-scoped data in process, and safe retry may
replay an idempotent operation, but neither creates a second durable authority. On-device OCR is a
privacy and platform choice; its bounded parser/confirmation provenance follows the selected
runtime and is not an offline synchronization mechanism.

## Why local backup is replacement, not synchronization?

A coherent backup is a snapshot of one local SQLite authority. Restoring it means replacing the
current local authority with that validated snapshot, not reconciling two independently changed
histories.

The implementation therefore validates an exported artifact, validates a selected candidate before
staging, activates only at startup before a normal local connection opens, snapshots the existing
database for rollback, validates the replacement again, and fails closed if rollback cannot be
completed safely. Staging can be canceled before restart. Success/failure evidence is retained for
user-visible recovery state.

This is intentionally different from synchronization. There is no record-by-record merge,
last-writer-wins rule, conflict graph, background replication, remote mirror, or automatic cloud
retention. Adding any of those would require a new authority/conflict design rather than extending
the current backup API casually.

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

This heading refers to the two **PostgreSQL Alembic** streams: remote application data and
promotion/control authority have different owners, credentials, lifecycles, and failure modes.
Application Alembic migrations must never acquire implicit authority over the control ledger, and
control migrations must not become feature-table migrations.

Local SQLite is a third persistence-evolution mechanism, not a third Alembic stream. Its
schema-version migration engine owns the fresh local semantic schema and must not replay the
PostgreSQL migration history or absorb Phase 5/control-plane infrastructure.

## Application requirement or production infrastructure?

| Concern | Needed to understand normal features? | Purpose |
| --- | --- | --- |
| Foods, servings, nutrients | Yes | Core nutrition definitions |
| DRI/FDA reference data, tracking preferences, Targets | Yes for Target work | Current comparison/configuration without rewriting history |
| Recipe revisions and Log snapshots | Yes | Correct application history |
| Local backup/restore | Yes for local-data maintenance | Validated replacement/recovery of the local SQLite authority |
| Ownership and create idempotency | Yes | Correct API/runtime behavior and retry safety |
| Apple Vision, guided capture, image-quality hints, parser provenance | Only for OCR work | Privacy-aware label capture and explicit review |
| Application migration 0018 local fence | Usually no | Production-like target prerequisite |
| Historical Phase 5C conversion | No | Safe migration of populated legacy Recipe data |
| Independent control database | No | Promotion evidence and workflow authority |
| MinIO WORM evidence | No | Immutable operational artifact copy |
| Control roles, leases, outbox, admission | No | Least-privilege production operations |

For the operational overview, continue with the [Control Plane Guide](../operations/control-plane.md).

## Next reading

- Use the [Architecture Decision Index](../architecture/decisions.md) when you need a shorter lookup.
- Read the [Architecture Overview](../architecture/overview.md) to map these reasons to system responsibilities.
- Choose a domain guide—[Foods](../features/foods-and-nutrition.md),
  [Recipes and Logs](../features/recipes-and-logging.md), or
  [OCR, Search, Offline Behavior, and Local Backup](../features/ocr-search-and-offline.md)—for execution flows.

## See also

- [Development Guide](development-guide.md) for code ownership
- [Testing Guide](../operations/testing.md) for the proof behind each invariant
- [Control Plane Guide](../operations/control-plane.md) for advanced operational decisions
