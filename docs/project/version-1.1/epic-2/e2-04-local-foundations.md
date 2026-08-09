# E2-04 — Local identity, calendar, and nutrient foundations

The local foundation is layered on the E2-03 SQLite schema without adding a
new table or selecting a runtime in the application provider. The single
durable row in `users` is the local runtime/owner UUID; bootstrap creates it
and its `user_profiles` row atomically, reuses it on reopen, and rejects a
database containing more than one owner candidate. The local authority scope
is derived as `local:<owner_uuid>` and does not use HTTP authentication.

`ensureLocalNutrientCatalog` fills only missing canonical rows from the frozen
E2-03 seed and then compares every catalog field, parent, and display order.
Changed, extra, or otherwise incompatible rows raise a non-retryable local
integrity error; no existing value is overwritten.

`LocalCalendarRuntime` implements the existing `CalendarRuntime` contract.
It stores only the confirmed IANA zone and revision in `user_profiles`, derives
`today` at read time, and leaves the device zone to the existing provisional
UI context. First establishment increments the revision, repeating the same
explicit establishment is idempotent, and a different zone requires a
preview/confirmation. Preview and confirmation use the same owner-scoped
Daily Log impact filter, ordering, Python-compatible `ensure_ascii` payload
serialization, and SHA-256 token as the remote service. Confirmation rechecks
the revision and token inside an isolated EXCLUSIVE SQLite transaction and
never changes Daily Log rows. Establishment, confirmation, and mutation
preconditions sample the authoritative clock only after that transaction
boundary is acquired.

The local precondition helpers mirror the remote confirmation, revision, and
future-date checks for later Daily Log adapters. All invariant-sensitive local
operations use the E2-03 exclusive transaction helper and the supplied native
transaction object. Feature adapters, Daily Logs, runtime selection, and
synchronization remain later Epic 2 work.
