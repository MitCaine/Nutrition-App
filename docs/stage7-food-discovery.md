# Stage 7C: Food discovery, favorites, recents, and source labels

Stage 7C adds user-scoped discovery metadata only. Favorites and recents never change Food ownership, nutrition, serving definitions, Recipe publication, or historical log snapshots.

## Favorite policy

`food_favorites` stores one `(user_id, food_item_id)` preference with an ownership-aware foreign key. Creation and removal are idempotent. Concurrent creation recovers only the PostgreSQL `food_favorites_pkey` violation (or SQLite's exact two-column equivalent) after rollback and verification of the winning row. Every unrelated integrity failure propagates. Metadata is retained when a Food is soft-deleted, while every active favorite query joins only active, ownership-valid Foods.

Favorites are intentionally limited to Foods eligible for `GET /foods?view=saved`: Manual, scanned-label, USDA, duplicated, and supported legacy/imported Foods. Managed Recipe projections remain excluded from Saved Foods, so Recipe favorites are deferred until the product has a coherent Recipe favorites surface. Favoriting never copies a Food.

## Recent policy

Recent means actual logged use. The backend groups the current user's Daily Logs by Food and orders by the maximum immutable `DailyLog.created_at`, descending, then Food UUID ascending for deterministic ties. `logged_date`, Food update timestamps, and log update timestamps do not affect recency. Deleting the newest log automatically exposes the next remaining use.

The endpoint returns timezone-aware UTC instants. Mobile formats them in the device timezone and never announces raw ISO timestamps. The initial bounded endpoint defaults to 10 rows and accepts 1–20.

Recents use the same Saved Food eligibility boundary as favorites. Active Recipe projections remain available in compatible generic selectors with a Recipe source label but are not reintroduced into Saved Foods.

## Source classification

The backend is authoritative. Mobile does not reconstruct source kind from marker fields.

Precedence is:

1. coherent same-owner managed Recipe projection → `recipe` / **Recipe**;
2. same-owner OCR confirmation trace → `ocr_confirmed` / **Scanned label**;
3. USDA source identity → `usda` / **USDA**;
4. Manual Food with recognized duplicate provenance → `duplicate` / **Duplicated Food**;
5. ordinary Manual Food → `manual` / **Manual**;
6. otherwise supported unmanaged or unverified provenance → `legacy` / **Other source**.

Duplicate classification requires a Manual, non-Recipe Food with no publication marker or same-owner OCR trace. Its `source_id` must be the canonical UUID string written by the production duplication path and identify a different Food owned by the same user. The immediate source lookup includes soft-deleted Foods, so origin remains stable after deletion. Malformed, missing, foreign-owner, and self-referential claims fall back to `legacy` / **Other source** and the claimed ID is not returned. Classification never walks duplicate ancestry.

Presentation loads Recipe backlinks and favorite identities in bounded queries, uses the existing bounded OCR relationship load, and performs at most one additional owner-scoped Food identity query for all duplicate candidates. Detail and list responses use this same path.

Any partial or incoherent Recipe marker graph remains integrity-invalid. Direct reads retain the structured integrity error and list discovery excludes the row rather than misclassifying it as Manual.

Source labels describe creation provenance, not mutation or nutrition authority. Scanned-label and duplicated Foods remain editable Manual Foods. Responses never include OCR trace contents, image references, internal publication revisions, or foreign-user discovery metadata.

## API and invalidation

- `GET /api/v1/foods/favorites`
- `PUT /api/v1/foods/{food_id}/favorite`
- `DELETE /api/v1/foods/{food_id}/favorite`
- `GET /api/v1/foods/recent?limit=10`

Food responses add `source_kind`, `source_label`, `is_favorite`, and `can_favorite`. Recent rows add `last_used_at`.

Favorite mutations invalidate Food detail, Saved Foods, favorites, and selector caches. Food soft deletion invalidates favorites and recents through the same Food cache boundary. Log creation and deletion invalidate recents; metadata-only log updates do not.

The Saved Foods screen intentionally displays at most five rows under **Favorites preview** and five under **Recent preview**. The API retains its documented recent limit of 10 by default; the headings make the compact truncation explicit without changing full Saved Foods search behavior.
