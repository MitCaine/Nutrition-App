# Project constitution

> **Document role: Current Guide.** This document defines the enduring purpose and engineering
> principles of Nutrition App. It should change only when the project's mission, intended scope,
> or foundational quality commitments change.

## Purpose

Nutrition App exists to help an individual understand and record nutrition without allowing later
edits, incomplete source data, or implementation shortcuts to make past records misleading. The
project should make everyday nutrition tracking understandable while preserving enough provenance
to explain how durable results were produced.

## Scope

The project supports personal nutrition organization and history: reusable food definitions,
composed meals, deliberate publication of reusable content, consumption records, label-assisted
data entry, nutrition comparison, and controlled import of external nutrition data.

The repository also supports the engineering and operational work required to preserve that data
safely as the application evolves. Operational machinery exists to protect the application and its
history; it is not the product's center.

## Non-goals

Nutrition App is not:

- a medical device, diagnostic system, or substitute for professional health advice;
- a public social network, shared household platform, or general multi-tenant nutrition service;
- an authority that silently invents missing nutrition facts or treats uncertainty as measured
  truth;
- a system that rewrites historical records merely because present-day definitions changed; or
- a generic deployment, database-migration, evidence, or infrastructure product.

New capabilities may extend the product, but they must not weaken these boundaries implicitly.

## Design philosophy

- **Historical truth over convenient recomputation.** Durable records should continue to mean what
  they meant when created.
- **Explicit uncertainty over false precision.** Missing, estimated, and measured-zero values are
  different facts.
- **Explicit authority over inferred success.** A command, cache, client, or external
  acknowledgement is not authoritative unless the owning boundary says it is.
- **Fail closed at trust boundaries.** Missing identity, ambiguous state, stale evidence, or
  incomplete qualification must not silently select a permissive path.
- **Bounded evidence over exhaustive retention.** Preserve what is needed for correctness,
  explanation, and audit while minimizing sensitive or unbounded material.
- **One canonical explanation.** Current state, invariants, architecture, decisions, operations,
  and history have distinct owners and should link rather than drift through copied prose.
- **Complexity must earn its place.** Add machinery only when it protects a demonstrated product,
  data-integrity, security, or operational need.

## Quality standards

Every change should be evaluated for:

- correctness of nutrition meaning and historical behavior;
- preservation of ownership, privacy, and trust boundaries;
- deterministic behavior under retry, failure, and concurrency where those conditions apply;
- explicit handling of uncertainty and invalid state;
- validation proportional to the claim being made;
- maintainability by an engineer who did not participate in the original implementation; and
- documentation updates at the canonical knowledge boundary affected by the change.

Passing a narrow happy-path test is not sufficient evidence for a broader claim. Performance and
convenience may improve a correct design; they do not waive correctness or authority.

## Intended deployment model

The intended deployment is personally controlled, private/internal, and single-user. Credentials,
transport, storage, and operational authority must be explicit and appropriate to that boundary.

A public multi-user or broadly shared service would be a different trust and product model. It
requires an explicit constitutional decision, dedicated identity and isolation architecture, and
new qualification; it must not emerge from relaxing private-deployment safeguards.

## Engineering priorities

When priorities compete, prefer:

1. preservation of truthful historical data;
2. clear ownership and authority boundaries;
3. safe, testable evolution of durable state;
4. understandable user behavior and recoverable failure;
5. maintainability, discoverability, and learning value; then
6. performance and operational convenience after correctness is established.

These priorities guide tradeoffs; the [Project Invariants](invariants.md) translate them into
technical truths, and the [Architecture Decision Index](../architecture/decisions.md) records the
accepted structural choices.

## Governance

Release status, roadmap items, migration heads, provider choices, and implementation technologies
do not belong in this Constitution. Record those in [Current State](current-state.md), current
architecture or operations guides, and historical records.

Amend this document only through deliberate review of the affected purpose, scope, non-goal, or
principle. Ordinary implementation changes should conform to it rather than edit it.
