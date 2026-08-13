# Epic 2 — Local-First SQLite Runtime

## Backlog status

The Architecture Review approves embedded SQLite as authoritative in local mobile mode while preserving the existing FastAPI/PostgreSQL system as an alternate remote runtime and reference implementation.

One authority is selected per installation/profile. Epic 2 introduces no synchronization, dual-write, automatic failover, background sync, multi-device merge, cloud backup, authentication redesign, public deployment, generic cross-platform ORM, PostgreSQL replacement, or Phase 5/control-plane SQLite port.

Implementation must preserve:

- immutable Daily Log nutrition history;
- immutable Recipe publication revisions;
- generated Recipe FoodItems as compatibility projections;
- logging against immutable source/revision state;
- immutable OCR correction provenance;
- fixed source identity for historical Log entries;
- exact nutrition and decimal semantics;
- one authoritative calendar and time zone;
- meaningful replay and idempotency behavior;
- transactional rollback;
- ownership scoping;
- explicit confirmed versus unresolved mutation outcomes;
- Epic 1 accessibility behavior; and
- remote PostgreSQL behavior.

Implementation must stop and return to architecture review whenever an issue’s architecture stop condition is reached.

Issue-level testing should remain focused and proportional. Broad repository, backend, mobile, device, and release suites belong primarily to E2-16 through E2-18 and final owner verification.

---

# Milestone 1 — Runtime and Persistence Foundations

## E2-01 — Establish the mobile runtime seam

### Purpose

Make mobile features depend on runtime-neutral interfaces while preserving current remote HTTP behavior.

### Background

Mobile feature modules currently construct HTTP paths directly, while HTTP errors, status semantics, URL configuration, and transport-derived owner identity leak above the transport implementation. SQLite feature work must not begin until a stable seam exists.

### Acceptance criteria

- Every current Calendar, Nutrient, Food, Recipe, Daily Log, Target, OCR, and USDA mobile operation is inventoried.
- Small feature-level runtime interfaces cover all current operations.
- The interfaces expose domain inputs, results, error modes, authority identity, and ordering requirements without exposing HTTP paths, headers, SQLite statements, or generic repositories.
- Existing HTTP behavior is moved behind one remote adapter.
- Screens, hooks, query keys, cache invalidation, navigation, accessibility, and user-visible behavior remain unchanged.
- A runtime-neutral error contract represents stable codes, field failures, retryability, outcome certainty, and optional structured details.
- HTTP failures map into the runtime-neutral contract without changing current user-facing messages or recovery decisions.
- Runtime identity is abstracted from URL/token mechanics, while the remote adapter preserves current remote identity behavior.
- Remote HTTP remains the only selectable production runtime.
- No SQLite dependency, schema, or local feature implementation is introduced.
- Architecture stop: stop if an interface cannot preserve existing behavior without exposing HTTP concepts to callers, changing a backend/product contract, or broadening the approved architecture.

### Out of scope

- SQLite dependencies or schema.
- Local runtime selection.
- Synchronization, dual-write, or fallback.
- Backend contract changes.
- Screen or workflow redesign.
- Generic repository providers or cross-platform ORMs.

### Dependencies

- None.

### Backend work

- No backend behavior is expected to change.
- Provide existing contract examples only if required by focused adapter tests.

### Frontend work

- Introduce runtime provision and dependency injection.
- Migrate feature calls away from direct HTTP-client knowledge.
- Replace upward-facing `ApiError` dependencies with runtime-neutral errors.
- Preserve all current hooks and screens.

### API work

- Define feature-level runtime interfaces.
- Implement the remote HTTP adapter.
- Define runtime-neutral error and authority-identity contracts.
- Preserve current HTTP request and response behavior internally.

### Migration work

- No database migration.
- No SQLite schema or dependency.

### Testing requirements

- Add focused interface-shape tests.
- Add focused remote-adapter request and response mapping tests.
- Add error-mapping and authority-identity tests.
- Run TypeScript checking.
- Run only affected feature tests needed to establish behavioral preservation.
- Defer the full mobile regression suite to cross-cutting qualification unless implementation evidence reveals broader risk.

### Estimated implementation size

L

### Recommended Codex model and effort

`gpt-5.6-sol` — xhigh

Reason: establishes the cross-cutting interface every later local adapter depends on, making a misplaced seam expensive to correct.

---

## E2-02 — Freeze exact value semantics and parity contracts

### Purpose

Establish exact cross-runtime representations and reusable behavioral fixtures before SQLite feature persistence depends on them.

The frozen contract is documented in the [E2-02 exact value and parity contract](e2-02-exact-value-contract.md).

### Background

PostgreSQL `NUMERIC`, timezone-aware timestamps, UUIDs, JSONB, and constraint errors cannot be mapped casually to JavaScript and SQLite. A wrong representation could silently corrupt historical nutrition or cause local and remote behavior to diverge.

### Acceptance criteria

- One authoritative decimal representation is approved for every persisted precision currently used by the application.
- Authoritative nutrition storage and arithmetic never use raw JavaScript floating point.
- Decimal contracts cover parsing, arithmetic, rounding, comparison, serialization, overflow, and invalid input.
- UUIDs use one canonical textual representation.
- Instants, date-only values, IANA zones, booleans, and JSON documents each have one canonical persisted and runtime representation.
- PostgreSQL-compatible response serialization is defined for every value class.
- Runtime-neutral errors have stable codes for ownership, validation, conflicts, constraint failures, unavailable dependencies, and unresolved outcomes.
- Shared behavioral fixtures cover representative Foods, Recipe publication, Daily Log snapshots, unknown nutrients, idempotent replay, and failure outcomes.
- The remote adapter passes the initial parity fixtures.
- No production SQLite feature table may precede approval of these contracts.
- Architecture stop: stop if the chosen codecs cannot reproduce PostgreSQL nutrition results and serialized contracts exactly, or if exactness requires changing the approved domain model.

### Out of scope

- Feature persistence.
- UI changes.
- Synchronization payloads or server change formats.
- Speculative future data representations.

### Dependencies

- E2-01.

### Backend work

- Validate golden response and calculation fixtures against current backend behavior.
- Add narrowly scoped fixture-generation support only if deterministic existing outputs cannot otherwise be captured.
- Do not add feature endpoints.

