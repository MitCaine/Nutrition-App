# Production Hardening Phase 5C2: checkpointed historical Recipe conversion

## Purpose and boundary

Phase 5C2 executes only deterministic `convert` decisions from the exact approved
`phase5c_conversion_plan_v2` produced by Phase 5C1. It records quarantine and block decisions as
audit outcomes without creating domain rows for them. It is an offline conversion-clone operation,
not an API and not production-promotion authorization.

The converter does not enrich Daily Logs, alter OCR data, regenerate compatibility projections,
repair malformed history, delete the archive, or automate cutover. If the converted clone is not
accepted, rollback is cutback to the retained pre-conversion clone; committed immutable revisions
are never deleted to simulate rollback.

## Eligibility and admission

Execution requires all of the following to match the approved plan exactly:

- migration `0016_phase5c_execution`;
- the original `historical_database_inventory_v1` digest;
- schema signature and conversion-rules versions;
- archive identity, structure, row counts, and archive/planning-source checksums;
- clone marker, source/clone identity, and operator-attestation evidence; and
- the manifest registered by the Phase 5C1 planner at migration 0015.

The converter validates the strict v2 plan shape and canonical digest before opening a run. Unknown
fields, a plan for another clone/archive, changed supporting Food evidence, current Recipe rows not
explained by checkpoints, or a non-maintenance database session fail closed. A different plan digest
cannot replace or continue an existing run.

Phase 5C operations hold the marker-derived maintenance advisory lock for admission and the normal
Phase 5C operation lock for serialization. The maintenance lock remains an offline operational
safety mechanism; it is not part of the application runtime lock hierarchy. Infrastructure must
still prevent ordinary clients from reconnecting to the clone.

## Operator authorization scopes

The immutable conversion plan answers what should happen; it is not permission to execute it. The
v1 bridge/planning attestation remains embedded in the marker and plan, while Phase 5C2 requires a
separate v2 attestation that explicitly includes `execution`, references the same marker digest,
and approves exactly one validated `phase5c_conversion_plan_v2`. It contains only the plan contract
version, canonical digest, archive identity, and canonical source checksums—not the plan body or
authored Recipe content.

This plan binding is part of the still-uncommitted v2 execution-attestation contract; no supported
or committed plan-unbound v2 execution attestation exists.

Supported bounded scopes are `bridge`, `planning`, `execution`, `bridge_and_planning`,
`planning_and_execution`, and `bridge_planning_and_execution`. Each scope grants only its named
operations. In particular, planning-only and bridge-only evidence cannot convert data, and
execution-only evidence cannot bridge or plan. Existing planning attestations remain valid for
planning but are intentionally non-executable.

Approving a clone or inventory is not equivalent to approving its conversion decisions. If the
planner produces a new manifest for any reason, the operator must generate a new execution
attestation from that exact plan file.

Execution authorization is offline operational evidence for this conversion clone. It is not user
authentication, a role system, or reusable production access control.

## Operator sequence

Complete Phase 5C1 through plan generation while the clone is exactly at
`0015_phase5c_conversion_control`. Inspect and retain the canonical plan and its digest. Create a
separate execution authorization against the already established marker; this does not overwrite
the marker or require the destructive bridge to run again:

```bash
cd apps/backend
NUTRITION_DATABASE_URL='<conversion-clone-url>' \
  .venv/bin/python -m scripts.create_phase5c_operator_attestation \
  --inventory phase5b-inventory.json \
  --source-production-identity phase5c-source-identity.json \
  --operator-attestation-id '<non-secret-execution-approval-id>' \
  --scope execution \
  --plan phase5c-conversion-plan.json \
  --clone-marker-id '<same-non-secret-marker-id>' \
  --conversion-clone-id '<same-non-secret-clone-id>' \
  > phase5c-execution-attestation.json
```

Then advance only that isolated clone to the execution revision:

```bash
cd apps/backend
NUTRITION_DATABASE_URL='<conversion-clone-url>' \
  alembic upgrade 0016_phase5c_execution
```

With no unrelated sessions connected, execute the exact plan and evidence:

