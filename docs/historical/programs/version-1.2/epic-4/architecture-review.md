# Version 1.2 Epic 4 — Architecture Review

> **Document role: Architecture Review.** This review evaluates the [Epic 4 Feature PRD](feature-prd.md) and [Epic 4 Data and Runtime Contracts](data-contracts.md) against the repository's established architecture and invariants. It does not authorize implementation until the planning package also passes repository documentation validation and project audit.

## Reviewed artifacts

This review was performed against:

- [Current Product Roadmap](../../../../project/product-roadmap.md);
- [Project Invariants](../../../../project/invariants.md);
- [Epic 4 research record](planning.md);
- [Epic 4 Grill decision record](accepted-decisions.md);
- [Epic 4 Feature PRD](feature-prd.md); and
- [Epic 4 Data and Runtime Contracts](data-contracts.md).

## Architectural assessment

**Decision: Approved, subject to repository validation/audit gate.**

Epic 4 can be implemented as a bounded extension of the existing Daily Logs capability and mobile presentation hierarchy. The accepted scope does not require a new application-data authority, synchronization, historical nutrition rewrite, target-history model, or broad analytics platform.

The main architectural additions are additive and coherent with current ownership:

1. date-owned Complete metadata alongside Daily Log history;
2. one bounded Daily Logs range-read contract for at most 30 calendar dates;
3. one shared History projection layer over equivalent local/remote daily evidence; and
4. new Daily Log / Daily Nutrition / History presentation routes built on existing navigation and read-state infrastructure.

No blocking architecture conflict was identified.

## 1. Daily Log ownership

Approved.

History remains a projection over Daily Log authority rather than a separate aggregate root or ninth runtime capability.

This is the correct ownership boundary because:

- historical nutrition already belongs to immutable Daily Log snapshots;
- Complete describes one Daily Log calendar date;
- History does not own independent mutations beyond the day-level Complete assertion exposed from Daily Log; and
- navigation from History returns to the authoritative Daily Log date for editing.

Introducing a standalone History authority would create unnecessary duplication and a risk of divergent historical truth.

## 2. Selected-authority invariant

Approved.

The PRD and data contract preserve the existing exactly-one-application-data-authority rule:

- local SQLite supplies local History evidence;
- remote FastAPI/PostgreSQL supplies remote History evidence;
- caches are authority-scoped; and
- failure never triggers fallback or mixed-authority range construction.

The bounded range endpoint is a new read operation inside the existing Daily Logs capability, not a new source of truth.

## 3. Immutable historical nutrition

Approved.

History consumes immutable Daily Log nutrient snapshots. It does not recalculate historical intake from current Foods or Recipes.

The design also preserves the distinction between:

- metadata-only Log edits;
- nutrition-affecting Log edits; and
- later source Food/Recipe edits.

Complete invalidation is tied to whether authoritative Daily Log nutrition evidence changed, not merely whether another object elsewhere in the graph changed.

This preserves the project's strongest historical invariant.

## 4. Complete-state model

Approved as an additive day-state boundary.

A positive date-owned Complete assertion is preferable to placing a redundant flag on every Log entry because the assertion describes coverage of the date as a whole.

The accepted model is architecturally sound provided implementation preserves these invariants:

- no Complete assertion on an empty date;
- no historical backfill;
- one active assertion per date/owner authority;
- automatic invalidation is atomic with nutrition-changing Log mutations;
- source and destination are both invalidated for a move;
- non-nutrition Log metadata changes preserve the assertion;
- current Target changes preserve the assertion; and
- remote Complete writes use deterministic mutation recovery.

The internal `completed_at`-equivalent field is acceptable as persistence/recovery evidence. It does not imply a product commitment to streaks, timing analytics, or behavioral scoring.

### Architecture gate

If the existing Daily Log mutation pipeline cannot clear Complete in the same authoritative transaction as a nutrition mutation, implementation must stop and return to architecture review. Eventual cleanup of a stale Complete flag is not acceptable.

## 5. Bounded History range read

Approved.

One range operation is preferable to 7 or 30 independent Daily Log summary reads because it:

- keeps remote latency bounded;
- avoids partial-range failure semantics;
- provides one coherent daily-evidence snapshot for the requested window;
- simplifies latest-request-wins behavior; and
- makes local/remote parity easier to prove.

The initial 30-date maximum is appropriately aligned with the accepted product scope. A future 90-day/custom feature may expand the contract deliberately rather than inheriting an accidentally unbounded endpoint.

The response should remain a read projection of daily aggregates rather than the complete individual Food/Log graph.

## 6. Shared projection layer

Approved and strongly recommended.

Local SQLite and remote FastAPI/PostgreSQL should retrieve semantically equivalent daily evidence. Complete-day averages, Logged-day averages, usable-day counts, gaps, and History chart values should then be calculated by one shared application/domain projection contract.

This avoids two independent implementations of denominator and unknown-value semantics.

Implementation must preserve exact-decimal behavior and should reuse existing shared Epic 2 value codecs/contracts wherever possible.

### Architecture gate

If platform constraints force local and remote History calculations to use separate independently maintained business rules, the implementation must add explicit parity fixtures at the shared contract boundary and demonstrate that the two paths cannot silently diverge. The preferred architecture remains one shared projection.

## 7. Exact values and uncertainty

Approved.

The PRD does not simplify history by collapsing unknown into zero or rounding daily values before aggregation.

The data contract correctly preserves:

