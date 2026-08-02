# Implementation Lessons

This document captures engineering lessons discovered during implementation that were not explicit in the Grill, PRD, or Architecture Review.

Its purpose is to improve future implementation quality and reduce review iterations.

These lessons are implementation guidance only. They do not override the Feature PRD, Architecture Review, or Epic backlog.

---

# E1-01 — Establish the Authoritative User Time Zone

## New architectural contracts become the new baseline

Once an Epic establishes a new invariant, treat that invariant as authoritative.

Do not preserve legacy behavior simply to satisfy existing tests.

Instead:

- update shared test fixtures
- update shared helpers
- update regression expectations

Production behavior must not be weakened for compatibility.

---

## Separate implementation correctness from regression qualification

A feature implementation can be correct even if existing regression tests still assume old behavior.

Review implementation independently from repository qualification.

After implementation is approved:

- qualify the regression suite
- update fixtures
- update tests

Do not redesign production behavior solely to satisfy outdated tests.

---

## Preserve bounded implementation

Foundational work should establish only the approved contract.

Do not implement later Epic behavior simply because it appears adjacent.

---

# E1-02 — Confirmed Authoritative Time-Zone Changes

## Bind confirmation to reviewed state

When users explicitly review computed consequences before confirmation, confirmation must prove they are confirming exactly those reviewed consequences.

A version number alone is insufficient.

---

## Recompute under the authoritative lock

If confirmation depends on calculated state:

- acquire the existing owner lock
- recompute
- compare against reviewed state
- commit only if identical

Never trust previously computed client state.

---

## Prefer deterministic proof over server sessions

Whenever practical:

- deterministic review tokens
- hashes
- server-verifiable state

are preferred over persisted preview sessions or temporary server state.

---

## Keep corrections bounded

Fix the discovered defect.

Do not redesign surrounding infrastructure.

Avoid introducing persistence, services, or abstractions that are unnecessary for the accepted design.

---

# E1-03 — Shared Domain Contracts

## Centralize shared contracts

Rules used by multiple workflows belong in reusable domain utilities.

Avoid duplicating validation across:

- API schemas
- services
- repositories
- frontend
- tests

---

## Separate compatibility projection from normalization

Historical data may require compatibility projection.

New writes must always normalize into the canonical representation.

Never normalize historical persisted data simply because newer rules exist.

---

## Preserve PATCH semantics

PATCH semantics must remain explicit:

- omitted field → preserve existing value
- explicit null → intentionally clear value

Never infer clearing from omission.

---

## Canonical representations belong in the domain

Canonical values should exist once.

Presentation layers may expose friendly terminology, but persistence and domain behavior must have exactly one canonical representation.

---

# General Guidance

Before introducing new infrastructure, ask:

- Can an existing abstraction solve this?
- Can the current locking discipline be reused?
- Can the existing transaction boundary be preserved?

Prefer bounded improvements over architectural expansion.

Always preserve:

- immutable nutrition history
- immutable Recipe publication
- immutable OCR provenance
- owner isolation
- transaction boundaries
- concurrency guarantees

The burden of proof is on introducing new architecture—not on reusing existing architecture.

---

# E1-04 — Replay-Safe and Concurrency-Aware Mutations

## Qualify database locking on the production database engine

Concurrency guarantees based on row locks cannot be validated through SQLite or sequential tests.

When correctness depends on PostgreSQL locking:

- add targeted PostgreSQL contention tests;
- require the tests to execute rather than skip;
- treat unavailable infrastructure as incomplete qualification;
- run exact test node IDs when validating a bounded correction.

## Establish all foundational invariants in concurrency fixtures

Contention tests must satisfy earlier Epic contracts before reaching the behavior under test.

Shared setup helpers should establish required owner state, such as the authoritative time zone, rather than bypassing production guards.

## Check mutable preconditions under the serializing lock

Any stale-generation or expected-state precondition must be evaluated after acquiring the same lock that serializes the mutation.

This applies to:

- expected timestamps;
- expected revisions;
- delete eligibility;
- replay receipts that may complete while a request waits.

## Recheck replay receipts after lock waits

An identical request may finish while another request is blocked on the row lock.

After acquiring the lock:

- re-read the receipt;
- return the confirmed prior outcome when present;
- do not execute the mutation a second time.

## Preserve stable conflicts under contention

A losing concurrent mutation must return the accepted domain conflict, such as `stale_log_entry`, rather than degrading into a generic not-found or infrastructure error.

