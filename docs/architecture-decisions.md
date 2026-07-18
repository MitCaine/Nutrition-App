# Architecture decision index

This is a memory aid for the project's major architectural choices. It answers “I remember we did
this—but why?” and points to the guide that contains the full explanation. It is an index, not a
replacement for the architecture or domain guides.

## Application and nutrition decisions

### Immutable Daily Log nutrition

**Decision:** A Daily Log stores resolved nutrient snapshots, and daily totals aggregate those
snapshots rather than current Food nutrient rows.

**Why it exists:** Food definitions are expected to be corrected over time; historical nutrition
must continue to describe what was resolved when the user logged it. Only an explicit Log edit
rebuilds that Log's snapshots.

**Read more:** [Recipes and Nutrition History](recipes-and-logging.md#daily-log-creation) and
[Why This Exists](why-this-exists.md#why-immutable-nutrition-history)

### Immutable Recipe revisions

**Decision:** Publishing a Recipe inserts a new immutable revision instead of overwriting published
state.

**Why it exists:** Mutable authoring and historical use have different lifecycles. A Recipe can
evolve while past Logs and nested Recipes retain the exact published content they used.

**Read more:** [Recipes and Nutrition History](recipes-and-logging.md#publication) and
[Why This Exists](why-this-exists.md#why-immutable-recipe-revisions)

### Recipe Food compatibility projections

**Decision:** A published Recipe is represented by a managed Food projection linked to one exact
publication revision.

**Why it exists:** Ingredient selection, serving resolution, search, and logging already understand
Foods. The projection reuses those paths without making mutable projection data the historical
authority.

**Read more:** [Recipes and Nutrition History](recipes-and-logging.md#recipe-compatibility-projection)
and [Why This Exists](why-this-exists.md#why-a-recipe-food-projection)

### Revision-backed nutrition logging

**Decision:** Recipe Logs store both the immutable publication revision and its exact amount
definition.

**Why it exists:** A compatibility Food can advance to a newer publication. The revision and amount
pair preserves both the Recipe state and serving meaning used by the historical Log.

**Read more:** [Recipes and Nutrition History](recipes-and-logging.md#logging-a-published-recipe) and
[Why This Exists](why-this-exists.md#why-revision-backed-logging)

### Unknown nutrients are not zero

**Decision:** Nutrient status distinguishes known, estimated, explicit zero, and unknown values.

**Why it exists:** Missing source data cannot safely be interpreted as a measured zero. Carrying
status through aggregation exposes incomplete contributors instead of creating false precision.

**Read more:** [Foods and Nutrition Domain](foods-and-nutrition.md#canonical-nutrition-model) and
[Why This Exists](why-this-exists.md#why-distinguish-unknown-from-zero)

### Explicit serving identities and gram weights

**Decision:** Serving-mode Recipe ingredients retain an exact serving ID, and household measures
imply mass only when an explicit gram weight exists.

**Why it exists:** Defaults and display labels can change. Exact serving semantics prevent silent
Recipe changes, while ambiguous remaps fail atomically instead of guessing.

**Read more:** [Foods and Nutrition Domain](foods-and-nutrition.md#serving-resolution) and
[Why This Exists](why-this-exists.md#why-explicit-serving-identities-and-gram-weights)

### Bounded OCR correction provenance

**Decision:** OCR confirmation stores versioned structured suggestions, observation IDs, and user
corrections, but not images, paths, complete raw OCR text, or unbounded parser responses.

**Why it exists:** Parser changes and corrections must remain explainable without making sensitive
capture material part of the long-lived nutrition record. Provenance is append-only and is not a
resolver input.

**Read more:** [OCR, Search, and Offline Behavior](ocr-search-and-offline.md#confirmation-and-provenance)
and [Why This Exists](why-this-exists.md#why-bounded-ocr-correction-provenance)

### Saved Foods and USDA Foods remain distinct

**Decision:** USDA search and preview do not become application Foods until an explicit import
creates a normal user-owned saved Food.

**Why it exists:** Upstream results have different availability, identity, and payload quality.
Explicit import normalizes provenance, servings, nutrients, and deduplication before Recipes or
Logs can depend on the item.

**Read more:** [Foods and Nutrition Domain](foods-and-nutrition.md#usda-fooddata-central) and
[OCR, Search, and Offline Behavior](ocr-search-and-offline.md#unified-food-search)

### Search is composed, not centralized

**Decision:** The mobile discovery screen combines an owner-scoped saved-Food query with a separate
backend USDA query. There is no search index or shared ranking service.

**Why it exists:** The two sources have different identity and persistence semantics. Keeping them
separate makes imports explicit and lets each failure or loading state remain visible.

**Read more:** [OCR, Search, and Offline Behavior](ocr-search-and-offline.md#unified-food-search)

### Online-first mobile architecture

**Decision:** TanStack Query provides in-process server-state caching, but there is no durable
nutrition cache, offline mutation queue, or synchronization engine.

**Why it exists:** Ownership, graph changes, immutable history, and authoritative calculations are
server transactions. Safe retry is implemented without claiming that a local mutation was
committed offline.

**Read more:** [OCR, Search, and Offline Behavior](ocr-search-and-offline.md#offline-and-caching-behavior)
and [Why This Exists](why-this-exists.md#why-an-online-first-design)

## Application structure and authority decisions

### Service-first, selective repository abstraction

**Decision:** Routers remain thin, services own transactional use cases, repositories centralize
reused or lock-sensitive queries, and small services may use SQLAlchemy directly when another
abstraction would not clarify authority.

**Why it exists:** A rigid repository for every table would add indirection without moving business
authority. The selective boundary keeps transaction and ownership decisions visible while still
reusing complex persistence behavior.

**Read more:** [Architecture Guide](architecture.md#backend-layers) and
[Repository Tour](repository-tour.md#appsbackend)

### Ownership is enforced at multiple layers

**Decision:** Routers resolve authenticated identity, services use owner-scoped operations, and
database relationships reinforce compatible ownership.

**Why it exists:** Friendly service errors and race-resistant database integrity solve different
parts of the same problem. A guessed UUID must not connect resources across users even if one layer
is implemented incorrectly.

**Read more:** [Foods and Nutrition Domain](foods-and-nutrition.md#ownership-and-retry-behavior) and
[Why This Exists](why-this-exists.md#why-ownership-enforcement-in-several-layers)

### Payload-bound create idempotency

**Decision:** Retryable create request IDs are scoped to the owner and operation and bound to a
canonical payload fingerprint plus retained response snapshot.

**Why it exists:** A lost mobile response must be safely replayable without allowing a changed
payload or an expired receipt to create a duplicate.

**Read more:** [Foods and Nutrition Domain](foods-and-nutrition.md#ownership-and-retry-behavior) and
[Why This Exists](why-this-exists.md#why-payload-bound-idempotency)

### Fail-closed deployment configuration

**Decision:** Deployment mode and API URL are explicit. Public production startup is rejected until
a real identity provider exists.

**Why it exists:** Development convenience must never become implicit production identity or
transport policy.

**Read more:** [Architecture Guide](architecture.md#configuration-and-authentication),
[Development Guide](development-guide.md#configuration-and-startup), and
[Why This Exists](why-this-exists.md#why-fail-closed-release-configuration)

### Separate application and control migration streams

**Decision:** Application data and operational promotion authority use separate Alembic streams,
credentials, and PostgreSQL databases.

**Why it exists:** Feature migrations must not implicitly control the promotion ledger, and control
migrations must not become a second application schema authority.

**Read more:** [Architecture Guide](architecture.md#migrations),
[Control Plane Guide](control-plane.md#qualification-and-migration-safety), and
[Why This Exists](why-this-exists.md#why-two-migration-streams)

## Production-hardening decisions

These decisions belong to the advanced operational subsystem. Feature developers can usually stop
at the preceding sections.

### Independent Control Plane

**Decision:** Promotion evidence and workflow authority live in a PostgreSQL database independent
of both source and candidate application databases.

**Why it exists:** Neither endpoint should be able to rewrite the evidence that authorizes its own
promotion or replacement. Control state must remain available when an application endpoint is not.

**Read more:** [Control Plane Guide](control-plane.md#what-it-is) and
[Why This Exists](why-this-exists.md#why-a-control-plane)

### WORM-bound canonical evidence

**Decision:** Exact canonical artifact bytes are registered in the control database and anchored to
an exact MinIO object version under COMPLIANCE retention.

**Why it exists:** The database records semantic authority while object-lock storage independently
preserves the admitted bytes. A filename or caller-provided digest alone is insufficient evidence.

**Read more:** [Control Plane Guide](control-plane.md#canonical-evidence-flow) and
[Why This Exists](why-this-exists.md#why-worm-evidence)

### Independent qualification

**Decision:** Qualification inventories authoritative objects, routines, triggers, constraints,
owners, grants, and projections, and tamper tests must make it fail.

**Why it exists:** A successful command does not prove that the surrounding security surface is
complete or unchanged. Qualification detects false-green manifests and authority drift.

**Read more:** [Control Plane Guide](control-plane.md#qualification-and-migration-safety),
[Testing Guide](testing.md#control-database-qualification), and
[Why This Exists](why-this-exists.md#why-qualification)

### Artifact-referenced admission pipeline

**Decision:** Executors request admission by referencing registered immutable evidence. PostgreSQL
locks and validates the complete semantic graph before recording a decision or advancing workflow.

**Why it exists:** The executor must not author or substitute authoritative observations, and an
individually valid artifact must not pass when its environment, source, freeze, plan, run, or
reconciliation bindings disagree.

**Read more:** [Control Plane Guide](control-plane.md#admission)

### PostgreSQL role separation

**Decision:** Application and control databases each use distinct owner, migrator, runtime or
executor, read-only, and operations roles with exact grants.

**Why it exists:** A runtime or executor credential must not gain schema ownership, evidence
authorship, migration authority, or an alternate path around write fencing and admission.

**Read more:** [Control Plane Guide](control-plane.md#authority-boundaries) and
[Production Hardening Stage 5C4.2a](production-hardening-phase5c4.2a.md)

## Next reading

- For system responsibilities, continue with the [Architecture Guide](architecture.md).
- For application behavior, choose [Foods and Nutrition](foods-and-nutrition.md),
  [Recipes and Nutrition History](recipes-and-logging.md), or
  [OCR, Search, and Offline Behavior](ocr-search-and-offline.md).
- For operational authority, continue with the optional [Control Plane Guide](control-plane.md).

## See also

- [Why This Exists](why-this-exists.md) provides longer-form rationale.
- [Development Guide](development-guide.md) maps decisions to code and tests.
- [Documentation index](README.md) provides role-based reading paths.