### Frontend work

- Add pure exact-value and canonical serialization modules.
- Replace no production calculations until their focused migration issue is active.
- Keep interface consumers independent of SQLite representation details.

### API work

- Freeze cross-adapter input, output, error, and serialization contracts.
- Define shared fixture formats consumable by remote and future local adapters.

### Migration work

- Specify the SQLite storage mapping that E2-03 must implement.
- Do not create production tables or a migration stream yet.

### Testing requirements

- Test precision boundaries, maximum values, zero, null, negative rejection, rounding, and overflow.
- Test timestamp, date, UUID, boolean, and JSON round trips.
- Run focused remote golden-fixture tests.
- Add cross-language or cross-runtime fixture comparisons where needed.
- Do not run broad repository suites unless the contract work changes existing runtime behavior unexpectedly.

### Estimated implementation size

L

### Recommended Codex model and effort

`gpt-5.6-sol` — max

Reason: exact-value and serialization decisions become permanent storage foundations, and mistakes could corrupt historical nutrition silently.

---

## E2-03 — Create the native SQLite schema and migration engine

### Purpose

Establish a durable, runtime-only SQLite database using the actual Expo/native SQLite driver.

### Background

Python in-memory SQLite tests provide useful reference behavior but do not qualify the mobile driver, filesystem lifecycle, migration behavior, deferred constraints, or triggers. PostgreSQL’s Alembic history must not be replayed one migration at a time.

### Acceptance criteria

- The mobile app owns a separate, versioned SQLite migration stream.
- The first SQLite migration creates the current 18-table semantic runtime model.
- Nutrient seed authority, indexes, foreign keys, composite ownership constraints, and integrity triggers are installed.
- Phase 5, control-plane, role, canary, promotion, historical bridge, and migration-owned operational tables are absent.
- Foreign-key enforcement and required connection settings are enabled on every connection.
- Deferred Recipe relationships are represented and qualified.
- SQLite enforces the active-source partial uniqueness contract.
- Append-only revision and provenance tables reject direct update and delete.
- The schema contains a bounded mechanism for approved complete Daily Log snapshot replacement without globally disabling guards.
- Migrations are atomic, version-checked, restartable after rollback, and never reset user data automatically.
- Fresh creation, close/reopen, already-current startup, failed migration rollback, and unsupported-future-version behavior pass on the native driver.
- Remote mode can start without opening SQLite.
- Architecture stop: stop if the native driver cannot support required transactions, deferred foreign keys, triggers, or safe migrations without weakening a core invariant.

### Out of scope

- Feature adapters.
- PostgreSQL migration changes.
- Historical data import.
- Synchronization.
- Porting operational infrastructure.
- Encryption or backup redesign.

### Dependencies

- E2-01.
- E2-02.

### Backend work

- No backend change.
- PostgreSQL models, Alembic migrations, and operational infrastructure remain authoritative and untouched.

### Frontend work

- Add native SQLite dependency and database lifecycle module.
- Keep database startup independent from feature UI and remote-mode startup.

### API work

- Expose only internal database readiness and migration results.
- Do not implement feature runtime operations.

### Migration work

- Create the SQLite migration ledger and baseline runtime schema.
- Install canonical seeds, indexes, constraints, and triggers.
- Implement atomic migration execution and failure recovery.

### Testing requirements

- Run focused native-driver schema and migration tests.
- Test fresh creation, reopen, current-version no-op, future-version rejection, and injected migration failure.
- Test direct foreign-key, uniqueness, ownership, and immutability violations.
- Test that remote mode does not initialize SQLite.
- Reserve full device lifecycle qualification for E2-16.

### Estimated implementation size

XL

### Recommended Codex model and effort

`gpt-5.6-sol` — max

Reason: establishes the durable schema and upgrade mechanism whose failure could make personal data inaccessible or invalid.

Implementation detail: [E2-03 native SQLite schema and migration stream](e2-03-sqlite-schema.md).

---

# Milestone 2 — Local Core Nutrition

## E2-04 — Implement local identity, calendar, and nutrient foundations

### Purpose

Establish the owner-scoped, calendar-aware, and nutrient-catalog foundation required by local mutations.

### Background

Local 1.0 is single-user, but owner identity, authoritative calendar state, and nutrient definitions remain integrity authorities. Device timezone must remain provisional until explicitly confirmed.

### Acceptance criteria

- A durable local runtime identity and one owner UUID are created idempotently.
- Local mode does not introduce HTTP authentication.
- Every owner-scoped stored row retains `user_id`.
- The canonical nutrient catalog is seeded idempotently.
- Incompatible nutrient seed drift is rejected rather than silently overwritten.
- Calendar state supports unconfirmed, confirmed, previewed change, stale confirmation, and revision semantics equivalent to remote mode.
- Device timezone is only a proposal until explicitly confirmed.
- Calendar changes never move or modify Daily Logs.
- Local mutation preconditions reject operations before calendar confirmation wherever remote mode does.
- Operations execute through the Calendar and Nutrient runtime interfaces.
- Architecture stop: stop if implementation requires removing owner fields, treating the device zone as silent authority, or changing established calendar semantics.

### Out of scope

- Runtime-selection UI.
- Multi-user authentication.
- Per-device or per-entry timezone authority.
- Timezone history.
- Daily Log implementation.

### Dependencies

- E2-03.

### Backend work

- No backend behavior change.
- Existing calendar behavior may be used as parity-fixture authority.

### Frontend work

- Connect existing calendar hooks and screens to the local adapter in focused tests.
- Preserve current confirmation, preview, and stale-context presentation.

### API work

- Implement local Calendar and Nutrient adapters.
- Preserve runtime-neutral calendar and error contracts.

### Migration work

- Implement local user/profile and nutrient repositories.
- Add idempotent owner bootstrap and seed validation.
- Use the schema established by E2-03 without broadening it.

### Testing requirements

- Test local identity and seed persistence across reopen.
- Test DST boundaries, zone confirmation, change preview, stale revisions, and invalid zones.
- Test owner scope and incompatible seed rejection.
- Exercise the focused Calendar and Nutrient parity fixtures.
- Run affected mobile calendar tests and TypeScript checking.

Implementation detail: [E2-04 local identity, calendar, and nutrient foundations](e2-04-local-foundations.md).

