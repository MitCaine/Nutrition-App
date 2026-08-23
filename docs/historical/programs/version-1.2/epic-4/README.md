# Version 1.2 Epic 4 — Nutrition History and Trends

> **Document role: Versioned Planning and Delivery Index.** This directory contains the frozen Epic 4 planning package and links to its active GitHub delivery backlog. It does not describe implemented behavior until the backlog has been delivered and qualified.

## Planning and delivery status

Epic 4 research and Grill are complete. The Feature PRD and architecture/data contracts are approved, and the implementation backlog has been decomposed.

The finalized package passed repository documentation validation, `scripts/project-audit.sh pre-commit`, and the repository issue-creator dry run at commit `df66941`. GitHub delivery was then created successfully:

- parent Epic: [#113 — Version 1.2 Epic 4 — GitHub Implementation Backlog](https://github.com/MitCaine/Nutrition-App/issues/113);
- child implementation issues: E4-01 through E4-17, [#114](https://github.com/MitCaine/Nutrition-App/issues/114) through [#130](https://github.com/MitCaine/Nutrition-App/issues/130); and
- six GitHub milestones matching the backlog milestone headings.

Epic 4 implementation is therefore **authorized**. No Epic 4 application implementation has landed yet. Delivery must follow the approved GitHub issue boundaries and dependencies.

## Canonical Epic 4 planning artifacts

1. [Planning / research record](planning.md) — competitor research, repository inventory, and pre-Grill working recommendations.
2. [Grill decision record](accepted-decisions.md) — accepted product and architecture-facing decisions from the completed Grill.
3. [Feature PRD](feature-prd.md) — normative Epic 4 product scope and acceptance contract.
4. [Data and Runtime Contracts](data-contracts.md) — normative Complete-state, range-read, exact-value, cache, and authority semantics.
5. [Architecture Review](architecture-review.md) — architecture assessment and gate decisions.
6. [Implementation Backlog](implementation-backlog.md) — bounded E4-01 through E4-17 task decomposition and source for GitHub delivery.

## Scope freeze

The PRD is the product authority for implementation. The data contracts own the technical semantics that local and remote implementations must preserve. The backlog decomposes those accepted contracts; it must not silently expand them.

New product ideas encountered during implementation belong in [Future Product and Scalability Options](../../../../project/future-product-and-scale.md) unless they are required to satisfy an accepted Epic 4 invariant or acceptance criterion.

## Delivery sequence

Implementation now proceeds through [GitHub Epic #113](https://github.com/MitCaine/Nutrition-App/issues/113). Follow the dependencies and parallelism rules in the [Implementation Backlog](implementation-backlog.md):

1. establish E4-01 Complete persistence;
2. proceed through the dependent Complete, History-range/projection, Daily Log/Daily Nutrition, History UI, Food-authoring, durability, and qualification issues;
3. run issue-specific tests and repository gates for every implementation change; and
4. close Epic 4 only through E4-16 qualification and E4-17 current-documentation reconciliation.

Current feature and architecture guides remain authoritative for what is implemented today. This versioned package owns the approved future scope until qualified implementation is promoted into those current guides.
