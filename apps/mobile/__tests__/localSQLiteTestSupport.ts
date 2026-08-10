import type { SQLiteDatabase } from "expo-sqlite";

import { SQLITE_BASELINE_SCHEMA_STATEMENTS } from "../src/storage/sqlite/schema";

type SqliteStatement = {
  all(...params: unknown[]): unknown[];
  get(...params: unknown[]): unknown;
  run(...params: unknown[]): { changes: number; lastInsertRowid: number | bigint };
};

type SqliteDatabaseSync = {
  close(): void;
  exec(source: string): void;
  prepare(source: string): SqliteStatement;
};

export type LocalSQLiteFixtureDatabase = {
  execAsync(source: string): Promise<void>;
  getFirstAsync<T>(source: string, params?: readonly unknown[]): Promise<T | null>;
  getAllAsync<T>(source: string, params?: readonly unknown[]): Promise<T[]>;
  runAsync(source: string, params?: readonly unknown[]): Promise<unknown>;
  asExpoDatabase(): SQLiteDatabase;
};

const { DatabaseSync } = require("node:sqlite") as {
  DatabaseSync: new (path: string) => SqliteDatabaseSync;
};

export class LocalSQLiteTestDatabase {
  private readonly native: SqliteDatabaseSync;
  private transactionTail: Promise<void> = Promise.resolve();
  beforeNextExclusiveTransaction?: () => Promise<void> | void;
  exclusiveTransactionCount = 0;

  constructor(path = ":memory:") {
    this.native = new DatabaseSync(path);
  }

  async initialize(): Promise<void> {
    this.native.exec("PRAGMA foreign_keys = ON");
    for (const statement of SQLITE_BASELINE_SCHEMA_STATEMENTS) {
      this.native.exec(statement);
    }
  }

  close(): void {
    this.native.close();
  }

  async execAsync(source: string): Promise<void> {
    this.native.exec(source);
  }

  async getFirstAsync<T>(source: string, params: readonly unknown[] = []): Promise<T | null> {
    return (this.native.prepare(source).get(...params) as T | undefined) ?? null;
  }

  async getAllAsync<T>(source: string, params: readonly unknown[] = []): Promise<T[]> {
    return this.native.prepare(source).all(...params) as T[];
  }

  async runAsync(source: string, params: readonly unknown[] = []): Promise<unknown> {
    return this.native.prepare(source).run(...params);
  }

  async withExclusiveTransactionAsync(
    operation: (transaction: SQLiteDatabase) => Promise<void>,
  ): Promise<void> {
    const previous = this.transactionTail;
    let release!: () => void;
    this.transactionTail = new Promise<void>((resolve) => { release = resolve; });
    await previous;
    try {
      const before = this.beforeNextExclusiveTransaction;
      this.beforeNextExclusiveTransaction = undefined;
      await before?.();
      this.exclusiveTransactionCount += 1;
      this.native.exec("BEGIN");
      try {
        await operation(this as unknown as SQLiteDatabase);
        this.native.exec("COMMIT");
      } catch (error) {
        try { this.native.exec("ROLLBACK"); } catch { /* transaction setup may already have failed */ }
        throw error;
      }
    } finally {
      release();
    }
  }

  asExpoDatabase(): SQLiteDatabase {
    return this as unknown as SQLiteDatabase;
  }
}

/**
 * Models Expo's isolated transaction connection while outer reads use a
 * separate connection that can observe only committed WAL state.
 */
export class ExpoIsolatedSQLiteTestDatabase implements LocalSQLiteFixtureDatabase {
  private readonly reader: SqliteDatabaseSync;

  constructor(private readonly path: string) {
    this.reader = new DatabaseSync(path);
  }

  async initialize(): Promise<void> {
    this.reader.exec("PRAGMA foreign_keys = ON");
    this.reader.exec("PRAGMA busy_timeout = 5000");
    this.reader.exec("PRAGMA journal_mode = WAL");
    this.reader.exec("PRAGMA synchronous = NORMAL");
    for (const statement of SQLITE_BASELINE_SCHEMA_STATEMENTS) {
      this.reader.exec(statement);
    }
  }

  close(): void {
    this.reader.close();
  }

  async execAsync(source: string): Promise<void> {
    this.reader.exec(source);
  }

  async getFirstAsync<T>(source: string, params: readonly unknown[] = []): Promise<T | null> {
    return (this.reader.prepare(source).get(...params) as T | undefined) ?? null;
  }

  async getAllAsync<T>(source: string, params: readonly unknown[] = []): Promise<T[]> {
    return this.reader.prepare(source).all(...params) as T[];
  }

  async runAsync(source: string, params: readonly unknown[] = []): Promise<unknown> {
    return this.reader.prepare(source).run(...params);
  }

