# Historical knowledge index

> **Document role: Historical Record.** This index preserves engineering chronology and learning
> paths without making historical material part of ordinary implementation context.

Historical documents retain their point-in-time assertions. They explain how the repository
arrived at its current architecture, but [Current State](../project/current-state.md), active guides,
implementation, and migrations define present behavior.

## Release and evidence records

- [Version 2.0 Release Record](releases/version-2.0-release.md)
- [Version 1.0 PostgreSQL Release Qualification](releases/version-1.0-release-qualification.md)
- [Version 1.0 Release Gate](releases/production-hardening-phase5c4.9.md)
- [Release Candidate 1 QA](releases/rc1-qa.md)
- [Manual QA Evidence](evidence/qa/README.md)
- Captured Phase 5C performance evidence remains beside the backend operator implementation in
  `apps/backend/evidence/phase5c/`.

## Completed version programs

- [Version 1.1 Product Roadmap](programs/version-1.1/version-1.1-roadmap.md)
- [Version 1.2 Epic 4 Planning and Delivery Index](programs/version-1.2/epic-4/README.md)
- [Implementation Lessons](engineering/implementation-lessons.md)

Additional retained implementation records:

- [E1-17 Accessibility Remediation Stage 1](programs/version-1.1/epic-1/accessibility-remediation-stage-1.md)
- [E1-17 Accessibility Remediation Stage 2](programs/version-1.1/epic-1/accessibility-remediation-stage-2.md)
- [Issue #108 Sticky Navigation Header Inventory](programs/version-1.1/issue-108-sticky-header-inventory.md)

These packages retain their original point-in-time assertions. Current feature,
architecture, project, and operations guides own present behavior.

## Product implementation stages

- [Implementation Stages](stages/implementation-stages.md)
- [Stage 5 OCR](stages/stage5-ocr.md)
- [Stage 6 Parser](stages/stage6-parser.md)
- [Stage 6 Confirmation](stages/stage6-confirmation.md)
- [Stage 7 Targets](stages/stage7-targets.md)
- [Stage 7 Food Discovery](stages/stage7-food-discovery.md)
- [Stage 7 Roadmap Closeout](stages/stage7-roadmap-closeout.md)

## Production-hardening chronology

- [Phase 1](production-hardening/production-hardening-phase1.md)
- [Phase 5A](production-hardening/production-hardening-phase5a.md)
- [Phase 5B](production-hardening/production-hardening-phase5b.md)
- [Phase 5C1](production-hardening/production-hardening-phase5c1.md)
- [Phase 5C2](production-hardening/production-hardening-phase5c2.md) and
  [5C2.2](production-hardening/production-hardening-phase5c2.2.md)
- [Phase 5C3a](production-hardening/production-hardening-phase5c3a.md) and
  [5C3b](production-hardening/production-hardening-phase5c3b.md)
- [Phase 5C4 design](production-hardening/production-hardening-phase5c4.md)
- [Phase 5C4.0 deployment decision](production-hardening/production-hardening-phase5c4.0.md)
- [Phase 5C4.2a role boundary](production-hardening/production-hardening-phase5c4.2a.md)
- [Phase 5C4.5 recovery validation](production-hardening/production-hardening-phase5c4.5.md)
- [Phase 5C4.6 activation authorization](production-hardening/production-hardening-phase5c4.6.md)
- [Phase 5C4.7a promotion authorization](production-hardening/production-hardening-phase5c4.7a.md)

Phase 5C4.7b and 5C4.8 remain active runbooks under the
[Operations Index](../operations/README.md); their phase lineage is retained in their headings and
links.

## Learning routes

- Immutable nutrition history: begin with [Project Invariants](../project/invariants.md), then use
  the Recipe/OCR stage records only for implementation chronology.
- Migration and data-safety evolution: follow Phase 5A through Phase 5C3a.
- Promotion and recovery safety: read the current
  [Control Plane Guide](../operations/control-plane.md), then follow Phase 5C4 records for provenance.
- Release evolution: compare RC1 evidence, Stage 7 closeout, and the Version 1.0 gate without
  treating their test counts or status language as current.