---

# E1-05 — Authoritative Date Navigation

## Keep calendar authority separate from device-local presentation

Authoritative Today must come from the confirmed application calendar rather than being independently inferred by each client.

Before confirmation, device-local calendar state may be used only as an explicitly provisional browsing context.

## Treat calendar dates as date-only values

Previous and Next navigation must use calendar-date arithmetic rather than adding or subtracting elapsed hours.

This avoids skipped or duplicated dates across:

- daylight-saving transitions;
- leap days;
- month and year boundaries;
- historical regional offset changes.

## Preserve the selected date when calendar context changes

A time-zone change or midnight rollover may reclassify the active date, but must not silently navigate the user elsewhere.

Recalculate:

- Today;
- past, present, or future classification;
- navigation availability;
- mutation eligibility.

Do not replace the selected date.

## Prevent cross-date stale-content leakage

Date-dependent query and view state must be keyed by the selected date.

When navigation changes the date:

- retire the previous date’s rendered content immediately;
- show the new date’s loading, failure, or success state;
- never display one date’s entries, totals, or target progress beneath another date heading.

Same-date refresh retention is a separate behavior and must not be generalized across date changes.

## Prefer authoritative calendar data over duplicated client logic

When the backend already owns a calendar fact such as authoritative Today, expose and consume that fact rather than independently reproducing the calculation on each client.

Client-side date utilities should handle date-only navigation and provisional presentation, not redefine server authority.

---

# E1-07 — Independent Read States and Confirmed Mutation Projection

## Model presentation states explicitly

Complex query presentation should use discriminated state models rather than
multiple interacting booleans.

Distinguish at least:

- initial loading;
- initial failure;
- empty authoritative data;
- success;
- same-date refreshing;
- refresh failure with retained stale data;
- unavailable or unknown dependent state.

## Keep related sections operationally independent

Entries, totals, and target progress may share presentation context, but should
retain separate caches, refreshes, failures, and retries.

A failure in one section must not hide or invalidate confirmed content in
another section.

## Do not present unknown state as zero

Unavailable entry consumption is not equivalent to authoritative zero intake.

When source data is unknown:

- suppress zero totals;
- suppress successful 0% target progress;
- show an explicit unavailable state;
- preserve legitimate zero values only when authoritative data loaded
  successfully.

## Separate mutation confirmation from read refresh

An authoritative mutation result remains confirmed even when later reads fail.

After confirmation:

- project the returned mutation result immediately;
- refresh affected sections independently;
- retain the confirmed projection on refresh failure;
- mark surrounding data stale rather than reverting the mutation.

## Retain stale data only within the same date key

Same-date refresh may retain visible data with a clear refreshing or stale
indicator.

Cross-date navigation must retire all prior-date section data immediately.

---

# E1-08 — Core Add Food Vertical Slice

## Qualify workflow identity across real navigation boundaries

Screen-level tests are insufficient when correctness depends on state surviving
multiple route transitions.

For multi-screen workflows, add an integration test using the real navigation
coordinator and actual screens responsible for:

- originating context;
- discovery;
- confirmation;
- cancellation;
- successful return;
- confirmed mutation projection.

## Preserve workflow identity explicitly

The originating date, meal context, acquisition path, browse state, and scroll
position must travel as typed workflow state.

Do not reconstruct them from the currently visible screen or current Today.

## Converge acquisition paths on one confirmation flow

General Add Food, meal-scoped Add Food, and later discovery sources should all
route into the same Log Food confirmation contract.

Avoid source-specific logging forms.

## Treat cancellation as workflow navigation, not workflow destruction

Cancelling confirmation should return to the discovery state that launched it.

Cancelling discovery should return to the originating Daily Log.

Preserve in-process state where the accepted contract requires it.

## Revalidate immutable origin context before commit

The originating date remains fixed throughout the flow, but its eligibility
must be checked against the latest authoritative calendar before mutation.

If it becomes invalid:

- block the mutation;
- retain the original date;
- never substitute Today or another date.

## Keep confirmed mutation results authoritative across read failures

Once creation is confirmed:

- project the returned entry immediately;
- refresh entries, totals, and targets independently;
- retain the confirmed entry if any refresh fails;
- represent surrounding data as stale rather than representing the save as
  uncertain.

---

# E1-09 — Unified Search and USDA Import Handoff

## Distinguish independent data sources from independent user modes

