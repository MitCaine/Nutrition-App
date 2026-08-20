# Phase 5C4.9: Version 1.0 release gate closure

> **Document role: Evidence Record.** This preserves the authoritative Version 1.0
> backend/control release gate. See [Current State](../../project/current-state.md) for the active
> Version 1.1 starting point.

Status: **bounded release corrections implemented; Version 1.0 readiness
requires successful repository validation and fresh qualification evidence
from the exact clean release commit**

## Frozen release boundary

Phase 5C4.9 changes no application or control migration head. The authoritative
heads remain:

Subsequent active development now continues from application head
`0033_complete_runtime_authority`; predecessor `0030_total_omega_3_nutrient`,
`0029_expand_nutrient_catalog`,
`0028_duplicate_food_source_identity`, `0027_serving_reference_measurement`,
`0026_food_nutrient_integrity`, predecessor
`0025_immutable_validator_head`, and migration `0024_recipe_log_current_provenance`
remain part of the historical chain, and this release boundary remains frozen as
recorded below.

- application: `0021_target_activation_execution`;
- control: `ops_0011_phase5c4_recovery_audit`.

It adds no runtime grant, activation authority, cutback authority, recovery
transition, or nutrition-domain schema. Immutable Daily Log snapshots, Recipe
publication revisions, Recipe FoodItem projections, OCR correction provenance,
ownership, lock ordering, replay safety, role separation, and fail-closed
authority remain unchanged.

## Bounded corrections

### PostgreSQL migration fixture lifecycle

The shared disposable migration fixture begins teardown only after it has
successfully acquired the PostgreSQL bootstrap surface. Advisory-lock
acquisition is tracked independently, so only the owning session unlocks it.
Managed roles are removed only after their initial inventory was observed and
only when the fixture created that role surface. An unavailable optional
PostgreSQL service therefore remains a skip and cannot be replaced by a
teardown `RuntimeError`.

### Frozen migration-0001 nutrients

Migration `0001_initial_schema` owns its original 16 nutrient rows directly.
It no longer imports the mutable runtime nutrient catalog. Future nutrients
must be introduced through additive forward migrations; they must not be
backfilled by changing 0001. Qualification compares a one-command replay
through the historical 0017 boundary with a replay paused after 0001 and then
continued, including schema shape, row counts, and exact nutrient data.

## Current operational flow

Activation remains the Phase 5C4.7b authority chain: purpose-specific
authorization and promotion evidence precede the separately authorized
schema-0021 migration; the target remains closed until one-use activation,
target-local runtime admission, and authoritative observation converge.
Emergency close is a separate fail-closed action.

Cutback remains the Phase 5C4.8 purpose-specific, signed, one-use
**preactivation** saga installed by ops 0011. It may route to the proven source
and restore source writes last only while activation authority has not made
divergence possible. It is not postactivation rollback.

Recovery remains evidence-driven. Interrupted provider actions reconcile from
authoritative observations; cumulative recovery qualification is read-only;
postactivation PITR qualification restores only a disposable target and grants
no rollback or source-reopen authority.

The implemented deployment boundary is private/internal single-user operation.
Public multi-user deployment is intentionally unsupported because no public
production authentication provider is installed. The local infrastructure
qualifier exercises PostgreSQL 16, pgBackRest, MinIO, and a vendor-neutral
provider stand-in; it does not certify a production routing provider.

## Release qualification

The canonical commands and exact suite inventory are maintained in
[Version 1.0 PostgreSQL Release Qualification](../../operations/version-1.0-release-qualification.md).

The release gate requires:

1. all repository-owned validation and documentation checks;
2. the affected and complete PostgreSQL qualification suites;
3. fresh-versus-incremental migration replay equivalence;
4. a clean committed source tree;
5. fresh retained infrastructure qualification evidence produced from that
   exact commit; and
6. a successful `scripts/session-end.sh`.

The canonical infrastructure summary must record `dirty_tree: false`, the
exact Git commit, inventory and configuration digests, overall qualification
status, measured RPO/RTO, scenario results, cleanup status, and explicit
limitations. Local provider qualification remains vendor-neutral and does not
claim provider certification, public authentication, or application-domain
recovery redesign.
