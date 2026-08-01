# Version 1.1 Epic 1 — GitHub Implementation Backlog

## Backlog status

The Architecture Review approves the Feature PRD within the roadmap’s evolutionary boundary. No requirement currently triggers the stop-and-return architecture gate.

Implementation must stop and return to roadmap review if authoritative time-zone support or client-local uncertain-mutation recovery is later found to require a persistence redesign, fundamental data-model change, or architectural rewrite.

---

# Milestone 1 — Calendar and Mutation Foundations

## E1-01 — Establish the authoritative user time zone

### Purpose

Provide one owner-scoped, confirmed IANA time zone as the authority for Daily Log calendar behavior.

### Background

Daily Log semantics must not silently follow device time-zone changes. The existing user/profile boundary can be extended additively without changing the Daily Log model.

### Acceptance criteria

- The application can retrieve whether the owner has an authoritative time zone and, when established, its IANA identifier.
- A valid client time zone may be proposed but is visibly identified as provisional.
- Establishment requires explicit user confirmation.
- Invalid or unknown IANA identifiers are rejected authoritatively.
- Daily Log mutation requests are rejected until a time zone is established.
- The confirmed zone is shared by all active clients for the owner.
- Device time-zone changes do not modify the authoritative zone.
- Confirmation re-evaluates the active date classification without changing the selected date.
- Existing Daily Logs and snapshots are not moved or modified.

### Out of scope

- Time-zone change impact review.
- Future-entry cleanup.
- Per-device or per-entry time zones.
- Public multi-user settings.

### Dependencies

- None.

### Backend work

- Add authoritative time-zone state to the existing owner settings/profile boundary.
- Validate IANA identifiers.
- Expose confirmed versus unconfirmed state.
- Add a shared mutation guard for owners without a confirmed zone.

### Frontend work

- Add authoritative-calendar state and cache handling.
- Present the proposed zone and require explicit confirmation.
- Refresh active Daily Log date classification after confirmation without navigation.

### API work

- Add authenticated read and initial-confirmation operations for authoritative calendar state.
- Return stable error codes for missing confirmation and invalid zones.

### Migration work

- Additive migration for the authoritative IANA identifier within the existing owner settings/profile boundary.
- Existing users must remain unconfirmed; no device zone may be backfilled silently.

### Testing requirements

- Unit tests for IANA validation.
- API tests for unconfirmed, confirmed, invalid, and cross-owner access.
- Migration replay and rollback tests.
- Mobile tests proving explicit confirmation and no silent adoption.
- Multi-client tests proving both clients receive the same authoritative zone.

### Estimated implementation size

L

---

## E1-02 — Support confirmed time-zone changes and impact review

### Purpose

Allow an established authoritative time zone to change without silently changing, moving, or deleting Daily Log entries.

### Background

A zone change can alter Today and reclassify existing dates as future-dated. The user must understand the impact before confirming it.

### Acceptance criteria

- A proposed change shows the current and proposed named zones.
- The preview states whether Today changes.
- The preview reports how many entries would become future-dated.
- The user can review affected dates or entries before confirmation.
- The confirmation explains that entries are reclassified, not moved, modified, or deleted.
- Reclassification does not block the zone change.
- Confirmation updates only authoritative calendar state.
- Active Add and Edit workflows retain their date and entered values when calendar authority changes.
- Active workflows disclose the context change and revalidate before commit.
- A workflow whose date becomes future-dated is blocked without selecting a replacement date.
- Concurrent zone changes use authoritative state and require renewed review rather than silently overwriting another change.

### Out of scope

- Editing or deleting affected entries.
- Moving entries automatically.
- Changing nutrition snapshots.
- Time-zone history or per-entry zone attribution.

### Dependencies

- E1-01.

### Backend work

- Calculate the impact of a proposed zone using authoritative owner data.
- Return affected entry counts and reviewable identifiers.
- Commit zone changes without updating Daily Log dates or snapshots.
- Detect stale zone-change confirmations.

### Frontend work

- Add change preview and confirmation to Settings.
- Provide affected-date or affected-entry review.
- Notify active Add/Edit workflows of calendar-context changes while retaining form state.
- Force pre-commit revalidation after a context change.

### API work

- Add time-zone change preview and confirmed change operations.
- Include sufficient authoritative calendar version/state for stale-context detection.

### Migration work

- None beyond E1-01 unless an additive calendar revision field is required within the same approved owner-settings boundary.

### Testing requirements

- DST-boundary and opposite-offset zone tests.
- Tests where Today changes and where it does not.
- Tests for zero, one, and multiple affected entries.
- Tests proving no Daily Log or snapshot changes.
- Active Add/Edit revalidation tests.
- Multi-client stale-change tests.

### Estimated implementation size

L

---

## E1-03 — Enforce shared meal and note contracts

### Purpose

Create one authoritative validation contract for meal assignment and notes across creation, editing, Repeat, compatibility data, clients, and backend validation.

### Background

The schema already carries meal and notes, but Version 1.1 requires constrained meal identifiers, explicit clearing semantics, Unicode-aware note validation, and legacy preservation.

### Acceptance criteria

- New meal values are limited to `breakfast`, `lunch`, `dinner`, `snack`, or absence.
- Unassigned is represented as absence, not as a stored fifth identifier.
- Omitted meal or note fields preserve existing values during partial edits.
- Explicit null clears the corresponding field.
- No meal is inferred from time of day.
- Notes remain plain text and preserve line breaks.
- Leading and trailing whitespace is trimmed before persistence.
- A trimmed empty note becomes absent.
- New or explicitly edited notes over 1,000 Unicode code points are rejected before save and by authoritative validation.
- Existing unsupported meals remain stored through unrelated edits.
- Explicitly selecting a supported meal or clearing it replaces an unsupported meal.
- Existing overlength notes remain intact through unrelated edits.
- Editing an overlength note requires compliance with the current limit.
- Validation returns stable, field-specific errors.

