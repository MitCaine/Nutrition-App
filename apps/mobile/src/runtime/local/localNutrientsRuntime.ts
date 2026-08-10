import type { SQLiteDatabase } from "expo-sqlite";

import type { NutrientDefinition } from "../../features/foods/api/types";
import type { NutrientsRuntime } from "../NutritionRuntime";
import { SQLITE_NUTRIENT_SEED_ROWS } from "../../storage/sqlite/schema";
import { withLocalWriteTransaction } from "./localWriteCoordinator";
import { LocalRuntimeError } from "./localErrors";

type NutrientRow = Readonly<{
  id: string;
  display_name: string;
  nutrient_kind: string;
  default_unit: string;
  parent_nutrient_id: string | null;
  display_order: number;
}>;

function catalogDrift(): LocalRuntimeError {
  return new LocalRuntimeError({
    kind: "conflict",
    code: "constraint_failed",
    message: "The local nutrient catalog does not match the canonical catalog.",
  });
}

function isExactSeedRow(row: NutrientRow | undefined, seed: (typeof SQLITE_NUTRIENT_SEED_ROWS)[number]): boolean {
  return row != null
    && row.id === seed[0]
    && row.display_name === seed[1]
    && row.nutrient_kind === seed[2]
    && row.default_unit === seed[3]
    && row.parent_nutrient_id === seed[4]
    && row.display_order === seed[5];
}

function toDefinition(row: NutrientRow): NutrientDefinition {
  return {
    id: row.id,
    display_name: row.display_name,
    default_unit: row.default_unit as NutrientDefinition["default_unit"],
    nutrient_kind: row.nutrient_kind,
    parent_nutrient_id: row.parent_nutrient_id,
    display_order: row.display_order,
  };
}

async function readAndValidateCatalog(transaction: SQLiteDatabase): Promise<NutrientDefinition[]> {
  const rows = await transaction.getAllAsync<NutrientRow>(
    `SELECT "id", "display_name", "nutrient_kind", "default_unit",
            "parent_nutrient_id", "display_order"
     FROM "nutrients"
     ORDER BY "display_order", "id"`,
  );
  if (
    rows.length !== SQLITE_NUTRIENT_SEED_ROWS.length
    || rows.some((row, index) => !isExactSeedRow(row, SQLITE_NUTRIENT_SEED_ROWS[index]))
  ) {
    throw catalogDrift();
  }
  return rows.map(toDefinition);
}

/**
 * Idempotently fill missing canonical rows, then reject any incompatible
 * value, extra row, or ordering drift.  `INSERT OR IGNORE` is deliberately
 * not used to overwrite a conflicting existing row.
 */
export async function ensureLocalNutrientCatalog(
  database: SQLiteDatabase,
): Promise<NutrientDefinition[]> {
  return withLocalWriteTransaction(database, async (transaction) => {
    for (const [id, displayName, nutrientKind, defaultUnit, parentNutrientId, displayOrder] of
      SQLITE_NUTRIENT_SEED_ROWS) {
      await transaction.runAsync(
        `INSERT OR IGNORE INTO "nutrients"
          ("id", "display_name", "nutrient_kind", "default_unit", "parent_nutrient_id", "display_order")
         VALUES (?, ?, ?, ?, ?, ?)`,
        [id, displayName, nutrientKind, defaultUnit, parentNutrientId, displayOrder],
      );
    }
    return readAndValidateCatalog(transaction);
  });
}

/** Local implementation of the runtime-neutral NutrientsRuntime contract. */
export class LocalNutrientsRuntime implements NutrientsRuntime {
  constructor(private readonly database: SQLiteDatabase) {}

  async list(): Promise<NutrientDefinition[]> {
    return ensureLocalNutrientCatalog(this.database);
  }
}

export function createLocalNutrientsRuntime(database: SQLiteDatabase): NutrientsRuntime {
  return new LocalNutrientsRuntime(database);
}