Multiple search sources may retain separate:

- queries at the data-access layer;
- caches;
- loading states;
- failures;
- refreshes;
- retries.

That does not imply separate user-facing modes.

When the product defines one search query with grouped results, both sources
must consume that same normalized query and appear together.

## Derive browse versus search state from the query contract

When empty query means browse and non-empty query means search:

- do not add a separate mode selector;
- replace browse sections when the query becomes non-empty;
- restore browse sections when the query is cleared;
- retain separate browse and search scroll contexts where required.

## Keep source failures isolated

An unavailable external catalog must not disable local discovery.

Saved Foods and USDA should remain independently understandable and retryable
even though they share one user query.

## Preserve explicit acquisition boundaries

USDA selection remains a sequence of distinct authoritative operations:

1. Preview the external record.
2. Explicitly import or reuse a reusable Food.
3. Open shared Log Food confirmation.
4. Create a Daily Log only after confirmation.

Do not combine import and logging into one mutation.

## Preserve reusable resources after confirmation cancellation

Once a Food has been authoritatively imported, cancelling Log Food
confirmation must not delete or roll back that reusable Food.

The catalog mutation and Daily Log mutation have separate transaction and
lifecycle boundaries.

## Validate lower-precedence prompts against authoritative artifacts

Implementation prompts can contain mistaken interaction terminology or
sequencing.

Before implementation:

- compare the prompt with the PRD, architecture review, and assigned issue;
- follow the declared precedence order;
- report any discrepancy rather than silently implementing the prompt’s
  conflicting design.

---

# E1-10 — Custom Food and Scan Label Acquisition Handoffs

## Extend existing acquisition workflows rather than duplicating them

When an established creation workflow already owns validation, persistence, and
error behavior, a new product surface should add only the routing and return
context required to reuse it.

Do not create Daily Log-specific variants of:

- Custom Food creation;
- OCR capture;
- OCR parsing;
- nutrition confirmation;
- Food persistence.

## Keep resource creation separate from Log creation

Custom Food and OCR confirmation create reusable Food resources.

Daily Log creation remains a separate operation requiring the shared Log Food
confirmation.

Consequently:

- successful acquisition must not create a Log automatically;
- cancelling Log confirmation must leave the Food saved;
- acquisition failure must never create a partial Log;
- the two operations retain separate transaction and lifecycle boundaries.

## Carry workflow context through reused screens

Existing screens may be reused while receiving a Daily Log-aware return route.

The navigation coordinator must preserve:

- originating date;
- meal context;
- discovery query and mode;
- scroll position;
- authoritative calendar context.

The reused acquisition screen should not become responsible for reconstructing
that context.

## Enforce unsupported platform routes at the navigation boundary

Platform-specific actions must be hidden on unsupported clients, and the
navigation coordinator must not expose a normal route into unsupported
behavior.

For Scan Label:

- iOS exposes and qualifies the complete handoff;
- Android omits the action and cannot enter the Daily Log OCR route;
- shared non-OCR Add Food behavior remains equivalent across platforms.

## Dependencies must be checked independently of issue numbering

Issue numbers do not necessarily define executable order.

Before starting an issue:

- inspect its explicit Dependencies section;
- verify every prerequisite is complete or determine whether the work can be
  safely staged without anticipating the dependency;
- do not infer sequence solely from E1-09, E1-10, E1-11 numbering.

---

# E1-11 — Shared Confirmation and Commit-Time Source Authority

## Client-side review is not an authority boundary

A client fingerprint or final refresh can improve responsiveness, but it cannot prove that the reviewed source remained unchanged until commit.

When a mutation depends on reviewed source state:

- send a server-verifiable authority version or token;
- validate it inside the authoritative transaction;
- reject stale authority before creating domain state.

## Bind confirmation to the exact source generation reviewed

The reviewed authority must distinguish all nutrition-affecting dimensions needed for correctness, including:

- mutable Food generation;
- active Recipe publication revision;
- selected serving or immutable amount identity;
- source availability.

Never silently substitute a newer source, serving, amount, or revision.

## Preserve replay before revalidating changed source authority

An identical retry of an already-confirmed request must return the original authoritative result even if the source changed later.

Replay receipt resolution must occur according to the established lock and transaction discipline before stale source validation can invalidate the retry.

## Qualify source mutation races on PostgreSQL

Commit-time source authority depends on real row-lock behavior.