### Out of scope

- Meal-group presentation.
- Note preview expansion.
- Rich text, links, attachments, or formatting.
- Custom meals.

### Dependencies

- None.

### Backend work

- Add shared meal and note validators.
- Correct partial-update presence semantics.
- Preserve unsupported meals and overlength notes unless their fields are explicitly edited.

### Frontend work

- Add reusable meal and note form validation.
- Count Unicode code points consistently.
- Present field-specific validation before submission.

### API work

- Tighten create and update request contracts while preserving legacy response compatibility.
- Return stable validation codes for unsupported meals and overlength notes.

### Migration work

- None. Existing legacy values must not be rewritten.

### Testing requirements

- Unicode boundary tests at 999, 1,000, and 1,001 code points.
- Whitespace, multiline, empty, omitted, and explicit-null tests.
- Supported and unsupported meal tests.
- Regression tests proving unrelated edits preserve legacy values.

### Estimated implementation size

M

---

## E1-04 — Make all Log mutations replay-safe and concurrency-aware

### Purpose

Provide the authoritative mutation contracts required for safe recovery from indeterminate create, edit, move, and delete outcomes.

### Background

Create already has request identity. Edit and delete require equivalent same-intent replay and reconciliation behavior, and active edits must detect intervening changes from another client.

### Acceptance criteria

- Create, edit, move, and delete accept owner-scoped mutation intent identity.
- Repeating the same intent with the same canonical payload returns the authoritative prior outcome without applying the mutation twice.
- Reusing an intent with a different payload is rejected.
- A caller can reconcile an intent after an indeterminate response.
- Reconciliation distinguishes confirmed success, confirmed non-commit, conflict, and unresolved outcome.
- Edit and delete reconciliation identifies the affected entry.
- Move reconciliation provides enough authoritative information to check both source and destination dates.
- Edit and delete reject stale entry preconditions when another client has changed or deleted the entry.
- Conflict responses require refresh and renewed user review.
- No automatic merge is performed.
- Mutation responses remain owner-isolated.
- Existing creation idempotency behavior remains compatible.

### Out of scope

- Client-local durable recovery UI.
- Cross-device pending-intent synchronization.
- Offline mutation queues.
- Collaborative or field-level merging.

### Dependencies

- E1-01.
- E1-03.

### Backend work

- Extend the existing idempotency/reconciliation pattern to update, move, and delete.
- Canonicalize request fingerprints.
- Record terminal outcomes needed for safe replay, including deletion.
- Enforce entry concurrency preconditions.

### Frontend work

- Extend API types to carry mutation identity and authoritative entry preconditions.
- Do not yet add durable recovery prompts; that belongs to E1-16.

### API work

- Extend update and delete contracts with mutation identity and stale-entry preconditions.
- Add or extend an authenticated mutation-status operation.
- Standardize replay, payload-conflict, stale-entry, non-commit, and unresolved error codes.

### Migration work

- Additive owner-scoped mutation receipt storage sufficient for update, move, and delete replay.
- Do not alter Daily Log ownership or snapshot tables.

### Testing requirements

- Same-intent replay tests for all mutation types.
- Changed-payload conflict tests.
- Concurrent identical request tests on PostgreSQL.
- Stale edit and delete tests.
- Move reconciliation tests covering both dates.
- Cross-owner isolation tests.
- Migration replay and rollback tests.

### Estimated implementation size

L

---

# Milestone 2 — Trustworthy Daily Log Review

## E1-05 — Implement authoritative date navigation and provisional browsing

### Purpose

Make date navigation obey the authoritative calendar while preventing cross-date data leakage and unsupported future browsing.

### Background

The existing Daily Log uses device-local dates. Version 1.1 requires authoritative calendar arithmetic, provisional read-only browsing, Today boundaries, and midnight rollover without retargeting the user.

### Acceptance criteria

- Previous and Next use calendar-date arithmetic in the authoritative or clearly identified provisional zone.
- Next stops at Today during ordinary browsing.
- A Today shortcut appears whenever another supported date is selected.
- Direct date selection remains available.
- Before time-zone confirmation, history is browsable but all mutation actions are unavailable.
- Provisional Today and future classifications identify the proposed zone.
- Midnight updates Today and navigation controls without changing the selected date or active workflow date.
- Changing dates immediately retires prior-date entries, totals, and target content.
- The new date shows only its own loading, failure, or success states.
- No component substitutes the current date for the selected date.
- DST transitions do not skip or duplicate calendar dates.

### Out of scope

- Future-date cleanup presentation.
- Same-date stale-content handling.
- Time-zone settings implementation.

### Dependencies

- E1-01.
- E1-02.

### Backend work

- None beyond the authoritative calendar contracts already established.

### Frontend work

- Replace device-local Today and date arithmetic in Daily Log navigation.
- Add Previous, Next, Today, and direct date-selection behavior.
- Gate mutation affordances during provisional browsing.
- Add midnight rollover reevaluation.
- Key all date-dependent view state by selected date.

### API work

- Consume the authoritative calendar state from E1-01 and E1-02.
- No additional endpoint is expected.

### Migration work

- None.

### Testing requirements

