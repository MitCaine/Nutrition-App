# Current product roadmap

> **Document role: Current Guide.** This document owns the canonical product Epic numbering used for current and future planning. Historical Version 1.1 records preserve their original numbering and should be read as point-in-time planning evidence.

Nutrition App now uses the following Epic sequence:

| Epic | Product area | Status | Provenance |
| --- | --- | --- | --- |
| Epic 1 | Daily Logging Flow | Complete | Implemented and qualified as Version 1.1 Epic 1. |
| Epic 2 | Local-First SQLite Runtime | Complete | Inserted as the technical/local-first Epic and implemented through the completed Epic 2 program. |
| Epic 3 | Nutrition Label Capture Confidence | Complete | Originally planned as product Epic 4; later absorbed and completed through Epic 2 OCR work and post-Epic-2 OCR/camera issues and physical-device qualification. |
| Epic 4 | Nutrition History and Trends | Planning package complete; validation gate pending | Originally planned as product Epic 2. Research/Grill, Feature PRD, architecture/data contracts, and implementation backlog are complete; implementation has not started. |
| Epic 5 | Recipe Reuse and Discovery | Planned; requires re-scope | Originally planned as product Epic 3. Considerable Recipe authoring, serving, publication, and navigation work already exists, but the remaining reuse/discovery outcome has not been completed as an Epic. |

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

The application already has the required trustworthy substrate: immutable Daily Log nutrient snapshots, exact daily summaries, explicit unknown-versus-zero semantics, target/reference context, and stable date-scoped Daily Logs. That substrate is not itself the History and Trends product feature.

The accepted Epic 4 outcome is a user-facing multi-day interpretation layer with explicit Complete-day/Logged-day denominator semantics, 7-day and 30-day calendar ranges, fixed macro overview charts, grouped additional nutrition detail, focused nutrient History, current-reference context, and navigation from a period result back to contributing Daily Log dates. It must continue to derive historical values only from immutable Daily Log snapshots and must not silently treat missing, unknown, or partially logged periods as zero intake.

The frozen planning package is indexed in [Version 1.2 Epic 4](version-1.2/epic-4/README.md). It contains the research record, completed Grill decisions, Feature PRD, architecture/data contracts, and bounded implementation backlog.

Epic 4 implementation has **not** started. Before GitHub implementation issues are created or application code changes begin, the finalized planning package must pass repository documentation validation and project audit. After those gates pass, implementation issues should be created from the frozen backlog rather than reopening product scope during delivery.

## Epic 5 — Recipe Reuse and Discovery

Epic 5 is the current name for the product work originally described as Version 1.1 product Epic 3.

Substantial prerequisite and adjacent work has already landed: Recipe authoring, nested Recipes, immutable publication/republication, `needs_republish`, serving/yield authoring, safe serving management, guarded drafts, fixed route headers, and Recipe-backed logging authority.

The original reuse/discovery outcome is therefore no longer a clean implementation plan and must be re-scoped before implementation. Remaining candidate product outcomes include coherent Recipe favorites/recent-use discovery, direct Recipe-context logging with explicit amount selection, Recipe duplication for independent variations, and user-facing lifecycle language that hides compatibility-projection mechanics without weakening publication semantics.

Epic 5 has not yet entered a new Grill/PRD/architecture/backlog cycle under the current numbering.

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

An Epic being listed here does not itself authorize implementation. Epic 4 now has a frozen planning package but remains blocked on repository validation/audit before issue creation or code work. Epic 5 remains planned and requires re-scope plus the normal Grill, PRD, architecture review, implementation backlog, and GitHub issue workflow before code changes begin.
