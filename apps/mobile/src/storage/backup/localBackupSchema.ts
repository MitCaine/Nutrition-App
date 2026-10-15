import { SQLITE_BASELINE_SCHEMA_STATEMENTS } from "../sqlite/schema";

/**
 * Complete SQLite column contract for every backup schema version admitted by
 * this app. Column order is intentionally absent: migration 003 adds nullable
 * serving reference columns at the end for upgraded databases.
 *
 * The version-7 column contract, unchanged in index-only version 8, is derived from the current fresh baseline plus the
 * migration ledger and migration 007 table. Migration 003 adds the same three
 * nullable TEXT columns to populated upgrades. Keep this backup-only contract
 * aligned with those executable schema sources; do not edit migration history
 * to change admission.
 *
 * A null default means no SQL DEFAULT clause. The string "NULL" would mean an
 * explicit SQL NULL default and is deliberately distinct.
 */
export type LocalBackupColumnRequirement = Readonly<{
  name: string;
  declaredType: string;
  notNull: boolean;
  primaryKeyPosition: number;
  defaultSql: string | null;
}>;

const CANONICAL_INSTANT_DEFAULT =
  "CASE WHEN substr(strftime('%f','now'),4,3) = '000' THEN strftime('%Y-%m-%dT%H:%M:%SZ','now') ELSE strftime('%Y-%m-%dT%H:%M:%S','now') || '.' || substr(strftime('%f','now'),4,3) || '000Z' END";

function column(
  name: string,
  declaredType: string,
  notNull: boolean,
  primaryKeyPosition: number,
  defaultSql: string | null,
): LocalBackupColumnRequirement {
  return Object.freeze({
    name,
    declaredType,
    notNull,
    primaryKeyPosition,
    defaultSql,
  });
}

function schemaTable(
  columns: readonly LocalBackupColumnRequirement[],
): readonly LocalBackupColumnRequirement[] {
  return Object.freeze(columns);
}