### Estimated implementation size

L

### Recommended Codex model and effort

`gpt-5.6-sol` — high

Reason: implementation is bounded, but authoritative calendar revisions and owner identity carry enough semantic risk to require Sol-level reasoning.

---

## E2-05 — Implement local Foods, servings, and nutrition resolution

### Purpose

Make saved Foods and exact nutrition resolution fully local.

### Background

Foods are mutable definitions, but their serving identities, nutrient status, source identity, ownership, and later historical use require strict transactional behavior and exact decimal calculations.

### Acceptance criteria

- Local mode supports list, search, get, create, update, duplicate, soft-delete, serving creation, and resolved-nutrition operations.
- Food nutrients preserve known, estimated, zero, and unknown status exactly.
- Serving resolution preserves explicit serving identity.
- Household measures imply mass only when an explicit gram weight exists.
- Nutrition calculations use the E2-02 exact-value module.
- Source identity and active-source uniqueness match remote behavior.
- Saved-Food operations exclude generated Recipe projection Foods.
- Serving and nutrient replacement is atomic.
- Validation or constraint failure rolls back the complete mutation.
- Composite ownership constraints reject cross-owner linkage directly.
- Food changes never alter existing Daily Log snapshots or immutable Recipe revisions.
- Stable local errors match the runtime parity contract.
- Architecture stop: stop if implementation requires floating-point authority, historical-row mutation, or treating projection Foods as ordinary editable Foods.

### Out of scope

- Favorites.
- USDA network behavior.
- Recipe authoring or publication.
- Daily Logs.
- Historical recalculation.

### Dependencies

- E2-02.
- E2-03.
- E2-04.

### Backend work

- No backend behavior change.
- Provide deterministic comparison fixtures only where existing responses are insufficient.

### Frontend work

- Connect existing Food hooks and screens to the local adapter in focused tests.
- Preserve current validation, loading, and error behavior.

### API work

- Implement the local Food runtime adapter.
- Map local constraint and validation failures into runtime-neutral errors.

### Migration work

- Implement Food, nutrient, source, and serving repositories.
- Apply exact-value codecs and transactional replacement behavior.
- Use established ownership and active-source constraints.

### Testing requirements

- Test CRUD, duplicate, source conflicts, soft deletion, serving replacement, and exact nutrition resolution.
- Inject failure between replacement stages and verify full rollback.
- Test direct ownership and source-identity constraint violations.
- Test deleted and unavailable source behavior.
- Exercise focused remote/local parity fixtures.
- Run affected Food feature tests and TypeScript checking.

### Estimated implementation size

XL

### Recommended Codex model and effort

`gpt-5.6-sol` — xhigh

Reason: exact nutrition resolution and atomic replacement span domain, persistence, and interface behavior with historical-integrity implications.

Implementation detail: [E2-05 local Foods, servings, and nutrition resolution](e2-05-local-foods.md).

---

## E2-06 — Implement local favorites and explicit USDA offline behavior

### Purpose

Complete Food discovery behavior without representing USDA as an offline capability.

### Background

Favorites are local application data. USDA search and preview remain external network capabilities whose unavailable and empty states must remain distinguishable.

### Acceptance criteria

- Favorite creation and removal are idempotent and owner-scoped.
- Favorites exclude deleted Foods and Recipe projections consistently with remote behavior.
- Local saved-Food discovery remains fully functional while offline.
- USDA search and preview report unavailable or offline status rather than returning a false empty result.
- Online USDA import creates a normal local Food atomically with source provenance and duplicate reconciliation.
- Imported data remains usable after the network becomes unavailable.
- No FastAPI process is required for local USDA import once an approved personal credential mechanism is configured.
- No USDA credential is hard-coded into a distributable mobile binary.
- USDA failure does not invalidate saved-Food or Recipe queries.
- Architecture stop: stop if acceptable personal USDA credential handling requires embedding a shared production secret or reintroducing a required server.

### Out of scope

- Offline USDA corpus.
- USDA synchronization or background retry.
- Search indexing services.
- Shared production credentials.
- Recipe or Daily Log implementation.

### Dependencies

- E2-05.

### Backend work

- Preserve the existing USDA backend for remote mode.
- No PostgreSQL behavior change.

### Frontend work

- Preserve composed Saved/USDA discovery.
- Preserve independent loading, empty, unavailable, and failure states.
- Connect favorites and local import outcomes to existing cache behavior.

### API work

- Implement the local Favorites adapter.
- Implement an external USDA gateway for local mode.
- Keep remote USDA behavior in the remote adapter.

### Migration work

- Implement favorites persistence.
- Use existing Food-source identity and duplicate constraints for imported Foods.
- No new synchronization metadata.

### Testing requirements

- Test favorite idempotency, owner scope, deletion filtering, and projection exclusion.
- Test USDA offline, timeout, malformed response, duplicate import, and successful import.
- Test imported Food persistence after reopen and later offline use.
- Run focused Food discovery and USDA tests only.
- Reserve broad offline qualification for E2-14 and E2-18.

### Estimated implementation size

L

### Recommended Codex model and effort

`Luna` — high

Reason: follows Food persistence and adapter patterns established by E2-05, with bounded external-error and UI-state integration.

---

# Milestone 3 — Immutable Recipes and Logging

## E2-07 — Implement local Recipe authoring and dependency integrity

### Purpose

Support mutable Recipe definitions locally while preserving ownership, serving identity, and graph correctness.

### Background

Recipe graph changes currently rely on serialized PostgreSQL transactions and deterministic dependency checks. SQLite must preserve observable outcomes without copying row-lock syntax.

### Acceptance criteria

- Local mode supports Recipe list, search, get, create, update, and approved deletion behavior.
- Ingredient references are owner-scoped.
- Ingredients refer to valid Food and serving identities.
- Direct and indirect Recipe cycles are rejected.
- Ingredient ordering and exact amounts remain deterministic.
- Ingredient or dependent Food changes mark affected Recipes for republish where required.
- Deletion dependency reports match current product behavior.
- Local writes serialize before graph discovery.
- Mutations reread current committed authority inside the write transaction.
- Every failure rolls back Recipe rows, ingredient rows, and dependency state completely.
- Architecture stop: stop if SQLite cannot preserve current graph outcomes without weakening cycle, ownership, serving, or dependency integrity.

