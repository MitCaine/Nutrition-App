# Project onboarding

> **Document role: Current Guide.** This page defines the minimum useful context for future
> engineers, implementation agents, and architecture reviewers.

## Before any implementation

1. Run the start step in the mandatory
   [Repository Session Contract](../operations/session-contract.md#repository-session-contract).
2. Read the [Project Constitution](constitution.md) for enduring scope and priorities.
3. Read [Current State](current-state.md) for what is true now.
4. Read [Project Invariants](invariants.md) for technical truths the change must preserve.
5. Locate the owning code and validation in the [Development Guide](development-guide.md).
6. Load only the affected feature, architecture, or operations guide from the
   [Documentation Index](../README.md).

This is the default context budget. Do not load phase histories, release evidence, or every feature
guide before an ordinary change.

## Task routing

| Task | Add to the minimum context |
| --- | --- |
| Food, serving, USDA, search, or Targets | [Foods and Nutrition](../features/foods-and-nutrition.md) |
| Recipe publication, revisions, projections, or Daily Logs | [Recipes and Nutrition History](../features/recipes-and-logging.md) |
| OCR, confirmation, mobile search, caching, or offline behavior | [OCR, Search, and Offline Behavior](../features/ocr-search-and-offline.md) |
| Cross-layer API, persistence, authentication, or runtime change | [Architecture Overview](../architecture/overview.md) and [Decision Index](../architecture/decisions.md) |
| Migration, role, qualification, release, recovery, or control-plane work | [Operations Index](../operations/README.md) |
| Terminology lookup | [Glossary](../reference/glossary.md) |
| Decision provenance or learning from project evolution | [Historical Knowledge Index](../historical/README.md) |

## Architecture review path

An architecture reviewer should read the Constitution, Current State, Project Invariants, the
Architecture Overview, the relevant entries in the Decision Index, and the affected feature or
operations guide. Review against the [change checklist](development-guide.md#change-checklist).
Load historical records only when verifying why or when a boundary was introduced.

## Human orientation path

An experienced engineer can become productive by reading, in order:

1. the [Project Constitution](constitution.md);
2. [Current State](current-state.md);
3. [Project Invariants](invariants.md);
4. the [Architecture Overview](../architecture/overview.md);
5. the relevant sections of the [Repository Tour](repository-tour.md); and
6. the owning section of the [Development Guide](development-guide.md).

Feature and operations guides are task-specific follow-up reading, not a prerequisite bundle.

## Working rules

- Treat implementation as authoritative and report documentation drift.
- Preserve immutable history, ownership, unknown-versus-zero semantics, and exact replay behavior.
- Use PostgreSQL for claims about migrations, locks, roles, grants, or concurrency.
- Do not infer authority from a command return when an authoritative observation is required.
- Keep historical records point-in-time; update current guides and link to the record.
- Finish with the validation selected by the Testing Guide and the session-end contract.

## What stays outside ordinary context

Historical stage documents, production-hardening chronology, RC1 evidence, manual QA worksheets,
and retained qualification manifests remain discoverable under `historical/` or evidence
directories. They are valuable for learning, audit, and provenance, but loading them by default
increases context without improving most implementation decisions.
