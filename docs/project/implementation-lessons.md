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