### Out of scope

- Recipe publication.
- Compatibility projections.
- Sharing or collaborative editing.
- Synchronization conflict graphs.
- Rewriting backend locking.

### Dependencies

- E2-05.

### Backend work

- No backend behavior change.
- Existing Recipe behavior and PostgreSQL tests remain reference authority.

### Frontend work

- Connect existing Recipe-authoring hooks and screens to the local adapter.
- Preserve current validation and dependency presentation.

### API work

- Implement the local Recipe-authoring adapter.
- Map graph, ownership, serving, and deletion failures into runtime-neutral errors.

### Migration work

- Implement Recipe and ingredient repositories.
- Implement graph discovery and validation inside serialized local write transactions.

### Testing requirements

- Test direct, indirect, and nested cycles.
- Test deleted Foods, invalid servings, owner mismatch, ingredient order, and exact amounts.
- Test republish marking and deletion dependencies.
- Inject failures across graph mutations and verify rollback.
- Test overlapping local writes and authoritative rereads.
- Exercise focused parity fixtures.

### Estimated implementation size

XL

### Recommended Codex model and effort

`gpt-5.6-sol` — xhigh

Reason: graph integrity and transaction ordering require subtle cross-layer reasoning even in a single-process SQLite runtime.

---

## E2-08 — Implement immutable Recipe publication and compatibility projections

### Purpose

Publish Recipes locally as immutable revisions with atomic compatibility projections.

### Background

A publication transaction creates immutable historical authority while advancing a mutable generated Food projection. Partial or mutable publication state would corrupt later logging history.

### Acceptance criteria

- Publication creates a new immutable revision, amount definitions, and nutrient snapshot rows.
- Revision numbering is monotonic per Recipe.
- Publication captures exact ingredient and nested-revision authority.
- The generated FoodItem, projection nutrients, servings, Recipe links, and active revision advance atomically.
- Projection Food data is never treated as historical authority.
- Intentional identical republishes remain distinct.
- Exact request replay does not create duplicate revisions.
- Direct update or delete of revision, amount-definition, and revision-nutrient rows is rejected.
- Failure at every publication stage leaves no partial revision or projection.
- Published Recipe logging inputs match remote response semantics.
- Dependency changes mark published Recipes stale without changing earlier revisions.
- Architecture stop: stop if publication requires disabling integrity triggers, rewriting prior revisions, or making projection data historical authority.

### Out of scope

- Recipe sharing.
- Revision synchronization.
- Remote publication redesign.
- Editing immutable revisions.
- General trigger-disabling mechanisms.

### Dependencies

- E2-07.

### Backend work

- No backend behavior change.
- Existing publication results may supply golden fixtures.

### Frontend work

- Connect existing publish and published-detail workflows to the local adapter.
- Preserve current stale/republish presentation.

### API work

- Extend the local Recipe adapter with publication operations.
- Preserve publication replay and error contracts.

### Migration work

- Implement publication repositories and the projection transaction.
- Use immutable triggers established by E2-03.
- Enforce revision, owner, active-link, and amount-definition membership constraints.

### Testing requirements

- Test first publication, republish, intentional identical publication, and exact replay.
- Test nested Recipe authority and stale dependency behavior.
- Attempt direct immutable-row updates and deletes.
- Inject failure at each publication/projection stage and verify complete rollback.
- Compare exact published nutrition and amount definitions with remote fixtures.

### Estimated implementation size

XL

### Recommended Codex model and effort

`gpt-5.6-sol` — max

Reason: incorrect publication or projection behavior could permanently corrupt immutable Recipe authority and every future Recipe-backed Log.

---

## E2-09 — Implement local Daily Log creation, snapshots, summaries, and Repeat

### Purpose

Deliver the central local nutrition-history workflow.

### Background

Daily Logs must capture current source authority as immutable historical snapshots and aggregate only those snapshots. Creation is the point at which mutable Food or Recipe authority becomes durable history.

Implementation detail: [E2-09 local Daily Logs, snapshots, summaries, and Repeat](e2-09-local-daily-logs.md).

### Acceptance criteria

- Local mode supports date-scoped listing, creation, detail/edit context, daily summary, Recent Entries, Recent Foods, and Repeat.
- Creation requires confirmed calendar authority.
- Prohibited future dates are rejected.
- Food logging resolves the current Food and exact selected serving.
- Recipe logging records the immutable publication revision and exact amount definition.
- Fixed source identity, food-name snapshot, consumed amount, and nutrient snapshots commit atomically.
- Daily summaries aggregate snapshots rather than mutable Food or projection rows.
- Unknown contributors remain distinguishable from zero.
- Repeat uses a historical event but resolves current loggable source authority according to Epic 1 rules.
- Exact create replay returns the retained result without duplicating a Log.
- Direct mutation of snapshot values or provenance is rejected.
- Failed creation leaves no Daily Log, snapshot, or idempotency residue.
- Architecture stop: stop if summaries or Repeat require mutable definitions to become historical authority, or if snapshot integrity cannot be enforced directly.

### Out of scope

- Log editing.
- Date moves.
- Permanent deletion.
- Legacy future cleanup.
- Recovery UI.
- Source replacement.

### Dependencies

- E2-04.
- E2-05.
- E2-08.

### Backend work

- No backend behavior change.
- Existing Daily Log behavior and fixtures remain reference authority.

### Frontend work

- Connect existing Add, confirmation, Daily Log, summary, Recent, and Repeat flows to the local adapter.
- Preserve current loading, projection, and accessibility behavior.

### API work

- Implement local Daily Log read and create operations.
- Implement runtime-neutral recent and summary results.
- Preserve replay semantics.

### Migration work

- Implement Daily Log and snapshot repositories.
- Implement summary and recent-entry queries.
- Use snapshot immutability and ownership constraints from E2-03.

### Testing requirements

- Test Food and Recipe-backed creation.
- Test unavailable sources, exact summaries, unknown nutrients, Recent, and Repeat.
- Test replay and payload mismatch behavior relevant to creation.
- Inject failure between Log, snapshot, and receipt writes.
- Attempt direct snapshot mutation.
- Exercise focused remote/local parity fixtures.

### Estimated implementation size

XL

### Recommended Codex model and effort

