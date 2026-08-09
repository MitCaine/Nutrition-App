# E2-09 — Local Daily Logs

The local Daily Log adapter is exposed by the SQLite runtime foundation as
`dailyLogs`. Creation runs in one exclusive SQLite transaction and resolves
the current owner-scoped Food or active Recipe publication exactly once.

## Authority and history

- A confirmed local calendar is required for creation; dates after the
  authoritative local date are rejected.
- Manual Food creation resolves the current Food serving and nutrient rows.
- Recipe creation resolves the immutable active publication revision and
  publication amount definition. Compatibility projection rows are never the
  historical nutrition authority. Projection serving compatibility uses the
  backend's exact label, unit, default, and decimal-equivalence rules, while
  gram-mode serving-multiplier provenance comes from the immutable revision's
  default serving conversion.
- The Daily Log stores fixed source identity, food-name/amount snapshots, and
  immutable nutrient snapshot rows. Later Food edits, serving replacement,
  soft deletion, Recipe republication, or projection changes do not rewrite
  the saved nutrition.
- Gram conversion and nutrient calculation use the backend-compatible
  28-digit response-decimal context. `NUMERIC(14,6)` rounding occurs only when
  the Daily Log and immutable snapshot values are bound for persistence. Each
  snapshot captures canonical calculation metadata with its nutrient basis and
  raw serving multiplier.
- Daily summaries aggregate snapshot rows only. Known and estimated values
  remain separate and retain derived unit-conversion precision without a
  single-column `NUMERIC(14,6)` aggregate cap. Power-of-ten unit conversions
  also preserve the result exponent and trailing zeros produced by the
  backend's Python Decimal operation sequence. Unknown contributors remain
  counted independently from explicit zero values.

## Reads and replay

The adapter supports date-scoped logs, future-entry reads, edit context, daily
summary, Recent Entries/Repeat eligibility, and Recent Foods. Recent Foods is
ordered by the newest `DailyLog.created_at` per owner-scoped Food, not by a
mutable Food timestamp. Repeat returns historical intent plus a current
source/amount reuse decision; confirmation creates a fresh snapshot set.
Food gram Repeat deliberately re-resolves the gram intent without reusing a
historical serving identity, so the current default serving or current direct
gram authority decides whether the intent remains exact. Serving-mode Repeat
continues to require its historical serving identity.
Date, future-date, Recent Entry, and Recent Food ordering compares canonical
instants through a SQLite sort key that expands terminal `Z` to `.000000Z`.
Stored timestamps and returned canonical spellings remain unchanged.

`log.create` uses the existing operation-idempotency table. Exact replay
returns the retained response, a changed payload is a conflict, and failed
creates roll back the receipt, Daily Log, and all snapshots together. The
fingerprint canonicalizes the raw request Decimal before `NUMERIC(14,6)`
persistence rounding and intentionally excludes `calendar_revision`.

Nutrition edits and deletion remain deferred to E2-10. The local runtime does
not disable immutable snapshot guards or use the E2-10 replacement scope for
normal creation.