- Unit tests for date arithmetic around DST and year/month boundaries.
- Fake-clock midnight tests.
- Cross-date cache isolation tests.
- Provisional browsing and mutation-gating tests.
- iOS and Android date-picker tests.

### Estimated implementation size

L

---

## E1-06 — Present meal-grouped entries, notes, and compatibility notices

### Purpose

Replace the flat entry list with the required meal organization and readable note presentation.

### Background

Meal context and notes already exist in the Log contract but are not fully presented.

### Acceptance criteria

- Breakfast, Lunch, Dinner, and Snack always appear in that fixed order.
- Named groups remain expanded, including when empty.
- Each named group exposes Add Food.
- Unassigned appears last only when it contains entries and has no Add action.
- Unsupported legacy meals are projected into Unassigned.
- Unsupported values are safely escaped and shown in a visually bounded notice.
- All entries remain visible; groups cannot collapse, filter, reorder, or support drag-and-drop.
- Entries within each group sort by creation time ascending and stable entry identifier.
- Editing does not change creation order.
- Creation time is not shown or described as consumption time.
- An empty date says “No food logged for this date.”
- Empty dates still show all four named groups and Add actions.
- Entry notes show no more than two preview lines.
- Overflow uses an ellipsis with Show more and Show less.
- Expansion is independent per entry, in place, and read-only.
- Entries without notes reserve no note space.

### Out of scope

- Per-meal totals.
- Meal inference.
- Manual ordering.
- Note editing.

### Dependencies

- E1-03.

### Backend work

- Ensure list responses expose immutable creation time and stable identifiers required for ordering.
- Preserve existing unsupported meal values.

### Frontend work

- Add fixed meal-group presentation.
- Add deterministic grouping and ordering.
- Add empty-day presentation.
- Add legacy meal notices and note preview expansion.

### API work

- Extend mobile response typing for creation time and meal fields already returned by the backend.
- No new endpoint is expected.

### Migration work

- None.

### Testing requirements

- Group order and empty-group tests.
- Deterministic tie-breaker tests.
- Unsupported meal escaping and bounding tests.
- Note preview and independent expansion tests.
- Empty-date tests.

### Estimated implementation size

M

---

## E1-07 — Separate Daily Log read states and project confirmed mutations

### Purpose

Make entries, totals, and target progress independently understandable while preserving confirmed mutation results through refresh failures.

### Background

These sections load independently but currently lack the complete loading, failure, stale, retry, and confirmed-result model.

### Acceptance criteria

- Entries, totals, and target progress each expose independent loading, success, failure, stale, and retry states.
- Entry failure is never shown as an empty day.
- Totals or target failure does not hide loaded entries.
- Retrying one section does not discard successful content in another.
- Same-date refresh may retain confirmed content only when clearly marked stale or potentially stale.
- Cross-date navigation never retains prior-date content.
- No-entry state represents unknown consumption and does not show confirmed zero intake or successful 0% target progress.
- Confirmed create, edit, move, and delete responses are reflected immediately.
- A later read failure does not reverse or make a confirmed mutation uncertain.
- Confirmed moves remain projected at their destination.
- Source and destination reads refresh independently after a move.

### Out of scope

- Indeterminate mutation recovery.
- Date navigation controls.
- New analytics or telemetry.

### Dependencies

- E1-05.

### Backend work

- Preserve independent entries, totals, and target endpoints and authoritative response semantics.

### Frontend work

- Add independent section-state models and retries.
- Add same-date stale markers.
- Add confirmed-result cache projection for all mutation types.
- Prevent empty or zero-progress presentation when entries are unavailable or absent.

### API work

- No new endpoint is expected.
- Normalize errors sufficiently for independent section retry behavior.

### Migration work

- None.

### Testing requirements

- All combinations of entry, totals, and target success/failure.
- Same-date refresh failure tests.
- Cross-date stale-content prevention tests.
- Confirmed create/edit/move/delete followed by refresh failure.
- Empty-day target semantics tests.

### Estimated implementation size

M

---

# Milestone 3 — Add Food from Daily Log

## E1-08 — Deliver the core Daily Log Add Food vertical slice

### Purpose

Allow users to start from a general or meal-specific Daily Log action, browse reusable Foods, confirm one entry, and return to the originating date.

### Background

The Daily Log currently lacks a direct Food-discovery entry point.

### Acceptance criteria

- General Add opens discovery with meal unset.
- Named meal Add opens discovery with that meal as an editable initial value.
- Empty-query browse mode shows, in order:
  1. Recent Entries;
  2. Favorites;
  3. Recent Foods;
  4. Saved Foods.
- Until E1-12 supplies Recent Entries, that section has an honest independent loading or unavailable state rather than fabricated results.
- Selecting a Favorite, Recent Food, or Saved Food goes directly to Log Food confirmation without Food Detail.
- The immutable target date is carried from Daily Log through discovery and confirmation.
- Successful creation returns to the originating date and immediately shows the confirmed entry.
- Cancelling discovery returns to the originating Daily Log.
- Add remains available on a supported date when entries fail to load.
- Entry-load failure produces a warning that the day cannot be reviewed and duplicate logging is possible.
- Recent Entries remains unavailable when its own data is unavailable.
- Favorites, Recent Foods, and Saved Foods retain independent availability.
- Add is unavailable before time-zone confirmation and on unsupported future dates.

### Out of scope

- USDA search/import.
- Custom Food and Scan Label handoffs.
- Repeat behavior.
- Full source-drift and transient-state hardening.

### Dependencies

- E1-03.
- E1-05.
- E1-06.
- E1-07.

### Backend work