`gpt-5.6-sol` — max

Reason: this issue creates immutable historical nutrition, so transaction or source-authority errors would permanently misstate user history.

---

## E2-10 — Implement local Daily Log edit, move, delete, and legacy cleanup

### Purpose

Complete mutation behavior for existing local historical entries.

### Background

Metadata edits, nutrition edits, date moves, permanent deletion, and legacy future cleanup have different historical consequences and must use a narrowly scoped snapshot-replacement mechanism.

### Acceptance criteria

- Metadata-only edits preserve snapshot IDs, values, provenance, and immutable creation time.
- Nutrition-affecting Food edits atomically replace the complete snapshot set using current source authority.
- Nutrition-affecting Recipe edits use the current active published revision.
- Recipe revision, amount provenance, and snapshot replacement change together.
- Source identity cannot be changed by edit.
- Date moves preserve nutrition snapshots and update date ownership only.
- Future-date restrictions and bounded legacy-future cleanup match Epic 1.
- Permanent deletion removes the owned entry through the approved snapshot deletion path.
- Source-unavailable metadata edits and deletion remain supported where Epic 1 permits them.
- SQLite replacement authority is limited to one owner and one Log transaction.
- Direct or partial snapshot replacement is rejected.
- Injected failure restores the complete prior entry and snapshot set.
- Architecture stop: stop if implementation changes source identity, weakens complete-set replacement, or requires dropping or disabling immutability protection.

### Out of scope

- Source replacement.
- Undo or deleted-entry recovery.
- Bulk edits.
- Automatic historical recalculation.
- General repair tools for immutable rows.

### Dependencies

- E2-07.
- E2-08.
- E2-09.

### Backend work

- No backend behavior change.
- PostgreSQL immutable-provenance behavior remains authoritative for remote mode.

### Frontend work

- Connect existing edit, move, delete, and legacy-cleanup flows to local operations.
- Preserve current confirmation, recovery handoff, and accessibility behavior.

### API work

- Complete local Daily Log mutation operations.
- Preserve runtime-neutral validation, conflict, unavailable-source, and outcome errors.

### Migration work

- Implement scoped snapshot replacement and approved deletion.
- Preserve append-only and direct-mutation triggers at all times.

### Testing requirements

- Test metadata preservation and nutrition replacement.
- Test current Recipe publication authority.
- Test unavailable sources, moves, future restrictions, legacy cleanup, and ownership.
- Attempt partial replacement and direct guard bypass.
- Inject failure at each edit and deletion stage.
- Verify full rollback and focused remote/local parity.

### Estimated implementation size

XL

### Recommended Codex model and effort

`gpt-5.6-sol` — max

Reason: this issue defines the sole permitted mutation path for immutable nutrition snapshots, making incorrect scope or rollback behavior data-corrupting.

---

## E2-11 — Implement local idempotency, restart recovery, and conflict semantics

### Purpose

Preserve deterministic mutation outcomes across overlapping calls, application termination, and restart.

### Background

A local database removes network uncertainty but not process termination between durable commit and UI confirmation. Local and remote recovery must remain isolated by authority.

### Acceptance criteria

- Local create, update, and delete operations bind request identity to a canonical payload fingerprint.
- Exact replay returns the retained outcome.
- Reusing an identity with a changed payload produces a stable conflict.
- All local writes use one serialized transaction coordinator.
- The coordinator acquires write authority before rereading mutable state.
- Busy or locked behavior is bounded.
- Confirmed commit, confirmed non-commit, retryable conflict, and unresolved outcome remain distinguishable.
- Recovery storage is keyed by runtime-neutral authority identity.
- Restart reconciliation reads local receipt and resource state before deciding whether to retry.
- Termination before commit, during transaction, after commit before response, and during recovery is covered.
- Local mode never consults remote mutation status.
- Remote mode never consults local receipts.
- Recovery never projects success before durable confirmation.
- Architecture stop: stop if correct recovery requires mixing authorities, claiming success before commit, or introducing synchronization.

### Out of scope

- Cross-device recovery.
- Server queues.
- Background sync.
- Collaborative mutation reconciliation.
- Automatic cross-authority retry.

### Dependencies

- E2-01.
- E2-09.
- E2-10.

### Backend work

- Preserve existing remote replay and mutation-status behavior.
- No backend redesign.

### Frontend work

- Adapt the Epic 1 recovery module to runtime-neutral operations and identity.
- Preserve existing confirmed and unresolved presentation.

### API work

- Add mutation-status and reconciliation operations to the relevant runtime interfaces.
- Implement local and remote adapters without cross-authority access.

### Migration work

- Implement durable local receipts and mutation-status storage.
- Implement the serialized local transaction coordinator and bounded busy handling.

### Testing requirements

- Test exact replay and payload mismatch.
- Test overlapping local mutation promises.
- Inject termination before, during, and after commit.
- Reopen the database and test reconciliation.
- Test busy timeout and stable error mapping.
- Test local/remote recovery identity isolation.
- Run focused recovery and mutation-projection tests.

### Estimated implementation size

L

### Recommended Codex model and effort

`gpt-5.6-sol` — max

Reason: restart and outcome-certainty errors can create duplicate mutations or falsely present uncommitted data as durable.

---

# Milestone 4 — Self-Contained Application Completion

## E2-12 — Implement local Targets and daily comparison

### Purpose

Complete local nutrition goals and date-specific progress.

### Background

Targets depend on established owner, calendar, exact-value, and immutable Daily Log patterns. Their local implementation should follow the repository and adapter conventions established by earlier issues.

### Acceptance criteria

- Local mode reads effective target configuration.
- Profile-derived defaults and explicit nutrient overrides retain current precedence.
- Target update and reset operations are owner-scoped and atomic.
- Daily comparison uses immutable Daily Log totals for the requested authoritative date.
- Unknown consumption and unavailable target states remain explicit.
- Percentages and displayed amounts use exact-value semantics.
- Overlapping local target mutations serialize and reread current configuration.
- Existing target screens and accessibility behavior remain unchanged.
- Focused local and remote parity fixtures pass.
- Architecture stop: stop if target parity requires redesigning the owner profile or replacing exact decimal semantics.

### Out of scope

- New target types.
- New health-profile fields.
- Recommendations or coaching.
- Analytics.
- Synchronization.

