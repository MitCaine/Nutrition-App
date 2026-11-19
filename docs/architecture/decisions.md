# Design decisions and invariants

The rules the app is built around, what each one means in practice, and why it was chosen. A change
that would break one of these needs a deliberate decision, not a quiet code change. The short list
in [AGENTS.md](../../AGENTS.md) points here.

Backend-only decisions (PostgreSQL locking, control plane, WORM evidence, qualification, role
separation) are in the [parked backend overview](../backend/README.md#backend-design-decisions).

## Tradeoffs at a glance

| Decision | Benefit | Cost | Why chosen |
| --- | --- | --- | --- |
| Immutable Daily Log nutrition | Past totals stay explainable after Food edits or deletion. | Logs store duplicated nutrient snapshots; Log edits rebuild them atomically. | Historical truth matters more than saving rows. |
| Immutable Recipe revisions | Logs and nested Recipes keep the exact published content. | Publication stores another graph and needs revision-resolution code. | Mutable authoring can't serve as historical authority. |
| Explicit publication | Users edit freely; "published" has one transactional meaning. | A Recipe can be stale (`needs_republish`) until republished. | Safer than silently changing every downstream consumer on save. |
| Recipe compatibility Food | Published Recipes reuse Food search, serving, ingredient and logging paths. | Projection must be regenerated and is never historical authority. | Reuse beats a parallel "loggable item" hierarchy while the revision link stays authoritative. |
| Explicit serving identity + gram authority | Labels and display units can change without changing physical meaning. | Serving edits need complete reference metadata or explicit review. | Household units aren't universal mass conversions. |
| Targets outside history | Profiles, DRI/FDA data and preferences evolve without changing past intake. | Comparison resolves target policy separately from Log snapshots. | Goals are interpretation, not historical facts. |
| Validated local backup replacement | Export/restore without a sync engine. | Restore needs validation, staging, restart-time activation and rollback. | Merge/sync would be a different architecture. |
| Layered ownership enforcement | Clear errors plus race-resistant integrity. | Owner predicates appear at several layers. | One missed check must not connect data across owners. |
| One explicit data authority | Each running app has one persisted authority, never mixed state. | No fallback between local and remote. | Correct sync would need conflict rules for every graph and immutable-history case. |
| Bounded OCR provenance | Parser behavior and corrections stay explainable with little privacy exposure. | Can't reproduce every detail of the original capture. | Structured evidence is worth keeping; images and raw OCR text aren't. |

## Nutrition history

### Immutable Daily Log nutrition

**Decision:** A Daily Log stores resolved nutrient snapshots, and daily totals aggregate those
snapshots, never current Food nutrient rows. Only an explicit Log edit rebuilds that Log's snapshots.

**Why:** People correct Food definitions. History must still describe what was resolved when the
item was logged. Editing the source Food alone changes future logging, not the past.

See [Daily Log creation](../features/recipes-and-logging.md#daily-log-creation).

### Unknown nutrients are not zero

**Decision:** Nutrient status distinguishes known, estimated, explicit zero, and unknown, and that
status is carried through resolution and aggregation.

**Why:** "The label says 0 mg" and "the source didn't provide sodium" support different conclusions.
Treating both as zero creates false confidence; carrying status exposes incomplete contributors.

See [Canonical nutrition model](../features/foods-and-nutrition.md#canonical-nutrition-model).

### Complete is explicit date-owned state

**Decision:** Complete is a persisted positive assertion per owner and Daily Log calendar date. It is
never inferred from Log presence or nutrient evidence. Nutrition-changing Log mutations clear it in
the same transaction; metadata-only or exactly snapshot-preserving edits may keep it.

**Consequence:** Absence means "not confirmed complete", not a stored negative. Migration doesn't
backfill it; backup/restore preserves explicit assertions without inventing them.

See [Complete day state](../features/recipes-and-logging.md#complete-day-state).

### History is a bounded projection over Daily Log evidence

**Decision:** History reads an inclusive, owner-scoped range of at most 30 dates of immutable Daily
Log evidence and Complete metadata through the Daily Logs capability. The UI shows 7- and 30-day
ranges ending yesterday. One shared projection
(`apps/mobile/src/features/history/historyProjection.ts`) owns averages, per-nutrient day counts,
exact decimal arithmetic, gaps and grouped rows.

**Consequence:** Missing dates stay gaps, explicit zero stays a usable zero, estimated and
mixed-unknown values stay numeric with provenance, and unknown-only evidence stays unavailable.
Current Targets are a separately labeled lens, not reconstructed historical goals.

See [Nutrition History and Trends](../features/recipes-and-logging.md#nutrition-history-and-trends).

## Recipes

### Immutable Recipe revisions

**Decision:** Publishing a Recipe inserts a new immutable revision (content, amount definitions,
nutrient totals) instead of overwriting published state. The mutable Recipe points at its active
revision; Logs and nested Recipes point at the revision they used.

**Why:** Authored Recipes change; logged meals must not. If Logs referenced the current Recipe,
editing it tomorrow would rewrite yesterday.

See [Publication](../features/recipes-and-logging.md#publication).

### Recipe Food compatibility projections

**Decision:** A published Recipe is represented by a managed Food projection linked to one exact
publication revision.

**Why:** Foods already work in ingredient selection, serving resolution, search, logging and
nesting. The projection reuses all of that. It is compatibility state only: the revision link, not
the projection, is the historical authority.

See [Recipe compatibility projection](../features/recipes-and-logging.md#recipe-compatibility-projection).

### Revision-backed nutrition logging

**Decision:** Recipe Logs store both the immutable publication revision and its exact amount
definition.

**Why:** The compatibility Food can advance to a newer publication. The revision + amount pair still
answers "which Recipe state and which serving meaning did this Log use?"

See [Logging a published Recipe](../features/recipes-and-logging.md#logging-a-published-recipe).

## Foods, servings and targets

### Explicit serving identities and gram weights

**Decision:** Serving-mode Recipe ingredients keep an exact serving ID. A household or display unit
implies mass only when an explicit gram weight establishes it. Servings may carry a complete
reference quantity/unit/gram-weight triple, all or none.

**Why:** "1 cup" is not a universal mass. Keeping the exact serving stops a later default-serving
change from silently altering a Recipe. Gram mass is the authority across mass/non-mass
presentation; if an edit can't preserve equivalence unambiguously, it requires review or fails
rather than guessing. Recipe serving references remap only to one semantically equivalent successor.

See [Serving resolution](../features/foods-and-nutrition.md#serving-resolution).

### Targets stay outside nutrition history

**Decision:** Targets resolve independently of Log snapshots. Order: per-nutrient tracking policy
(`recommended`, `custom`, `amount_only`, `ignored`), then manual overrides, then the bounded
Mifflin–St Jeor calorie estimate, DRI RDA/AI recommendations, and FDA Daily Values. Nutrients without
an established goal stay amount-only; unsupported cases stay explicitly unavailable.

**Why:** A Log answers what was eaten; a target answers how current settings interpret it. Changing a
profile, preference, override, DRI dataset or FDA catalog must never change stored revisions or
snapshots.

See [Targets and comparisons](../features/foods-and-nutrition.md#targets-and-comparisons).

### Saved Foods and USDA Foods remain distinct

**Decision:** USDA search results and previews are not app Foods until an explicit import creates a
normal owner-scoped saved Food. Discovery combines a saved-Food query with a separate USDA query;
there is no shared search index.

**Why:** Upstream results differ in availability, identity and quality. Import normalizes
provenance, servings, nutrients and deduplication before Recipes or Logs can depend on the item, and
keeping the queries separate keeps each failure or loading state visible.

See [Unified Food search](../features/ocr-search-and-offline.md#unified-food-search).

## OCR

### Bounded OCR correction provenance

**Decision:** OCR confirmation stores versioned structured suggestions, observation IDs and user
corrections, append-only. It never stores images, file paths, full raw OCR text or unbounded parser
output, and provenance is never a resolver input.

**Why:** OCR is probabilistic and parser rules evolve, so a regression needs to be explainable.
Storing images or raw text would add privacy risk without helping nutrition resolution. Guided
camera framing and image-quality checks are capture aids only and never replace explicit
confirmation.

See [Confirmation and provenance](../features/ocr-search-and-offline.md#confirmation-and-provenance).

## Data authority and safety

### One explicit application-data authority

**Decision:** Startup selects exactly one data authority (`EXPO_PUBLIC_NUTRITION_DATA_AUTHORITY`)
before the runtime, query cache, recovery or storage initialize. The app uses `local` (on-device
SQLite); `remote` (the parked FastAPI/PostgreSQL backend) is kept for possible future use.
Deployment mode is a separate setting.

**Why:** Selection never implies fallback, dual writes, synchronization, cache sharing or data
migration. TanStack Query caches only in process, and safe retry replays idempotent operations, but
neither creates a second durable authority. Direct USDA lookup is an external integration, not a data
authority.

See [System boundaries](overview.md#system-boundaries).

### Local backup restore is validated replacement, not synchronization

**Decision:** Export creates a complete, validated standalone SQLite snapshot. Restore validates and
stages a copy without touching the active database, then activates it at the next startup, after
snapshotting existing data for rollback. If rollback itself can't complete safely, the local
database won't open.

**Why:** Restoring replaces one authority with a validated snapshot; it doesn't reconcile two
histories. There is no record merge, last-writer-wins, background replication or cloud mirror.
Adding any of those would need a new design.

See [Local backup and restore](../features/ocr-search-and-offline.md#local-backup-and-restore).

### Ownership is enforced at multiple layers

**Decision:** Identity is resolved at the boundary, operations are owner-scoped, and stored
relationships reinforce compatible ownership (composite foreign keys in PostgreSQL; owner-scoped
contracts in SQLite).

**Why:** Clear errors and race-resistant integrity solve different parts of the same problem. A
guessed ID must not connect one owner's Food to another's Recipe, revision, Log or target, even if
one layer has a bug.

See [Ownership and retry behavior](../features/foods-and-nutrition.md#ownership-and-retry-behavior).

### Payload-bound create idempotency

**Decision:** Retryable request IDs are scoped to owner and operation and bound to a canonical
payload fingerprint plus the retained response. Receipts never expire.

**Why:** A lost response must be safely replayable. An exact replay returns the committed response; a
changed payload under the same ID is a conflict; an expired receipt would eventually allow a
duplicate. A receipt and its mutation commit atomically, and later edits or deletion don't replace
the accepted response.

A missing or incomplete receipt stays **unresolved**: absence can't prove the original write didn't
commit. The mobile recovery manager keeps unresolved journal entries and polls status without
resending the write.

See [Ownership and retry behavior](../features/foods-and-nutrition.md#ownership-and-retry-behavior).

### SQLite schema evolves on its own

**Decision:** The local SQLite schema (`apps/mobile/src/storage/sqlite`) is a fresh semantic model
with its own schema-version migrations. It doesn't replay the backend's Alembic history, and none of
the backend's control-plane or role infrastructure is part of it.

**Consequence:** Add new migrations; never edit applied ones.

### No repository provider/factory layer

**Decision:** `NutritionRuntime` is an application capability boundary, not a swappable
table-by-table repository factory.

**Why:** Each running app has one explicitly selected authority, and focused test seams provide
enough substitution. A generic provider layer would add indirection without clarifying ownership.
