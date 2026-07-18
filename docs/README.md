# Documentation index

This documentation is organized by what you are trying to change, not by the order in which the
project was built. Ordinary application work and advanced production operations deliberately have
different reading paths.

## Choose a reading path

### I am returning to the project

1. Read the [Repository Tour](repository-tour.md).
2. Read [Why This Exists](why-this-exists.md) for the reasoning behind the invariants.
3. Read the [Architecture Guide](architecture.md) to map that reasoning to system boundaries.
4. Read the subsystem or domain guide for the area you plan to change.
5. Use the [Development Guide](development-guide.md) as a code-and-test index.
6. Use the [Architecture Decision Index](architecture-decisions.md) to refresh a specific decision.

### I am working on application features

You can ignore the production-hardening phase records and control-plane implementation unless your
change touches migrations, runtime credentials, write fencing, canary startup, or historical
database conversion.

- [Foods and Nutrition Domain](foods-and-nutrition.md): nutrients, servings, Foods, USDA, discovery,
  and Targets.
- [Recipes and Nutrition History](recipes-and-logging.md): Recipe authoring, publication revisions,
  compatibility projections, Daily Logs, and immutable snapshots.
- [OCR, Search, and Offline Behavior](ocr-search-and-offline.md): Apple Vision, parsing,
  confirmation provenance, unified search, caching, and network boundaries.
- [Why This Exists](why-this-exists.md): the reasoning behind the main invariants.
- [Architecture Decision Index](architecture-decisions.md): concise decision, rationale, and
  deeper-reading links.

### I am working on deployment or historical migration

1. Read the [Control Plane Guide](control-plane.md).
2. Follow its links to the relevant `production-hardening-*` design record.
3. Use the [Testing Guide](testing.md) before changing a migration, role, control routine, or
   evidence contract.

The control plane is optional reading for feature development. It is an operations subsystem, not
the center of the application domain.

## Guide map

| Guide | Question it answers |
| --- | --- |
| [Repository Tour](repository-tour.md) | Where do I start, and what can I ignore? |
| [Architecture Guide](architecture.md) | Which layer owns each responsibility? |
| [Foods and Nutrition Domain](foods-and-nutrition.md) | How do Foods, nutrients, servings, USDA, discovery, and Targets work? |
| [Recipes and Nutrition History](recipes-and-logging.md) | Why are Recipes published as revisions and Logs stored as snapshots? |
| [OCR, Search, and Offline Behavior](ocr-search-and-offline.md) | What runs on-device, on the backend, or only while online? |
| [Why This Exists](why-this-exists.md) | What problem is each architectural invariant solving? |
| [Architecture Decision Index](architecture-decisions.md) | I remember a decision—where is its rationale? |
| [Glossary](reference/glossary.md) | What does a project-specific term mean here? |
| [Development Guide](development-guide.md) | Which files, APIs, migrations, and tests should I touch? |
| [Testing Guide](testing.md) | Which suite proves which guarantee? |
| [Control Plane Guide](control-plane.md) | What is Phase 5, and when do I need to understand it? |

## Design and qualification records

The following documents preserve implementation history, exact contracts, or release evidence.
They are intentionally more detailed than the reader guides:

- [Implementation stages](stages.md) and [roadmap closeout](stage7-roadmap-closeout.md)
- [Release-candidate QA](rc1-release-qa.md)
- [Production Hardening Phase 1](production-hardening-phase1.md)
- [Phase 5A](production-hardening-phase5a.md), [Phase 5B](production-hardening-phase5b.md),
  [Phase 5C1](production-hardening-phase5c1.md),
  [Phase 5C2](production-hardening-phase5c2.md),
  [Phase 5C2.2](production-hardening-phase5c2.2.md),
  [Phase 5C3a](production-hardening-phase5c3a.md), and
  [Phase 5C3b](production-hardening-phase5c3b.md)
- [Phase 5C4 design](production-hardening-phase5c4.md),
  [deployment profile decision](production-hardening-phase5c4.0.md), and
  [PostgreSQL role boundary](production-hardening-phase5c4.2a.md)
- [OCR implementation](stage5-ocr.md), [confirmation](stage6-confirmation.md),
  [parser](stage6-parser.md), and [Food discovery](stage7-food-discovery.md)
- [Manual QA evidence](evidence/qa/README.md) and the captured Phase 5C performance manifests
  described by [Phase 5C3b](production-hardening-phase5c3b.md)

These records should not be rewritten into introductory guides: the guides explain the stable
architecture and link back when exact historical authority matters.

## Next reading

- Returning after a break: [Repository Tour](repository-tour.md)
- Understanding rationale: [Why This Exists](why-this-exists.md)
- Refreshing one decision or term: [Architecture Decision Index](architecture-decisions.md) or
  [Glossary](reference/glossary.md)
- Starting a change: [Development Guide](development-guide.md)

## See also

- [Project README](../README.md)
- [Architecture Guide](architecture.md)
- [Why This Exists](why-this-exists.md)
- [Glossary](reference/glossary.md)
