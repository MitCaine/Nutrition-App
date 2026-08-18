# Architecture decision index

> **Document role: Current Guide.** This is the authoritative index of accepted architectural
> decisions.

This index records what the project has deliberately chosen. The
[Project Constitution](../project/constitution.md) defines enduring constraints, the
[Project Invariants](../project/invariants.md) own extended technical rationale, and current
architecture, feature, and operations guides describe implementation. Decision entries stay
concise and link to those canonical explanations.

Every entry is **Accepted** unless it is explicitly marked otherwise. Its heading is its stable
repository anchor: do not silently rename or delete a decision when it is superseded. Mark the old
entry superseded, name its replacement, and preserve provenance. The historical Phase 5C4.0
deployment-profile record remains decision provenance; the current boundary is maintained in the
[Control Plane Guide](../operations/control-plane.md#evolution-of-production-hardening).

## Decision map

### Application and nutrition

- [Immutable Daily Log nutrition](#immutable-daily-log-nutrition)
- [Immutable Recipe revisions](#immutable-recipe-revisions)
- [Recipe Food compatibility projections](#recipe-food-compatibility-projections)
- [Revision-backed nutrition logging](#revision-backed-nutrition-logging)
- [Unknown nutrients are not zero](#unknown-nutrients-are-not-zero)
- [Explicit serving identities and gram weights](#explicit-serving-identities-and-gram-weights)
- [Reference-derived Targets stay outside nutrition history](#reference-derived-targets-stay-outside-nutrition-history)
- [Bounded OCR correction provenance](#bounded-ocr-correction-provenance)
- [Saved Foods and USDA Foods remain distinct](#saved-foods-and-usda-foods-remain-distinct)
- [Search is composed, not centralized](#search-is-composed-not-centralized)
- [Online-first mobile architecture](#online-first-mobile-architecture)
- [Explicit mobile application-data authority](#explicit-mobile-application-data-authority)
- [Local backup restore is validated replacement, not synchronization](#local-backup-restore-is-validated-replacement-not-synchronization)

### Application structure and authority

- [Service-first, selective repository abstraction](#service-first-selective-repository-abstraction)
- [Ownership is enforced at multiple layers](#ownership-is-enforced-at-multiple-layers)
- [Payload-bound create idempotency](#payload-bound-create-idempotency)
- [Fail-closed deployment configuration](#fail-closed-deployment-configuration)
- [Separate application and control migration streams](#separate-application-and-control-migration-streams)

### Operational safety

- [Independent Control Plane](#independent-control-plane)
- [WORM-bound canonical evidence](#worm-bound-canonical-evidence)
- [Independent qualification](#independent-qualification)
- [Artifact-referenced admission pipeline](#artifact-referenced-admission-pipeline)
- [PostgreSQL role separation](#postgresql-role-separation)

## Application and nutrition decisions

### Immutable Daily Log nutrition

**Decision:** A Daily Log stores resolved nutrient snapshots, and daily totals aggregate those
snapshots rather than current Food nutrient rows.

**Consequence:** Food definitions are expected to be corrected over time; historical nutrition
must continue to describe what was resolved when the user logged it. Only an explicit Log edit
rebuilds that Log's snapshots.

**Read more:** [Recipes and Nutrition History](../features/recipes-and-logging.md#daily-log-creation) and
[Project Invariants](../project/invariants.md#why-immutable-nutrition-history)

### Immutable Recipe revisions

**Decision:** Publishing a Recipe inserts a new immutable revision instead of overwriting published
state.

**Consequence:** Mutable authoring and historical use have different lifecycles. A Recipe can
evolve while past Logs and nested Recipes retain the exact published content they used.

**Read more:** [Recipes and Nutrition History](../features/recipes-and-logging.md#publication) and
[Project Invariants](../project/invariants.md#why-immutable-recipe-revisions)

### Recipe Food compatibility projections

**Decision:** A published Recipe is represented by a managed Food projection linked to one exact
publication revision.

**Consequence:** Ingredient selection, serving resolution, search, and logging already understand
Foods. The projection reuses those paths without making mutable projection data the historical
authority.

**Read more:** [Recipes and Nutrition History](../features/recipes-and-logging.md#recipe-compatibility-projection)
and [Project Invariants](../project/invariants.md#why-a-recipe-food-projection)

### Revision-backed nutrition logging

**Decision:** Recipe Logs store both the immutable publication revision and its exact amount
definition.

**Consequence:** A compatibility Food can advance to a newer publication. The revision and amount
pair preserves both the Recipe state and serving meaning used by the historical Log.

**Read more:** [Recipes and Nutrition History](../features/recipes-and-logging.md#logging-a-published-recipe) and
[Project Invariants](../project/invariants.md#why-revision-backed-logging)

### Unknown nutrients are not zero

**Decision:** Nutrient status distinguishes known, estimated, explicit zero, and unknown values.

**Consequence:** Missing source data cannot safely be interpreted as a measured zero. Carrying
status through aggregation exposes incomplete contributors instead of creating false precision.

**Read more:** [Foods and Nutrition Domain](../features/foods-and-nutrition.md#canonical-nutrition-model) and
[Project Invariants](../project/invariants.md#why-distinguish-unknown-from-zero)

### Explicit serving identities and gram weights

**Decision:** Serving-mode Recipe ingredients retain an exact serving ID. A household or display
unit implies mass only when an explicit gram weight establishes physical equivalence. Serving
records may additionally retain a complete reference quantity/unit/gram-weight triple so changing
the displayed unit does not silently change the physical amount represented.

**Consequence:** Defaults, labels, and user-facing units can change without changing authored or
logged meaning. Cross-dimension serving edits preserve gram authority or fail for explicit review;
partial/ambiguous reference measurements are rejected instead of guessed. Active Recipe serving
references remap only when one successor preserves the same serving semantics.

**Read more:** [Foods and Nutrition Domain](../features/foods-and-nutrition.md#serving-resolution) and
[Project Invariants](../project/invariants.md#why-explicit-serving-identities-and-gram-weights)

### Reference-derived Targets stay outside nutrition history

**Decision:** Target presentation/configuration is resolved independently from immutable nutrition
history. Per-nutrient tracking policy is applied first; manual overrides supersede dynamic
recommendations; calories may use the bounded Mifflin–St Jeor estimate; nutrients may use an
available DRI RDA/AI recommendation and then an FDA Daily Value reference. Nutrients without an
established goal can remain amount-only, and unsupported cases remain explicitly unavailable.

**Consequence:** Changing a profile, tracking preference, manual override, DRI dataset, or FDA
reference changes what the app compares against, never what a historical Log contained. The app can
represent `recommended`, `custom`, `amount_only`, and `ignored` tracking without inventing a target
where reference science does not establish one.

**Read more:** [Foods and Nutrition Domain](../features/foods-and-nutrition.md#targets-and-comparisons) and
[Project Invariants](../project/invariants.md#why-target-configuration-stays-outside-immutable-nutrition-history)

### Bounded OCR correction provenance

**Decision:** OCR confirmation stores versioned structured suggestions, observation IDs, and user
corrections, but not images, paths, complete raw OCR text, or unbounded parser responses.

**Consequence:** Parser changes and corrections must remain explainable without making sensitive
capture material part of the long-lived nutrition record. Provenance is append-only and is not a
resolver input. Guided camera framing and image-quality checks remain acquisition/review aids, not
new persisted nutrition authority.

**Read more:** [OCR, Search, Offline Behavior, and Local Backup](../features/ocr-search-and-offline.md#confirmation-and-provenance)
and [Project Invariants](../project/invariants.md#why-bounded-ocr-correction-provenance)

### Saved Foods and USDA Foods remain distinct

**Decision:** USDA search and preview do not become application Foods until an explicit import
creates a normal user-owned saved Food.

**Consequence:** Upstream results have different availability, identity, and payload quality.
Explicit import normalizes provenance, servings, nutrients, and deduplication before Recipes or
Logs can depend on the item.

**Read more:** [Foods and Nutrition Domain](../features/foods-and-nutrition.md#usda-fooddata-central) and
[OCR, Search, Offline Behavior, and Local Backup](../features/ocr-search-and-offline.md#unified-food-search)

### Search is composed, not centralized

**Decision:** The mobile discovery screen combines an owner-scoped saved-Food query with a separate
selected-authority USDA query. Local mode can call FoodData Central directly through
`localUsdaRuntime`; remote mode uses the backend USDA integration. There is no shared search index
or ranking service.

**Consequence:** The two sources have different identity and persistence semantics. Keeping them
separate makes imports explicit and lets each failure or loading state remain visible.

**Read more:** [OCR, Search, Offline Behavior, and Local Backup](../features/ocr-search-and-offline.md#unified-food-search)

### Online-first mobile architecture

**Status:** Superseded for mobile application-data authority by
[Explicit mobile application-data authority](#explicit-mobile-application-data-authority). It remains
the historical remote-mode and no-synchronization decision.

**Decision:** TanStack Query provides in-process server-state caching, but there is no durable
nutrition cache, offline mutation queue, or synchronization engine.

**Consequence:** Ownership, graph changes, immutable history, and authoritative calculations are
server transactions in remote mode. Safe retry is implemented without claiming that a local
mutation was committed offline.

**Read more:** [OCR, Search, Offline Behavior, and Local Backup](../features/ocr-search-and-offline.md#offline-and-caching-behavior)
and [Project Invariants](../project/invariants.md#why-an-online-first-design)

### Explicit mobile application-data authority

**Decision:** Mobile startup explicitly selects exactly one `local` or `remote` application-data
authority before runtime construction, Query cache creation, recovery, SQLite initialization, or
remote transport initialization. Deployment/security mode is a separate setting.

**Consequence:** Local mode uses the composed SQLite adapters without FastAPI or PostgreSQL; remote
mode preserves the existing API and authentication boundary. Selection never implies fallback,
dual writes, synchronization, cache sharing, recovery sharing, or data migration. Local USDA is a
separate direct external integration and is not an application-data authority.

**Read more:** [Architecture Overview](overview.md#system-boundaries) and the completed
[Epic 2 implementation backlog](../project/version-1.1/epic-2/implementation-backlog.md)

### Local backup restore is validated replacement, not synchronization

**Decision:** Local backup export creates a complete validated standalone SQLite snapshot. Restore
first inspects and stages a validated copy without modifying the active database, then activates it
only at a later local-runtime bootstrap. Existing local data is snapshotted for rollback before
replacement, and an unrecoverable rollback failure prevents the local authority from opening.

**Consequence:** The app has a safe explicit local recovery path without introducing merge,
synchronization, replication, conflict-resolution, or cloud-backup semantics. Invalid candidates
cannot become active through the normal flow, staging can be canceled before restart, and restore
failure preserves the prior local authority whenever safe rollback is possible.

**Read more:** [Local backup and restore](../features/ocr-search-and-offline.md#local-backup-and-restore) and
[Project Invariants](../project/invariants.md#why-local-backup-is-replacement-not-synchronization)

## Application structure and authority decisions

### Service-first, selective repository abstraction

**Decision:** Routers remain thin, services own transactional use cases, repositories centralize
reused or lock-sensitive queries, and small services may use SQLAlchemy directly when another
abstraction would not clarify authority.

**Consequence:** A rigid repository for every table would add indirection without moving business
authority. The selective boundary keeps transaction and ownership decisions visible while still
reusing complex persistence behavior.

**Read more:** [Architecture Overview](overview.md#backend-layers) and
[Repository Tour](../project/repository-tour.md#appsbackend)

### Ownership is enforced at multiple layers

**Decision:** Routers resolve authenticated identity, services use owner-scoped operations, and
database relationships reinforce compatible ownership.

**Consequence:** Friendly service errors and race-resistant database integrity solve different
parts of the same problem. A guessed UUID must not connect resources across users even if one layer
is implemented incorrectly.

**Read more:** [Foods and Nutrition Domain](../features/foods-and-nutrition.md#ownership-and-retry-behavior) and
[Project Invariants](../project/invariants.md#why-ownership-enforcement-in-several-layers)

### Payload-bound create idempotency

**Decision:** Retryable create request IDs are scoped to the owner and operation and bound to a
canonical payload fingerprint plus retained response snapshot.

**Consequence:** A lost mobile response must be safely replayable without allowing a changed
payload or an expired receipt to create a duplicate.

**Read more:** [Foods and Nutrition Domain](../features/foods-and-nutrition.md#ownership-and-retry-behavior) and
[Project Invariants](../project/invariants.md#why-payload-bound-idempotency)

### Fail-closed deployment configuration

**Decision:** Deployment mode and API URL are explicit. Public production startup is rejected until
a real identity provider exists.

**Consequence:** Development convenience must never become implicit production identity or
transport policy.

**Read more:** [Architecture Overview](overview.md#configuration-and-authentication),
[Development Guide](../project/development-guide.md#configuration-and-startup), and
[Project Invariants](../project/invariants.md#why-fail-closed-release-configuration)

### Separate application and control migration streams

**Decision:** Remote application data and operational promotion authority use separate Alembic
streams, credentials, and PostgreSQL databases. Local SQLite has its own schema-version migration
engine and is intentionally not an Alembic replay.

**Consequence:** Local SQLite evolution, remote feature migrations, and control migrations are
separate authority boundaries. Feature migrations must not implicitly control the promotion
ledger, control migrations must not become application schema, and PostgreSQL migration history
must not be mechanically ported into SQLite.

**Read more:** [Architecture Overview](overview.md#migrations),
[Control Plane Guide](../operations/control-plane.md#qualification-and-migration-safety), and
[Project Invariants](../project/invariants.md#why-two-migration-streams)

## Production-hardening decisions

These decisions belong to the advanced operational subsystem. Feature developers can usually stop
at the preceding sections.

### Independent Control Plane

**Decision:** Promotion evidence and workflow authority live in a PostgreSQL database independent
of both source and candidate application databases.

**Consequence:** Neither endpoint should be able to rewrite the evidence that authorizes its own
promotion or replacement. Control state must remain available when an application endpoint is not.

**Read more:** [Control Plane Guide](../operations/control-plane.md#what-it-is) and
[Project Invariants](../project/invariants.md#why-a-control-plane)

### WORM-bound canonical evidence

**Decision:** Exact canonical artifact bytes are registered in the control database and anchored to
an exact MinIO object version under COMPLIANCE retention.

**Consequence:** The database records semantic authority while object-lock storage independently
preserves the admitted bytes. A filename or caller-provided digest alone is insufficient evidence.

**Read more:** [Control Plane Guide](../operations/control-plane.md#canonical-evidence-flow) and
[Project Invariants](../project/invariants.md#why-worm-evidence)

### Independent qualification

**Decision:** Qualification inventories authoritative objects, routines, triggers, constraints,
owners, grants, and projections, and tamper tests must make it fail.

**Consequence:** A successful command does not prove that the surrounding security surface is
complete or unchanged. Qualification detects false-green manifests and authority drift.

**Read more:** [Control Plane Guide](../operations/control-plane.md#qualification-and-migration-safety),
[Testing Guide](../operations/testing.md#control-database-qualification), and
[Project Invariants](../project/invariants.md#why-qualification)

### Artifact-referenced admission pipeline

**Decision:** Executors request admission by referencing registered immutable evidence. PostgreSQL
locks and validates the complete semantic graph before recording a decision or advancing workflow.

**Consequence:** The executor must not author or substitute authoritative observations, and an
individually valid artifact must not pass when its environment, source, freeze, plan, run, or
reconciliation bindings disagree.

**Read more:** [Control Plane Guide](../operations/control-plane.md#admission)

### PostgreSQL role separation

**Decision:** Application and control databases each use distinct owner, migrator, runtime or
executor, read-only, and operations roles with exact grants.

**Consequence:** A runtime or executor credential must not gain schema ownership, evidence
authorship, migration authority, or an alternate path around write fencing and admission.

**Read more:** [Control Plane Guide](../operations/control-plane.md#authority-boundaries) and
[Production Hardening Stage 5C4.2a](../historical/production-hardening/production-hardening-phase5c4.2a.md)

## Next reading

- For system responsibilities, continue with the [Architecture Overview](overview.md).
- For application behavior, choose [Foods and Nutrition](../features/foods-and-nutrition.md),
  [Recipes and Nutrition History](../features/recipes-and-logging.md), or
  [OCR, Search, Offline Behavior, and Local Backup](../features/ocr-search-and-offline.md).
- For operational authority, continue with the optional [Control Plane Guide](../operations/control-plane.md).

## See also

- [Project Invariants](../project/invariants.md) provides longer-form rationale.
- [Project Constitution](../project/constitution.md) defines the enduring constraints decisions
  must respect.
- [Glossary](../reference/glossary.md) defines the terms used by these decisions.
- [Development Guide](../project/development-guide.md) maps decisions to code and tests.
- [Documentation index](../README.md) provides role-based reading paths.
