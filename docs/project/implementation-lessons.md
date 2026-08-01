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

## Qualify locking behavior on the database that implements the lock

Concurrency behavior depending on row locks cannot be qualified through SQLite or ordinary sequential tests.

When correctness depends on PostgreSQL locking:

- add targeted PostgreSQL contention tests;
- verify the tests execute rather than skip;
- treat unavailable infrastructure as incomplete qualification, not a passing result.

## Check mutable preconditions under the serializing lock

Any precondition protecting a mutable generation must be evaluated after acquiring the same lock that serializes the mutation.

This includes:

- stale-entry timestamps;
- expected revisions;
- replay receipts that may have completed while waiting.

## Recheck replay state after lock waits

A concurrent identical request may complete while another request waits for the row lock.

After acquiring the lock:

- re-read the replay receipt;
- return the prior authoritative outcome when it exists;
- do not attempt the mutation again.

## Preserve stable domain conflicts under contention

Contention must not degrade a known domain conflict into a generic not-found or infrastructure error.

The losing operation must return the accepted stable conflict, such as `stale_log_entry`, when its precondition is no longer valid.