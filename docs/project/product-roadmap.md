# Current product roadmap

> **Document role: Current Guide.** This document owns the canonical product Epic numbering used for current and future planning. Historical Version 1.1 records preserve their original numbering and should be read as point-in-time planning evidence.

Nutrition App now uses the following Epic sequence:

| Epic | Product area | Status | Provenance |
| --- | --- | --- | --- |
| Epic 1 | Daily Logging Flow | Complete | Implemented and qualified as Version 1.1 Epic 1. |
| Epic 2 | Local-First SQLite Runtime | Complete | Inserted as the technical/local-first Epic and implemented through the completed Epic 2 program. |
| Epic 3 | Nutrition Label Capture Confidence | Complete | Originally planned as product Epic 4; later absorbed and completed through Epic 2 OCR work and post-Epic-2 OCR/camera issues and physical-device qualification. |
| Epic 4 | Nutrition History and Trends | Pre-Grill planning | Originally planned as product Epic 2. Trustworthy immutable history exists; current research is defining the separate multi-day trends/history product surface before Grill/PRD work. |
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

The remaining Epic outcome is a user-facing multi-day interpretation layer, including useful recent time windows, trend views, completeness/unknown indicators, target/reference context, and navigation from a period result back to contributing Daily Log dates. It must continue to derive historical values only from immutable Daily Log snapshots and must not silently treat missing or partially logged periods as zero intake.

Pre-Grill research, competitor patterns, repository reuse opportunities, working product recommendations, architecture constraints, and unresolved choices are recorded in [Epic 4 planning](version-1.2/epic-4/planning.md). That planning record does not authorize implementation. Epic 4 still requires resolved Grill decisions, a Feature PRD, architecture review, implementation backlog, and GitHub implementation issues before code changes begin.

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

An Epic being listed here does not itself authorize implementation. Epic 4 is currently in pre-Grill research; Epic 5 remains planned and requires re-scope. Both still require the normal Grill, PRD, architecture review, implementation backlog, and GitHub issue workflow before code changes begin.