Add PostgreSQL contention tests for both serial orders:

- Log creation wins first;
- source mutation or republication wins first.

Require the tests to execute with zero skips before claiming qualification.

## Preserve the established lock order across projections and owners

Recipe-backed logging may involve both a compatibility Food projection and its owning Recipe.

Stabilize them in the established order:

1. lock the Food projection;
2. lock the Recipe;
3. resolve and validate the active publication revision;
4. create snapshots atomically.

Do not read one generation of the projection while validating another Recipe revision.

## Separate reusable resource lifecycle from confirmation state

USDA imports, Custom Foods, and OCR-created Foods remain reusable resources even when Log confirmation is cancelled.

The shared confirmation owns only the Daily Log mutation and its transient draft state.

---

# E1-12 — Recent Entries and Safe Repeat

## Repeat copies historical intent, not historical authority

A historical Daily Log may provide reusable intent such as:

- source Food;
- quantity;
- meal;
- note reference;
- prior amount choice.

The new entry must still resolve current authoritative Food or active Recipe
publication state.

Never recreate nutrition from historical snapshots.

## Keep eligibility independent from amount reusability

A historical entry may remain eligible for Repeat even when its prior serving
or amount cannot be mapped safely.

In that case:

- preserve the source and other valid context;
- leave the amount unselected;
- require explicit current selection;
- do not exclude the entry solely because the prior amount is stale.

## Make safe reuse an authoritative backend decision

The client should not infer whether a historical serving or amount remains
valid.

Return explicit metadata describing:

- current source authority;
- current loggability;
- exact, equivalent, ambiguous, or unavailable reuse;
- the current reusable amount identity when one exists.

The mobile client should only prefill amounts the backend has declared safe.

## Do not infer semantic equivalence from gram weight alone

Equal gram weight does not prove serving equivalence.

For mutable Food servings, safe equivalence requires complete authoritative
semantics such as:

- normalized quantity;
- normalized unit;
- gram weight.

If deleted historical serving semantics are unavailable:

- do not parse labels;
- do not reconstruct from snapshots;
- do not use gram weight heuristics;
- require explicit reselection.

## Preserve stronger immutable Recipe mapping

Recipe publication amount definitions retain immutable semantic metadata.

They may be mapped across revisions only when the complete semantic contract is
unambiguous, including mode, quantity, unit, and gram equivalent.

Do not weaken this mapping merely to align it with mutable Food fallback
behavior.

## Treat note reuse as an explicit user action

Historical notes are reference context, not automatic defaults.

Repeat should:

- start with a blank note;
- expose Copy notes only for compliant content;
- preserve multiline and Unicode content exactly when copied;
- never truncate overlength legacy notes;
- treat whitespace-only notes as absent.

## Create a genuinely new Log

Repeat must use the ordinary create flow with new:

- Daily Log identity;
- timestamps;
- client request identity;
- mutation receipt;
- source authority;
- nutrition snapshots.

Historical entries remain immutable discovery records.

---

# E1-13 — Editing Current Authority While Preserving Historical Integrity

## Editing replaces authority, not history

A Daily Log edit does not replay historical nutrition.

Instead:

- preserve the Daily Log identity;
- resolve the current authoritative source;
- generate new nutrition snapshots;
- replace the previous snapshot set atomically.

Historical nutrition survives through immutable snapshot history, not by retaining obsolete authority on the edited Log.

## Provenance must always match generated nutrition

Whenever nutrition is regenerated, every authority reference stored on the Log must describe the authority that produced those snapshots.

Never allow:

- current snapshots;
- historical Recipe revision IDs;
- historical amount-definition IDs;

to coexist on the same edited entry.

Snapshot provenance and snapshot content are one atomic unit.

## Metadata edits and nutrition edits have different authority requirements

Metadata-only edits (meal, note, valid date) should not require an available nutrition source.

Nutrition-affecting edits always require:

- current source availability;
- current authority validation;
- current amount validation.

Separating these paths improves resilience without weakening correctness.

## Shared confirmation should unify Add, Repeat, and Edit

Once a confirmation workflow exists, every mutation surface should reuse it.

The confirmation should own:

- authority validation;
- replay safety;
- calendar validation;
- source review;
- amount selection.

Business workflows should differ only in how they initialize that confirmation state.

## Update provenance and snapshots atomically

Whenever replacing nutrition snapshots:

- replace snapshots;
- update provenance references;
- update compatible serving references;
- complete replay receipt;