### Dependencies

- E2-04.
- E2-09.

### Backend work

- Preserve existing target behavior.
- No backend schema or service changes are expected.

### Frontend work

- Connect existing target settings and progress UI to the local adapter.
- Preserve current validation, errors, and accessibility.

### API work

- Implement the local Targets adapter.
- Preserve existing runtime-neutral target results and failures.

### Migration work

- Implement target persistence and profile-based calculation using established local patterns.
- No new schema beyond E2-03 is expected.

### Testing requirements

- Test defaults, overrides, reset, unknown totals, unavailable configuration, and date isolation.
- Inject mutation failure and verify rollback.
- Test overlapping updates.
- Exercise focused exact-value and remote/local parity tests.
- Run affected target feature tests.

### Estimated implementation size

L

### Recommended Codex model and effort

`Luna` — high

Reason: follows already-established local repositories, exact-value modules, and transaction patterns with limited new architecture.

---

## E2-13 — Move OCR parsing, confirmation, and provenance on-device

### Purpose

Make the supported OCR workflow independent of FastAPI.

### Background

Apple Vision recognition already runs on-device, but parsing, confirmation, Food creation, and immutable provenance currently depend on backend behavior.

### Acceptance criteria

- The current parser contract is ported to an on-device module with an explicit parser version.
- Existing golden OCR fixtures produce compatible structured suggestions and diagnostics.
- Confirmation validates user corrections locally.
- Food creation and immutable trace creation occur atomically.
- The trace stores bounded structured suggestions, observation IDs, corrections, parser/schema versions, and request identity.
- Images, paths, complete raw OCR text, and unbounded parser payloads are not retained.
- Confirmation replay is deterministic.
- Replay does not create duplicate Foods or traces.
- Direct update and delete of provenance rows is rejected.
- The workflow completes with FastAPI unavailable.
- Existing iOS recognition and accessibility behavior remain intact.
- Android retains the established platform-gated behavior.
- Architecture stop: stop if parity requires retaining excluded sensitive data, changing the provenance contract, or introducing an unapproved native-recognition architecture.

### Out of scope

- Android OCR.
- Image retention.
- Complete raw-text retention.
- Parser analytics or model training.
- Cloud OCR.
- Synchronization.

### Dependencies

- E2-02.
- E2-03.
- E2-05.

### Backend work

- Preserve the existing parser and remote adapter.
- Provide deterministic fixture authority where needed.
- Do not redesign backend OCR.

### Frontend work

- Add the local parser and confirmation modules.
- Connect existing scan and confirmation flows to the local adapter.
- Preserve privacy and accessibility behavior.

### API work

- Implement the local OCR adapter.
- Preserve parser versions, confirmation inputs, errors, and response contracts.

### Migration work

- Implement immutable confirmation-trace persistence.
- Apply append-only enforcement and replay identity constraints.

### Testing requirements

- Run the golden parser fixture corpus.
- Test corrections, malformed recognition, replay, duplicate prevention, and rollback.
- Inventory persisted fields to prove excluded capture data is absent.
- Run focused iOS native OCR and accessibility tests where available.
- Reserve full physical-device qualification for E2-16.

### Estimated implementation size

XL

### Recommended Codex model and effort

`gpt-5.6-sol` — xhigh

Reason: parser parity, privacy constraints, atomic Food creation, and immutable provenance span native, domain, and persistence layers.

---

## E2-14 — Enable explicit local runtime selection and serverless operation

### Purpose

Make the completed local adapters an explicitly selectable application authority.

### Background

Local and remote implementations must never silently mix, dual-write, or fail over. Runtime selection must occur before feature queries, recovery, and database initialization.

### Acceptance criteria

- Runtime authority is selected before feature queries, recovery, or database initialization.
- `local` and `remote` are explicit supported modes.
- Local mode requires no API URL, bearer token, or backend health check.
- Remote mode preserves current URL, authentication, and fail-closed configuration.
- Local mode uses only local adapters for application data.
- Remote mode uses only remote adapters for application data.
- USDA is the only permitted local-mode network feature and remains visibly external.
- No automatic fallback, dual-write, shadow-write, or transparent copying exists.
- Runtime identity scopes Query caches, recovery records, and local state.
- Explicit authority switching retires prior in-memory caches.
- Authority switching does not claim that the other authority contains the same data.
- All supported core workflows complete while FastAPI and PostgreSQL are unreachable.
- Local mode becomes the intended self-contained release mode only after all feature interfaces qualify.
- Architecture stop: stop if runtime selection requires sharing live state between authorities or making either mode a silent fallback for the other.

### Out of scope

- Data merge.
- Implicit migration.
- Synchronization.
- Automatic runtime selection.
- Transparent fallback.
- Shared live caches.

### Dependencies

- E2-06.
- E2-08.
- E2-11.
- E2-12.
- E2-13.

### Backend work

- No backend behavior change.

### Frontend work

- Implement runtime configuration and bootstrap.
- Scope caches and recovery by runtime identity.
- Preserve explicit loading and failure presentation.
- Add only the bounded runtime-selection presentation required by the approved architecture.

### API work

- Complete the adapter registry and authority-selection module.
- Enforce local/remote adapter isolation.

### Migration work

- Open and migrate the local database only in local mode.
- Prove remote startup does not initialize local application persistence.

### Testing requirements

- Test local startup without URL, token, or backend.
- Test remote startup with existing configuration rules.
- Spy on network and database access to detect mixed authority.
- Test explicit switching, cache retirement, and recovery isolation.
- Run focused complete-local smoke workflows.
- Defer full mobile and remote regression suites to E2-17 and E2-18.

### Estimated implementation size

L

### Recommended Codex model and effort

`gpt-5.6-sol` — xhigh

Reason: authority selection is a cross-cutting integration point where accidental fallback or mixed state would violate the Epic’s central architecture.

---

## E2-15 — Deliver one-time PostgreSQL-to-SQLite personal data transfer

### Purpose

Preserve existing personal application data during the local-first cutover.

### Background

A bounded point-in-time transfer is materially different from synchronization. It must preserve immutable history exactly without writing to the PostgreSQL source or creating an incremental protocol.

The binding implementation and operator contract is the
[E2-15 Transfer Architecture and Runbook](e2-15-transfer-architecture.md).