- Reuse existing favorite, recent Food, saved Food, and create-Log behavior.

### Frontend work

- Add general and meal-specific navigation into a Daily Log discovery screen.
- Build ordered browse sections with independent states.
- Route Food selections directly to shared confirmation.
- Return confirmed results to the immutable originating date.

### API work

- Reuse existing Food discovery and Log creation APIs.
- Align client contracts with the date, meal, and validation rules.

### Migration work

- None.

### Testing requirements

- General and each named meal entry point.
- Browse section order and independent failures.
- Direct selection without Food Detail.
- Entry-load failure warning.
- Cancellation and successful return to the originating date.
- Integration test from Daily Log through confirmed create.

### Estimated implementation size

L

---

## E1-09 — Add Saved Food and USDA search mode with import handoff

### Purpose

Support Daily Log search without weakening the explicit USDA import boundary.

### Background

A non-empty query must replace browse shortcuts with separate Saved Foods and USDA results.

### Acceptance criteria

- Non-empty queries replace browse sections with clearly separated Saved Foods and USDA groups.
- Clearing the query restores browse mode and preserves Daily Log context.
- Saved Food search results proceed directly to Log Food confirmation.
- USDA results enter the existing explicit preview/import workflow.
- Successful USDA import creates a reusable Food and continues to Log Food confirmation.
- Import alone never creates a Daily Log entry.
- Cancelling Log Food confirmation leaves the imported Food saved.
- USDA failure does not make Saved Food search or historical Daily Logs unavailable.
- No live USDA dependency is added to saved-Food or historical views.

### Out of scope

- USDA import redesign.
- Automatic import or logging.
- Changes to USDA provenance.
- Offline USDA behavior.

### Dependencies

- E1-08.
- E1-11.

### Backend work

- Reuse existing USDA search/import and Food creation services.
- Preserve separate catalog creation and Log creation transactions.

### Frontend work

- Add search-mode switching and separated result groups.
- Add Daily Log-aware USDA preview/import return routing.
- Continue successful import to shared confirmation with date and discovery context intact.

### API work

- Reuse existing USDA and Food APIs.
- No combined import-and-log endpoint may be introduced.

### Migration work

- None.

### Testing requirements

- Query transition and clearing tests.
- Saved result direct-handoff tests.
- USDA import success, cancel, failure, and retry tests.
- Verification that import never creates a Log entry.
- USDA outage tests proving Saved Foods and Daily Log history remain usable.

### Estimated implementation size

M

---

## E1-10 — Add Custom Food and supported Scan Label handoffs

### Purpose

Allow creation of a new reusable Food from Daily Log discovery while preserving the existing Custom Food and OCR workflows.

### Background

These are acquisition handoffs, not redesigns. Platform support differs for Scan Label.

### Acceptance criteria

- Custom Food launches the existing creation workflow with Daily Log context retained.
- Successful Custom Food creation continues to Log Food confirmation.
- Cancelling confirmation leaves the Food saved and creates no Log entry.
- Scan Label is present on supported iOS clients.
- Successful iOS Scan Label confirmation creates a reusable Food and continues to Log Food confirmation.
- Android does not show Scan Label or expose an unsupported OCR route.
- Cancelling or failing acquisition never creates a partial Daily Log entry.
- All successful acquisition paths converge on the same Log Food confirmation.

### Out of scope

- Redesign of Custom Food.
- Redesign of OCR capture, parsing, or confirmation.
- Android OCR.
- Combined Food-and-Log transactions.

### Dependencies

- E1-08.
- E1-11.

### Backend work

- Reuse existing Custom Food and OCR-confirmed Food creation behavior.

### Frontend work

- Add Daily Log-aware creation return routes.
- Continue successful creation to shared confirmation.
- Apply platform gating for Scan Label.

### API work

- Reuse existing Food and OCR APIs.
- No combined creation-and-log endpoint.

### Migration work

- None.

### Testing requirements

- Custom Food success, cancellation, and failure.
- iOS Scan Label routing and successful continuation.
- Android absence and route-inaccessibility tests.
- Verification that cancellation leaves the Food saved but no Log created.

### Estimated implementation size

M

---

## E1-11 — Harden shared Log Food confirmation and transient workflow state

### Purpose

Ensure every acquisition path uses one authoritative confirmation flow that remains correct when source or calendar context changes.

### Background

The selected Food, serving definitions, Recipe publication, or time-zone context may change while confirmation is open.

### Acceptance criteria

- Confirmation visibly presents the immutable date, current authoritative source, serving, amount, meal, notes, and applicable log-specific values.
- Meal defaults remain editable and clearable.
- Backdated creation uses the current authoritative source at commit.
- The consumption date never selects a historical source definition.
- If the Food, active Recipe publication, or selected serving changes, save is blocked until authoritative data is refreshed and reviewed.
- No replacement serving or source is selected silently.
- Ambiguous nutrition-affecting selections are cleared.
- If the source is no longer loggable, the user returns to discovery with the target date preserved.
- Cancelling confirmation returns exactly one level to discovery.
- Returning to discovery restores date, originating meal default, mode, query, section state, scroll position, and other transient discovery context.
- Returning from ordinary backgrounding preserves unsubmitted state while the process remains alive.
- Process termination may discard unsubmitted state and never creates a partial entry.
- Food creation/import and Log creation remain separate explicit transactions.
- Selection, acquisition handoff, and cancellation never commit a Log entry.

### Out of scope

- Durable drafts or workflow resume after process termination.
- Offline authoring.
- Repeat-specific prefilling.
- Source replacement during Edit.

### Dependencies