const VERSION_7_COLUMN_REQUIREMENTS = Object.freeze({
    users: schemaTable([
      column("id", "TEXT", true, 1, null),
      column("email", "TEXT", true, 0, null),
      column("display_name", "TEXT", false, 0, null),
      column("created_at", "TEXT", true, 0, CANONICAL_INSTANT_DEFAULT),
    ]),
    user_profiles: schemaTable([
      column("user_id", "TEXT", true, 1, null),
      column("birth_date", "TEXT", false, 0, null),
      column("height_cm", "TEXT", false, 0, null),
      column("weight_kg", "TEXT", false, 0, null),
      column("biological_sex_for_reference_calculations", "TEXT", false, 0, null),
      column("activity_level", "TEXT", false, 0, null),
      column("energy_estimation_context", "TEXT", true, 0, "'general_adult'"),
      column("authoritative_time_zone", "TEXT", false, 0, null),
      column("calendar_revision", "INTEGER", true, 0, "0"),
      column("created_at", "TEXT", true, 0, CANONICAL_INSTANT_DEFAULT),
      column("updated_at", "TEXT", true, 0, CANONICAL_INSTANT_DEFAULT),
    ]),
    nutrients: schemaTable([
      column("id", "TEXT", true, 1, null),
      column("display_name", "TEXT", true, 0, null),
      column("nutrient_kind", "TEXT", true, 0, null),
      column("default_unit", "TEXT", true, 0, null),
      column("parent_nutrient_id", "TEXT", false, 0, null),
      column("display_order", "INTEGER", true, 0, null),
    ]),
    food_items: schemaTable([
      column("id", "TEXT", true, 1, null),
      column("user_id", "TEXT", false, 0, null),
      column("name", "TEXT", true, 0, null),
      column("brand", "TEXT", false, 0, null),
      column("source_type", "TEXT", true, 0, null),
      column("source_id", "TEXT", false, 0, null),
      column("recipe_publication_revision_id", "TEXT", false, 0, null),
      column("is_recipe", "INTEGER", true, 0, "0"),
      column("notes", "TEXT", false, 0, null),
      column("created_at", "TEXT", true, 0, CANONICAL_INSTANT_DEFAULT),
      column("updated_at", "TEXT", true, 0, CANONICAL_INSTANT_DEFAULT),
      column("deleted_at", "TEXT", false, 0, null),
    ]),
    food_sources: schemaTable([
      column("id", "TEXT", true, 1, null),
      column("food_item_id", "TEXT", true, 0, null),
      column("source_type", "TEXT", true, 0, null),
      column("external_id", "TEXT", false, 0, null),
      column("raw_payload", "TEXT", false, 0, null),
      column("metadata", "TEXT", false, 0, null),
      column("created_at", "TEXT", true, 0, CANONICAL_INSTANT_DEFAULT),
    ]),
    food_nutrients: schemaTable([
      column("id", "TEXT", true, 1, null),
      column("food_item_id", "TEXT", true, 0, null),
      column("nutrient_id", "TEXT", true, 0, null),
      column("amount", "TEXT", false, 0, null),
      column("unit", "TEXT", true, 0, null),
      column("basis", "TEXT", true, 0, null),
      column("data_status", "TEXT", true, 0, null),
      column("confidence", "TEXT", false, 0, null),
      column("source", "TEXT", true, 0, null),
      column("is_user_confirmed", "INTEGER", true, 0, "0"),
      column("original_amount", "TEXT", false, 0, null),
      column("original_unit", "TEXT", false, 0, null),
      column("original_text", "TEXT", false, 0, null),
      column("created_at", "TEXT", true, 0, CANONICAL_INSTANT_DEFAULT),
      column("updated_at", "TEXT", true, 0, CANONICAL_INSTANT_DEFAULT),
    ]),
    serving_definitions: schemaTable([
      column("id", "TEXT", true, 1, null),
      column("food_item_id", "TEXT", true, 0, null),
      column("label", "TEXT", true, 0, null),
      column("quantity", "TEXT", true, 0, null),
      column("unit", "TEXT", true, 0, null),
      column("gram_weight", "TEXT", false, 0, null),
      column("reference_quantity", "TEXT", false, 0, null),
      column("reference_unit", "TEXT", false, 0, null),
      column("reference_gram_weight", "TEXT", false, 0, null),
      column("is_default", "INTEGER", true, 0, "0"),
      column("source", "TEXT", true, 0, null),
      column("confidence", "TEXT", false, 0, null),
      column("is_user_confirmed", "INTEGER", true, 0, "0"),
    ]),
    recipes: schemaTable([
      column("id", "TEXT", true, 1, null),
      column("user_id", "TEXT", true, 0, null),
      column("published_food_item_id", "TEXT", false, 0, null),
      column("active_publication_revision_id", "TEXT", false, 0, null),
      column("name", "TEXT", true, 0, null),
      column("notes", "TEXT", false, 0, null),
      column("serving_count_yield", "TEXT", false, 0, null),
      column("final_cooked_weight_grams", "TEXT", false, 0, null),
      column("final_cooked_weight_display_quantity", "TEXT", false, 0, null),
      column("final_cooked_weight_display_unit", "TEXT", false, 0, null),
      column("needs_republish", "INTEGER", true, 0, "0"),
      column("created_at", "TEXT", true, 0, CANONICAL_INSTANT_DEFAULT),
      column("updated_at", "TEXT", true, 0, CANONICAL_INSTANT_DEFAULT),
      column("deleted_at", "TEXT", false, 0, null),
    ]),
    recipe_ingredients: schemaTable([
      column("id", "TEXT", true, 1, null),
      column("user_id", "TEXT", true, 0, null),
      column("recipe_id", "TEXT", true, 0, null),
      column("food_item_id", "TEXT", true, 0, null),
      column("position", "INTEGER", true, 0, null),
      column("amount_quantity", "TEXT", true, 0, null),
      column("amount_unit", "TEXT", true, 0, null),
      column("amount_display_quantity", "TEXT", false, 0, null),
      column("amount_display_unit", "TEXT", false, 0, null),
      column("serving_definition_id", "TEXT", false, 0, null),
      column("resolved_gram_amount", "TEXT", false, 0, null),
      column("preparation_note", "TEXT", false, 0, null),
    ]),
    recipe_publication_revisions: schemaTable([
      column("id", "TEXT", true, 1, null),
      column("recipe_id", "TEXT", true, 0, null),
      column("user_id", "TEXT", true, 0, null),
      column("revision_number", "INTEGER", true, 0, null),
      column("published_at", "TEXT", true, 0, CANONICAL_INSTANT_DEFAULT),
      column("creation_origin", "TEXT", true, 0, null),
      column("provenance_confidence", "TEXT", true, 0, null),
      column("published_name", "TEXT", true, 0, null),
      column("published_notes", "TEXT", false, 0, null),
      column("content_digest", "TEXT", true, 0, null),
    ]),
    recipe_publication_amount_definitions: schemaTable([
      column("id", "TEXT", true, 1, null),
      column("revision_id", "TEXT", true, 0, null),
      column("display_order", "INTEGER", true, 0, null),
      column("display_label", "TEXT", true, 0, null),
      column("semantic_mode", "TEXT", true, 0, null),
      column("display_quantity", "TEXT", false, 0, null),
      column("display_unit", "TEXT", true, 0, null),
      column("gram_equivalent", "TEXT", false, 0, null),
      column("is_default", "INTEGER", true, 0, "0"),
      column("conversion_metadata", "TEXT", false, 0, null),
    ]),
    recipe_publication_nutrients: schemaTable([
      column("id", "TEXT", true, 1, null),
      column("revision_id", "TEXT", true, 0, null),
      column("nutrient_id", "TEXT", true, 0, null),
      column("amount", "TEXT", false, 0, null),
      column("unit", "TEXT", true, 0, null),
      column("basis", "TEXT", true, 0, null),
      column("data_status", "TEXT", true, 0, null),
      column("diagnostic_provenance", "TEXT", false, 0, null),
    ]),
    daily_logs: schemaTable([
      column("id", "TEXT", true, 1, null),
      column("user_id", "TEXT", true, 0, null),
      column("food_item_id", "TEXT", true, 0, null),
      column("food_name_snapshot", "TEXT", false, 0, null),
      column("client_request_id", "TEXT", false, 0, null),
      column("client_request_fingerprint", "TEXT", false, 0, null),
      column("logged_date", "TEXT", true, 0, null),
      column("meal_type", "TEXT", false, 0, null),
      column("amount_quantity", "TEXT", true, 0, null),
      column("amount_unit", "TEXT", true, 0, null),
      column("serving_definition_id", "TEXT", false, 0, null),
      column("recipe_publication_revision_id", "TEXT", false, 0, null),
      column("recipe_publication_amount_definition_id", "TEXT", false, 0, null),
      column("gram_amount", "TEXT", false, 0, null),
      column("package_fraction", "TEXT", false, 0, null),
      column("notes", "TEXT", false, 0, null),
      column("created_at", "TEXT", true, 0, CANONICAL_INSTANT_DEFAULT),
      column("updated_at", "TEXT", true, 0, CANONICAL_INSTANT_DEFAULT),
    ]),
    daily_log_nutrient_snapshots: schemaTable([
      column("id", "TEXT", true, 1, null),
      column("daily_log_id", "TEXT", true, 0, null),
      column("source_food_item_id", "TEXT", true, 0, null),
      column("source_food_nutrient_id", "TEXT", false, 0, null),
      column("serving_definition_id", "TEXT", false, 0, null),
      column("nutrient_id", "TEXT", true, 0, null),
      column("amount", "TEXT", false, 0, null),
      column("unit", "TEXT", true, 0, null),
      column("data_status", "TEXT", true, 0, null),
      column("consumed_amount_quantity", "TEXT", true, 0, null),
      column("consumed_amount_unit", "TEXT", true, 0, null),
      column("consumed_gram_amount", "TEXT", false, 0, null),
      column("consumed_package_fraction", "TEXT", false, 0, null),
      column("calculation_metadata", "TEXT", false, 0, null),
    ]),
    daily_log_day_completions: schemaTable([
      column("logged_date", "TEXT", true, 1, null),
      column("completed_at", "TEXT", true, 0, null),
    ]),
    food_favorites: schemaTable([
      column("user_id", "TEXT", true, 1, null),
      column("food_item_id", "TEXT", true, 2, null),
      column("created_at", "TEXT", true, 0, CANONICAL_INSTANT_DEFAULT),
    ]),
    ocr_nutrition_confirmation_traces: schemaTable([
      column("id", "TEXT", true, 1, null),
      column("user_id", "TEXT", true, 0, null),
      column("food_item_id", "TEXT", true, 0, null),
      column("parser_version", "TEXT", true, 0, null),
      column("image_source_type", "TEXT", true, 0, null),
      column("schema_version", "TEXT", true, 0, null),
      column("trace_snapshot", "TEXT", true, 0, null),
      column("client_request_id", "TEXT", true, 0, null),
      column("request_fingerprint", "TEXT", true, 0, null),
      column("confirmed_at", "TEXT", true, 0, CANONICAL_INSTANT_DEFAULT),
    ]),
    nutrition_targets: schemaTable([
      column("id", "TEXT", true, 1, null),
      column("user_id", "TEXT", true, 0, null),
      column("target_type", "TEXT", true, 0, null),
      column("nutrient_id", "TEXT", true, 0, null),
      column("min_amount", "TEXT", false, 0, null),
      column("target_amount", "TEXT", false, 0, null),
      column("max_amount", "TEXT", false, 0, null),
      column("unit", "TEXT", true, 0, null),
      column("basis", "TEXT", true, 0, null),
      column("source", "TEXT", true, 0, null),
      column("metadata", "TEXT", false, 0, null),
      column("created_at", "TEXT", true, 0, CANONICAL_INSTANT_DEFAULT),
      column("updated_at", "TEXT", true, 0, CANONICAL_INSTANT_DEFAULT),
    ]),
    create_operation_idempotency: schemaTable([
      column("id", "TEXT", true, 1, null),
      column("user_id", "TEXT", true, 0, null),
      column("operation", "TEXT", true, 0, null),
      column("client_request_id", "TEXT", true, 0, null),
      column("request_fingerprint", "TEXT", true, 0, null),
      column("resource_id", "TEXT", true, 0, null),
      column("response_snapshot", "TEXT", false, 0, null),
      column("completed_at", "TEXT", false, 0, null),
      column("created_at", "TEXT", true, 0, CANONICAL_INSTANT_DEFAULT),
    ]),
    nutrition_schema_migrations: schemaTable([
      column("version", "INTEGER", true, 1, null),
      column("migration_id", "TEXT", true, 0, null),
      column("applied_at", "TEXT", true, 0, null),
    ]),
    nutrition_daily_log_snapshot_replacement_scopes: schemaTable([
      column("user_id", "TEXT", true, 1, null),
      column("daily_log_id", "TEXT", true, 2, null),
      column("original_snapshot_count", "INTEGER", true, 0, null),
      column("deleted_snapshot_count", "INTEGER", true, 0, "0"),
      column("header_touched", "INTEGER", true, 0, "0"),
    ]),
});