  async withExclusiveTransactionAsync(
    operation: (transaction: SQLiteDatabase) => Promise<void>,
  ): Promise<void> {
    const writer = new DatabaseSync(this.path);
    writer.exec("BEGIN");
    const transaction = {
      execAsync: async (source: string) => { writer.exec(source); },
      getFirstAsync: async <T>(source: string, params: readonly unknown[] = []) =>
        (writer.prepare(source).get(...params) as T | undefined) ?? null,
      getAllAsync: async <T>(source: string, params: readonly unknown[] = []) =>
        writer.prepare(source).all(...params) as T[],
      runAsync: async (source: string, params: readonly unknown[] = []) =>
        writer.prepare(source).run(...params),
    } as unknown as SQLiteDatabase;
    try {
      await operation(transaction);
      writer.exec("COMMIT");
    } catch (error) {
      try { writer.exec("ROLLBACK"); } catch { /* setup may already have failed */ }
      throw error;
    } finally {
      writer.close();
    }
  }

  asExpoDatabase(): SQLiteDatabase {
    return this as unknown as SQLiteDatabase;
  }
}

export async function seedLocalOwner(
  database: LocalSQLiteFixtureDatabase,
  ownerId: string,
): Promise<void> {
  await database.runAsync(
    `INSERT INTO "users" ("id", "email", "display_name") VALUES (?, ?, ?)`,
    [ownerId, `${ownerId}@example.invalid`, "Local test owner"],
  );
}

export async function seedLocalFood(
  database: LocalSQLiteFixtureDatabase,
  input: {
    id: string;
    ownerId: string;
    name?: string;
    deletedAt?: string | null;
    servingId?: string;
    gramWeight?: string | null;
  },
): Promise<void> {
  await database.runAsync(
    `INSERT INTO "food_items"
      ("id", "user_id", "name", "source_type", "is_recipe", "deleted_at")
     VALUES (?, ?, ?, 'manual', 0, ?)`,
    [input.id, input.ownerId, input.name ?? "Ingredient Food", input.deletedAt ?? null],
  );
  if (input.servingId) {
    await database.runAsync(
      `INSERT INTO "serving_definitions"
        ("id", "food_item_id", "label", "quantity", "unit", "gram_weight", "is_default", "source", "is_user_confirmed")
       VALUES (?, ?, '1 serving', '1.000000', 'serving', ?, 1, 'manual', 1)`,
      [input.servingId, input.id, input.gramWeight ?? null],
    );
  }
}

export async function seedPublishedRecipeProjection(
  database: LocalSQLiteFixtureDatabase,
  input: {
    ownerId: string;
    recipeId: string;
    projectionId: string;
    revisionId: string;
    name?: string;
    needsRepublish?: boolean;
  },
): Promise<void> {
  await database.execAsync("BEGIN");
  try {
    await database.runAsync(
      `INSERT INTO "recipes"
        ("id", "user_id", "name", "needs_republish", "created_at", "updated_at")
       VALUES (?, ?, ?, ?, '2026-01-01T00:00:00.000000Z', '2026-01-01T00:00:00.000000Z')`,
      [input.recipeId, input.ownerId, input.name ?? "Published Recipe", input.needsRepublish ? 1 : 0],
    );
    await database.runAsync(
      `INSERT INTO "recipe_publication_revisions"
        ("id", "recipe_id", "user_id", "revision_number", "published_at", "creation_origin",
         "provenance_confidence", "published_name", "content_digest")
       VALUES (?, ?, ?, 1, '2026-01-01T00:00:00.000000Z', 'normal_publication', 'complete', ?, ?)`,
      [input.revisionId, input.recipeId, input.ownerId, input.name ?? "Published Recipe", input.revisionId],
    );
    await database.runAsync(
      `INSERT INTO "food_items"
        ("id", "user_id", "name", "source_type", "source_id", "recipe_publication_revision_id",
         "is_recipe", "created_at", "updated_at")
       VALUES (?, ?, ?, 'recipe', ?, ?, 1, '2026-01-01T00:00:00.000000Z', '2026-01-01T00:00:00.000000Z')`,
      [input.projectionId, input.ownerId, input.name ?? "Published Recipe", input.recipeId, input.revisionId],
    );
    await database.runAsync(
      `INSERT INTO "serving_definitions"
        ("id", "food_item_id", "label", "quantity", "unit", "gram_weight", "is_default", "source", "is_user_confirmed")
       VALUES (?, ?, '1 serving', '1.000000', 'serving', '100.000000', 1, 'recipe', 0)`,
      [`${input.projectionId.slice(0, -1)}f`, input.projectionId],
    );
    await database.runAsync(
      `UPDATE "recipes" SET "published_food_item_id" = ?, "active_publication_revision_id" = ? WHERE "id" = ?`,
      [input.projectionId, input.revisionId, input.recipeId],
    );
    await database.execAsync("COMMIT");
  } catch (error) {
    try { await database.execAsync("ROLLBACK"); } catch { /* best effort */ }
    throw error;
  }
}