- E1-02.
- E1-03.
- E1-04.
- E1-08.

### Backend work

- Validate current source authority and selected amount at commit.
- Return explicit source-changed, serving-changed, and no-longer-loggable conflicts.
- Preserve atomic snapshot creation.

### Frontend work

- Add meal and note controls to shared confirmation.
- Add source/calendar precondition handling and explicit review state.
- Preserve and restore transient discovery state.
- Clear ambiguous selections without choosing replacements.

### API work

- Include sufficient source authority/version information in confirmation inputs or commit preconditions.
- Standardize source-change conflict responses.

### Migration work

- None.

### Testing requirements

- Food serving replacement during confirmation.
- Recipe republication during confirmation.
- Source deletion during confirmation.
- Calendar change during confirmation.
- Cancellation hierarchy and full discovery-state restoration.
- Background/process-termination behavior.
- Backdated creation using current source.
- Atomicity tests proving no partial Log creation.

### Estimated implementation size

L

---

# Milestone 4 — Repeat, Edit, Move, Delete, and Compatibility Cleanup

## E1-12 — Implement Recent Entries and single-entry Repeat

### Purpose

Provide the sole history-derived authoring workflow without copying stale historical authority.

### Background

Repeat must treat each prior Log as a distinct discovery choice and always create a newly confirmed entry.

### Acceptance criteria

- Recent Entries contains the 10 most recently created eligible entries, newest first.
- There is no rolling-day cutoff or deduplication.
- Eligibility requires a source date of Today or earlier and a currently loggable Food or active published Recipe.
- Eligibility does not require every historical serving or amount to remain reusable.
- Each result shows log date, meal when present, serving and amount, and whether a note exists.
- Selecting a result prepares exactly one new entry and opens shared confirmation.
- Repeat uses the current Food or active published Recipe revision at commit, not historical snapshots.
- The target date is the currently viewed Daily Log date and remains immutable.
- Safely resolvable serving and amount values may be prefilled.
- Ambiguous serving or amount values remain unselected.
- Explicit meal-group context overrides historical meal.
- General Add reuses only a supported historical meal; otherwise meal remains unset.
- Unsupported legacy meals are never propagated.
- Notes start blank.
- A currently compliant historical note may be shown read-only with explicit Copy notes.
- Notes are never copied automatically or truncated.
- Overlength legacy notes do not offer Copy notes.
- Entry identifiers, timestamps, event provenance, and historical snapshots are not copied.
- Future entries never appear as Repeat sources.
- No Duplicate, Copy Meal, Copy Day, bulk Repeat, bulk reassignment, or bulk deletion action is introduced.

### Out of scope

- Bulk operations.
- Automatic note copying.
- Historical source reconstruction.
- Duplicate Log Entry.

### Dependencies

- E1-03.
- E1-08.
- E1-11.

### Backend work

- Add an owner-scoped Recent Entries query with required eligibility and deterministic ordering.
- Resolve current source loggability without altering historical entries.
- Return distinguishing context and safe reuse metadata.

### Frontend work

- Populate the Recent Entries discovery section.
- Add Repeat initialization, meal precedence, note reference, and Copy notes behavior.
- Route every Repeat through shared confirmation.

### API work

- Add a bounded Recent Entries read operation with a fixed limit of 10.
- Keep Repeat commit on the ordinary create-Log operation.

### Migration work

- Add an index only if query-plan evidence shows the existing owner/creation ordering is insufficient; no data migration.

### Testing requirements

- Eligibility and newest-first ordering.
- No cutoff and no deduplication.
- Food deletion and Recipe republication cases.
- Safe and ambiguous serving mapping.
- Meal precedence.
- Compliant, overlength, absent, and multiline note cases.
- Future-source exclusion.
- Verification that historical snapshots and identity are never reused.

### Estimated implementation size

L

---

## E1-13 — Implement historically safe entry editing and date moves

### Purpose

Allow explicit corrections while preserving source identity and the distinction between metadata and nutrition-affecting edits.

### Background

The existing edit path regenerates nutrition broadly and blocks some source-unavailable metadata changes. Version 1.1 requires narrower, explicit behavior.

### Acceptance criteria

- Edit may change date, meal, notes, serving, and amount.
- Source identity is not editable.
- Correcting the source requires confirmed deletion and a new Add Food flow.
- Date, meal, and note-only changes preserve existing snapshots exactly.
- Serving or amount changes atomically replace snapshots using the same current authoritative source.
- Prior entry versions are not retained.
- Food or Recipe changes outside explicit Log editing never recalculate the entry.
- If the source is unavailable, meal, note, valid date move, and deletion remain allowed.
- Nutrition-affecting edits are rejected when the source is unavailable.
- Unsupported legacy meals and overlength notes survive unrelated edits.
- Backdated nutrition edits use the current authoritative source at commit.
- A valid date move preserves snapshots, removes the entry from the source day, navigates to the destination day, and shows the entry there.
- Source and destination totals and targets refresh independently.
- An edit without a date change remains on the current day.
- Stale edits caused by another client stop, refresh authoritative state, and require renewed review.
- Editing never changes creation time.

### Out of scope

- Source replacement.
- Automatic merges.
- Edit history.
- Future-to-future movement.
- Automatic historical recalculation.

### Dependencies

- E1-02.
- E1-03.
- E1-04.
- E1-05.
- E1-07.
- E1-11.

### Backend work

- Separate metadata-only and nutrition-affecting edit paths.
- Permit snapshot-preserving edits when the source is unavailable.
- Preserve source identity and creation time.
- Apply current source resolution only for nutrition-affecting edits.
- Enforce stale-entry preconditions.