export const LOCAL_BACKUP_SCHEMA_REQUIREMENTS_BY_VERSION: Readonly<
  Record<number, Readonly<Record<string, readonly LocalBackupColumnRequirement[]>>>
> = Object.freeze({
  7: VERSION_7_COLUMN_REQUIREMENTS,
  8: VERSION_7_COLUMN_REQUIREMENTS,
});

export function getLocalBackupSchemaRequirements(
  schemaVersion: number,
): Readonly<Record<string, readonly LocalBackupColumnRequirement[]>> | undefined {
  return LOCAL_BACKUP_SCHEMA_REQUIREMENTS_BY_VERSION[schemaVersion];
}

function hasOnlyOuterParentheses(value: string): boolean {
  if (!value.startsWith("(") || !value.endsWith(")")) return false;

  let depth = 0;
  let quote: "'" | '"' | "`" | "]" | null = null;
  for (let index = 0; index < value.length; index += 1) {
    const character = value[index];
    const next = value[index + 1];

    if (quote !== null) {
      if (character === quote) {
        if (next === quote && quote !== "]") {
          index += 1;
        } else {
          quote = null;
        }
      }
      continue;
    }

    if (character === "'" || character === '"' || character === "`") {
      quote = character;
    } else if (character === "[") {
      quote = "]";
    } else if (character === "(") {
      depth += 1;
    } else if (character === ")") {
      depth -= 1;
      if (depth < 0 || (depth === 0 && index !== value.length - 1)) {
        return false;
      }
    }
  }

  return depth === 0 && quote === null;
}

