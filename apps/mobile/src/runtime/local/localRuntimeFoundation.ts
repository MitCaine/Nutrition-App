import type { SQLiteDatabase } from "expo-sqlite";

import {
  openNutritionDatabase,
  type NutritionDatabaseHandle,
  type OpenNutritionDatabaseOptions,
} from "../../storage/sqlite/migrations";
import type { NutrientsRuntime } from "../NutritionRuntime";
import {
  ensureLocalOwner,
  type LocalOwnerIdentity,
} from "./localIdentity";
import {
  createLocalCalendarRuntime,
  type LocalCalendarRuntime,
  type LocalCalendarRuntimeOptions,
} from "./localCalendarRuntime";
import {
  createLocalNutrientsRuntime,
  ensureLocalNutrientCatalog,
} from "./localNutrientsRuntime";

export type LocalRuntimeFoundation = Readonly<{
  database: SQLiteDatabase;
  identity: LocalOwnerIdentity;
  authority: LocalOwnerIdentity["authority"];
  calendar: LocalCalendarRuntime;
  nutrients: NutrientsRuntime;
}>;

export type OpenLocalRuntimeFoundationOptions = OpenNutritionDatabaseOptions & Readonly<{
  calendar?: LocalCalendarRuntimeOptions;
}>;

/** Bootstrap identity and catalog on an already migrated E2-03 database. */
export async function bootstrapLocalRuntimeFoundation(
  database: SQLiteDatabase,
  calendarOptions: LocalCalendarRuntimeOptions = {},
): Promise<LocalRuntimeFoundation> {
  const identity = await ensureLocalOwner(database);
  await ensureLocalNutrientCatalog(database);
  return {
    database,
    identity,
    authority: identity.authority,
    calendar: createLocalCalendarRuntime(database, identity.ownerId, calendarOptions),
    nutrients: createLocalNutrientsRuntime(database),
  };
}

export type OpenLocalRuntimeHandle = LocalRuntimeFoundation & Readonly<{
  migration: NutritionDatabaseHandle["migration"];
  readiness: NutritionDatabaseHandle["readiness"];
  semanticTables: NutritionDatabaseHandle["semanticTables"];
  close(): Promise<void>;
}>;

/**
 * Open, migrate, and bootstrap the local foundation without selecting a
 * runtime in the app provider.  E2-05+ feature adapters can compose these
 * capabilities into a full NutritionRuntime later.
 */
export async function openLocalRuntimeFoundation(
  options: OpenLocalRuntimeFoundationOptions = {},
): Promise<OpenLocalRuntimeHandle> {
  const { calendar: calendarOptions, ...databaseOptions } = options;
  const handle = await openNutritionDatabase(databaseOptions);
  try {
    const foundation = await bootstrapLocalRuntimeFoundation(handle.database, calendarOptions);
    return {
      ...foundation,
      migration: handle.migration,
      readiness: handle.readiness,
      semanticTables: handle.semanticTables,
      close: handle.close,
    };
  } catch (error) {
    try {
      await handle.close();
    } catch {
      // Preserve the bootstrap/integrity failure; close is best effort.
    }
    throw error;
  }
}

export { createLocalCalendarRuntime };