### Frontend work

- Add date, meal, note, serving, and amount editing.
- Disable only nutrition-affecting controls when the source is unavailable.
- Navigate and refresh correctly after a move.
- Handle stale-entry conflicts through refresh and review.

### API work

- Preserve omitted versus explicit-null field semantics.
- Return enough edit context to distinguish permitted metadata and nutrition changes.
- Use the replay-safe mutation contract from E1-04.

### Migration work

- None.

### Testing requirements

- Snapshot byte/value preservation for metadata edits and moves.
- Atomic snapshot replacement for serving and amount changes.
- Source-unavailable edit matrix.
- Fixed source identity and creation-time tests.
- Source/destination refresh failure combinations.
- Concurrent edit and delete conflicts.
- Recipe revision and mutable Food cases.

### Estimated implementation size

L

---

## E1-14 — Add permanent deletion with explicit consequences

### Purpose

Require deliberate, contextual confirmation before permanently removing one Daily Log entry.

### Background

Deletion currently occurs directly and does not explain its scope.

### Acceptance criteria

- Delete opens a confirmation identifying the entry and date.
- Confirmation includes sufficient available context: name, meal, serving, and amount.
- Confirmation states that only the Daily Log entry and its historical nutrition snapshots are removed.
- Reusable Foods, Recipes, USDA imports, and catalog data remain unchanged.
- Confirmed deletion is permanent.
- After success, the user remains on the same date.
- Groups or empty state update immediately.
- A later refresh failure does not restore the confirmed deletion.
- Stale or already-deleted entries require authoritative refresh.
- No Undo, recycle bin, soft delete, or recovery window is offered.

### Out of scope

- Bulk deletion.
- Catalog deletion.
- Deleted-entry recovery.

### Dependencies

- E1-04.
- E1-06.
- E1-07.

### Backend work

- Preserve hard deletion of the owned entry and its snapshots only.
- Use replay-safe delete and stale-entry behavior from E1-04.

### Frontend work

- Add contextual destructive confirmation.
- Project confirmed deletion immediately.
- Handle stale and replayed outcomes correctly.

### API work

- Use the replay-safe delete contract from E1-04.
- Return or reconcile sufficient terminal outcome information.

### Migration work

- None beyond E1-04.

### Testing requirements

- Confirmation content tests.
- Entry/snapshot deletion and catalog-preservation tests.
- Same-date empty/group update tests.
- Replayed delete and concurrent delete tests.
- Refresh-failure-after-confirmation tests.

### Estimated implementation size

M

---

## E1-15 — Deliver the legacy future-entry cleanup experience

### Purpose

Preserve and resolve compatibility future entries without weakening the normal no-future mutation rule.

### Background

Existing entries or a time-zone change may produce future-dated compatibility data. These entries must not appear in the normal Daily Log.

### Acceptance criteria

- No Version 1.1 mutation can create a new future-dated entry.
- Existing or reclassified future entries remain preserved.
- Direct navigation to a future date opens a dedicated cleanup experience.
- With entries, the screen presents a flat identifying list.
- Each item shows Food or Recipe, date, serving and amount, note preview, unsupported-meal notice, and available identifying metadata.
- Only View, Delete, and Edit-to-move actions are available.
- A future entry may be saved only when the same edit moves it to Today or earlier.
- Any save leaving the entry future-dated is rejected, regardless of other changes.
- Future-to-future movement is prohibited.
- Future entries cannot be Repeat sources.
- Once moved into the supported range, an otherwise eligible entry may re-enter Recent Entries.
- An empty future date says “No legacy entries on this future date.”
- The empty state provides navigation back to the supported range.
- Future screens omit normal meal groups, Add Food, Repeat, totals, target progress, and the ordinary empty-day state.
- Zone changes remain allowed even when they create compatibility future entries.

### Out of scope

- Automatic movement or deletion.
- Normal logging on future dates.
- Meal-group presentation for future dates.
- Future scheduling or meal planning.

### Dependencies

- E1-02.
- E1-04.
- E1-05.
- E1-06.
- E1-12.
- E1-13.
- E1-14.

### Backend work

- Enforce future-date mutation rules using the current authoritative zone.
- Support owner-scoped future-entry listing and identifying metadata.
- Preserve compatible future entries until explicit movement or deletion.

### Frontend work

- Route future dates to the cleanup screen.
- Add flat-list presentation and restricted actions.
- Add edit-to-move behavior and supported-range navigation.

### API work

- Add or extend an owner-scoped future-date compatibility read operation.
- Return stable rejection codes for newly future-dated and future-to-future mutations.

### Migration work

- None. Existing dates must not be rewritten.

### Testing requirements

- Existing and time-zone-reclassified future entries.
- Empty and populated cleanup dates.
- Allowed delete and move-to-supported-range operations.
- Rejected create, Repeat, metadata-only future save, and future-to-future move.
- Verification that normal Daily Log sections are absent.
- Reintegration into Recent Entries after a valid move.

### Estimated implementation size

L

---

# Milestone 5 — Recovery and Release Qualification

## E1-16 — Implement durable client-local uncertain-mutation recovery

### Purpose

Prevent duplicate or conflicting actions after a mutation’s commit outcome becomes indeterminate.

### Background

The originating client must retain only enough locked information to reconcile the exact operation after interruption or process termination.

### Acceptance criteria