/**
 * Normalize only SQLite-insensitive keyword/function case, whitespace outside
 * quoted tokens, and balanced parentheses that wrap the entire default.
 * Quoted text, numeric spelling, NULL, and expression structure are preserved.
 */
export function normalizeLocalBackupDefault(value: string): string {
  let unwrapped = value.trim();
  while (hasOnlyOuterParentheses(unwrapped)) {
    unwrapped = unwrapped.slice(1, -1).trim();
  }

  let normalized = "";
  let quote: "'" | '"' | "`" | "]" | null = null;
  for (let index = 0; index < unwrapped.length; index += 1) {
    const character = unwrapped[index];
    const next = unwrapped[index + 1];

    if (quote !== null) {
      normalized += character;
      if (character === quote) {
        if (next === quote && quote !== "]") {
          normalized += next;
          index += 1;
        } else {
          quote = null;
        }
      }
      continue;
    }

    if (character === "'" || character === '"' || character === "`") {
      quote = character;
      normalized += character;
    } else if (character === "[") {
      quote = "]";
      normalized += character;
    } else if (!/\s/.test(character)) {
      normalized += character.toUpperCase();
    }
  }

  return normalized;
}

export function localBackupDefaultsMatch(
  actual: string | null,
  expected: string | null,
): boolean {
  if (actual === null || expected === null) return actual === expected;
  return normalizeLocalBackupDefault(actual) === normalizeLocalBackupDefault(expected);
}


