# Glossary

These definitions describe how terms are used in this repository. They are not general nutrition,
database, or mobile-development definitions. Follow the links when a term carries an invariant or
an operational authority boundary.

## Nutrition and application domain

### Food (`FoodItem`)

The persisted, user-owned nutrition entity used by serving resolution, Recipes, search, and Logs.
“Food” is the reader-facing term; `FoodItem` is the principal model/type name. A Food may be manual,
duplicated, USDA-imported, OCR-confirmed, or a managed Recipe compatibility projection. See
Foods and Nutrition.

### Saved Food

A Food explicitly persisted in the application for one owner. A USDA search result is not a Saved
Food until import succeeds. See Food sources.

### USDA Food and USDA import

A **USDA Food** is an upstream FoodData Central search/preview result. **USDA import** is the
explicit selected-authority operation that normalizes it into a user-owned Saved Food with retained
source identity: local mode imports into SQLite after a direct USDA request, while remote mode uses
the FastAPI/PostgreSQL integration. See
USDA FoodData Central.

### Nutrient Catalog

The canonical ordered set of nutrient identities, hierarchy, default units, and reference metadata
used by Foods, USDA/OCR mapping, summaries, and Targets. It includes ordinary macro/micronutrients
and current fatty-acid identities such as total Omega-3, ALA, EPA, DHA, and linoleic acid/Omega-6.
The catalog is not a user-editable target table.

### Qualified Nutrient Unit

A canonical semantic nutrition unit whose qualifier changes biological meaning, such as
`mcg RAE`, `mcg DFE`, `mg NE`, or `mg alpha-tocopherol`. These are not interchangeable with plain
`mcg`/`mg` merely because the mass scale is similar. Ordinary `g`/`mg`/`mcg` can be mass-converted;
a qualified semantic unit must match its canonical meaning.

### Serving Definition

A user/source-defined amount consisting of a label, quantity/unit, optional gram weight, source and
confirmation metadata, and optionally one complete reference measurement. A Food with servings has
exactly one default serving.

### Serving Reference Measurement

The optional all-or-none triple `reference_quantity`, `reference_unit`, and
`reference_gram_weight`. It records the physical measurement behind a serving so changing the
serving's displayed unit does not silently change the amount represented. See
Serving resolution.

### Gram Authority

The rule that explicit gram mass is the physical authority when relating a serving across mass and
non-mass presentation. Household/display units do not imply a mass conversion by themselves. An
edit that cannot preserve physical equivalence must be reviewed or rejected rather than guessed.

### Recipe

The mutable, user-owned authoring graph: name, yields, ingredients, ordering, and preparation notes.
Editing it does not modify an earlier publication revision. See
Authored Recipes.

### Publication

The explicit transaction that validates an authored Recipe, captures immutable revision content,
updates its active publication pointer, and creates/updates its compatibility Food projection. See
Publication.

### Recipe Revision / Publication Revision / Published Revision

Names for the immutable Recipe content captured by one successful publication. “Publication
revision” is the most precise reader-facing term; code types use Recipe revision/publication names.
It is insert-only and remains available to Logs and nested Recipes. See
Immutable Recipe revisions.

### Immutable Revision

A publication revision whose captured header, ingredients, amount definitions, and nutrient facts
cannot be edited in place. A changed Recipe is represented by another publication, not by rewriting
this row graph.

### Current Revision / Active Publication Revision

The immutable revision currently selected by a mutable Recipe for new downstream use. “Active
publication revision” is preferred because older revisions remain valid historical records. See
Publication.

### Draft Revision

Not a persisted concept in the current application. The authored Recipe itself is mutable draft
state; a revision exists only after publication. Do not add a `DraftRevision` layer by terminology
alone.

### Recipe compatibility Food projection (`FoodItem`)

A generated, managed Food-shaped projection of one published Recipe, linked to an exact publication
revision so existing Food selection, serving, nesting, and logging paths can be reused. It is
compatibility state, not historical authority. See
Recipe compatibility projection.

### Needs Republish (`needs_republish`)

A mutable Recipe flag showing authored content no longer matches the active publication. It clears
only after a successful new publication; it does not mutate or invalidate prior revisions.

### Amount Definition