- An indeterminate create, edit, move, or delete creates one locked recovery record on the originating client.
- The record contains only the exact submitted identity, payload information required for replay, target identity, and required reconciliation context.
- The pending payload cannot be edited or casually resubmitted.
- Retry or status check uses the same intent.
- Confirmed success completes and removes the recovery record.
- Confirmed non-commit makes the same operation safely retryable.
- Edit and delete reconciliation refresh the affected entry.
- Move reconciliation checks source and destination dates.
- Optimistic local state is never treated as proof.
- Recovery survives process termination.
- Dismissing the prompt does not erase or resolve uncertainty.
- Starting a separate operation that may duplicate or conflict requires an explicit warning that the first operation may already have committed.
- Unresolved recovery restrictions take precedence over ordinary Add availability.
- Other clients rely only on authoritative state and do not receive the originating client’s pending record.
- No recovery record acts as a draft, new-work queue, offline queue, or cross-device resume mechanism.

### Out of scope

- Durable unsubmitted drafts.
- Offline authoring.
- Cross-device pending-intent synchronization.
- Collaborative recovery or automatic merge.

### Dependencies

- E1-04.
- E1-07.
- E1-08.
- E1-13.
- E1-14.
- E1-15.

### Backend work

- Support authoritative reconciliation through E1-04 contracts.
- No server-side synchronization of client recovery prompts.

### Frontend work

- Add minimal durable recovery storage.
- Add startup and foreground reconciliation.
- Add locked recovery prompts, dismissal behavior, same-intent retry, and duplicate/conflict warnings.
- Refresh the correct date and entry sets after reconciliation.

### API work

- Consume mutation-status and replay contracts from E1-04.
- No additional workflow-sync API.

### Migration work

- No backend migration beyond E1-04.
- Client-local storage versioning may be required for the bounded recovery record.

### Testing requirements

- Simulated transport loss before and after commit for every mutation type.
- Process termination and restart.
- Dismissal without erasure.
- Same-intent retry and changed-action warning.
- Move reconciliation across both dates.
- Confirmed non-commit.
- Multi-client tests proving no pending-record synchronization.

### Estimated implementation size

L

---

## E1-17 — Qualify and remediate Epic 1 accessibility

### Purpose

Establish equivalent access to every supported Epic 1 workflow.

### Background

Accessibility is a release requirement, not a follow-up enhancement.

### Acceptance criteria

- Every supported Epic 1 workflow is operable with VoiceOver on iOS and TalkBack on Android.
- Qualification covers:
  - date navigation and picker;
  - provisional and confirmed calendar states;
  - meal groups and Add actions;
  - browse, search, Recent Entries, and Repeat;
  - acquisition handoffs;
  - Log Food confirmation;
  - editing, moving, notes, and deletion;
  - legacy future cleanup;
  - loading, stale, failure, and retry states;
  - uncertain-mutation recovery; and
  - destructive confirmations.
- iOS qualification includes Scan Label.
- Android omits Scan Label and exposes no unsupported OCR route.
- Dynamic text and large accessibility sizes remain usable.
- Supported keyboard workflows remain usable.
- Controls have appropriate labels, roles, hints, and state.
- Focus order is logical.
- Dynamic changes and errors produce useful announcements.
- No platform-supported capability is unavailable solely because assistive technology is active.
- Discovered Epic 1 accessibility defects are remediated before closure.

### Out of scope

- Android OCR.
- New capabilities not included in Epic 1.
- Redesign of existing OCR internals.

### Dependencies

- E1-05 through E1-16.

### Backend work

- None unless remediation identifies an inaccessible error contract lacking usable semantics.

### Frontend work

- Perform accessibility remediation across all Epic 1 screens and shared components.
- Add appropriate focus and announcement behavior.

### API work

- None expected.

### Migration work

- None.

### Testing requirements

- Automated accessibility-semantic tests where supported.
- Manual VoiceOver and TalkBack qualification.
- Large-text and supported keyboard evidence.
- iOS Scan Label accessibility evidence.
- Recorded defect and retest evidence.

### Estimated implementation size

L

---

## E1-18 — Run Epic 1 end-to-end release qualification

### Purpose

Verify the complete user outcome, architecture invariants, scope boundaries, and absence of requirement gaps before Epic closure.

### Background

Individual issue tests do not replace an integrated release pass across dates, clients, source changes, failures, and compatibility states.

### Acceptance criteria

- All nine Feature PRD success criteria have release evidence.
- No date ever displays another date’s entries, totals, or targets.
- Every supported acquisition source converges on one explicit confirmation.
- Historical snapshot invariants pass for source changes, metadata edits, nutrition edits, Repeat, moves, and deletion.
- Confirmed and uncertain mutation outcomes remain distinguishable.
- Multi-client time-zone, edit, and delete conflicts require authoritative refresh and review.
- Legacy future entries, unsupported meals, and overlength notes remain bounded compatibility behavior.
- All accessibility evidence from E1-17 is complete.
- The release introduces no:
  - meal planning or future scheduling;
  - custom meals or meal inference;
  - consumption times or per-meal analytics;
  - offline authoring or mutation queues;
  - durable unsubmitted drafts;
  - bulk or Duplicate workflows;
  - source replacement during Edit;
  - undo or deleted-entry recovery;
  - automatic historical recalculation;
  - Android OCR;
  - collaborative merge or cross-device recovery;
  - rich-text notes or attachments;
  - analytics instrumentation;
  - public or multi-user behavior; or
  - technology migration or architectural rewrite.
- No elapsed-time or tap-count gate is imposed.
- Faster logging is evidenced by direct handoffs, preserved context, shared confirmation, and immediate confirmed results.
- Any discovery that crosses the approved architecture gate stops release work and returns the Epic to roadmap review.

