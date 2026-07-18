# Production Hardening Phase 5C3b: conversion performance qualification

## Purpose and boundary

Phase 5C3b measures the existing correctness-first Phase 5C bridge, planner, converter, and
independent verifier on deterministic representative-volume PostgreSQL fixtures. It emits
`phase5c_performance_qualification_manifest_v1`. It does not optimize conversion, change plan v2,
change either attestation contract, change checkpoints, change qualification receipt v1, authorize
promotion, or perform cutover or recovery.

Correctness qualification and performance qualification answer different questions. Phase 5C3a
proves that one completed clone is internally correct. Phase 5C3b first requires that same
independent qualification and exact converter restart verification, then evaluates resource and
workload ceilings. Passing performance budgets cannot override a correctness failure.

The command is offline operator tooling, not an API route. Benchmark and instrumentation evidence
is external JSON; no performance table or instrumentation state is added to the application
database.

## Disposable-target admission

The operator must create a dedicated empty PostgreSQL database. The database name must begin with
`nutrition_phase5c_benchmark_`, use the bounded benchmark naming convention, and be repeated exactly
with `--confirm-disposable-database`. The command refuses:

- a non-PostgreSQL target;
- a name or confirmation mismatch;
- any existing application table or non-public user schema; or
- another active session in the target database.

The harness verifies but does not create, reset, drop, or reuse the database. A failed or interrupted
fixture creation requires a fresh target. This avoids turning benchmark code into destructive
database administration. `NUTRITION_DEPLOYMENT_MODE=test` and the canonical
`NUTRITION_DATABASE_URL` are both explicit; Alembic and the benchmark runtime must resolve the same
URL.

## Deterministic fixture tiers

Fixture generator `phase5c_performance_fixture_generator_v1` uses UUIDv5 identities, a fixed UTC
clock, exact Decimals, stable table/row ordering, and one explicit 63-bit seed. The manifest binds
the blueprint digest, streamed logical-data digest, and exact source table counts. A reduced test
fixture is contractually named `TEST_REDUCED` and cannot be emitted as T0.

| Tier | Recipes | Foods | Daily Logs | OCR scans | Convert / quarantine / block | Ingredients p50 / p95 | Graph depth / breadth |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| T0 | 50 | 250 | 5,000 | 1,000 | 45 / 4 / 1 | 4 / 10 | 3 / 2 |
| T1 | 1,000 | 3,000 | 100,000 | 25,000 | 900 / 80 / 20 | 8 / 25 | 5 / 3 |
| T2 | 10,000 | 25,000 | 1,000,000 | 250,000 | 9,000 / 800 / 200 | 10 / 50 | 8 / 5 |
| T3 | 50,000 | 100,000 | 5,000,000 | 1,000,000 | 45,000 / 4,000 / 1,000 | 10 / 50 | 8 / 5 |

Nested dependencies are a deterministic convert-only acyclic graph. Quarantine and block subjects
remain outside parent conversion graphs so graph propagation cannot change the declared
distribution. T0 uses up to four serving rows per Food; T1 uses six; T2/T3 use eight. The current
catalog has 16 valid nutrient identities, so the generator records 16 rows per Food rather than
inventing duplicate or unsupported identities to fill the published 25/40/50 ceilings.

T1 through T3 require `--opt-in-large-tier` and never run through ordinary pytest. The full T0
PostgreSQL qualification test requires `NUTRITION_RUN_PHASE5C_T0=1`. Ordinary tests use pure deterministic
fixtures and synthetic measurements; they do not assert wall-clock timing.

## Measurements and classification

The following stages are separate in the manifest: fixture creation, inventory, marker creation,
bridge, migration to planning head, planning, migration to execution head, execution-attestation
creation, conversion, execution-receipt generation, independent qualification, and restart
verification.

Temporary SQLAlchemy event listeners record aggregate query counts, transaction duration,
operation-lock wait/hold duration, and logical relation-read categories. A no-op observer brackets
converter subjects and retries so full-source reads can be distinguished from run-level reads. The
observer does not change conversion transactions, checkpoints, retries, or receipts and never
retains subject identities. Listeners are removed in `finally`.

“Full scan” in the manifest means an unbounded logical relation read visible to SQLAlchemy or the
known whole-table Recipe-marker Food projection predicate; it does not otherwise claim that
PostgreSQL selected a physical sequential-scan plan. The categories distinguish:

- fixed/run-level planning-source and archive/supporting-source reads;
- full planning-source reads inside a subject;
- bounded subject dependency queries;
- Daily Log relation reads, including those repeated inside a subject; and
- OCR relation reads, including those repeated inside a subject.

The manifest also records stage wall and process CPU time, process peak RSS (or an explicit
unavailable method), per-stage RSS high-water growth, subject duration/query distributions,
bounded subject-dependency query count, operation-lock wait/hold distributions, retries, receipt
sizes, database size, PostgreSQL/Python/platform versions, CPU count, available-memory evidence,
selected cache mode, an operator-supplied bounded storage description, and an allowlist of relevant
PostgreSQL settings. Per-stage RSS growth reports increases in the process high-water mark while a
stage is active; zero is intentionally inconclusive when an earlier stage already established a
higher process peak.
It never stores SQL, SQL parameters, database URLs, credentials, usernames, Recipe/Food names,
notes, or OCR content.

`cold` and `warm` are operator-declared comparison modes. The command does not evict operating
system or PostgreSQL caches. Record the preparation procedure outside the manifest and compare only
runs with equivalent reference environments.

## Initial reference ceilings

