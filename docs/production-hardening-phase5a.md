# Production Hardening Phase 5A: legacy Recipe migration safety

## Admission rule

Migration `0004_recipe_domain_foundation` replaces the pre-0004 Recipe schema. The original
migration renamed `recipes` and `recipe_ingredients`, created incompatible replacement tables, and
dropped the renamed tables without copying their rows. That operation is valid only when both
legacy tables are empty.

Before its first rename or other destructive DDL, 0004 now locks both legacy tables and checks for
rows. The upgrade proceeds only when both tables are empty. If either table contains a row, the
migration raises an explicit error stating that historical Recipe conversion is required. The
transaction rolls back and leaves the legacy schema and all rows unchanged.

## Operator implications

- New and otherwise empty databases upgrade through 0004 and onward normally.
- A database stopped at 0003 with any legacy Recipe or Recipe Ingredient data cannot upgrade
  through 0004 in this release.
- Such a populated database requires a future conversion whose mapping has been independently
  defined and proven correct. Do not delete rows merely to bypass the guard.
- A database already upgraded through the earlier destructive form of 0004 cannot recover rows
  that were discarded during that upgrade unless a usable pre-upgrade backup exists.

Phase 5A deliberately provides no historical conversion, revision repair, inventory report,
dry-run conversion, or best-effort mapping. Blocking is the intended safe behavior when the old
tables contain data.

The separate [Phase 5B inventory](production-hardening-phase5b.md) can report aggregate historical
state without changing the database; it still performs no conversion or repair.

The [Phase 5C1 bridge and planner](production-hardening-phase5c1.md) can now preserve eligible
legacy tables on an isolated conversion clone and produce a deterministic conversion manifest.
Phase 5C1 still performs no historical Recipe conversion.
