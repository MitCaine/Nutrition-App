# Glossary

These definitions describe how terms are used in this repository. They are not general nutrition,
database, or mobile-development definitions. Follow the links when a term carries an invariant or
an operational authority boundary.

## Nutrition and application domain

### Food (`FoodItem`)

The persisted, user-owned nutrition entity used by serving resolution, Recipes, search, and Logs.
“Food” is the reader-facing term; `FoodItem` is the principal model/type name. A Food may be manual,
duplicated, USDA-imported, OCR-confirmed, or a managed Recipe compatibility projection. See
[Foods and Nutrition](../foods-and-nutrition.md#food-lifecycle).

### Saved Food

A Food that has been explicitly persisted in the application for one owner. A USDA search result is
not a Saved Food until import succeeds. See [Food sources](../foods-and-nutrition.md#food-sources).

### USDA Food and USDA import

A **USDA Food** is an upstream FoodData Central search or preview result. **USDA import** is the
explicit backend transaction that normalizes it into a user-owned Saved Food with retained source
identity. See [USDA FoodData Central](../foods-and-nutrition.md#usda-fooddata-central).

### Recipe

The mutable, user-owned authoring graph: name, yield, ingredients, ordering, and preparation notes.
Editing it does not modify an earlier publication revision. See
[Authored Recipes](../recipes-and-logging.md#authored-recipes).

### Publication

The explicit transaction that validates an authored Recipe, captures immutable revision content,
updates its active publication pointer, and creates or updates its compatibility Food projection.
See [Publication](../recipes-and-logging.md#publication).

### Recipe Revision / Publication Revision / Published Revision

Names for the immutable Recipe content captured by one successful publication. “Publication
revision” is the most precise reader-facing term; code types use Recipe revision/publication names.
It is insert-only and remains available to Logs and nested Recipes. See
[Immutable Recipe revisions](../architecture-decisions.md#immutable-recipe-revisions).

### Immutable Revision

A publication revision whose captured header, ingredients, amount definitions, and nutrient facts
cannot be edited in place. A changed Recipe is represented by another publication, not by rewriting
this row graph.

### Current Revision / Active Publication Revision

The immutable revision currently selected by a mutable Recipe for new downstream use. “Active
publication revision” is preferred because older revisions remain valid historical records; they
are not obsolete data. See [Publication](../recipes-and-logging.md#publication).

### Draft Revision

Not a persisted concept in the current application. The authored Recipe itself is mutable draft
state; a revision exists only after publication. Do not add a `DraftRevision` layer by terminology
alone.

### Recipe compatibility Food projection (`FoodItem`)

A generated, managed Food-shaped projection of one published Recipe, linked to an exact publication
revision so existing Food selection, serving, nesting, and logging paths can be reused. It is
compatibility state, not historical authority. See
[Recipe compatibility projection](../recipes-and-logging.md#recipe-compatibility-projection).

### Needs Republish (`needs_republish`)

A mutable Recipe flag showing that authored content no longer matches the active publication. It
clears only after a successful new publication; it does not mutate or invalidate prior revisions.

### Amount Definition

The exact serving or gram-based quantity semantics attached to a published Recipe and referenced by
a Recipe-backed Log. It preserves what an amount meant even after another publication changes the
Recipe. See [Logging a published Recipe](../recipes-and-logging.md#logging-a-published-recipe).

### Revision Resolution

The backend process that resolves a Recipe-backed Food/Log to one exact immutable revision and
amount definition before calculating consumed nutrition. See
[Revision-backed nutrition logging](../architecture-decisions.md#revision-backed-nutrition-logging).

### Daily Log

The dated collection of user-owned consumed-food entries and their persisted nutrient snapshots.
Daily totals aggregate snapshots, never current mutable Food nutrients. See
[Daily Log creation](../recipes-and-logging.md#daily-log-creation).

### Daily Log Snapshot / Nutrient Snapshot

The nutrients and provenance resolved for the consumed amount when a Log entry is created or
explicitly edited. Snapshot rows preserve history when a source Food changes or is deleted.

### Historical Nutrition

Nutrition already committed to immutable publication revisions or Daily Log snapshots. It is read
from retained historical facts rather than recomputed from the latest authored Recipe or Food.
See [Why immutable nutrition history?](../why-this-exists.md#why-immutable-nutrition-history).

### OCR Provenance

The bounded, versioned, append-only structured trace connecting OCR suggestions, source observation
IDs, confirmation actions, and corrections. It excludes images and unbounded raw OCR and is not a
nutrition resolver input. See
[Confirmation and provenance](../ocr-search-and-offline.md#confirmation-and-provenance).

### Ownership Enforcement

The combined route identity, owner-scoped service/query behavior, and relationship constraints that
prevent a resource UUID from crossing user boundaries. See
[Why ownership is layered](../why-this-exists.md#why-ownership-enforcement-in-several-layers).

## Code and persistence boundaries

### Canonical Domain Model

The shared meaning enforced by backend schemas, domain/nutrition code, services, and persistence—not
a single class or generated cross-platform model. Backend Pydantic/domain behavior is authoritative;
the small `packages/shared-contracts` reference is not a generated API SDK. See
[System boundaries](../architecture.md#system-boundaries).

### Repository Contract

The owner-scoped, transaction-aware query or persistence behavior exposed by one of the selective
backend repository classes. It is an internal Python boundary, not a swappable storage-provider
interface. See [Repositories and models](../architecture.md#repositories-and-models).

### Persistence Layer

SQLAlchemy models, repositories, migrations, constraints, and transaction behavior that store the
application domain in PostgreSQL. Services own use-case transactions; repositories do not become a
second business-authority layer.

### Repository Provider / Repository Factory

Not implemented abstractions in this repository. The app uses selective repository classes and
direct construction/dependency wiring for one authoritative PostgreSQL backend. Introducing a
provider or factory to swap persistence engines would be a new architectural decision, not an
extension point that already exists. See the
[repository tradeoff](../why-this-exists.md#decision-tradeoffs-at-a-glance).

### Native SQLite

Not part of the mobile runtime. SQLite may appear in backend unit-test configuration for portable
logic, but PostgreSQL is authoritative for locks, constraints, grants, migrations, and concurrency.
The mobile app has no durable SQLite nutrition cache or mutation queue. See
[Offline and caching behavior](../ocr-search-and-offline.md#offline-and-caching-behavior).

### Application Migration Stream

The Alembic history under `app/migrations`, applied only to the application PostgreSQL database.
It owns Foods, Recipes, Logs, OCR traces, Targets, historical-conversion metadata, and local fence
prerequisites. See [Migrations](../architecture.md#migrations).

### Control Migration Stream

The independent Alembic history under `app/control_migrations`, applied only with the control
migration configuration and credential. It owns promotion evidence and authority, never feature
tables. See [Qualification and migration safety](../control-plane.md#qualification-and-migration-safety).

## Historical conversion and control operations

These terms belong to the advanced production-hardening subsystem. Feature developers generally do
not need them before contributing to the Nutrition App.

### Historical Inventory

A privacy-bounded, read-only description of a populated database before historical Recipe
conversion. It records counts, classifications, schema facts, and snapshot anchors without
repairing the source. See [Production Hardening Phase 5B](../production-hardening-phase5b.md).

### Historical Bridge / Archive Bridge

The Phase 5C1 compatibility layer that preserves legacy Recipe facts in archive/bridge structures
on an isolated clone so a deterministic conversion plan can be produced. “Historical bridge” is
the canonical stage name; “archive bridge” refers to its retained archive metadata, not a separate
runtime subsystem. See [Production Hardening Phase 5C1](../production-hardening-phase5c1.md).

### Control Plane

The independent PostgreSQL authority for immutable operational evidence, admission, promotion
workflow, event/outbox state, and minimal gate projection. It is an advanced operations subsystem,
not the primary Nutrition App domain. See [Control Plane Guide](../control-plane.md).

### Canonical Artifact

A strictly validated, versioned contract serialized by the one canonical JSON implementation. Its
SHA-256 digest and byte count bind the exact evidence admitted by the control plane.

### WORM Evidence

Canonical artifact bytes anchored to an exact versioned object under COMPLIANCE retention, with
bucket, key, version, digest, byte count, and retention facts bound in the control database. WORM
preserves bytes; it does not by itself authenticate the human or collector. See
[Canonical evidence flow](../control-plane.md#canonical-evidence-flow).

### Qualification

Independent inventory and validation of the authoritative database surface, including routines,
owners, grants, triggers, constraints, projections, and expected seed/registry data. Tampering with
an authoritative object must make qualification fail.

### Runtime Qualification

Qualification evidence about whether a runtime or candidate database exposes the expected schema,
roles, functions, and prerequisites. It is not permission to promote, and normal application
runtime does not yet consume the independent control gate. See
[Current runtime boundary](../control-plane.md#current-runtime-boundary).

### Migration Admission

The fail-closed decision that a database and migration path satisfy the required identity, schema,
role, evidence, and policy prerequisites before a high-risk transition proceeds. In Phase 5C4,
admission authority belongs to control PostgreSQL, not to an executor exit code.

### Admission

A SERIALIZABLE control-database decision over a complete, locked evidence graph. An accepted
artifact in isolation is insufficient when environment, source, candidate, freeze, plan, run,
qualification, performance, or WORM bindings disagree. See [Admission](../control-plane.md#admission).

### Historical Bridge Qualification Receipt

Deterministic evidence that an isolated historical Recipe conversion result satisfies its bounded
correctness contract. It is evidence consumed by later policy; it is not itself promotion
authorization.

## Next reading

- Read [Why This Exists](../why-this-exists.md) for the rationale behind application invariants.
- Use the [Architecture Decision Index](../architecture-decisions.md) to locate a specific decision.
- Return to the [Documentation Index](../README.md) to choose a domain or operations path.

## See also

- [Repository Tour](../repository-tour.md)
- [Architecture Guide](../architecture.md)
- [Development Guide](../development-guide.md)