export type LocalBackupTriggerRequirement = Readonly<{ name: string; table: string; sql: string }>;

// Supported v7 baseline guards plus migration002's Food guards. Index-only v8
// retains these exact definitions; no applied migration is rewritten or run here.
const VERSION_7_TRIGGER_SQL = [
  ...SQLITE_BASELINE_SCHEMA_STATEMENTS.filter((sql) => /^CREATE TRIGGER /i.test(sql.trim())),
  `CREATE TRIGGER IF NOT EXISTS "trg_food_nutrients_nonnegative_insert"
      BEFORE INSERT ON "food_nutrients"
      WHEN NEW."amount" IS NOT NULL AND substr(NEW."amount", 1, 1) = '-'
      BEGIN
        SELECT RAISE(ABORT, 'constraint_failed: Food nutrient amount must be non-negative');
      END;`,
  `CREATE TRIGGER IF NOT EXISTS "trg_food_nutrients_nonnegative_update"
      BEFORE UPDATE OF "amount" ON "food_nutrients"
      WHEN NEW."amount" IS NOT NULL AND substr(NEW."amount", 1, 1) = '-'
      BEGIN
        SELECT RAISE(ABORT, 'constraint_failed: Food nutrient amount must be non-negative');
      END;`,
];
const VERSION_7_TRIGGER_REQUIREMENTS = Object.freeze(VERSION_7_TRIGGER_SQL.map((sql) => {
  const header = /^CREATE TRIGGER(?: IF NOT EXISTS)? "([^"]+)"[\s\S]*?\bON "([^"]+)"/i.exec(sql.trim());
  if (!header) throw new Error("Invalid required backup trigger declaration");
  return Object.freeze({ name: header[1], table: header[2], sql });
}));

export function getLocalBackupTriggerRequirements(version: number): readonly LocalBackupTriggerRequirement[] {
  if (version !== 7 && version !== 8) throw new Error("Unsupported backup trigger contract version");
  return VERSION_7_TRIGGER_REQUIREMENTS;
}

/** Compare the known definitions, not arbitrary SQL semantic equivalence.
 * Preserve quoted identifiers/literals and token boundaries; ignore only
 * unquoted case/whitespace and SQLite's omitted CREATE IF NOT EXISTS clause.
 */
export function localBackupTriggerDefinitionsMatch(actual: string | null, expected: string): boolean {
  if (actual === null) return false;
  const tokens = (sql: string): string => {
    const declaration = sql.trim().replace(/^CREATE\s+TRIGGER\s+IF\s+NOT\s+EXISTS\s+/i, "CREATE TRIGGER ")
      .replace(/;\s*$/, "");
    const pieces = declaration.match(/'(?:''|[^'])*'|"(?:""|[^"])*"|`(?:``|[^`])*`|\[[^\]]*\]|[a-zA-Z_][a-zA-Z_0-9]*|[^\s]/g) ?? [];
    return JSON.stringify(pieces.map((token) => /^[a-zA-Z_]/.test(token) ? token.toUpperCase() : token));
  };
  return tokens(actual) === tokens(expected);
}