### Acceptance criteria

- A read-only PostgreSQL exporter emits one versioned transfer package for active application data.
- Phase 5, control-plane, role, promotion, evidence, and operational tables are excluded.
- The package contains canonical values, schema identity, codec version, record counts, per-section digests, and an overall digest.
- UUIDs, timestamps, dates, exact decimals, JSON, owner links, immutable revisions, snapshots, provenance, and relevant idempotency records are preserved.
- Export requires a stable point-in-time source.
- The required source quiescence or freeze procedure is documented.
- Import targets a new or empty local profile.
- Import occurs in one atomic transaction.
- Post-import qualification checks ownership, foreign keys, projections, active revision links, immutable row sets, snapshot totals, and counts.
- Any digest, version, codec, constraint, or qualification failure leaves no partial imported data.
- Reimport cannot behave as an incremental update.
- PostgreSQL remains unmodified.
- The package is not a sync journal and creates no cursor, tombstone, or background process.
- This issue is coordinated with ChatGPT Work for source-selection, privacy, and freeze approval.
- Architecture stop: stop if transfer requires PostgreSQL writes, control-plane authority, concurrent-source reconciliation, or repeatable synchronization.

### Out of scope

- Incremental export.
- Bidirectional transfer.
- Conflict resolution.
- Cloud backup.
- Background transfer.
- Synchronization metadata.
- PostgreSQL mutation.

### Dependencies

- E2-03.
- E2-08.
- E2-11.
- E2-12.
- E2-13.

### Backend work

- Implement the read-only PostgreSQL export command.
- Qualify source schema identity and point-in-time stability.
- Leave application and control databases unchanged.

### Frontend work

- Implement the approved explicit import flow or operator-assisted file handoff.
- Present clear validation, progress, success, and failure outcomes.

### API work

- Define the versioned transfer-package contract.
- Do not add a synchronization endpoint.

### Migration work

- Implement the transactional SQLite importer.
- Implement post-import integrity qualification.
- Admit only supported schema and codec versions.

### Testing requirements

- Export a representative PostgreSQL fixture.
- Test exact import counts, digests, decimals, timestamps, revisions, snapshots, and provenance.
- Test tampered, truncated, incompatible, and duplicate packages.
- Inject failure throughout import and verify an empty target remains.
- Verify the PostgreSQL source is unchanged.
- Reserve full real-data and device qualification for owner-coordinated validation and E2-16.

### Qualification status

E2-15 native iOS qualification is complete: C1–C10 each passed individually,
RUN ALL passed, and the final RESET passed. This included document-picker
cancellation, the production first-start import UI, and file-backed SQLite
migration, import, rollback, reimport rejection, bootstrap retry, and reopen
paths. No personal data or device paths are recorded here.

Separately, the earlier local/no-API iOS and Android Expo exports passed as
static bundle validation; no Android native runtime execution is claimed.

### Estimated implementation size

XL

### Recommended Codex model and effort

`gpt-5.6-sol` — max

Reason: this issue moves complete immutable personal history across storage engines, so representation or transaction errors could cause irreversible loss or corruption.

---

# Milestone 5 — Migration and Release Qualification

## E2-16 — Qualify native SQLite lifecycle, migrations, termination, and accessibility

### Purpose

Prove the embedded runtime under real device, filesystem, upgrade, termination, and accessibility conditions.

### Background

Unit tests and Python SQLite cannot establish native-driver behavior, application lifecycle behavior, durable commit, upgrade safety, or device accessibility.

### Acceptance criteria

- Fresh install succeeds on supported iOS targets. Android native execution is removed personal-project scope.
- Database close/reopen and ordinary restart preserve all data.
- Upgrade from every shipped SQLite schema version succeeds.
- Injected migration failure rolls back.
- The prior schema remains usable or the application fails closed without destructive reset.
- Termination before, during, and after representative mutations preserves atomicity and supports reconciliation.
- Representative Food, Recipe publication, Daily Log edit/delete, Target, and OCR operations survive restart.
- Direct integrity qualification passes after each lifecycle scenario.
- Low-storage or filesystem failure is reported without automatic database reset.
- Manual VoiceOver, TalkBack, and Android native accessibility qualification are removed personal-project scope; permanent automated accessibility contracts remain.
- OCR receives its established iOS physical-device qualification.
- Remediation remains bounded to approved Epic 2 behavior.
- ChatGPT Work coordinates physical-device and manual accessibility evidence.
- Architecture stop: stop if a native-driver limitation makes safe migration, durable commit, restart recovery, or a preserved invariant unattainable without architectural change.

### Out of scope

- New feature UX.
- New performance targets.
- Cloud backup.
- Synchronization.
- Broad redesign during qualification.

### Dependencies

- E2-14.
- E2-15.

### Backend work

- No backend implementation.
- Backend may supply controlled source fixtures for transfer qualification.

### Frontend work

- Add only bounded lifecycle or accessibility corrections discovered during qualification.
- Preserve approved interactions and accessibility behavior.

### API work

- No new runtime capability.
- Exercise existing local interfaces under lifecycle failure.

### Migration work

- Qualify the native migration stream across supported versions.
- Test failed upgrade rollback, future-version rejection, and post-upgrade integrity.

### Testing requirements

- Run the approved native iOS database lifecycle tests. Android native execution and manual accessibility are removed personal-project scope.
- Use physical devices or development builds where native behavior requires them.
- Run upgrade, migration failure, filesystem failure, kill/restart, and reconciliation scenarios.
- Run representative local feature tests after lifecycle events.
- Use owner-coordinated iOS OCR evidence where required; do not claim removed manual VoiceOver/TalkBack evidence.
- Keep automated remediation tests focused; broader evidence is the purpose of this issue.

### Qualification status

E2-16A–E2-16J are closed within the retained scope documented in the
[E2-16 closure and evidence record](e2-16-closure-evidence.md). The temporary E2-16 route,
isolated identity, database/checkpoint/direct-integrity helpers, failure fixtures, and harness-only
tests were removed by E2-16J. Permanent SQLite migration, local-authority, OCR, recovery,
runtime-hook, and E2-15 transfer behavior remains. The complete native Stage-F matrix is not
claimed; Android, TalkBack, and manual VoiceOver evidence are intentionally not applicable.