- known contribution;
- estimated contribution;
- explicit zero;
- unknown contributors;
- unknown-only selected nutrient; and
- no-Log dates.

The average denominator is nutrient-specific after the global Complete/Logged mode is selected. This is necessary because Complete describes logging coverage rather than nutrient completeness.

No architectural issue was identified.

## 8. Target/reference boundary

Approved.

Current target/reference configuration remains owned by the existing Targets capability. Historical intake evidence is cached independently from current target context.

This is a clean separation because:

- target changes do not rewrite historical intake;
- the app does not have a historical target-version stream;
- target/reference context can be refreshed independently; and
- the UI explicitly labels the reference as current.

Historical target reconstruction remains out of scope and would require a separate versioned-state design.

## 9. Calendar and timezone behavior

Approved.

The design reuses the authoritative date model already established for Daily Logs.

History ranges are calendar-date windows rather than elapsed-hour intervals. Existing historical Log dates and Complete assertions remain attached to their stored authoritative dates when timezone settings later change.

No new time-of-day ownership is introduced.

This avoids reopening the already-solved calendar authority problem.

## 10. Cache and failure model

Approved.

The accepted cache key of selected authority plus exact start/end dates matches the existing authority boundary.

The invalidation strategy is appropriately granular:

- Log/Complete mutations invalidate only overlapping ranges;
- moves invalidate ranges containing either date;
- target changes do not refetch historical intake; and
- stale same-range evidence may remain visible only with an explicit refresh-failure indication.

Latest-request-wins is required to prevent out-of-order remote responses from replacing newer range selections.

No cache is permitted to become a second persistent authority.

## 11. UI/navigation architecture

Approved.

The accepted product hierarchy fits existing mobile architecture without a fourth bottom tab:

- Daily Log remains the primary logging route;
- Daily Nutrition becomes a dedicated one-day analysis route;
- Nutrition History becomes a dedicated multi-day route under Daily Log; and
- Nutrition Details/focused nutrient History can be implemented as bounded nested route/sheet state.

The design intentionally reduces the current Daily Log's vertical analytical density rather than expanding it further.

`react-native-svg` is already present, so the initial chart requirement does not itself justify another chart dependency.

Thirty-day chart mechanics remain a qualification decision: static first; horizontal scrolling only if physical-device evidence requires it while preserving one date per observation.

## 12. Manual Food authoring change

Approved as a presentation refinement, not a nutrient-model change.

Restricting the default visible form to the conventional Nutrition Facts subset does not alter:

- canonical nutrient identities;
- storage semantics;
- unknown-versus-zero behavior; or
- existing populated extended nutrients.

Grouped `More nutrients` disclosure is a bounded way to prevent catalog growth from overwhelming ordinary authoring.

No architecture migration is required solely for this UI change.

## 13. Backup/restore and one-time transfer

Approved with explicit qualification requirement.

Complete is authoritative Daily Log metadata and therefore belongs in:

- coherent local SQLite backup/restore; and
- the existing one-time remote-to-local transfer mechanism.

This does not create synchronization because the transfer remains a bounded migration operation and backup remains replacement/recovery.

Implementation must qualify older source data with no Complete records as `not confirmed complete`, never inferred true.

## 14. Security and ownership

No new cross-owner capability is introduced.

Remote day-state persistence and range reads must use the same owner isolation rules as Daily Logs. History must not make first-logged-date bounds, Complete state, or aggregate evidence observable across owners.

No public multi-user/account architecture is added.

## 15. Accessibility scope

Comprehensive accessibility-specific chart product design was deliberately deferred during Grill.

This does not authorize regressions in existing shared platform primitives or removal of already-present labels/roles. It means Epic 4 does not expand scope into a dedicated VoiceOver/chart-accessibility program or app-specific accessibility settings.

Deferred accessibility expansion remains in the future-product register.

## 16. Explicitly rejected architecture expansions

Epic 4 does not justify:

- a fourth bottom-navigation tab;
- a ninth History runtime capability;
- a separate History database/cache authority;
- local/remote synchronization;
- fallback reads;
- dual writes;
- historical target versioning;
- a generic analytics warehouse;
- contributor-ranking materialization;
- meal/time-of-day event modeling;
- automatic trend/coaching inference; or
- an unbounded range/reporting API.

## 17. Architectural risks and controls

### Risk: stale Complete after nutrition mutation

Control: clear Complete atomically inside the same selected-authority mutation transaction.

### Risk: local/remote denominator drift

Control: equivalent daily-evidence contract plus shared projection/parity fixture.

### Risk: historical target misrepresentation

Control: current reference stays a separately labeled presentation lens.

### Risk: range response payload growth

Control: hard 30-date bound and aggregate-per-date evidence rather than individual entries.

### Risk: 30-day chart unreadability

Control: physical-device qualification with horizontal scrolling allowed only if static bars fail.

### Risk: migration falsely marks history Complete

Control: no-backfill migration and explicit fixture coverage.

### Risk: cache crosses authority/date boundaries

Control: authority + exact range identity and overlap-specific invalidation.

## 18. Architecture decision

**Approved.** The Feature PRD and data contracts fit the repository's established architecture and may proceed to bounded task decomposition.

Implementation remains gated on:

1. a complete [implementation backlog](implementation-backlog.md);
2. repository documentation validation passing; and
3. the repository project audit passing for the finalized planning package.

A failure of those gates is documentation/repository drift that must be corrected before implementation authorization; it is not permission to bypass the gate.