```bash
NUTRITION_DATABASE_URL='<conversion-clone-url>' \
  .venv/bin/python -m scripts.execute_historical_recipe_conversion \
  --plan phase5c-conversion-plan.json \
  --inventory phase5b-inventory.json \
  --attestation phase5c-execution-attestation.json \
  --clone-marker-id '<non-secret-marker-id>' \
  --conversion-clone-id '<non-secret-clone-id>' \
  --format json \
  > phase5c-execution-receipt.json
```

Supply `--archive-schema` when Phase 5C1 used a non-default archive. The identifiers are bounded
audit labels, not credentials. The database URL remains an environment-only input and is never
included in the receipt.

## Mapping and immutable baseline

For each `convert` subject, the converter preserves the legacy Recipe UUID, owner, timestamps,
ingredient UUIDs, Food UUIDs, serving UUIDs, authored quantities and units, resolved grams,
preparation notes, and deterministic positions. Current name and notes come only from the validated
existing Recipe projection. Null-or-positive serving count and a positive normalized gram yield are
copied under the approved planner rule.

The existing projection Food UUID is reused. Its serving, nutrient, source, and timestamp rows are
not regenerated or overwritten. One revision is captured from that exact projection with revision
number 1, origin `legacy_projection_capture`, and confidence `transition_baseline`; the current
canonical revision digest authority calculates its digest. The Recipe and projection are linked to
that revision.

Projection nutrition is captured, not recalculated, because it is the authoritative historical
published surface. Authored-Recipe equivalence is evaluated separately. Legacy display units that
exactly match the selected serving are interpreted through that serving's stored quantity solely for
the comparison; the persisted legacy authored quantity and unit remain unchanged. A mismatch sets
`needs_republish`; the projection is never overwritten to hide it.

## Transactions, graph order, and checkpoints

Each converted Recipe runs in one PostgreSQL `SERIALIZABLE` transaction. The converter locks the
projection and referenced Foods together in sorted UUID order, then the archived Recipe and its
ingredients. It rechecks the full source evidence, ownership, serving membership, projection
identity, defaults, nutrients, and graph assumptions before writing Recipe, ingredients, immutable
revision children, projection linkage, and the `domain_committed` checkpoint atomically.

Converted children are processed before converted parents; UUID order is the deterministic
tie-breaker. A parent never proceeds until every planned converted child has committed and verified.
Only PostgreSQL serialization failures and deadlocks are retried, with a maximum of three attempts
and full source revalidation on every attempt. Other failures persist a bounded reason code and roll
back the whole subject.

Migration 0016 creates `phase5c_conversion_runs` and `phase5c_conversion_outcomes`. The run binds the
plan, inventory, signature, rules, archive checksums, marker/planning-attestation evidence, exact
execution attestation version, isolation contract, identity, scope and digest, converter version,
and baseline Daily Log/OCR state digests. Each outcome binds one source UUID, planned disposition,
reason, source checksum, checkpoint state, and—only when converted—the reused projection and created
revision identity/digest. Constraints enforce valid state and converted/non-converted shapes.

## Restart and verification

An exact completed restart re-verifies and skips each subject. It checks Recipe and ingredient
mapping, projection content, exactly one valid transition revision, active links, staleness, source
checksum, and unchanged Daily Log/OCR state. Quarantine and block outcomes similarly recheck their
plan identity, reason, and source evidence. A failed deterministic outcome is not silently retried.
An unexplained, partial, or tampered current domain fails admission. Restart also requires the exact
same execution authorization evidence; another otherwise valid execution approval cannot silently
take over an existing run.

The domain transaction first records `domain_committed`; a separate read-only post-commit check then
marks the outcome completed and verified. If that check fails, the outcome and run are marked failed
without deleting already committed immutable data. Operator review and clone cutback are required.

The execution receipt contains only versions, run and plan identities, aggregate counts, source
UUIDs, stable dispositions/reasons, converted target/projection/revision identities and digests,
verification state, and a canonical report digest. It excludes authored names, notes, instructions,
preparation text, emails, OCR content, credentials, URLs, and arbitrary exception text.

## Deferred Phase 5C3 boundary

Phase 5C2 does not authorize production promotion. Promotion/cutover verification, archive cleanup,
legacy Daily Log revision-link enrichment, quarantine repair, OCR changes, and alternate historical
schema signatures require separately reviewed work.