E2-17 remote/PostgreSQL qualification and E2-18 final release qualification remain unclaimed and
are not started by this cleanup.

### Estimated implementation size

XL

### Recommended Codex model and effort

`gpt-5.6-sol` — xhigh

Reason: qualification spans native storage, migrations, process termination, and accessibility, while ChatGPT Work must coordinate manual device evidence.

---

## E2-17 — Qualify remote-mode regression and absence of mixed authority

### Purpose

Prove that adding local mode did not weaken PostgreSQL or accidentally create synchronization, fallback, or dual authority.

### Background

PostgreSQL remains the remote concurrency and production-hardening authority. Cross-runtime isolation must be established through both tests and static inspection.

### Acceptance criteria

- Full remote mobile behavior runs through the remote adapter.
- The complete ordinary backend suite passes.
- Required PostgreSQL migration replay, immutable provenance, ownership, concurrency, and lock-order suites pass.
- Remote mode opens no local application database.
- Remote mode reads no local mutation receipts.
- Local mode makes no application-data HTTP requests.
- No operation writes to both authorities.
- No automatic fallback occurs after local or remote failure.
- No sync queue, change feed, tombstone, background replication job, or shadow-write path exists.
- Phase 5, control migrations, canary behavior, role topology, and production-hardening objects remain unchanged.
- Any PostgreSQL correction is separately justified as a bounded compatibility defect.
- Architecture stop: stop if remote compatibility requires redesigning PostgreSQL behavior or introducing shared live state between authorities.

### Out of scope

- Improving PostgreSQL architecture.
- Replacing FastAPI.
- Synchronization preparation.
- Porting operational infrastructure.
- New remote product behavior.

### Dependencies

- E2-14.

### Backend work

- Run remote regression and PostgreSQL-specific qualification.
- Apply only explicitly reviewed, bounded compatibility corrections.

### Frontend work

- Qualify the remote adapter and remote-mode workflows.
- Audit that remote mode has no local application-data dependency.

### API work

- Test authority isolation and existing remote contracts.
- Audit adapter wiring for fallback, shadow write, or mixed reads.

### Migration work

- Run required PostgreSQL migration qualification.
- Prove remote mode does not initialize or migrate SQLite.
- Confirm PostgreSQL and control migration histories are unchanged unless a bounded correction was approved.

### Testing requirements

- Run the full ordinary backend suite.
- Run the full remote mobile suite.
- Run required PostgreSQL opt-in migration, provenance, ownership, and concurrency suites.
- Use network and database spies to detect mixed authority.
- Perform static dependency and schema audits for prohibited sync infrastructure.
- Report exact passes, skips, warnings, and any bounded correction.

### Estimated implementation size

L

### Recommended Codex model and effort

`gpt-5.6-sol` — xhigh

Reason: this is a broad cross-runtime audit involving PostgreSQL concurrency authority and the Epic’s prohibition on mixed state.

---

## E2-18 — Run Epic 2 end-to-end release qualification

### Purpose

Verify the complete self-contained outcome, preserved invariants, and excluded scope before Epic closure.

### Background

Individual issue evidence does not prove that every workflow operates coherently without a backend or that remote mode remains intact. Final closure requires an E1-18-style cross-cutting decision.

### Acceptance criteria

- Fresh local install, reopen, schema upgrade, and failed migration rollback have release evidence.
- Application termination and restart recovery have release evidence.
- Local Foods, Recipes, publication, Daily Logs, Repeat, edit/move/delete, Targets, and OCR pass end to end.
- Immutable Log history, Recipe revisions, OCR provenance, fixed source identity, generated projections, ownership, exact decimals, idempotency, and rollback pass direct qualification.
- The complete local app operates with FastAPI and PostgreSQL unavailable.
- USDA unavailability is explicit and does not affect saved data.
- E2-16 evidence is complete only for the retained scope recorded in its closure document; removed
  manual accessibility scope is not a release claim.
- Remote mobile and PostgreSQL evidence from E2-17 is complete.
- One-time personal data import passes if included.
- Static and runtime audits find no synchronization, dual-write, automatic fallback, speculative tombstones, or cross-authority recovery.
- Requirements and issue acceptance criteria have an exclusive coverage map with no gaps.
- All tests, opt-in exclusions, warnings, device limitations, and deferred work are reported exactly.
- Qualification defects are corrected only within approved issue scope.
- ChatGPT Work coordinates requirements traceability, architecture-gate review, manual-evidence acceptance, and final closure.
- Architecture stop: any discovery showing that a preserved invariant, the single-authority rule, or self-contained runtime goal cannot be achieved within the approved architecture stops release work and returns the Epic to architecture review.

### Out of scope

- New product behavior.
- Synchronization or cloud backup.
- Architecture redesign.
- New performance targets.
- Public or collaborative deployment.
- Speculative follow-up infrastructure.

### Dependencies

- E2-16.
- E2-17.

### Backend work

- Run final backend and PostgreSQL qualification.
- Correct only bounded defects within approved Epic 2 scope.

### Frontend work

- Run final local and remote mobile qualification.
- Correct only bounded defects within approved Epic 2 scope.

### API work

- Run final parity and authority-isolation audits.
- Add no new interface unless an approved acceptance criterion is otherwise impossible and architecture review authorizes it.

### Migration work

- Run final SQLite schema, upgrade, rollback, integrity, and import qualification.
- Run required PostgreSQL migration regression.
- Confirm no control-plane or Phase 5 migration scope entered Epic 2.

### Testing requirements

- Run the complete cross-cutting review profile.
- Run full backend and mobile suites.
- Run required PostgreSQL and native SQLite opt-in suites.
- Include the retained physical-device evidence from E2-16; removed manual accessibility scope is
  not a release claim.
- Exercise backend-unavailable local operation and explicit USDA-unavailable behavior.
- Validate one-time transfer if included.
- Run documentation, requirement-traceability, repository-integrity, and prohibited-scope audits.
- Report exact passes, skips, warnings, manual evidence, and deferred work.

### Estimated implementation size

L

### Recommended Codex model and effort

`gpt-5.6-sol` — xhigh

Reason: Codex should execute and diagnose the cross-cutting qualification, while ChatGPT Work coordinates architecture review, evidence acceptance, and the final release decision.
