# E2-02 — Exact value and parity contract

This document freezes the value boundary required before any SQLite feature
persistence is introduced. PostgreSQL remains the current nutrition and
serialization authority. The mobile codecs in
`apps/mobile/src/shared/exact/` are pure, runtime-neutral helpers; they do not
select a runtime, open SQLite, or replace existing feature calculations.

## Decimal authority

Every persisted PostgreSQL `NUMERIC` column currently uses one of these
shapes. The mobile representation is a non-negative, fixed-scale decimal
string. `null` remains `null`; it is never represented by zero or an empty
string.

| PostgreSQL type | Existing uses | Mobile codec | Maximum stored value |
| --- | --- | --- | --- |
| `NUMERIC(14,6)` | Food nutrients and servings, Recipe amounts, publication values, Daily Log quantities/snapshots, Targets | `NUMERIC_14_6` | `99999999.999999` |
| `NUMERIC(8,3)` | User height and weight | `NUMERIC_8_3` | `99999.999` |
| `NUMERIC(5,4)` | OCR confidence values | `NUMERIC_5_4` | `9.9999` |

Inputs are decimal text without whitespace, a sign, or an exponent. Leading
zeroes are accepted and removed during serialization. Values with more
fractional digits are rounded to the storage scale using `ROUND_HALF_UP`
(ties away from zero; the persisted domain rejects negative values). Overflow
is checked after rounding, so `99999999.9999995` is rejected rather than
wrapped. Zero is emitted at the fixed scale, for example `0.000000`.

Arithmetic operates on `BigInt` coefficients at the selected scale. Addition,
subtraction, multiplication, division, comparison, and coarser-scale rounding
are available from `decimal.ts`; no authoritative value is converted through
JavaScript `Number`. Negative results, division by zero, malformed input, and
overflow are explicit errors.

## Canonical scalar and document values

| Value | Canonical persisted/runtime representation |
| --- | --- |
| UUID | Lower-case, hyphenated 36-character text (`xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`) |
| Instant | UTC ISO-8601 text ending in `Z`; no fractional part at zero microseconds, otherwise exactly six fractional digits (for example `2026-02-28T23:59:59.100000Z`) |
| Date-only | Gregorian `YYYY-MM-DD` text; invalid dates and year `0000` are rejected |
| IANA zone | The backend-validated, trimmed IANA key, preserving aliases byte-for-byte after trimming (for example `America/Los_Angeles`) |
| Boolean | JSON `true` or `false`, never a numeric or textual substitute |
| JSON document | Compact, sorted-key JSON; arrays retain order; non-finite and unsafe integer values are rejected; exact nutrition decimals in documents remain strings |

The scalar codecs accept only these forms and serialize back to the same
canonical spelling. `canonicalJsonStringify` follows the backend's compact,
UTF-8, sorted-key JSON behavior for the supported JSON value set, and
`parseCanonicalJson` rejects alternate whitespace, key order, or number
spellings.

Backend response models continue to own HTTP response serialization. Values
read directly from PostgreSQL retain their existing fixed `NUMERIC` scale as
strings. Derived response values retain the backend `Decimal` result scale
(which can be finer than six places, for example `0.28349523` after a
per-100-gram conversion) and are serialized as plain decimal strings without
floating-point conversion. `decimal.ts` exposes separate response-decimal
helpers for this case; persisted values still use the three fixed storage
specifications above. UUIDs, dates, UTC instants, booleans, and JSON documents
use the forms above. No FastAPI response model or remote HTTP contract is
changed by E2-02.

## Runtime-neutral error vocabulary

`apps/mobile/src/runtime/runtimeErrorCodes.ts` freezes the category codes that
future adapters can use when no feature-specific diagnostic is available:

| Category | Stable code |
| --- | --- |
| ownership failure | `ownership_denied` |
| validation failure | `validation_failed` |
| conflict | `conflict` |
| constraint failure | `constraint_failed` |
| unavailable dependency | `dependency_unavailable` |
| unresolved mutation outcome | `mutation_unresolved` |

E2-01 remote diagnostic codes remain intact in `RuntimeError.code`; this
catalogue is additive and does not rewrite existing wire codes or user-facing
messages.

## Shared parity fixtures

`packages/shared-contracts/e2-02/parity-fixtures.json` is the cross-runtime
fixture source. It covers precision boundaries, zero, rounding, arithmetic,
invalid decimal input, UUID/date/instant/zone/boolean round trips, canonical
JSON, and representative Food, Recipe publication, Daily Log snapshot,
unknown-nutrient, idempotent-replay, and failure-outcome documents. The
focused mobile and backend tests consume the same file. The backend test
compares decimal results with `Decimal`/`ROUND_HALF_UP` and its current
canonical JSON utility; no endpoint or database change is involved.

## JavaScript `Number` audit and deferred migration

E2-02 deliberately adds codecs without changing production feature
calculations. The following existing call sites are audited and deferred to a
focused migration issue before they can become local persistence authority:

| Call site | Current use | Decision |
| --- | --- | --- |
| `features/foods/utils/amountForm.ts` | UI amount parsing and mass-to-gram display metadata, including `Number` multiplication | Defer exact conversion migration; remote backend remains authoritative |
| `features/foods/validation/foodValidation.ts` | Client-side positive/zero validation | Defer exact comparator migration; validation does not replace server checks |
| `features/recipes/utils/recipeDraft.ts` | Draft validation; payload conversion delegates mass units | Defer validation migration; `massUnits.ts` already uses `BigInt` for its bounded display conversion |
| `features/logging/validation/logValidation.ts` and `features/logging/utils/logFoodForm.ts` | Client-side quantity guards | Defer exact comparator migration; persisted nutrition remains server-owned |
| `features/targets/targetProgress.ts` and `shared/nutrition/display.ts` | Progress bounds and display formatting | UI-only; defer if reused for local authoritative calculations |
| `features/recipes/screens/RecipeFormScreen.tsx` | Display/field comparison | UI-only; no persistence authority |
| `features/foods/api/foodApi.ts` and `features/logging/utils/dailyLogDisplay.ts` | Timestamp/date parsing and ordering | Calendar/instant codec migration remains separate; no nutrition arithmetic |
| `features/usda/utils/usdaSearchQuery.ts`, OCR diagnostics, recovery counters, and navigation helpers | Integer controls, geometry/confidence display, retry metadata, or indices | Not nutrition authority; no E2-02 migration required |

No new production `Number` arithmetic was introduced. A future local feature
issue must replace the deferred nutrition conversion/validation call sites
with these codecs before writing exact values to SQLite.

## SQLite mapping reserved for E2-03

The future SQLite adapter must store all three decimal classes as `TEXT` using
the fixed-scale strings above, never `REAL`; nullable columns remain nullable.
UUIDs, instants, date-only values, IANA zones, and canonical JSON documents
are also `TEXT`. Booleans use SQLite integer `0`/`1` at the persistence edge
and are exposed as strict runtime booleans. This is a contract only: E2-02
creates no SQLite table, trigger, or migration.

## Boundary and stop condition

No SQLite schema, migration stream, local runtime, synchronization payload,
backend contract, or PostgreSQL migration is part of E2-02. If a future codec
cannot reproduce an existing PostgreSQL nutrition result or serialized
contract exactly without changing the approved domain model, work stops and
returns to architecture review.