The exact serving- or gram-based quantity semantics attached to a published Recipe and referenced by
a Recipe-backed Log. It preserves what an amount meant even after another publication changes the
Recipe. See Logging a published Recipe.

### Revision Resolution

The selected runtime process that resolves a Recipe-backed Food/Log to one exact immutable revision
and amount definition before calculating consumed nutrition. See
Revision-backed nutrition logging.

### Daily Log

The dated collection of user-owned consumed-food entries and their persisted nutrient snapshots.
Daily totals aggregate snapshots, never current mutable Food nutrients. See
Daily Log creation.

### Daily Log Snapshot / Nutrient Snapshot

The nutrients and provenance resolved for the consumed amount when a Log entry is created or
explicitly edited. Snapshot rows preserve history when a source Food changes or is deleted.

### Historical Nutrition

Nutrition already committed to immutable publication revisions or Daily Log snapshots. It is read
from retained historical facts rather than recomputed from the latest authored Recipe or Food.
This term does not imply the application currently has a separate longitudinal trends/analytics
subsystem. See [Why immutable nutrition history?](architecture/decisions.md#immutable-daily-log-nutrition).

### DRI / Dietary Reference Intake

The versioned canonical reference dataset used by Target resolution for nutrient recommendations
and applicable upper limits. The app resolves established RDA or AI recommendations for supported
adult reference profiles; it does not turn every DRI source fact into a target. Current supported
life stages include general adults and bounded pregnancy/lactation profiles. See
Targets and comparisons.

### DRI Recommendation

One resolved nutrient recommendation from the canonical DRI dataset. It can be an RDA or AI,
fixed or per-kilogram, and may carry separate upper-limit metadata. A missing/unsupported DRI
recommendation remains explicit rather than being fabricated.

### FDA Daily Value

Versioned regulatory reference data used as a Target fallback/reference where applicable. FDA
Daily Values are not properties of a Food nutrient row and do not rewrite historical nutrition.

### Target Tracking Mode

The effective presentation/comparison mode returned for a nutrient:
`recommended`, `custom`, `amount_only`, or `ignored`.

- `recommended` means a dynamic current recommendation/reference is active or currently unavailable
  under the recommendation policy.
- `custom` means a manual override is the effective target.
- `amount_only` tracks consumed amount without a goal/reference target.
- `ignored` excludes the nutrient from comparison presentation.

### Tracking Preference

A persisted explicit user preference for a nutrient to be `amount_only` or `ignored`. Absence of a
preference means dynamic default resolution applies. Preferences are configuration, not historical
nutrition facts.

### OCR Provenance

The bounded, versioned, append-only structured trace connecting OCR suggestions, source observation
IDs, confirmation actions, and corrections. It excludes images and unbounded raw OCR and is not a
nutrition resolver input. See
Confirmation and provenance.

### OCR Image-Quality Inspection

Best-effort native pre-recognition analysis of a captured/selected local image. It can return
bounded focus/luminance/text-region metrics used for conservative advisory warnings. It is not an
authority that accepts/rejects nutrition facts, and its absence/failure does not automatically fail
recognition.

### Guided Nutrition Camera

The app-owned `expo-camera` nutrition-label capture preview with back-camera lens selection,
framing guidance, and accessible capture/cancel controls. Framing marks are guidance rather than a
persisted crop or nutrition boundary.

### Ownership Enforcement

The combined route identity, owner-scoped service/query behavior, and relationship constraints that
prevent a resource UUID from crossing user boundaries. See
[Why ownership is layered](architecture/decisions.md#ownership-is-enforced-at-multiple-layers).

## Code and persistence boundaries

### NutritionRuntime

The mobile application's authority-neutral interface for Calendar, nutrients, Foods, Recipes,
Daily Logs, Targets, OCR, and USDA. Startup selects exactly one implementation before ordinary
application-data use: local SQLite or remote FastAPI/PostgreSQL. Feature code should not bypass
this boundary to mix authorities. Local backup activation is a bounded pre-runtime maintenance
operation because it may replace the local database before this authority opens. See
Explicit mobile application-data authority.

### Local SQLite Authority / Local Mode

The authoritative on-device application-data runtime selected with
`EXPO_PUBLIC_NUTRITION_DATA_AUTHORITY=local`. It persists the current semantic model in
`expo-sqlite` and does not require FastAPI/PostgreSQL for application-data operations. It is not a
cache or replica of the remote database and does not synchronize automatically.

### Remote Authority / Remote Mode

The preserved FastAPI/PostgreSQL application runtime selected with
`EXPO_PUBLIC_NUTRITION_DATA_AUTHORITY=remote`. Mobile requests use the remote adapter and central
HTTP/authentication client. Remote mode does not receive durable local application-data writes as a
fallback.

### Local Backup Artifact

A validated standalone SQLite snapshot created from the active local application database for
explicit export. It contains application SQLite data but excludes separately stored secrets such as
the personal USDA credential. It is not a sync package or a remote backup.

### Pending / Staged Restore

A selected backup that has been validated and copied into the pending-restore namespace without
modifying the active database. It can be canceled before restart. Activation is attempted only at
a subsequent local-runtime bootstrap.

### Restore Activation

The restart-time replacement of the local SQLite authority with a validated staged backup. When an
active database exists, the app first creates a rollback snapshot. The replacement is validated
again and a failed activation restores the prior authority where safe rollback is possible. An
unrecoverable rollback failure prevents ambiguous local startup. See
Local backup and restore.

### Canonical Domain Model

The shared semantic meaning both runtime authorities must preserve: nutrition/status semantics,
serving/reference authority, immutable Recipe revisions, Daily Log snapshots, owner scope,
idempotency, provenance, Target/reference behavior, and public response contracts. It is not one
generated cross-platform class. See System boundaries.

### Runtime Adapter

A local or remote implementation of the `NutritionRuntime` capability interfaces. Local adapters
own application behavior against SQLite; remote adapters translate the same mobile-facing contract
to the existing FastAPI API.

### Repository Contract

In the remote backend, the owner-scoped, transaction-aware query or persistence behavior exposed by
selective Python repository classes. It is not the cross-authority abstraction; that role belongs
to `NutritionRuntime`. Local runtime code may use local repository helpers where they clarify
SQLite persistence without reproducing the backend's class structure.

### Persistence Layer

The authority-specific durable implementation beneath `NutritionRuntime`.

- Local application data: `apps/mobile/src/storage/sqlite` plus local runtime/repository code.
- Local maintenance: `apps/mobile/src/storage/backup`, which validates/exports/replaces the local
  SQLite authority but does not provide ordinary feature persistence.
- Remote application data: SQLAlchemy models/repositories plus application Alembic migrations in
  PostgreSQL.
- Operations: independent control PostgreSQL, which is not an application-data authority.

### Repository Provider / Repository Factory

A generic swappable persistence-provider/factory abstraction is not implemented. `NutritionRuntime`
is a deliberate application capability boundary, not a table-by-table repository factory. Adding a
generic ORM/provider layer would be a new architectural decision.

### Native SQLite

The implemented local application-data authority. `expo-sqlite` stores the fresh semantic local
schema, with explicit schema versioning/migrations, canonical exact-value encodings, foreign keys,
WAL configuration, bounded busy handling, and local transaction/write coordination. It is not an
offline cache layered under PostgreSQL.

### SQLite Schema Evolution

The local schema-version migration mechanism under `apps/mobile/src/storage/sqlite`. The SQLite
schema is a fresh semantic model and intentionally does not replay PostgreSQL Alembic
revision-by-revision. Phase 5/control-plane and PostgreSQL role/promotion infrastructure stay out of
SQLite.

### Backend migration streams

The parked backend has its own application and control Alembic streams, separate from SQLite. See
the [backend overview](backend/README.md#migrations).

### Shared contract fixtures

Machine-readable parity/transfer fixtures under `packages/shared-contracts/` that pin the
cross-runtime contract (including the PostgreSQL-to-SQLite transfer format). They are regression
evidence, not a generated API SDK.

Production-hardening and control-plane terms (control plane, WORM evidence, qualification,
admission) are defined in the [backend overview](backend/README.md#production-hardening-glossary).

## See also

- [Architecture overview](architecture/overview.md)
- [Design decisions](architecture/decisions.md)
- [Documentation index](README.md)
