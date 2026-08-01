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