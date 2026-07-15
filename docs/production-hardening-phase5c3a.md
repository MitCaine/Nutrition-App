# Production Hardening Phase 5C3a: independent conversion qualification

## Purpose and boundary

Phase 5C3a independently determines whether a completed Phase 5C2 conversion clone is internally
consistent. It is a PostgreSQL-only, offline, read-only operator command. It emits qualification
evidence; it does not authorize production promotion, change infrastructure, repair a clone, enrich
Daily Logs, alter OCR history, or optimize conversion performance.

Converter restart verification answers whether the converter can safely continue its own
checkpoint state. Independent qualification instead re-queries the final database from the approved
plan, archive, run, outcomes, immutable domain rows, and execution receipt. The qualifier does not
import or call converter checkpoint-verification functions.

## Admission and read-only behavior

Qualification requires the exact:

- `phase5c_conversion_plan_v2` and inventory document;
- plan-bound v2 execution attestation;
- clone marker and conversion-clone identity;
- archive identity and source roots;
- completed and verified migration-0016 conversion run; and
- canonical `phase5c_execution_receipt_v1` produced by that run.

The command validates evidence before and after taking the Phase 5C operation lock. It holds the
marker-derived shared maintenance lock, refuses non-maintenance sessions, and performs qualification
inside a PostgreSQL `REPEATABLE READ`, `READ ONLY` transaction. The verification transaction is
rolled back. Before and after state digests cover every table in the current and archive schemas.
The external receipt is never inserted into the database.

The maintenance advisory lock is operational evidence for the offline conversion clone, not a
permanent application lock-hierarchy rule. Infrastructure isolation remains required.

## Operator command

With no unrelated sessions connected to the completed conversion clone:

```bash
cd apps/backend
NUTRITION_DATABASE_URL='<conversion-clone-url>' \
  .venv/bin/python -m scripts.verify_historical_recipe_conversion \
  --plan phase5c-conversion-plan.json \
  --inventory phase5b-inventory.json \
  --attestation phase5c-execution-attestation.json \
  --execution-receipt phase5c-execution-receipt.json \
  --clone-marker-id '<same-non-secret-marker-id>' \
  --conversion-clone-id '<same-non-secret-clone-id>' \
  --archive-schema nutrition_phase5c_archive \
  --format json \
  > phase5c-qualification-receipt.json
```

`NUTRITION_DATABASE_URL` is mandatory and remains environment-only. Diagnostic mode emits only a
version, `not_qualified`, one bounded reason code, and a digest:

```bash
... -m scripts.verify_historical_recipe_conversion ... --diagnostic-only --format json
```

Diagnostic output is not a qualification receipt.

## Independent verification

For each plan subject, the qualifier recomputes the approved archived Recipe checksum and compares
the archived mapping with current Recipe and ingredient rows. Converted subjects must have the exact
owner, projection, authored amounts, serving identities, resolved grams, positions, preparation
data, supported timestamps, and active links established by the approved conversion mapping.

Exactly one transition-baseline revision must exist. Its owner, Recipe, revision number, origin,
confidence, amount definitions, nutrient snapshots, and canonical content digest must be valid. The
existing projection must be reused, remain identical to the revision capture, and retain its exact
plan-bound Food, serving, nutrient, and source evidence. `needs_republish` is recomputed from the
authored Recipe rather than trusted from the checkpoint.

Quarantined and blocked subjects must have no current Recipe, authored ingredients, revision, or
managed projection linkage. The qualifier also refuses extra or missing outcomes, unexplained
Recipes or revisions, extra managed links, unexpected revision children, and domain rows not
accounted for by converted plan subjects.

The final dependency graph is reconstructed from current authored ingredients and projection links.
It must be owner-consistent, acyclic, deterministic, and contain only valid converted nested
dependencies. Migration 0016 does not persist commit order, so Phase 5C3a proves final-state graph
correctness and does not claim to prove historical child-before-parent commit order.

Daily Log and nutrient-snapshot rows are hashed using the exact Phase 5C2 baseline semantics and
compared with the run baseline. The same is done for OCR scans, parse results, corrections, and
confirmation traces. These rows are read but never enriched or changed. Archived Recipe roots and
the planning supporting-source root must still match the plan, execution authorization, archive
metadata, and conversion run.

The execution receipt is validated as a strict canonical contract and reconciled subject-by-subject
with persisted outcomes. Its run ID binds it to the run, and the run independently binds the exact
execution-attestation digest. Counts and receipt fields are never trusted without database
comparison.

## Qualification receipt

`phase5c_conversion_qualification_receipt_v1` contains only:

- verifier, plan, execution-attestation, and execution-receipt versions and digests;
- conversion run ID, clone-marker digest, archive-identity digest, inventory digest, schema digest,
  and conversion-rules version;
- planned and observed aggregate counts and bounded reason-code counts;
- archive/supporting-source, Daily Log, OCR, and outcome-ledger digests;
- `qualified`; and
- a canonical receipt digest.

The outcome-ledger digest covers deterministic safe per-subject identities, dispositions, reason
codes, source checksums, converted target/projection/revision identities, revision digests, and final
verification states. Only the aggregate ledger digest appears in the compact receipt.

The receipt excludes authored names, notes, instructions, preparation text, emails, OCR content,
credentials, database URLs, SQL, and arbitrary exceptions. Repeating qualification over unchanged
state produces the same receipt.

## Bounded failures

Qualification fails closed with one of these stable reason codes:

- `qualification_evidence_mismatch`
- `qualification_archive_checksum_changed`
- `qualification_outcome_cardinality_invalid`
- `qualification_converted_mapping_invalid`
- `qualification_revision_digest_invalid`
- `qualification_projection_snapshot_invalid`
- `qualification_staleness_invalid`
- `qualification_dependency_cycle`
- `qualification_dependency_invalid`
- `qualification_nonconvert_domain_row_exists`
- `qualification_daily_log_state_changed`
- `qualification_ocr_state_changed`
- `qualification_unexplained_current_domain_row`
- `qualification_execution_receipt_mismatch`
- `qualification_run_incomplete`
- `qualification_snapshot_unstable`

Raw database or exception messages are not included.

## Phase 5C3b performance handoff

A valid Phase 5C3a receipt is evidence that the clone is internally consistent. It is not evidence
that conversion duration, resource use, backup/cutback procedures, source write-freeze equivalence,
application smoke tests, quarantine policy, or deployment cutover are acceptable. Phase 5C3b adds
representative-volume performance evidence without changing this receipt. Recovery exercises,
promotion eligibility, cutover, and any checksum optimization remain separately deferred. See
[Phase 5C3b](production-hardening-phase5c3b.md).
