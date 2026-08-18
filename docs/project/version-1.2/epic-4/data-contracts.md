# Version 1.2 Epic 4 — Data and Runtime Contracts

> **Document role: Architecture/Data Contract.** This document defines the normative data semantics and runtime boundaries required to implement the [Epic 4 Feature PRD](feature-prd.md). It is intentionally more precise than the [research record](planning.md) and [Grill record](accepted-decisions.md).

## 1. Contract goals

Epic 4 must add multi-day History without creating a new authority or weakening Daily Log snapshot semantics.

The contract therefore has four primary responsibilities:

1. persist a durable positive Complete assertion for one authoritative Daily Log calendar date;
2. expose one bounded range read through the existing Daily Logs runtime capability;
3. return enough per-date evidence to calculate all supported History projections in one shared layer; and
4. preserve local/remote semantic parity, exact values, unknown-versus-zero distinctions, and deterministic mutation outcomes.

## 2. Authority ownership

### 2.1 Existing capability ownership

Nutrition History remains owned by `DailyLogsRuntime` / the existing Daily Logs capability.

No ninth `History` capability is introduced.

History does not own independent application data. It reads:

- immutable Daily Log nutrient snapshots;
- date-level Complete metadata; and
- current target/reference context through the existing Targets capability when presentation needs it.

### 2.2 Selected authority

For one running context, exactly one application-data authority is selected:

- local SQLite; or
- remote FastAPI/PostgreSQL.

The following are prohibited:

- mixed-authority range construction;
- fallback from remote History to SQLite;
- dual reads used as reconciliation;
- shadow reads/writes;
- synchronization;
- background replication; and
- a shared live cache that becomes a second authority.

Cache entries must remain scoped to the selected authority.

## 3. Authoritative calendar contract

History dates reuse the existing authoritative Daily Log calendar model.

- Request dates are date-only values.
- Range endpoints are inclusive.
- Range length is counted in calendar dates.
- Initial History accepts at most 30 dates.
- Initial History does not include Today; the maximum endpoint is yesterday according to the authoritative calendar.
- DST changes do not alter range cardinality.
- Timezone/calendar-setting changes do not migrate existing Log ownership or Complete assertions to another date.
- Log creation timestamps are not used to determine History date ownership.

## 4. Complete-state persistence contract

### 4.1 Semantic model

Complete is positive date-owned application state.

Conceptually:

```text
DailyLogDayCompletion
- owner/date identity
- logged_date: LocalDate
- completed_at: Instant
```

Exact physical table/column names may follow existing repository conventions, but the semantic owner is the Daily Log calendar date.

Absence of a row/assertion means `not confirmed complete`. It does not mean a persisted negative or `Incomplete` classification.

### 4.2 Storage requirements

Remote PostgreSQL persistence must be owner-scoped. Local SQLite persistence must follow the existing local authority's owner/runtime conventions without inventing a second owner model merely for Complete.

Required invariants:

- at most one active Complete assertion per authoritative date;
- an assertion cannot exist for an empty date;
- migration creates no assertions for pre-existing dates;
- `completed_at` is retained as internal persistence evidence;
- backup/restore includes Complete state;
- one-time authority transfer includes Complete state; and
- Complete metadata must not modify or re-encode immutable nutrient snapshots.

### 4.3 Mark-Complete mutation

The logical operation is:

```text
markDayComplete(date, mutationIntent)
```

Preconditions:

- date is Today or earlier under the authoritative calendar;
- the date contains at least one authoritative Daily Log entry;
- no unresolved nutrition-changing mutation for that date is being treated as authoritative client state; and
- the selected authority is writable.

Postcondition:

- one positive Complete assertion exists for the date with authoritative persistence evidence.

Remote behavior must use the existing deterministic Daily Log mutation identity/reconciliation model. An indeterminate response must be reconcilable without guessing or applying duplicate intent.

Initial Epic 4 does not require a public/manual `clearDayComplete` user action.

### 4.4 Automatic invalidation

Nutrition-affecting Daily Log mutations must atomically invalidate Complete for every affected date.

The invariant is:

```text
if authoritative daily nutrition evidence changes:
    the affected date is no longer Complete
```

Required behavior:

- create on a Complete date clears Complete;
- deleting an entry from a Complete date clears Complete;
- deleting the final entry also leaves no Complete assertion because the date is empty;
- moving an entry clears Complete on source and destination dates;
- serving/amount edit clears Complete if the resulting nutrient snapshot differs;
- serving/amount edit preserves Complete if the resulting nutrient snapshot is exactly unchanged;
- note-only edit preserves Complete;
- meal-label-only edit preserves Complete;
- current Target changes preserve Complete;
- later source Food/Recipe edits preserve Complete for existing historical entries because their stored snapshots remain unchanged.

The Log mutation and Complete invalidation must share one authoritative transaction/atomic operation. A committed nutrition mutation with a stale Complete assertion is not an acceptable intermediate result.

## 5. History range request contract

The logical capability operation is:

```text
getHistoryRange(startDate, endDate)
```

Request rules:

