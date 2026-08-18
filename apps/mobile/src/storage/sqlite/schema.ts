/**
 * The local runtime schema is a fresh semantic model.  It is intentionally
 * not a replay of the PostgreSQL Alembic stream.
 *
 * E2-02 fixes the storage edge for exact values: nutrition decimals are TEXT
 * fixed-scale strings, UUIDs/instants/dates/zones/JSON are canonical TEXT, and
 * booleans are INTEGER 0/1.  Feature adapters are responsible for using the
 * codecs before binding values; this module only establishes the durable
 * columns and their relational guards.
 */

import { NUTRIENT_RELATIONAL_SEED_ROWS } from "../../shared/nutrition/catalog";

export const SQLITE_SCHEMA_VERSION = 7;
export const SQLITE_DATABASE_NAME = "nutrition.db";

export const SQLITE_MIGRATION_LEDGER_TABLE = "nutrition_schema_migrations";
export const SQLITE_SNAPSHOT_SCOPE_TABLE =
  "nutrition_daily_log_snapshot_replacement_scopes";

/** The nineteen semantic application tables owned by the local runtime. */
export const SQLITE_SEMANTIC_TABLES = [
  "users",
  "user_profiles",
  "nutrients",
  "food_items",
  "food_sources",
  "food_nutrients",
  "serving_definitions",
  "recipes",
  "recipe_ingredients",
  "recipe_publication_revisions",
  "recipe_publication_amount_definitions",
  "recipe_publication_nutrients",
  "daily_logs",
  "daily_log_nutrient_snapshots",
  "daily_log_day_completions",
  "food_favorites",
  "ocr_nutrition_confirmation_traces",
  "nutrition_targets",
  "create_operation_idempotency",
] as const;

export type SQLiteSemanticTable = (typeof SQLITE_SEMANTIC_TABLES)[number];

const CANONICAL_INSTANT_DEFAULT =
  "(CASE WHEN substr(strftime('%f','now'),4,3) = '000' " +
  "THEN strftime('%Y-%m-%dT%H:%M:%SZ','now') " +
  "ELSE strftime('%Y-%m-%dT%H:%M:%S','now') || '.' || " +
  "substr(strftime('%f','now'),4,3) || '000Z' END)";

const instant = () => `TEXT NOT NULL DEFAULT ${CANONICAL_INSTANT_DEFAULT}`;
const bool = (column: string, defaultValue = 0) =>
  `INTEGER NOT NULL DEFAULT ${defaultValue} CHECK ("${column}" IN (0, 1))`;

/**
 * One baseline migration creates all runtime tables, indexes, and guards in a
 * single transaction.  The statements remain separate so tests can inspect
 * the native driver's exact execution boundary and injected failures can be
 * rolled back by the migration runner.
 */
