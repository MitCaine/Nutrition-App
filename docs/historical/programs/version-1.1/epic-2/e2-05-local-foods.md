# E2-05 — Local Foods, servings, and nutrition resolution

The local Food adapter composes the existing E2-03 SQLite schema and E2-04
owner identity. It does not add a migration or change the schema version. All
Food mutations run through the isolated EXCLUSIVE SQLite transaction helper
and use the supplied transaction object for every read and write.

Food definitions are owner-scoped, use the existing active source identity
index, and are soft-deleted rather than physically removed. Manual Foods may
be created, searched, updated, duplicated, and deleted; duplicate provenance
points at the same-owner source Food. Generated Recipe Foods are classified as
read-only projections and are excluded from the saved-Food view. Favorites,
recent Foods, Recipe authoring, USDA network behavior, Daily Logs, and
historical recalculation remain outside this issue.

Serving and nutrient replacement deletes and recreates the complete child set
inside the same transaction. A failure injected after the Food, serving, or
nutrient stage aborts the transaction, so no partial generation is committed.
Inputs are validated with the E2-02 fixed-scale decimal codecs. Nutrient rows
retain known, estimated, zero, and unknown status; zero is stored as the
canonical fixed-scale zero and unknown values remain nullable.

Resolved Food amounts mirror the remote serving-resolution rules. A household
serving converts to grams only when its explicit `gram_weight` exists. Basis
selection and derived values use the BigInt-backed response decimal helpers;
no JavaScript Number participates in persisted or authoritative nutrition
calculation.