- both endpoints are inclusive LocalDate values;
- `startDate <= endDate`;
- range contains at most 30 calendar dates;
- `endDate <= yesterday` for the initial History product;
- invalid or oversized ranges fail explicitly rather than being silently truncated; and
- one request is satisfied entirely by the selected authority.

The remote implementation must use one bounded HTTP operation rather than one request per date.

## 6. History range response contract

The response is daily evidence, not an already-rendered chart and not the individual Food/Log graph.

Conceptually:

```text
HistoryRangeEvidence
- start_date: LocalDate
- end_date: LocalDate
- first_logged_date: LocalDate | null
- days: HistoryDayEvidence[]
```

`days` contains exactly one record for each calendar date in the requested inclusive range, ordered ascending by date.

### 6.1 Per-date evidence

Conceptually:

```text
HistoryDayEvidence
- date: LocalDate
- has_logs: boolean
- is_complete: boolean
- nutrients: map<NutrientId, HistoryNutrientEvidence>
```

For a no-Log date:

- `has_logs = false`;
- `is_complete = false`; and
- nutrient evidence must remain absent/unavailable rather than becoming explicit zero.

### 6.2 Nutrient evidence

The range contract should reuse the existing daily aggregate semantics wherever possible. It must preserve enough information to distinguish:

- known numeric contribution;
- estimated numeric contribution;
- explicit zero evidence;
- unknown contributors;
- no usable numerical value; and
- no Logs for the date.

Conceptually, each nutrient evidence item must provide semantic equivalents of:

```text
HistoryNutrientEvidence
- nutrient_id
- canonical_unit
- known_amount
- estimated_amount
- has_numeric_evidence
- is_explicit_zero_total
- has_unknown_contributors
- unknown_contributor_count
```

The implementation may use an existing richer aggregate type instead of introducing these exact field names if all required distinctions remain recoverable.

### 6.3 Usable numeric value

For History calculations:

```text
numeric_amount = known_amount + estimated_amount
```

An estimated amount is usable numeric evidence, while retaining its estimated provenance.

A nutrient/date has a usable numeric value when the aggregate contract supports a numerical amount, including an explicit numerical zero.

A date with only unknown/unavailable selected-nutrient evidence has no usable numeric value and must not be converted to zero.

Unknown contributors do not automatically disqualify an otherwise usable numeric value. The app may show the useful numeric amount while preserving uncertainty metadata internally.

## 7. First-logged-date bounds contract

`first_logged_date` is the earliest authoritative date in the selected authority that contains at least one Daily Log entry.

- If no Logs exist, it is `null`.
- It is not installation date, account creation date, transfer date, or Today.
- It allows History paging to stop before entirely pre-history ranges without probing indefinitely.
- It must remain authority-scoped.

The implementation may obtain this bound as part of the bounded range operation or through an equivalent bounded metadata mechanism, but the user-visible behavior must not require sequential empty-range probing.

## 8. Shared History projection contract

Local SQLite and remote FastAPI/PostgreSQL produce the same `HistoryRangeEvidence` semantics.

One shared application/domain projection layer must calculate:

- Complete-day averages;
- Logged-day averages;
- usable-day counts;
- coverage counts;
- chart points/gaps;
- selected-date exact values; and
- grouped Nutrition Details rows.

Do not independently implement average/denominator rules inside SQLite SQL and backend FastAPI business logic if doing so would create two semantic authorities for the same calculation.

Authority-specific code is responsible for retrieving equivalent daily evidence. Shared code is responsible for interpreting it for History.

## 9. Average contract

### 9.1 Complete-day mode

For nutrient `N` over range `R`:

```text
eligible_dates = dates where
    day.is_complete
    AND N has usable numeric evidence

average = exact_sum(N.numeric_amount over eligible_dates) / count(eligible_dates)
```

The UI reports the actual numeric denominator, e.g. `Complete-day average · 4 days used`.

A Complete day whose selected nutrient is entirely unknown/unavailable does not enter the nutrient's numeric denominator.

### 9.2 Logged-day mode

```text
eligible_dates = dates where
    day.has_logs
    AND N has usable numeric evidence

average = exact_sum(N.numeric_amount over eligible_dates) / count(eligible_dates)
```

No-Log dates do not enter the denominator.

### 9.3 Exact arithmetic

- Do not round each day's value before averaging.
- Sum exact stored decimal representations first.
- Divide using the repository's exact-decimal/history calculation conventions.
- Round only the final presentation value according to canonical nutrient display precision.
- Stable canonical units are used throughout the selected range.

The existing [Epic 2 exact-value contract](../../version-1.1/epic-2/e2-02-exact-value-contract.md) remains authoritative where it defines shared exact-value encoding/decoding semantics.

## 10. Missing, zero, estimated, and unknown contract

These states must not collapse:

| State | `has_logs` | Usable numeric value | Chart meaning |
| --- | --- | --- | --- |
| No Logs | false | no | gap / `No logs` |
| Logged, selected nutrient unknown-only | true | no | unavailable, not zero |
| Explicit numerical zero | true | yes, zero | true zero observation |
| Known numeric amount | true | yes | numeric bar/value |
| Estimated numeric amount | true | yes | numeric value with estimated provenance |
| Numeric amount + unknown contributors | true | yes | numeric value retained; uncertainty metadata preserved |