export const SQLITE_BASELINE_SCHEMA_STATEMENTS: readonly string[] = [
  `CREATE TABLE IF NOT EXISTS "users" (
    "id" TEXT PRIMARY KEY NOT NULL,
    "email" TEXT NOT NULL UNIQUE,
    "display_name" TEXT,
    "created_at" ${instant()}
  )`,

  `CREATE TABLE IF NOT EXISTS "user_profiles" (
    "user_id" TEXT PRIMARY KEY NOT NULL,
    "birth_date" TEXT,
    "height_cm" TEXT,
    "weight_kg" TEXT,
    "biological_sex_for_reference_calculations" TEXT,
    "activity_level" TEXT,
    "energy_estimation_context" TEXT NOT NULL DEFAULT 'general_adult',
    "authoritative_time_zone" TEXT,
    "calendar_revision" INTEGER NOT NULL DEFAULT 0 CHECK ("calendar_revision" >= 0),
    "created_at" ${instant()},
    "updated_at" ${instant()},
    FOREIGN KEY ("user_id") REFERENCES "users" ("id")
  )`,

  `CREATE TABLE IF NOT EXISTS "nutrients" (
    "id" TEXT PRIMARY KEY NOT NULL,
    "display_name" TEXT NOT NULL,
    "nutrient_kind" TEXT NOT NULL,
    "default_unit" TEXT NOT NULL,
    "parent_nutrient_id" TEXT,
    "display_order" INTEGER NOT NULL,
    FOREIGN KEY ("parent_nutrient_id") REFERENCES "nutrients" ("id")
  )`,

  `CREATE TABLE IF NOT EXISTS "food_items" (
    "id" TEXT PRIMARY KEY NOT NULL,
    "user_id" TEXT,
    "name" TEXT NOT NULL,
    "brand" TEXT,
    "source_type" TEXT NOT NULL,
    "source_id" TEXT,
    "recipe_publication_revision_id" TEXT,
    "is_recipe" ${bool("is_recipe")},
    "notes" TEXT,
    "created_at" ${instant()},
    "updated_at" ${instant()},
    "deleted_at" TEXT,
    CONSTRAINT "ck_food_items_publication_revision_has_owner"
      CHECK ("recipe_publication_revision_id" IS NULL OR "user_id" IS NOT NULL),
    CONSTRAINT "uq_food_items_identity_user" UNIQUE ("id", "user_id"),
    CONSTRAINT "uq_food_items_projection_identity_revision_owner"
      UNIQUE ("id", "recipe_publication_revision_id", "user_id"),
    FOREIGN KEY ("user_id") REFERENCES "users" ("id"),
    CONSTRAINT "fk_food_items_publication_revision_owner"
      FOREIGN KEY ("recipe_publication_revision_id", "user_id")
      REFERENCES "recipe_publication_revisions" ("id", "user_id")
      ON DELETE RESTRICT
  )`,

  `CREATE TABLE IF NOT EXISTS "food_sources" (
    "id" TEXT PRIMARY KEY NOT NULL,
    "food_item_id" TEXT NOT NULL,
    "source_type" TEXT NOT NULL,
    "external_id" TEXT,
    "raw_payload" TEXT,
    "metadata" TEXT,
    "created_at" ${instant()},
    FOREIGN KEY ("food_item_id") REFERENCES "food_items" ("id")
  )`,

  `CREATE TABLE IF NOT EXISTS "food_nutrients" (
    "id" TEXT PRIMARY KEY NOT NULL,
    "food_item_id" TEXT NOT NULL,
    "nutrient_id" TEXT NOT NULL,
    "amount" TEXT,
    "unit" TEXT NOT NULL,
    "basis" TEXT NOT NULL,
    "data_status" TEXT NOT NULL,
    "confidence" TEXT,
    "source" TEXT NOT NULL,
    "is_user_confirmed" ${bool("is_user_confirmed")},
    "original_amount" TEXT,
    "original_unit" TEXT,
    "original_text" TEXT,
    "created_at" ${instant()},
    "updated_at" ${instant()},
    CONSTRAINT "uq_food_nutrients_identity_food_nutrient"
      UNIQUE ("id", "food_item_id", "nutrient_id"),
    FOREIGN KEY ("food_item_id") REFERENCES "food_items" ("id"),
    FOREIGN KEY ("nutrient_id") REFERENCES "nutrients" ("id")
  )`,

  `CREATE TABLE IF NOT EXISTS "serving_definitions" (
    "id" TEXT PRIMARY KEY NOT NULL,
    "food_item_id" TEXT NOT NULL,
    "label" TEXT NOT NULL,
    "quantity" TEXT NOT NULL,
    "unit" TEXT NOT NULL,
    "gram_weight" TEXT,
    "reference_quantity" TEXT,
    "reference_unit" TEXT,
    "reference_gram_weight" TEXT,
    "is_default" ${bool("is_default")},
    "source" TEXT NOT NULL,
    "confidence" TEXT,
    "is_user_confirmed" ${bool("is_user_confirmed")},
    CONSTRAINT "uq_serving_definitions_identity_food" UNIQUE ("id", "food_item_id"),
    FOREIGN KEY ("food_item_id") REFERENCES "food_items" ("id")
  )`,

  `CREATE TABLE IF NOT EXISTS "recipes" (
    "id" TEXT PRIMARY KEY NOT NULL,
    "user_id" TEXT NOT NULL,
    "published_food_item_id" TEXT,
    "active_publication_revision_id" TEXT,
    "name" TEXT NOT NULL,
    "notes" TEXT,
    "serving_count_yield" TEXT,
    "final_cooked_weight_grams" TEXT,
    "final_cooked_weight_display_quantity" TEXT,
    "final_cooked_weight_display_unit" TEXT,
    "needs_republish" ${bool("needs_republish")},
    "created_at" ${instant()},
    "updated_at" ${instant()},
    "deleted_at" TEXT,
    CONSTRAINT "ck_recipes_serving_count_positive"
      CHECK ("serving_count_yield" IS NULL OR ("serving_count_yield" NOT LIKE '-%' AND "serving_count_yield" <> '0.000000')),
    CONSTRAINT "ck_recipes_final_weight_positive"
      CHECK ("final_cooked_weight_grams" IS NULL OR ("final_cooked_weight_grams" NOT LIKE '-%' AND "final_cooked_weight_grams" <> '0.000000')),
    CONSTRAINT "ck_recipes_publication_links_paired"
      CHECK (("published_food_item_id" IS NULL) = ("active_publication_revision_id" IS NULL)),
    CONSTRAINT "uq_recipes_id_user_id" UNIQUE ("id", "user_id"),
    FOREIGN KEY ("user_id") REFERENCES "users" ("id"),
    CONSTRAINT "fk_recipes_active_publication_revision_owner"
      FOREIGN KEY ("active_publication_revision_id", "id", "user_id")
      REFERENCES "recipe_publication_revisions" ("id", "recipe_id", "user_id")
      ON DELETE RESTRICT
      DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT "fk_recipes_publication_projection"
      FOREIGN KEY ("published_food_item_id", "active_publication_revision_id", "user_id")
      REFERENCES "food_items" ("id", "recipe_publication_revision_id", "user_id")
      DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY ("published_food_item_id") REFERENCES "food_items" ("id") ON DELETE SET NULL
  )`,

  `CREATE TABLE IF NOT EXISTS "recipe_ingredients" (
    "id" TEXT PRIMARY KEY NOT NULL,
    "user_id" TEXT NOT NULL,
    "recipe_id" TEXT NOT NULL,
    "food_item_id" TEXT NOT NULL,
    "position" INTEGER NOT NULL,
    "amount_quantity" TEXT NOT NULL,
    "amount_unit" TEXT NOT NULL,
    "amount_display_quantity" TEXT,
    "amount_display_unit" TEXT,
    "serving_definition_id" TEXT,
    "resolved_gram_amount" TEXT,
    "preparation_note" TEXT,
    CONSTRAINT "uq_recipe_ingredients_recipe_position" UNIQUE ("recipe_id", "position"),
    CONSTRAINT "fk_recipe_ingredients_recipe_owner"
      FOREIGN KEY ("recipe_id", "user_id") REFERENCES "recipes" ("id", "user_id")
      ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT "fk_recipe_ingredients_food_owner"
      FOREIGN KEY ("food_item_id", "user_id") REFERENCES "food_items" ("id", "user_id")
      DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT "fk_recipe_ingredients_serving_food"
      FOREIGN KEY ("serving_definition_id", "food_item_id")
      REFERENCES "serving_definitions" ("id", "food_item_id")
      DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT "ck_recipe_ingredients_amount_positive"
      CHECK ("amount_quantity" NOT LIKE '-%' AND "amount_quantity" <> '0.000000'),
    CONSTRAINT "ck_recipe_ingredients_grams_positive"
      CHECK ("resolved_gram_amount" IS NULL OR ("resolved_gram_amount" NOT LIKE '-%' AND "resolved_gram_amount" <> '0.000000')),
    FOREIGN KEY ("recipe_id") REFERENCES "recipes" ("id") ON DELETE CASCADE,
    FOREIGN KEY ("food_item_id") REFERENCES "food_items" ("id"),
    FOREIGN KEY ("serving_definition_id") REFERENCES "serving_definitions" ("id") ON DELETE SET NULL
  )`,

  `CREATE TABLE IF NOT EXISTS "recipe_publication_revisions" (
    "id" TEXT PRIMARY KEY NOT NULL,
    "recipe_id" TEXT NOT NULL,
    "user_id" TEXT NOT NULL,
    "revision_number" INTEGER NOT NULL,
    "published_at" ${instant()},
    "creation_origin" TEXT NOT NULL,
    "provenance_confidence" TEXT NOT NULL,
    "published_name" TEXT NOT NULL,
    "published_notes" TEXT,
    "content_digest" TEXT NOT NULL,
    CONSTRAINT "uq_recipe_publication_revision_number"
      UNIQUE ("recipe_id", "revision_number"),
    CONSTRAINT "uq_recipe_publication_revision_identity_owner"
      UNIQUE ("id", "recipe_id", "user_id"),
    CONSTRAINT "uq_recipe_publication_revision_identity_user"
      UNIQUE ("id", "user_id"),
    CONSTRAINT "ck_recipe_publication_revision_number_positive" CHECK ("revision_number" > 0),
    CONSTRAINT "ck_recipe_publication_revision_origin"
      CHECK ("creation_origin" IN ('normal_publication', 'explicit_republish', 'legacy_projection_capture')),
    CONSTRAINT "ck_recipe_publication_revision_provenance"
      CHECK ("provenance_confidence" IN ('complete', 'transition_baseline', 'partial', 'ambiguous')),
    CONSTRAINT "fk_recipe_publication_revision_recipe_owner"
      FOREIGN KEY ("recipe_id", "user_id") REFERENCES "recipes" ("id", "user_id")
      ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY ("user_id") REFERENCES "users" ("id") ON DELETE RESTRICT
  )`,

  `CREATE TABLE IF NOT EXISTS "recipe_publication_amount_definitions" (
    "id" TEXT PRIMARY KEY NOT NULL,
    "revision_id" TEXT NOT NULL,
    "display_order" INTEGER NOT NULL,
    "display_label" TEXT NOT NULL,
    "semantic_mode" TEXT NOT NULL,
    "display_quantity" TEXT,
    "display_unit" TEXT NOT NULL,
    "gram_equivalent" TEXT,
    "is_default" ${bool("is_default")},
    "conversion_metadata" TEXT,
    CONSTRAINT "uq_recipe_publication_amount_identity_revision" UNIQUE ("id", "revision_id"),
    CONSTRAINT "uq_recipe_publication_amount_order" UNIQUE ("revision_id", "display_order"),
    CONSTRAINT "uq_recipe_publication_amount_semantic_label"
      UNIQUE ("revision_id", "semantic_mode", "display_label"),
    CONSTRAINT "ck_recipe_publication_amount_order_nonnegative" CHECK ("display_order" >= 0),
    CONSTRAINT "ck_recipe_publication_amount_semantic_mode" CHECK ("semantic_mode" IN ('serving', 'g')),
    CONSTRAINT "ck_recipe_publication_amount_mode_shape"
      CHECK (("semantic_mode" = 'g' AND "display_quantity" IS NULL AND "display_unit" = 'g' AND "gram_equivalent" IS NULL)
        OR ("semantic_mode" = 'serving' AND "display_quantity" IS NOT NULL AND "display_quantity" NOT LIKE '-%' AND "display_quantity" <> '0.000000')),
    CONSTRAINT "ck_recipe_publication_amount_grams_positive"
      CHECK ("gram_equivalent" IS NULL OR ("gram_equivalent" NOT LIKE '-%' AND "gram_equivalent" <> '0.000000')),
    FOREIGN KEY ("revision_id") REFERENCES "recipe_publication_revisions" ("id") ON DELETE RESTRICT
  )`,

  `CREATE TABLE IF NOT EXISTS "recipe_publication_nutrients" (
    "id" TEXT PRIMARY KEY NOT NULL,
    "revision_id" TEXT NOT NULL,
    "nutrient_id" TEXT NOT NULL,
    "amount" TEXT,
    "unit" TEXT NOT NULL,
    "basis" TEXT NOT NULL,
    "data_status" TEXT NOT NULL,
    "diagnostic_provenance" TEXT,
    CONSTRAINT "uq_recipe_publication_nutrient_identity_basis"
      UNIQUE ("revision_id", "nutrient_id", "basis"),
    CONSTRAINT "ck_recipe_publication_nutrient_basis"
      CHECK ("basis" IN ('per_serving', 'per_100g', 'per_gram')),
    CONSTRAINT "ck_recipe_publication_nutrient_status"
      CHECK ("data_status" IN ('known', 'estimated', 'unknown', 'zero')),
    CONSTRAINT "ck_recipe_publication_nutrient_nonnegative"
      CHECK ("amount" IS NULL OR "amount" NOT LIKE '-%'),
    CONSTRAINT "ck_recipe_publication_nutrient_status_amount"
      CHECK (("data_status" = 'unknown' AND "amount" IS NULL)
        OR ("data_status" = 'zero' AND "amount" = '0.000000')
        OR ("data_status" IN ('known', 'estimated') AND "amount" IS NOT NULL)),
    FOREIGN KEY ("revision_id") REFERENCES "recipe_publication_revisions" ("id") ON DELETE RESTRICT,
    FOREIGN KEY ("nutrient_id") REFERENCES "nutrients" ("id") ON DELETE RESTRICT
  )`,

  `CREATE TABLE IF NOT EXISTS "daily_logs" (
    "id" TEXT PRIMARY KEY NOT NULL,
    "user_id" TEXT NOT NULL,
    "food_item_id" TEXT NOT NULL,
    "food_name_snapshot" TEXT,
    "client_request_id" TEXT,
    "client_request_fingerprint" TEXT,
    "logged_date" TEXT NOT NULL,
    "meal_type" TEXT,
    "amount_quantity" TEXT NOT NULL,
    "amount_unit" TEXT NOT NULL,
    "serving_definition_id" TEXT,
    "recipe_publication_revision_id" TEXT,
    "recipe_publication_amount_definition_id" TEXT,
    "gram_amount" TEXT,
    "package_fraction" TEXT,
    "notes" TEXT,
    "created_at" ${instant()},
    "updated_at" ${instant()},
    CONSTRAINT "ck_daily_logs_publication_links_paired"
      CHECK (("recipe_publication_revision_id" IS NULL AND "recipe_publication_amount_definition_id" IS NULL)
        OR ("recipe_publication_revision_id" IS NOT NULL AND "recipe_publication_amount_definition_id" IS NOT NULL)),
    CONSTRAINT "fk_daily_logs_publication_revision_owner"
      FOREIGN KEY ("recipe_publication_revision_id", "user_id")
      REFERENCES "recipe_publication_revisions" ("id", "user_id") ON DELETE RESTRICT
      DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT "fk_daily_logs_food_owner"
      FOREIGN KEY ("food_item_id", "user_id") REFERENCES "food_items" ("id", "user_id")
      DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT "fk_daily_logs_serving_food"
      FOREIGN KEY ("serving_definition_id", "food_item_id")
      REFERENCES "serving_definitions" ("id", "food_item_id")
      DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT "uq_daily_logs_identity_food" UNIQUE ("id", "food_item_id"),
    CONSTRAINT "ck_daily_logs_client_request_paired"
      CHECK (("client_request_id" IS NULL AND "client_request_fingerprint" IS NULL)
        OR ("client_request_id" IS NOT NULL AND "client_request_fingerprint" IS NOT NULL)),
    CONSTRAINT "uq_daily_logs_user_client_request" UNIQUE ("user_id", "client_request_id"),
    CONSTRAINT "fk_daily_logs_publication_amount_membership"
      FOREIGN KEY ("recipe_publication_amount_definition_id", "recipe_publication_revision_id")
      REFERENCES "recipe_publication_amount_definitions" ("id", "revision_id") ON DELETE RESTRICT,
    FOREIGN KEY ("user_id") REFERENCES "users" ("id"),
    FOREIGN KEY ("food_item_id") REFERENCES "food_items" ("id"),
    FOREIGN KEY ("serving_definition_id") REFERENCES "serving_definitions" ("id") ON DELETE SET NULL
  )`,

  `CREATE TABLE IF NOT EXISTS "daily_log_nutrient_snapshots" (
    "id" TEXT PRIMARY KEY NOT NULL,
    "daily_log_id" TEXT NOT NULL,
    "source_food_item_id" TEXT NOT NULL,
    "source_food_nutrient_id" TEXT,
    "serving_definition_id" TEXT,
    "nutrient_id" TEXT NOT NULL,
    "amount" TEXT,
    "unit" TEXT NOT NULL,
    "data_status" TEXT NOT NULL,
    "consumed_amount_quantity" TEXT NOT NULL,
    "consumed_amount_unit" TEXT NOT NULL,
    "consumed_gram_amount" TEXT,
    "consumed_package_fraction" TEXT,
    "calculation_metadata" TEXT,
    CONSTRAINT "fk_log_snapshots_daily_log_food"
      FOREIGN KEY ("daily_log_id", "source_food_item_id")
      REFERENCES "daily_logs" ("id", "food_item_id") DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT "fk_log_snapshots_source_nutrient_food_identity"
      FOREIGN KEY ("source_food_nutrient_id", "source_food_item_id", "nutrient_id")
      REFERENCES "food_nutrients" ("id", "food_item_id", "nutrient_id") DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT "fk_log_snapshots_serving_food"
      FOREIGN KEY ("serving_definition_id", "source_food_item_id")
      REFERENCES "serving_definitions" ("id", "food_item_id") DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY ("daily_log_id") REFERENCES "daily_logs" ("id"),
    FOREIGN KEY ("source_food_item_id") REFERENCES "food_items" ("id"),
    FOREIGN KEY ("source_food_nutrient_id") REFERENCES "food_nutrients" ("id") ON DELETE SET NULL,
    FOREIGN KEY ("serving_definition_id") REFERENCES "serving_definitions" ("id") ON DELETE SET NULL,
    FOREIGN KEY ("nutrient_id") REFERENCES "nutrients" ("id")
  )`,

  `CREATE TABLE IF NOT EXISTS "daily_log_day_completions" (
    "logged_date" TEXT PRIMARY KEY NOT NULL,
    "completed_at" TEXT NOT NULL
  )`,

  `CREATE TABLE IF NOT EXISTS "food_favorites" (
    "user_id" TEXT NOT NULL,
    "food_item_id" TEXT NOT NULL,
    "created_at" ${instant()},
    PRIMARY KEY ("user_id", "food_item_id"),
    CONSTRAINT "fk_food_favorites_food_owner"
      FOREIGN KEY ("food_item_id", "user_id") REFERENCES "food_items" ("id", "user_id") ON DELETE RESTRICT,
    FOREIGN KEY ("user_id") REFERENCES "users" ("id")
  )`,

  `CREATE TABLE IF NOT EXISTS "ocr_nutrition_confirmation_traces" (
    "id" TEXT PRIMARY KEY NOT NULL,
    "user_id" TEXT NOT NULL,
    "food_item_id" TEXT NOT NULL,
    "parser_version" TEXT NOT NULL,
    "image_source_type" TEXT NOT NULL,
    "schema_version" TEXT NOT NULL,
    "trace_snapshot" TEXT NOT NULL,
    "client_request_id" TEXT NOT NULL,
    "request_fingerprint" TEXT NOT NULL,
    "confirmed_at" ${instant()},
    CONSTRAINT "uq_ocr_confirmation_food" UNIQUE ("food_item_id"),
    CONSTRAINT "uq_ocr_confirmation_user_request" UNIQUE ("user_id", "client_request_id"),
    CONSTRAINT "fk_ocr_confirmation_traces_food_owner"
      FOREIGN KEY ("food_item_id", "user_id") REFERENCES "food_items" ("id", "user_id"),
    FOREIGN KEY ("user_id") REFERENCES "users" ("id"),
    FOREIGN KEY ("food_item_id") REFERENCES "food_items" ("id")
  )`,

  `CREATE TABLE IF NOT EXISTS "nutrition_targets" (
    "id" TEXT PRIMARY KEY NOT NULL,
    "user_id" TEXT NOT NULL,
    "target_type" TEXT NOT NULL,
    "nutrient_id" TEXT NOT NULL,
    "min_amount" TEXT,
    "target_amount" TEXT,
    "max_amount" TEXT,
    "unit" TEXT NOT NULL,
    "basis" TEXT NOT NULL,
    "source" TEXT NOT NULL,
    "metadata" TEXT,
    "created_at" ${instant()},
    "updated_at" ${instant()},
    CONSTRAINT "uq_nutrition_target_user_type_nutrient"
      UNIQUE ("user_id", "target_type", "nutrient_id"),
    FOREIGN KEY ("user_id") REFERENCES "users" ("id"),
    FOREIGN KEY ("nutrient_id") REFERENCES "nutrients" ("id")
  )`,

  `CREATE TABLE IF NOT EXISTS "create_operation_idempotency" (
    "id" TEXT PRIMARY KEY NOT NULL,
    "user_id" TEXT NOT NULL,
    "operation" TEXT NOT NULL,
    "client_request_id" TEXT NOT NULL,
    "request_fingerprint" TEXT NOT NULL,
    "resource_id" TEXT NOT NULL,
    "response_snapshot" TEXT,
    "completed_at" TEXT,
    "created_at" ${instant()},
    CONSTRAINT "uq_create_idempotency_user_operation_request"
      UNIQUE ("user_id", "operation", "client_request_id"),
    CONSTRAINT "ck_create_idempotency_completion_paired"
      CHECK (("response_snapshot" IS NULL AND "completed_at" IS NULL)
        OR ("response_snapshot" IS NOT NULL AND "completed_at" IS NOT NULL)),
    FOREIGN KEY ("user_id") REFERENCES "users" ("id")
  )`,

  // This is an internal guard table, not a feature or operational authority.
  // Rows are created and removed inside the same replacement transaction.  It
  // deliberately has no foreign key to daily_logs: an approved owner/log
  // delete removes the snapshots before deleting the log, then the helper
  // validates and removes this row before commit.
  `CREATE TABLE IF NOT EXISTS "${SQLITE_SNAPSHOT_SCOPE_TABLE}" (
    "user_id" TEXT NOT NULL,
    "daily_log_id" TEXT NOT NULL,
    "original_snapshot_count" INTEGER NOT NULL CHECK ("original_snapshot_count" >= 0),
    "deleted_snapshot_count" INTEGER NOT NULL DEFAULT 0 CHECK ("deleted_snapshot_count" >= 0),
    "header_touched" INTEGER NOT NULL DEFAULT 0 CHECK ("header_touched" IN (0, 1)),
    PRIMARY KEY ("user_id", "daily_log_id")
  )`,

  `CREATE INDEX IF NOT EXISTS "ix_food_sources_food_item_id"
    ON "food_sources" ("food_item_id")`,
  `CREATE INDEX IF NOT EXISTS "ix_food_nutrients_food_item_id"
    ON "food_nutrients" ("food_item_id")`,
  `CREATE INDEX IF NOT EXISTS "ix_serving_definitions_food_item_id"
    ON "serving_definitions" ("food_item_id")`,
  `CREATE INDEX IF NOT EXISTS "ix_recipe_ingredients_food_item_id"
    ON "recipe_ingredients" ("food_item_id")`,
  `CREATE INDEX IF NOT EXISTS "ix_recipe_ingredients_serving_definition_id"
    ON "recipe_ingredients" ("serving_definition_id")`,
  `CREATE INDEX IF NOT EXISTS "ix_recipe_ingredients_recipe_owner"
    ON "recipe_ingredients" ("recipe_id", "user_id")`,
  `CREATE INDEX IF NOT EXISTS "ix_recipe_ingredients_food_owner"
    ON "recipe_ingredients" ("food_item_id", "user_id")`,
  `CREATE INDEX IF NOT EXISTS "ix_recipe_ingredients_serving_food"
    ON "recipe_ingredients" ("serving_definition_id", "food_item_id")`,
  `CREATE INDEX IF NOT EXISTS "ix_recipes_publication_projection"
    ON "recipes" ("published_food_item_id", "active_publication_revision_id", "user_id")`,
  `CREATE INDEX IF NOT EXISTS "ix_daily_logs_food_owner"
    ON "daily_logs" ("food_item_id", "user_id")`,
  `CREATE INDEX IF NOT EXISTS "ix_daily_logs_serving_food"
    ON "daily_logs" ("serving_definition_id", "food_item_id")`,
  `CREATE INDEX IF NOT EXISTS "ix_log_snapshots_daily_log_food"
    ON "daily_log_nutrient_snapshots" ("daily_log_id", "source_food_item_id")`,
  `CREATE INDEX IF NOT EXISTS "ix_log_snapshots_source_nutrient_food"
    ON "daily_log_nutrient_snapshots" ("source_food_nutrient_id", "source_food_item_id", "nutrient_id")`,
  `CREATE INDEX IF NOT EXISTS "ix_log_snapshots_serving_food"
    ON "daily_log_nutrient_snapshots" ("serving_definition_id", "source_food_item_id")`,

  `CREATE UNIQUE INDEX IF NOT EXISTS "uq_serving_definitions_one_default_per_food"
    ON "serving_definitions" ("food_item_id") WHERE "is_default" = 1`,
  `CREATE UNIQUE INDEX IF NOT EXISTS "uq_food_items_publication_revision_projection"
    ON "food_items" ("recipe_publication_revision_id")
    WHERE "recipe_publication_revision_id" IS NOT NULL`,
  `CREATE UNIQUE INDEX IF NOT EXISTS "ix_food_items_active_source_identity"
    ON "food_items" ("user_id", "source_type", "source_id")
    WHERE "deleted_at" IS NULL AND "source_id" IS NOT NULL AND "source_type" != 'manual'`,
  `CREATE INDEX IF NOT EXISTS "ix_food_items_source_identity_all"
    ON "food_items" ("user_id", "source_type", "source_id")`,
  `CREATE UNIQUE INDEX IF NOT EXISTS "uq_recipe_publication_amount_one_gram_mode"
    ON "recipe_publication_amount_definitions" ("revision_id") WHERE "semantic_mode" = 'g'`,
  `CREATE UNIQUE INDEX IF NOT EXISTS "uq_recipe_publication_amount_one_default"
    ON "recipe_publication_amount_definitions" ("revision_id") WHERE "is_default" = 1`,

  `CREATE TRIGGER IF NOT EXISTS "nutrition_snapshot_scope_validate_insert"
    BEFORE INSERT ON "${SQLITE_SNAPSHOT_SCOPE_TABLE}"
    WHEN NOT EXISTS (
      SELECT 1 FROM "daily_logs"
      WHERE "id" = NEW."daily_log_id" AND "user_id" = NEW."user_id"
    ) OR NEW."original_snapshot_count" IS NOT (
      SELECT COUNT(*) FROM "daily_log_nutrient_snapshots"
      WHERE "daily_log_id" = NEW."daily_log_id"
    )
    BEGIN
      SELECT RAISE(ABORT, 'sqlite_snapshot_scope_owner_mismatch');
    END`,

  ...immutableTriggerStatements(
    "recipe_publication_revisions",
    "phase0020_revision",
  ),
  ...immutableTriggerStatements(
    "recipe_publication_nutrients",
    "phase0020_revision_nutrient",
  ),
  ...immutableTriggerStatements(
    "recipe_publication_amount_definitions",
    "phase0020_revision_amount",
  ),
  ...immutableTriggerStatements(
    "ocr_nutrition_confirmation_traces",
    "phase0020_ocr_trace",
  ),

  `CREATE TRIGGER IF NOT EXISTS "phase0020_snapshot_immutable_update"
    BEFORE UPDATE ON "daily_log_nutrient_snapshots"
    WHEN NOT (
      OLD."id" IS NEW."id"
      AND OLD."daily_log_id" IS NEW."daily_log_id"
      AND OLD."source_food_item_id" IS NEW."source_food_item_id"
      AND OLD."nutrient_id" IS NEW."nutrient_id"
      AND OLD."amount" IS NEW."amount"
      AND OLD."unit" IS NEW."unit"
      AND OLD."data_status" IS NEW."data_status"
      AND OLD."consumed_amount_quantity" IS NEW."consumed_amount_quantity"
      AND OLD."consumed_amount_unit" IS NEW."consumed_amount_unit"
      AND OLD."consumed_gram_amount" IS NEW."consumed_gram_amount"
      AND OLD."consumed_package_fraction" IS NEW."consumed_package_fraction"
      AND OLD."calculation_metadata" IS NEW."calculation_metadata"
      AND (
        OLD."source_food_nutrient_id" IS NOT NEW."source_food_nutrient_id"
        OR OLD."serving_definition_id" IS NOT NEW."serving_definition_id"
      )
      AND (
        OLD."source_food_nutrient_id" IS NEW."source_food_nutrient_id"
        OR (OLD."source_food_nutrient_id" IS NOT NULL AND NEW."source_food_nutrient_id" IS NULL
          AND NOT EXISTS (SELECT 1 FROM "food_nutrients" WHERE "id" = OLD."source_food_nutrient_id"))
      )
      AND (
        OLD."serving_definition_id" IS NEW."serving_definition_id"
        OR (OLD."serving_definition_id" IS NOT NULL AND NEW."serving_definition_id" IS NULL
          AND NOT EXISTS (SELECT 1 FROM "serving_definitions" WHERE "id" = OLD."serving_definition_id"))
      )
    )
    BEGIN
      SELECT RAISE(ABORT, 'phase0020_snapshot_immutable_update');
    END`,

  `CREATE TRIGGER IF NOT EXISTS "phase0020_snapshot_immutable_delete"
    BEFORE DELETE ON "daily_log_nutrient_snapshots"
    WHEN EXISTS (SELECT 1 FROM "daily_logs" WHERE "id" = OLD."daily_log_id")
      AND NOT EXISTS (
        SELECT 1 FROM "${SQLITE_SNAPSHOT_SCOPE_TABLE}"
        WHERE "user_id" = (SELECT "user_id" FROM "daily_logs" WHERE "id" = OLD."daily_log_id")
          AND "daily_log_id" = OLD."daily_log_id"
      )
    BEGIN
      SELECT RAISE(ABORT, 'phase0020_snapshot_immutable_delete');
    END`,

  `CREATE TRIGGER IF NOT EXISTS "phase0020_snapshot_replacement_delete_count"
    AFTER DELETE ON "daily_log_nutrient_snapshots"
    WHEN EXISTS (
      SELECT 1 FROM "${SQLITE_SNAPSHOT_SCOPE_TABLE}"
      WHERE "daily_log_id" = OLD."daily_log_id"
    )
    BEGIN
      UPDATE "${SQLITE_SNAPSHOT_SCOPE_TABLE}"
      SET "deleted_snapshot_count" = "deleted_snapshot_count" + 1
      WHERE "daily_log_id" = OLD."daily_log_id";
    END`,

  `CREATE TRIGGER IF NOT EXISTS "phase0020_daily_log_immutable_update"
    BEFORE UPDATE ON "daily_logs"
    WHEN OLD."id" IS NOT NEW."id"
      OR OLD."user_id" IS NOT NEW."user_id"
      OR OLD."food_item_id" IS NOT NEW."food_item_id"
      OR OLD."food_name_snapshot" IS NOT NEW."food_name_snapshot"
      OR OLD."client_request_id" IS NOT NEW."client_request_id"
      OR OLD."client_request_fingerprint" IS NOT NEW."client_request_fingerprint"
      OR OLD."created_at" IS NOT NEW."created_at"
      OR (
        NOT (
          OLD."amount_quantity" IS NEW."amount_quantity"
          AND OLD."amount_unit" IS NEW."amount_unit"
          AND OLD."serving_definition_id" IS NEW."serving_definition_id"
          AND OLD."recipe_publication_revision_id" IS NEW."recipe_publication_revision_id"
          AND OLD."recipe_publication_amount_definition_id" IS NEW."recipe_publication_amount_definition_id"
          AND OLD."gram_amount" IS NEW."gram_amount"
          AND OLD."package_fraction" IS NEW."package_fraction"
        )
        AND NOT EXISTS (
          SELECT 1 FROM "${SQLITE_SNAPSHOT_SCOPE_TABLE}"
          WHERE "user_id" = OLD."user_id" AND "daily_log_id" = OLD."id"
        )
        AND NOT (
          OLD."serving_definition_id" IS NOT NULL
          AND NEW."serving_definition_id" IS NULL
          AND NOT EXISTS (
            SELECT 1 FROM "serving_definitions"
            WHERE "id" = OLD."serving_definition_id"
          )
          AND OLD."id" IS NEW."id"
          AND OLD."user_id" IS NEW."user_id"
          AND OLD."food_item_id" IS NEW."food_item_id"
          AND OLD."food_name_snapshot" IS NEW."food_name_snapshot"
          AND OLD."client_request_id" IS NEW."client_request_id"
          AND OLD."client_request_fingerprint" IS NEW."client_request_fingerprint"
          AND OLD."logged_date" IS NEW."logged_date"
          AND OLD."meal_type" IS NEW."meal_type"
          AND OLD."amount_quantity" IS NEW."amount_quantity"
          AND OLD."amount_unit" IS NEW."amount_unit"
          AND OLD."recipe_publication_revision_id" IS NEW."recipe_publication_revision_id"
          AND OLD."recipe_publication_amount_definition_id" IS NEW."recipe_publication_amount_definition_id"
          AND OLD."gram_amount" IS NEW."gram_amount"
          AND OLD."package_fraction" IS NEW."package_fraction"
          AND OLD."notes" IS NEW."notes"
          AND OLD."created_at" IS NEW."created_at"
          AND OLD."updated_at" IS NEW."updated_at"
        )
      )
    BEGIN
      SELECT RAISE(ABORT, 'phase0020_daily_log_immutable_update');
    END`,

  `CREATE TRIGGER IF NOT EXISTS "phase0020_daily_log_replacement_header_touched"
    AFTER UPDATE ON "daily_logs"
    WHEN EXISTS (
      SELECT 1 FROM "${SQLITE_SNAPSHOT_SCOPE_TABLE}"
      WHERE "user_id" = OLD."user_id" AND "daily_log_id" = OLD."id"
    )
      AND NOT EXISTS (
        SELECT 1 FROM "daily_log_nutrient_snapshots"
        WHERE "daily_log_id" = OLD."id"
      )
      AND NOT (
        OLD."serving_definition_id" IS NOT NULL
        AND NEW."serving_definition_id" IS NULL
        AND NOT EXISTS (
          SELECT 1 FROM "serving_definitions"
          WHERE "id" = OLD."serving_definition_id"
        )
        AND OLD."id" IS NEW."id"
        AND OLD."user_id" IS NEW."user_id"
        AND OLD."food_item_id" IS NEW."food_item_id"
        AND OLD."food_name_snapshot" IS NEW."food_name_snapshot"
        AND OLD."client_request_id" IS NEW."client_request_id"
        AND OLD."client_request_fingerprint" IS NEW."client_request_fingerprint"
        AND OLD."logged_date" IS NEW."logged_date"
        AND OLD."meal_type" IS NEW."meal_type"
        AND OLD."amount_quantity" IS NEW."amount_quantity"
        AND OLD."amount_unit" IS NEW."amount_unit"
        AND OLD."recipe_publication_revision_id" IS NEW."recipe_publication_revision_id"
        AND OLD."recipe_publication_amount_definition_id" IS NEW."recipe_publication_amount_definition_id"
        AND OLD."gram_amount" IS NEW."gram_amount"
        AND OLD."package_fraction" IS NEW."package_fraction"
        AND OLD."notes" IS NEW."notes"
        AND OLD."created_at" IS NEW."created_at"
        AND OLD."updated_at" IS NEW."updated_at"
      )
    BEGIN
      UPDATE "${SQLITE_SNAPSHOT_SCOPE_TABLE}"
      SET "header_touched" = 1
      WHERE "user_id" = OLD."user_id" AND "daily_log_id" = OLD."id";
    END`,
];

function immutableTriggerStatements(table: string, prefix: string): string[] {
  return [
    `CREATE TRIGGER IF NOT EXISTS "${prefix}_immutable_update"
      BEFORE UPDATE ON "${table}"
      BEGIN
        SELECT RAISE(ABORT, 'phase0020_immutable_row_mutation');
      END`,
    `CREATE TRIGGER IF NOT EXISTS "${prefix}_immutable_delete"
      BEFORE DELETE ON "${table}"
      BEGIN
        SELECT RAISE(ABORT, 'phase0020_immutable_row_mutation');
      END`,
  ];
}

export const SQLITE_NUTRIENT_SEED_ROWS =
  NUTRIENT_RELATIONAL_SEED_ROWS;