### Out of scope

- New product telemetry.
- Performance targets not present in the PRD.
- Future Epic work.

### Dependencies

- E1-01 through E1-17.

### Backend work

- Resolve only qualification defects within already approved issue scope.

### Frontend work

- Resolve only qualification defects within already approved issue scope.

### API work

- No new API design; only corrections to approved contracts.

### Migration work

- Run full migration qualification for migrations introduced by E1-01 and E1-04.
- No additional migration is expected.

### Testing requirements

- Full backend and mobile regression suites.
- PostgreSQL concurrency and migration qualification.
- Cross-platform end-to-end scenarios.
- Multi-client conflict scenarios.
- DST and midnight scenarios.
- Source-change and source-unavailable scenarios.
- Failure injection for independent reads and uncertain mutations.
- Compatibility fixtures for future entries, unsupported meals, and overlength notes.
- Final requirements traceability audit.

### Estimated implementation size

M

---

# Recommended implementation order

1. E1-01 — Authoritative user time zone
2. E1-02 — Time-zone changes and impact review
3. E1-03 — Meal and note contracts
4. E1-04 — Replay-safe mutation contracts
5. E1-05 — Date navigation and provisional browsing
6. E1-06 — Meal-grouped Daily Log presentation
7. E1-07 — Independent read and confirmed-result states
8. E1-08 — Core Daily Log Add Food slice
9. E1-11 — Shared confirmation hardening
10. E1-09 — USDA search/import handoff
11. E1-10 — Custom Food and Scan Label handoffs
12. E1-12 — Recent Entries and Repeat
13. E1-13 — Edit and date move
14. E1-14 — Permanent deletion
15. E1-15 — Legacy future cleanup
16. E1-16 — Uncertain-mutation recovery
17. E1-17 — Accessibility qualification and remediation
18. E1-18 — End-to-end release qualification

The numbering remains stable even though E1-11 precedes E1-09 and E1-10 in implementation order; E1-11 establishes the shared confirmation behavior those acquisition handoffs consume.

# Safe parallel implementation

After E1-01:

- E1-02 and E1-03 may proceed in parallel.
- E1-04 may begin once the canonical field contract from E1-03 is stable.
- E1-05 may proceed alongside E1-04 after E1-02’s calendar contract is stable.
- E1-06 may proceed alongside E1-05 and E1-04 after E1-03.
- E1-07 may proceed while E1-06 is being completed after its E1-05 date-state dependency is stable.
- E1-09 and E1-10 may proceed in parallel after E1-08 and E1-11.
- E1-12 and E1-14 may proceed in parallel once their listed dependencies are complete.
- Backend portions of E1-13 may proceed alongside E1-12; its final mobile integration still depends on E1-11.
- E1-17 qualification planning and test-case preparation may begin early, but qualification and remediation cannot finish before E1-16.
- E1-18 begins only after every implementation and accessibility issue is complete.

E1-15 and E1-16 should remain late integration issues because each consumes behavior from several earlier mutation workflows.

# Exclusive Feature PRD coverage map

This map assigns each requirement to one primary implementation owner. Dependencies may consume the resulting capability but must not reimplement it.

| Feature PRD requirement | Exclusive owner |
| --- | --- |
| §§1–2 purpose, scope, private/internal single-owner boundary | E1-18 |
| §3.1 date authority, navigation arithmetic, rollover, and cross-date isolation | E1-05 |
| §3.2 initial authoritative time-zone establishment | E1-01 |
| §3.2 zone-change preview, confirmation, reclassification, and active-flow revalidation | E1-02 |
| §3.3 metadata/snapshot isolation, fixed source identity, and nutrition-affecting edit behavior | E1-13 |
| §3.3 Repeat use of current authority | E1-12 |
| §3.3 backdated creation use of current authority | E1-11 |
| §4.1 meal groups, ordering, expansion, and creation-time meaning | E1-06 |
| §4.2 empty-day wording and group availability | E1-06 |
| §4.2 unknown-consumption and target-progress semantics | E1-07 |
| §5.1 browse mode, direct Saved/Favorite/Recent Food selection, and Add during entry failure | E1-08 |
| §5.1 search mode and USDA handoff | E1-09 |
| §5.1 Custom Food, Scan Label, and platform behavior | E1-10 |
| §5.2 confirmation authority and source-change handling | E1-11 |
| §5.3 cancellation hierarchy and transient context | E1-11 |
| §5.4 entry-load failure behavior and discovery-source independence | E1-08 |
| §6 Recent Entries and Repeat | E1-12 |
| §7 editing and moving | E1-13 |
| §8 deletion | E1-14 |
| §9.1 meal field contract | E1-03 |
| §9.2 note validation and legacy preservation | E1-03 |
| §9.2 note preview and expansion | E1-06 |
| §10.1 legacy future entries | E1-15 |
| §10.2 unsupported legacy meals | E1-03 |
| §10.2 legacy-meal presentation | E1-06 |
| §10.3 legacy overlength notes | E1-03 |
| §10.3 Repeat Copy-notes restriction | E1-12 |
| §11.1 independent reads | E1-07 |
| §11.2 confirmed mutation projection | E1-07 |
| §11.3 authoritative replay and reconciliation contracts | E1-04 |
| §11.3 client-local recovery behavior | E1-16 |
| §12 accessibility qualification | E1-17 |
| §13 non-goals | E1-18 |
| §14 architecture gate | E1-18 |
| §15 success criteria | E1-18 |

No Feature PRD requirement is orphaned, and no implementation behavior has more than one primary owner.