inside one transaction.

Rollback must restore the previous state completely.

## Preserve identity while replacing generations

Editing creates a new authoritative nutrition generation without creating a new Daily Log.

Stable identity and changing authority are compatible provided that:

- snapshot generations are replaced atomically;
- provenance stays synchronized;
- immutable publication rows themselves are never modified.

---

# E1-14 — Permanent Deletion and Authoritative Reconciliation

## Destructive confirmation should explain domain consequences

A deletion prompt should identify what will be removed and what will remain.

For Daily Log deletion, distinguish:

- the selected Daily Log entry;
- its stored nutrition snapshots;
- reusable Foods;
- Recipes and immutable publication revisions;
- USDA imports and catalog data.

Generic confirmation language is insufficient when users need to understand the
scope of permanent removal.

## Never infer an uncertain deletion from local presentation

A transport failure does not prove whether deletion committed.

During uncertainty:

- retain the exact client request identity;
- do not optimistically remove the entry;
- reconcile against authoritative mutation status;
- project removal only after confirmed success;
- offer the same reviewed retry only after confirmed non-commit.

## Confirmed deletion remains authoritative across read failures

After the server confirms deletion:

- remove the entry from the visible date immediately;
- refresh entries, totals, and target progress independently;
- retain the deletion if any refresh fails;
- mark surrounding data stale rather than restoring the entry.

A failed read does not reverse a confirmed mutation.

## Preserve replay and stale preconditions under the row lock

Deletion must serialize with edits and competing deletes.

Under the owned Daily Log row lock:

- recheck an identical replay receipt;
- validate `expected_updated_at`;
- reserve the receipt;
- delete snapshots and the entry atomically;
- complete the receipt in the same transaction.

Competing stale operations must return the accepted stable conflict rather than
a generic not-found result.

## Keep Log deletion separate from source-resource lifecycle

Deleting a historical Log must not delete or mutate:

- its reusable Food;
- its Recipe;
- immutable Recipe publications;
- OCR provenance;
- unrelated entries.

The Log and its entry-local snapshots are one lifecycle boundary. Source
resources have their own independent lifecycle.

## Do not introduce recovery semantics accidentally

Permanent deletion in this Epic has:

- no Undo;
- no recycle bin;
- no soft-delete interval;
- no tombstone restoration.

Durable recovery of an uncertain submitted intent is a separate concern from
recovering an authoritatively deleted record.

---

# E1-15 — Legacy Future-Entry Cleanup

## Historical cleanup must not weaken current invariants

Cleanup exists to resolve data created before a newer invariant was established.

It must not reopen the invalid behavior for normal use.

For future-dated Daily Logs:

- ordinary future views remain browse-only;
- new future entries remain prohibited;
- only existing legacy rows appear in the cleanup surface;
- resolving the last legacy row removes the exceptional surface naturally.

## Build cleanup as a restricted capability

Reusing an existing mutation does not require exposing its entire general-purpose UI.

When cleanup permits only a date move:

- pass an explicit typed workflow mode;
- structurally remove unrelated editing controls;
- submit only the allowed field and required preconditions;
- retain backend validation as defense in depth.

Do not present invalid actions and rely on server rejection as the primary product experience.

## Preserve domain state during date-only movement

Moving an entry between calendar dates changes only ownership by day.

A date-only move must preserve:

- Daily Log identity;
- created timestamp;
- quantity and amount;
- meal and note;
- nutrition snapshots;
- Food and Recipe provenance.

No current nutrition authority is required when nutrition is not being recalculated.

## Keep unavailable sources manageable

A deleted or inactive source may prevent nutrition editing, but it must not prevent cleanup operations that do not require source resolution.

Legacy entries with unavailable sources should still support:

- read-only identification;
- movement to a valid date;
- permanent deletion.

## Reuse qualified mutations rather than creating cleanup mutations

Cleanup should compose existing authoritative operations:

- E1-13 date-only replay-safe update;
- E1-14 replay-safe permanent deletion.

Do not add cleanup-specific persistence, transaction semantics, or duplicate mutation endpoints unless the existing contracts are genuinely insufficient.

## Make exceptional UI disappear when the exception is resolved

Cleanup state should be derived from remaining legacy data rather than maintained separately.

After all affected entries are moved or deleted:

- the cleanup list becomes empty;
- ordinary future browsing remains;
- no cleanup flag or retained workflow state is needed.

---