A parent nutrient must not be manufactured from incomplete children merely to fill a missing value.

## 11. Target/reference contract

Historical range evidence does not own current target state.

Current target/reference context is retrieved through the existing Targets capability and applied as a presentation lens.

Consequences:

- target changes do not alter `HistoryRangeEvidence`;
- target changes do not require invalidating historical range cache entries;
- focused charts may update their current reference line immediately after target change; and
- no historical target line/version stream is created.

## 12. Cache identity and invalidation

A History range cache key must include semantic equivalents of:

```text
selected_authority + start_date + end_date
```

`Complete days` versus `Logged days` is not part of cache identity because both are deterministic projections over one evidence payload.

Invalidation rules:

- Log mutation on date D invalidates cached ranges containing D;
- Complete mutation on D invalidates cached ranges containing D;
- move from S to D invalidates cached ranges containing S or D;
- unrelated ranges remain valid; and
- Target changes update target/reference context but do not invalidate the intake evidence range.

A cached local range never satisfies a remote range request and vice versa.

## 13. Loading and stale-response contract

The visible range label and visible evidence must always identify the same requested range.

- On range change, retire old-range analytical values before presenting the new range as current.
- Same-range cached evidence may remain visible after a refresh failure only with an explicit compact stale/refresh-failure indication.
- Different-range evidence may not remain visible under the new label.
- Rapid paging uses latest-request-wins semantics.
- A superseded response must not overwrite a newer requested range.
- Remote failure without valid same-range remote cache produces Retry/error, never authority fallback.

## 14. Nutrition Details payload sufficiency

One loaded History range must include all canonical nutrient daily aggregates needed by:

- the four overview cards;
- Nutrition Facts rows;
- Vitamins;
- Minerals;
- Fatty Acids; and
- focused nutrient History.

Opening additional nutrient groups or a focused nutrient must not cause another authoritative 7/30-day range read solely because that nutrient was not part of the macro overview.

## 15. Manual Food authoring contract

Manual Food authoring changes presentation density but not nutrient persistence semantics.

- The conventional Nutrition Facts subset is visible by default.
- Additional nutrients are disclosed through grouped `More nutrients` sections.
- Adding an extended nutrient initializes it as unknown.
- Typing an explicit `0` retains zero semantics.
- Clearing/not knowing a value retains unknown semantics.
- Existing populated extended nutrients remain visible on edit.
- Create and edit share the same nutrient discovery taxonomy.

The canonical nutrient catalog and IDs remain unchanged by this form simplification.

## 16. Backup, restore, and transfer contract

Complete state is part of coherent Daily Log application data.

Therefore:

- local backup export includes it in the validated SQLite snapshot;
- staged restore validation/activation preserves it;
- one-time remote-to-local transfer carries it with the corresponding Daily Log dates;
- transfer remains one-time migration, not sync; and
- absence of Complete state in older source data maps to `not confirmed complete`, never inferred true.

## 17. Migration contract

Implementation requires additive persistence changes for both supported application-data authorities where applicable.

Migration rules:

- no historical backfill of Complete;
- no nutrient snapshot rewrite;
- no automatic date reinterpretation;
- remote ownership isolation is preserved;
- rollback/replay follows repository migration policy; and
- local schema upgrade remains deterministic for existing databases.

The current preserved remote migration head remains `0030_total_omega_3_nutrient` until implementation introduces and qualifies a successor. Planning documentation must not predeclare an unimplemented migration head as current.

## 18. Qualification fixture

At minimum, parity/contract tests must include:

- no-history authority (`first_logged_date = null`);
- earliest partial range;
- no-Log dates inside a populated range;
- explicit zero selected nutrient;
- known selected nutrient;
- estimated selected nutrient;
- numeric selected nutrient with unknown contributors;
- unknown-only selected nutrient;
- Complete and unconfirmed logged dates;
- one Complete usable date;
- Complete date with selected nutrient unknown-only;
- mixed Complete/Logged denominator switching;
- 7-day and 30-day bounds;
- oversized range rejection;
- end-after-yesterday rejection for the initial History contract;
- DST, month, and year boundaries;
- target change without history-range invalidation;
- source Food/Recipe edit without historical change;
- nutrition mutation with atomic Complete invalidation;
- same-snapshot serving-equivalent edit preserving Complete;
- move invalidating source and destination Complete/cache ranges;
- stale response arriving after a newer range request;
- remote failure with and without same-range cache;
- backup/restore of Complete;
- one-time transfer of Complete; and
- local/remote evidence and shared-projection parity.

## 19. Architecture gate

If implementation cannot satisfy this contract without introducing synchronization, a ninth data authority/capability, historical target reconstruction, mutation non-atomicity, or weakening unknown/exact-value semantics, implementation must stop and return to architecture review rather than broadening the Epic implicitly.
