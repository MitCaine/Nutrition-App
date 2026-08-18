# Version 1.2 Epic 4 — Nutrition History and Trends

> **Document role: Versioned Planning Index.** This directory contains the frozen Epic 4 planning package. It does not describe implemented behavior until the backlog has been delivered and qualified.

## Planning status

Epic 4 research and Grill are complete. The Feature PRD and architecture/data contracts are approved, and the implementation backlog has been decomposed.

Implementation remains **not authorized** until the finalized planning package passes repository documentation validation and project audit. GitHub implementation issues should be created only after that gate passes.

## Canonical Epic 4 planning artifacts

1. [Planning / research record](planning.md) — competitor research, repository inventory, and pre-Grill working recommendations.
2. [Grill decision record](accepted-decisions.md) — accepted product and architecture-facing decisions from the completed Grill.
3. [Feature PRD](feature-prd.md) — normative Epic 4 product scope and acceptance contract.
4. [Data and Runtime Contracts](data-contracts.md) — normative Complete-state, range-read, exact-value, cache, and authority semantics.
5. [Architecture Review](architecture-review.md) — architecture assessment and gate decisions.
6. [Implementation Backlog](implementation-backlog.md) — bounded E4-01 through E4-17 task decomposition.

## Scope freeze

The PRD is the product authority for implementation. The data contracts own the technical semantics that local and remote implementations must preserve. The backlog decomposes those accepted contracts; it must not silently expand them.

New product ideas encountered during implementation belong in [Future Product and Scalability Options](../../future-product-and-scale.md) unless they are required to satisfy an accepted Epic 4 invariant or acceptance criterion.

## Authorization sequence

The remaining pre-implementation sequence is:

1. validate Markdown/link/reachability contracts with `python scripts/validate-docs.py`;
2. pass the repository pre-commit project audit through `scripts/project-audit.sh pre-commit` or the equivalent CI/session-contract run;
3. reconcile any planning-document drift found by those gates; and
4. create GitHub implementation issues from the frozen backlog.

No application code should be changed before this sequence is complete.
