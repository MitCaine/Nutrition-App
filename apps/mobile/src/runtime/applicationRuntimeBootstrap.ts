import type { MobileRuntimeConfig } from "../../config/runtimeConfig";

import type { NutritionRuntime } from "./NutritionRuntime";

export const NUTRITION_RUNTIME_CAPABILITIES = [
  "calendar",
  "nutrients",
  "foods",
  "recipes",
  "dailyLogs",
  "targets",
  "ocr",
  "usda",
] as const;

export type ApplicationRuntimeHandle = Readonly<{
  runtime: NutritionRuntime;
  close(): Promise<void>;
}>;

export type ApplicationRuntimeBootstrapDependencies = Readonly<{
  /**
   * Optional pre-open maintenance boundary for the selected local authority.
   * Restore activation runs here so it can never overlap a live local runtime.
   */
  activatePendingLocalRestore?(): Promise<void>;
  openLocalRuntime(): Promise<NutritionRuntime & Readonly<{ close(): Promise<void> }>>;
  loadRemoteRuntime(): Promise<NutritionRuntime>;
}>;

const defaultDependencies: ApplicationRuntimeBootstrapDependencies = {
  async activatePendingLocalRestore() {
    // Keep backup/native storage code outside the remote-authority module graph.
    const { activatePendingLocalRestore } = require("../storage/backup/localBackup") as
      typeof import("../storage/backup/localBackup");
    await activatePendingLocalRestore();
  },
  async openLocalRuntime() {
    // Expo/Jest share this lazy CommonJS boundary. The selected branch is the
    // only point at which either registry module is evaluated.
    const { openLocalRuntimeFoundation } = require("./local/localRuntimeFoundation") as
      typeof import("./local/localRuntimeFoundation");
    const { getStoredUsdaCredential } = require("./local/usdaCredentialStore") as
      typeof import("./local/usdaCredentialStore");
    return openLocalRuntimeFoundation({
      usda: { credentialProvider: getStoredUsdaCredential },
    });
  },
  async loadRemoteRuntime() {
    const { remoteNutritionRuntime } = require("./remote/remoteNutritionRuntime") as
      typeof import("./remote/remoteNutritionRuntime");
    return remoteNutritionRuntime;
  },
};

function assertCompleteRuntime(
  runtime: NutritionRuntime,
  expectedAuthority: MobileRuntimeConfig["dataAuthority"],
): void {
  if (runtime.authority.kind !== expectedAuthority) {
    throw new Error(
      `Nutrition runtime authority mismatch: selected ${expectedAuthority}, received ${runtime.authority.kind}.`,
    );
  }
  for (const capability of NUTRITION_RUNTIME_CAPABILITIES) {
    if (!runtime[capability]) {
      throw new Error(`Nutrition runtime is missing the ${capability} capability.`);
    }
  }
}

/**
 * Construct exactly one application-data authority after configuration has
 * explicitly selected it. No branch probes, opens, or falls back to the other.
 */
export async function bootstrapApplicationRuntime(
  configuration: MobileRuntimeConfig,
  dependencies: ApplicationRuntimeBootstrapDependencies = defaultDependencies,
): Promise<ApplicationRuntimeHandle> {
  if (configuration.dataAuthority === "local") {
    await dependencies.activatePendingLocalRestore?.();
    const runtime = await dependencies.openLocalRuntime();
    try {
      assertCompleteRuntime(runtime, "local");
      return { runtime, close: () => runtime.close() };
    } catch (error) {
      try {
        await runtime.close();
      } catch {
        // Preserve the authority/registry failure; closing is best effort.
      }
      throw error;
    }
  }

  const runtime = await dependencies.loadRemoteRuntime();
  assertCompleteRuntime(runtime, "remote");
  return { runtime, close: async () => undefined };
}

export class SupersededRuntimeSelectionError extends Error {
  constructor() {
    super("Runtime selection was superseded by a newer explicit selection.");
    this.name = "SupersededRuntimeSelectionError";
  }
}

/** Serializes explicit selection changes so two live authorities never overlap. */
export class ApplicationRuntimeSelectionManager {
  private current: ApplicationRuntimeHandle | null = null;
  private generation = 0;
  private tail: Promise<void> = Promise.resolve();

  constructor(
    private readonly bootstrap: (
      configuration: MobileRuntimeConfig,
    ) => Promise<ApplicationRuntimeHandle> = bootstrapApplicationRuntime,
  ) {}

  select(configuration: MobileRuntimeConfig): Promise<ApplicationRuntimeHandle> {
    const generation = ++this.generation;
    const operation = this.tail.then(async () => {
      const previous = this.current;
      this.current = null;
      if (previous) await previous.close();
      if (generation !== this.generation) throw new SupersededRuntimeSelectionError();

      const next = await this.bootstrap(configuration);
      if (generation !== this.generation) {
        await next.close();
        throw new SupersededRuntimeSelectionError();
      }
      this.current = next;
      return next;
    });
    this.tail = operation.then(() => undefined, () => undefined);
    return operation;
  }

  dispose(): Promise<void> {
    ++this.generation;
    const operation = this.tail.then(async () => {
      const current = this.current;
      this.current = null;
      if (current) await current.close();
    });
    this.tail = operation.then(() => undefined, () => undefined);
    return operation;
  }
}
