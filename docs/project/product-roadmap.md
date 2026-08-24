# Current product roadmap

> **Document role: Current Guide.** This document owns the canonical product Epic numbering used for current and future planning. Historical Version 1.1 records preserve their original numbering and should be read as point-in-time planning evidence.

Nutrition App now uses the following Epic sequence:

| Epic | Product area | Status | Provenance |
| --- | --- | --- | --- |
| Epic 1 | Daily Logging Flow | Complete | Implemented and qualified as Version 1.1 Epic 1. |
| Epic 2 | Local-First SQLite Runtime | Complete | Inserted as the technical/local-first Epic and implemented through the completed Epic 2 program. |
| Epic 3 | Nutrition Label Capture Confidence | Complete | Originally planned as product Epic 4; later absorbed and completed through Epic 2 OCR work and post-Epic-2 OCR/camera issues and physical-device qualification. |
| Epic 4 | Nutrition History and Trends | Complete | Implemented through E4-01–E4-15 and qualified across local SQLite, physical PostgreSQL 16, shared projections, and the target iPhone by E4-16. |
| Epic 5 | Recipe Reuse and Discovery | Outcome complete; retired | Originally planned as product Epic 3. Its concrete reuse/discovery outcomes are now delivered through the existing Recipe architecture plus bounded issues #149 and #150, so no retroactive Epic delivery program is required. |

## Epic 3 — Nutrition Label Capture Confidence

Epic 3 is considered complete. It does not require another implementation backlog merely to reproduce the old roadmap structure.

The original product outcome was to make label-assisted Food creation dependable and understandable on supported physical iOS devices. The current implementation now includes:

- an app-owned native iOS camera path plus photo-library selection;
- non-rigid Nutrition Facts framing guidance;
- permission, cancellation, retake, and reselect recovery;
- best-effort pre-recognition image-quality inspection with conservative user warnings;
- on-device Apple Vision recognition;
- conservative parser recovery for representative OCR fragmentation and obvious character loss;
- structured confirmation that directs unresolved and unknown values through explicit user review;
- reviewed low-confidence values that are not rejected solely because OCR confidence was low;
- structured serving correction in confirmation;
- immutable bounded OCR correction provenance and idempotent confirmation;
- temporary-image cleanup with no durable image, image-path, full raw OCR text, or unbounded recognition-response retention; and
- physical-iPhone qualification of representative framing, skew, blur, exposure/glare, darkness, close-focus, retake/use-anyway, and surrounding-package-text cases.

Automatic ROI/cropping was evaluated conditionally during capture-quality work and was not shown by physical testing to provide enough remaining benefit to warrant a follow-up. Manual crop editing remains a future option rather than unfinished Epic 3 scope.

The following historical/post-program issues provide important completion evidence: #89, #93, #95, #98, #99, #100, #111, and #112, together with the completed Epic 2 OCR implementation and qualification work.

## Epic 4 — Nutrition History and Trends

Epic 4 is the current name for the product work originally described as Version 1.1 product Epic 2.

The delivered capability builds on immutable Daily Log nutrient snapshots, exact daily summaries, explicit unknown-versus-zero semantics, target/reference context, and stable date-scoped Daily Logs.

The implemented History surface provides explicit Complete-day/Logged-day denominator semantics, 7-day and 30-day calendar ranges ending yesterday, fixed macro overview charts, grouped Nutrition Details, focused nutrient History, current-reference context, and navigation from exact daily values back to the contributing Daily Log date. Historical values derive only from immutable Daily Log snapshots: missing dates remain gaps, explicit zero remains zero, and unknown-only evidence remains unavailable rather than becoming invented intake.

The frozen package is indexed in [Version 1.2 Epic 4](../historical/programs/version-1.2/epic-4/README.md). It retains the research record, completed Grill decisions, Feature PRD, architecture/data contracts, bounded implementation backlog, and delivery sequence as point-in-time planning and closure provenance.

The finalized package passed repository documentation validation, the pre-commit project audit, and the repository issue-creator dry run at commit `df66941`, then bounded delivery proceeded through E4-01–E4-17 ([#114](https://github.com/MitCaine/Nutrition-App/issues/114) through [#130](https://github.com/MitCaine/Nutrition-App/issues/130)). E4-16 supplied final automated and physical release evidence. Separate follow-ups #144, #147, and #148 cover documentation-validation hardening, Expo patch compatibility, and parallel-chart selected-date viewport alignment; none is unfinished Epic 4 acceptance scope.

## Epic 5 — Recipe Reuse and Discovery

Epic 5 is the current name for the product work originally described as Version 1.1 product Epic 3. Its original concrete outcomes are now outcome complete, and Epic 5 is retired as a planning unit rather than being reopened for a retroactive Grill/PRD/backlog cycle.

The delivered capability combines the pre-existing Recipe architecture with the final bounded product work:

- mutable Recipe authoring, nested Recipes, serving/yield authoring, guarded drafts, immutable publication/republication, and explicit `needs_republish` semantics;
- Draft, Published/current, and Update Needed lifecycle presentation plus Recipe-oriented discovery and recent-use reuse delivered through #149;
- direct `Log Recipe` through the established amount/serving logging flow, preserving one exact immutable publication revision;
- user-facing Recipe language that does not require understanding managed Food compatibility projections, while retaining those projections as internal architecture;
- independent editable Recipe duplication delivered through #150, with a new Recipe identity, unpublished state, collision-aware/idempotent creation semantics, and no copied publication or Daily Log history.

[#149](https://github.com/MitCaine/Nutrition-App/issues/149) and [#150](https://github.com/MitCaine/Nutrition-App/issues/150) are the bounded terminal delivery evidence for the remaining reuse/discovery and duplication outcomes. The historical Version 1.1 roadmap remains point-in-time provenance and is not rewritten to manufacture a retroactive Epic 5 delivery package.

Future Recipe ideas require newly scoped product decisions or issues on their own merits; they are not unfinished acceptance scope for this retired planning unit.

## Historical numbering map

The retained Version 1.1 product roadmap predates insertion of the Local-First SQLite Runtime Epic and used a different product order. Interpret its product headings as follows:

| Historical Version 1.1 product label | Current canonical label |
| --- | --- |
| Epic 1 — Daily Logging Flow | Epic 1 — Daily Logging Flow |
| Product Epic 2 — Nutrition History and Trends | Epic 4 — Nutrition History and Trends |
| Product Epic 3 — Recipe Reuse and Discovery | Epic 5 — Recipe Reuse and Discovery |
| Product Epic 4 — Nutrition Label Capture Confidence | Epic 3 — Nutrition Label Capture Confidence |

This remapping is intentional. It reflects the completed insertion of SQLite as Epic 2 and the decision to close the already-implemented Nutrition Label Capture Confidence work as Epic 3 rather than leaving it artificially behind still-unimplemented product Epics.

## Planning rule

Epic numbers in new issues, PRDs, architecture reviews, project boards, and conversation should use this current sequence. Historical records should not be rewritten to pretend this numbering existed when they were authored; where historical material is reused, translate through the mapping above.

An Epic being listed here does not itself authorize implementation. Epic 4 is complete because its approved package was delivered and qualified through the bounded GitHub backlog. Epic 5 is outcome complete and retired as a planning unit because its concrete historical outcomes are now delivered; new Recipe work requires newly scoped authority rather than reopening the retired Epic.
