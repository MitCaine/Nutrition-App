import type { NutritionDatabaseHandle, OpenNutritionDatabaseOptions } from "../../storage/sqlite/migrations";
import { openNutritionDatabase } from "../../storage/sqlite/migrations";
import { SQLITE_SEMANTIC_TABLES } from "../../storage/sqlite/schema";
import {
  bootstrapOpenedLocalRuntimeFoundation,
  type OpenLocalRuntimeHandle,
} from "../../runtime/local/localRuntimeFoundation";
import {
  importPersonalTransfer,
  type TransferImportOptions,
  type TransferImportResult,
} from "./transferImporter";

export type LocalFirstStartState = "requires_decision" | "existing_data";

export type LocalFirstStartImportedRuntime = Readonly<{
  handle: OpenLocalRuntimeHandle;
  transferResult: TransferImportResult;
}>;

export class LocalFirstStartBootstrapError extends Error {
  constructor(
    readonly transferResult: TransferImportResult,
    readonly cause: unknown,
  ) {
    super("Transfer committed successfully, but local startup did not complete.");
    this.name = "LocalFirstStartBootstrapError";
  }
}

export type LocalFirstStartCoordinator = Readonly<{
  databaseHandle: NutritionDatabaseHandle;
  state: LocalFirstStartState;
  importTransfer(document: string, options?: TransferImportOptions): Promise<LocalFirstStartImportedRuntime>;
  startEmpty(): Promise<OpenLocalRuntimeHandle>;
  continueExisting(): Promise<OpenLocalRuntimeHandle>;
  retryLocalStartup(): Promise<LocalFirstStartImportedRuntime>;
  close(): Promise<void>;
}>;

export type LocalFirstStartDependencies = Readonly<{
  openDatabase(options?: OpenNutritionDatabaseOptions): Promise<NutritionDatabaseHandle>;
  bootstrap(handle: NutritionDatabaseHandle): Promise<OpenLocalRuntimeHandle>;
  importTransfer(
    database: NutritionDatabaseHandle["database"],
    document: string,
    options?: TransferImportOptions,
  ): Promise<TransferImportResult>;
}>;

const defaults: LocalFirstStartDependencies = {
  openDatabase: openNutritionDatabase,
  bootstrap: (handle) => {
    const { getStoredUsdaCredential } = require("../../runtime/local/usdaCredentialStore") as
        typeof import("../../runtime/local/usdaCredentialStore");

    return bootstrapOpenedLocalRuntimeFoundation(handle, {
      usda: {
        credentialProvider: getStoredUsdaCredential,
      },
    });
  },
  importTransfer: importPersonalTransfer,
};

async function hasApplicationData(handle: NutritionDatabaseHandle): Promise<boolean> {
  for (const table of SQLITE_SEMANTIC_TABLES) {
    if (table === "nutrients") continue;
    const row = await handle.database.getFirstAsync<{ count: number }>(
      `SELECT COUNT(*) AS "count" FROM "${table}"`,
    );
    if (row?.count !== 0) return true;
  }
  return false;
}

export async function prepareLocalFirstStart(
  databaseOptions: OpenNutritionDatabaseOptions = {},
  dependencies: LocalFirstStartDependencies = defaults,
): Promise<LocalFirstStartCoordinator> {
  const handle = await dependencies.openDatabase(databaseOptions);
  let transferred = false;
  let completed = false;
  let transferResult: TransferImportResult | null = null;
  try {
    const state: LocalFirstStartState = await hasApplicationData(handle)
      ? "existing_data"
      : "requires_decision";
    const complete = async (): Promise<OpenLocalRuntimeHandle> => {
      if (completed) throw new Error("Local first-start decision is already complete.");
      const runtime = await dependencies.bootstrap(handle);
      completed = true;
      return runtime;
    };
    const completeImportedStartup = async (): Promise<LocalFirstStartImportedRuntime> => {
      if (!transferResult) throw new Error("Transfer import has not committed.");
      try {
        return { handle: await complete(), transferResult };
      } catch (error) {
        throw new LocalFirstStartBootstrapError(transferResult, error);
      }
    };
    return {
      databaseHandle: handle,
      state,
      async importTransfer(document, options) {
        if (state !== "requires_decision" || transferred) {
          throw new Error("Transfer import is unavailable after local application data exists.");
        }
        transferResult = await dependencies.importTransfer(handle.database, document, options);
        transferred = true;
        return completeImportedStartup();
      },
      async startEmpty() {
        if (state !== "requires_decision" || transferred) {
          throw new Error("Empty-profile startup is unavailable after transfer import.");
        }
        return complete();
      },
      async continueExisting() {
        if (state !== "existing_data") {
          throw new Error("Existing local startup is unavailable for an empty database.");
        }
        return complete();
      },
      async retryLocalStartup() {
        if (state !== "requires_decision" || !transferred || !transferResult) {
          throw new Error("Local startup retry is unavailable before a committed transfer.");
        }
        return completeImportedStartup();
      },
      close: async () => {
        if (!completed) await handle.close();
      },
    };
  } catch (error) {
    await handle.close().catch(() => undefined);
    throw error;
  }
}