Budget contract `phase5c_performance_budgets_v1` implements the Phase 5C3b ceilings:

| Tier | Bridge | Planning | Conversion | Qualification | Subject p95 / p99 | Peak RSS | Execution receipt |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| T0 | 5 min | 10 min | 30 min | 30 min | 0.75 s / 1.5 s | 512 MiB | 2 MiB |
| T1 | 5 min | 10 min | 30 min | 30 min | 0.75 s / 1.5 s | 512 MiB | 2 MiB |
| T2 | 30 min | 45 min | 3 h | 3 h | 1.5 s / 3 s | 1 GiB | 16 MiB |
| T3 | 2 h | 3 h | 12 h | 12 h | 2 s / 5 s | 1.5 GiB | 64 MiB |

Every tier limits the compact qualification receipt to 256 KiB. Versioned query ceilings are
10,000, 200,000, 2,000,000, and 10,000,000 total queries for T0–T3, with subject p95/p99 ceilings of
100/150 queries. Structural scan ceilings are deliberately independent of Recipe count: at most six
global source passes, 54 archive/support relation reads, eight Daily Log relation reads, 16 OCR
relation reads, and no global source, Daily Log, or OCR full read inside a subject.

These values are initial reference-environment ceilings, not universal production SLAs. A budget
failure is evidence for a separately reviewed correction; it is not permission for the harness to
change correctness behavior.

## Operator command

Run from `apps/backend` with no other connection to the externally created target:

```bash
NUTRITION_DEPLOYMENT_MODE=test \
NUTRITION_DATABASE_URL='<disposable-benchmark-url>' \
  .venv/bin/python -m scripts.qualify_phase5c_performance \
  --tier T0 \
  --fixture-seed 20260714 \
  --storage-environment 'isolated local SSD' \
  --cache-mode warm \
  --confirm-disposable-database nutrition_phase5c_benchmark_example \
  --output evidence/phase5c/phase5c-performance-t0.json
```

Use `--available-memory-mib` when the operating system cannot provide available-memory evidence.
Add `--opt-in-large-tier` for T1, T2, or T3. The canonical JSON is written to `--output`; stdout is
human text derived from that manifest (or canonical JSON with `--format json`). Existing output
files are not overwritten.

The command exits nonzero when correctness fails or any required budget fails, after writing the
manifest when the full measured path completed. Errors before safe evidence exists are bounded
reason codes and never echo the URL or exception.

## Measured Phase 5C2.1 optimization

The committed initial T0 manifest identified repeated per-subject planning-source, Daily Log, and
OCR scans. Phase 5C2.1 implements the bounded correction that evidence justified:

- admission and finalization retain complete archive/planning-source verification;
- each subject reuses the existing canonical plan-v2 checksum over an exact bounded source payload;
- convertible subjects also verify the archived owner still exists;
- immutable run binding columns are checked with one bounded control-row query;
- Daily Log and OCR roots are captured or verified once per invocation and once at finalization; and
- independent qualification remains a separate complete read-only verification.

No mutable cache, new checksum algorithm, plan change, receipt change, authorization change,
checkpoint change, or operator command was introduced. Migration 0017 adds only the supporting and
dynamic-archive indexes needed to make bounded subject lookups usable at representative scale;
partially completed v1 converter runs retain their stored evidence and restart compatibility after
that non-semantic upgrade.

The same T0 seed, fixture blueprint digest, logical-data digest, dimensions, PostgreSQL host, and
warm-cache declaration produced this comparison. Wall time is environment evidence, not an SLA:

| Metric | Initial T0 | Phase 5C2.1 T0 |
| --- | ---: | ---: |
| Global source passes | 213 | 25 |
| Archive/support relation scans | 632 | 68 |
| Daily Log relation scans | 196 | 20 |
| OCR relation scans | 389 | 37 |
| Per-subject source / Daily / OCR scans | 140 / 90 / 180 | 0 / 0 / 0 |
| Total queries | 6,081 | 5,517 |
| Conversion wall time | 20.849 s | 2.176 s |
| Restart-verification wall time | 15.452 s | 1.288 s |
| Independent-qualification wall time | 1.520 s | 1.484 s |
| Subject p95 time / queries | 0.475 s / 72 | 0.046 s / 65 |

The [initial manifest](../apps/backend/evidence/phase5c/phase5c-performance-t0.json) and
[optimized manifest](../apps/backend/evidence/phase5c/phase5c-performance-t0-optimized.json) preserve the detailed
aggregate evidence. Both independently qualified correctness and restart behavior.

Phase 5C2.2 repeated the same T0 workload after the archive-index provisioning correction. The
[requalification manifest](../apps/backend/evidence/phase5c/phase5c-performance-t0-requalified.json) preserves that
evidence. Its aggregate and per-subject scan vectors exactly match the optimized manifest; the only
structural query delta is 15 bridge/migration metadata queries. The exhaustive proof-obligation
analysis and recommendation to stop optimization are documented in
[Production Hardening Phase 5C2.2](production-hardening-phase5c2.2.md).

The optimized manifest still reports `performance_failed` for the four aggregate scan ceilings.
Stages outside conversion and restart already account for 19 global-source, 54 archive/support, 12
Daily Log, and 21 OCR scans; independent qualification intentionally contributes a complete scan.
Conversion and restart each add the bounded admission/final verification passes. Phase 5C2.1 does
not relabel those reads, weaken independent qualification, or revise the v1 budget contract to hide
that remaining measured work.

No result from this command authorizes production promotion, cutover, recovery, quarantine
acceptance, archive cleanup, Daily Log enrichment, or OCR cleanup.
