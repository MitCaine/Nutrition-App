import React from "react";
import { Pressable, Text } from "react-native";
import TestRenderer, { act } from "react-test-renderer";
import type { SQLiteDatabase } from "expo-sqlite";

import type { NutritionRuntime } from "../src/runtime/NutritionRuntime";
import type { OpenLocalRuntimeHandle } from "../src/runtime/local/localRuntimeFoundation";
import type { NutritionDatabaseHandle } from "../src/storage/sqlite/migrations";
import {
  prepareLocalFirstStart,
} from "../src/transfer/e2_15/localFirstStartCoordinator";
import { LocalFirstStartRuntimeBootstrap } from "../src/transfer/e2_15/LocalFirstStartGate";
import { E2_15_MAXIMUM_TRANSFER_BYTES } from "../src/transfer/e2_15/transferPackage";
import type { TransferImportResult } from "../src/transfer/e2_15/transferImporter";

const TRANSFER_RESULT: TransferImportResult = {
  ownerId: "00000000-0000-4000-8000-000000000001",
  overallDigest: "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
  sectionCounts: {
    users: 1,
    user_profiles: 2,
    food_items: 3,
    food_sources: 4,
    food_nutrients: 5,
    serving_definitions: 6,
    food_favorites: 7,
    recipes: 8,
    recipe_ingredients: 9,
    recipe_publication_revisions: 10,
    recipe_publication_amount_definitions: 11,
    recipe_publication_nutrients: 12,
    daily_logs: 13,
    daily_log_nutrient_snapshots: 14,
    ocr_nutrition_confirmation_traces: 15,
    nutrition_targets: 16,
    create_operation_idempotency: 17,
  },
};

function runtimeHandle(): OpenLocalRuntimeHandle {
  return {
    authority: { kind: "local", recoveryScope: "local:00000000-0000-4000-8000-000000000001" },
    close: jest.fn(async () => undefined),
  } as unknown as OpenLocalRuntimeHandle;
}

function databaseHandle(hasData: boolean): NutritionDatabaseHandle {
  const database = {
    getFirstAsync: jest.fn(async (sql: string) => ({
      count: hasData && sql.includes('FROM "users"') ? 1 : 0,
    })),
  } as unknown as SQLiteDatabase;
  return {
    database,
    db: database,
    migration: { fromVersion: 1, toVersion: 1, appliedVersions: [], alreadyCurrent: true },
    readiness: { ready: true, schemaVersion: 1 },
    semanticTables: [],
    close: jest.fn(async () => undefined),
  };
}

function expectRenderedTextContaining(renderer: TestRenderer.ReactTestRenderer, fragment: string): void {
  expect(renderer.root.findAllByType(Text).some((instance) =>
    typeof instance.props.children === "string" && instance.props.children.includes(fragment),
  )).toBe(true);
}

test("empty local startup stays before owner bootstrap until an explicit decision", async () => {
  const handle = databaseHandle(false);
  const runtime = runtimeHandle();
  const bootstrap = jest.fn(async () => runtime);
  const importTransfer = jest.fn(async () => TRANSFER_RESULT);
  const coordinator = await prepareLocalFirstStart({}, {
    openDatabase: jest.fn(async () => handle),
    bootstrap,
    importTransfer,
  });
  expect(coordinator.state).toBe("requires_decision");
  expect(bootstrap).not.toHaveBeenCalled();
  await coordinator.importTransfer("document");
  expect(importTransfer).toHaveBeenCalledWith(handle.database, "document", undefined);
  expect(bootstrap).toHaveBeenCalledWith(handle);
});

test("coordinator retains committed transfer evidence when local bootstrap fails and retries bootstrap only", async () => {
  const handle = databaseHandle(false);
  const runtime = runtimeHandle();
  const bootstrap = jest.fn()
    .mockRejectedValueOnce(new Error("SQLite runtime foundation unavailable"))
    .mockResolvedValueOnce(runtime);
  const importTransfer = jest.fn(async () => TRANSFER_RESULT);
  const coordinator = await prepareLocalFirstStart({}, {
    openDatabase: jest.fn(async () => handle),
    bootstrap,
    importTransfer,
  });

  await expect(coordinator.importTransfer("document")).rejects.toMatchObject({
    transferResult: TRANSFER_RESULT,
  });
  expect(importTransfer).toHaveBeenCalledTimes(1);
  expect(coordinator.databaseHandle).toBe(handle);

  const retried = await coordinator.retryLocalStartup();
  expect(retried).toEqual({ handle: runtime, transferResult: TRANSFER_RESULT });
  expect(importTransfer).toHaveBeenCalledTimes(1);
  expect(bootstrap).toHaveBeenCalledTimes(2);
});

test("existing local data bypasses import choice while remote concerns remain absent", async () => {
  const handle = databaseHandle(true);
  const runtime = runtimeHandle();
  const bootstrap = jest.fn(async () => runtime);
  const importTransfer = jest.fn(async () => TRANSFER_RESULT);
  const coordinator = await prepareLocalFirstStart({}, {
    openDatabase: jest.fn(async () => handle),
    bootstrap,
    importTransfer,
  });
  expect(coordinator.state).toBe("existing_data");
  await coordinator.continueExisting();
  expect(bootstrap).toHaveBeenCalledTimes(1);
  expect(importTransfer).not.toHaveBeenCalled();
});

test("accessible first-start UI imports a cache copy and requires explicit continue", async () => {
  const handle = runtimeHandle();
  const database = databaseHandle(false);
  const remove = jest.fn(async () => undefined);
  const importTransfer = jest.fn(async () => TRANSFER_RESULT);
  const coordinator = await prepareLocalFirstStart({}, {
    openDatabase: jest.fn(async () => database),
    bootstrap: jest.fn(async () => handle),
    importTransfer,
  });
  const dependencies = {
    prepare: jest.fn(async () => coordinator),
    pickCachedTransfer: jest.fn(async () => ({
      name: "owner.nutrition-transfer.json",
      size: 100,
      readText: async () => "package",
      remove,
    })),
  };
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(
      LocalFirstStartRuntimeBootstrap,
      {
        dependencies,
        children: (_runtime: NutritionRuntime) => React.createElement(Text, null, "app-ready"),
      },
    ));
  });
  const importButton = renderer.root.findByProps({ accessibilityLabel: "Import transfer file" });
  expect(renderer.root.findByProps({ accessibilityLabel: "Start with empty local profile" })).toBeDefined();
  await act(async () => { importButton.props.onPress(); });
  expect(importTransfer).toHaveBeenCalledWith(
    database.database,
    "package",
    expect.objectContaining({ onCheckpoint: expect.any(Function) }),
  );
  expect(remove).toHaveBeenCalledTimes(1);
  expect(renderer.root.findByProps({ children: "Transfer complete" })).toBeDefined();
  expect(renderer.root.findByProps({ children: TRANSFER_RESULT.overallDigest })).toBeDefined();
  expectRenderedTextContaining(renderer, "users: 1");
  expect(renderer.root.findAllByProps({ children: "app-ready" })).toHaveLength(0);
  const continueButton = renderer.root.findByProps({ accessibilityLabel: "Continue to Nutrition App" });
  await act(async () => { continueButton.props.onPress(); });
  expect(renderer.root.findByProps({ children: "app-ready" })).toBeDefined();
  await act(async () => { renderer.unmount(); });
});

test("failed import remains visible, retryable, and removes only the cache copy", async () => {
  const remove = jest.fn(async () => undefined);
  const coordinator = {
    databaseHandle: databaseHandle(false),
    state: "requires_decision" as const,
    importTransfer: jest.fn()
      .mockRejectedValueOnce(new Error("Transfer digest is invalid"))
      .mockResolvedValueOnce({ handle: runtimeHandle(), transferResult: TRANSFER_RESULT }),
    startEmpty: jest.fn(),
    continueExisting: jest.fn(),
    retryLocalStartup: jest.fn(),
    close: jest.fn(async () => undefined),
  };
  const dependencies = {
    prepare: jest.fn(async () => coordinator),
    pickCachedTransfer: jest.fn(async () => ({
      name: "owner.nutrition-transfer.json",
      size: 100,
      readText: async () => "bad",
      remove,
    })),
  };
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(
      LocalFirstStartRuntimeBootstrap,
      { dependencies, children: () => null },
    ));
  });
  await act(async () => {
    renderer.root.findByProps({ accessibilityLabel: "Import transfer file" }).props.onPress();
  });
  expect(renderer.root.findByProps({ accessibilityRole: "alert" }).props.children).toBe("Transfer digest is invalid");
  expect(renderer.root.findAllByType(Pressable)).toHaveLength(2);
  expect(remove).toHaveBeenCalledTimes(1);
  await act(async () => {
    renderer.root.findByProps({ accessibilityLabel: "Import transfer file" }).props.onPress();
  });
  expect(coordinator.importTransfer).toHaveBeenCalledTimes(2);
  expect(remove).toHaveBeenCalledTimes(2);
  expect(renderer.root.findByProps({ children: "Transfer complete" })).toBeDefined();
  await act(async () => { renderer.unmount(); });
});

test("committed transfer with bootstrap failure retains evidence and offers bootstrap-only retry", async () => {
  const database = databaseHandle(false);
  const runtime = runtimeHandle();
  const bootstrap = jest.fn()
    .mockRejectedValueOnce(new Error("SQLite runtime foundation unavailable"))
    .mockResolvedValueOnce(runtime);
  const importTransfer = jest.fn(async () => TRANSFER_RESULT);
  const coordinator = await prepareLocalFirstStart({}, {
    openDatabase: jest.fn(async () => database),
    bootstrap,
    importTransfer,
  });
  const remove = jest.fn(async () => undefined);
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(
      LocalFirstStartRuntimeBootstrap,
      {
        dependencies: {
          prepare: async () => coordinator,
          pickCachedTransfer: async () => ({
            name: "owner.nutrition-transfer.json",
            size: 100,
            readText: async () => "package",
            remove,
          }),
        },
        children: () => React.createElement(Text, null, "app-ready"),
      },
    ));
  });

  await act(async () => {
    renderer.root.findByProps({ accessibilityLabel: "Import transfer file" }).props.onPress();
  });
  expect(importTransfer).toHaveBeenCalledTimes(1);
  expect(bootstrap).toHaveBeenCalledTimes(1);
  expect(renderer.root.findByProps({ accessibilityRole: "header" }).props.children)
    .toBe("Transfer committed; local startup incomplete");
  expect(renderer.root.findByProps({ accessibilityRole: "alert" }).props.children)
    .toContain("SQLite runtime foundation unavailable");
  expect(renderer.root.findAllByProps({ accessibilityLabel: "Import transfer file" })).toHaveLength(0);
  expect(renderer.root.findAllByProps({ accessibilityLabel: "Start with empty local profile" })).toHaveLength(0);
  expect(renderer.root.findByProps({ children: TRANSFER_RESULT.overallDigest })).toBeDefined();
  expectRenderedTextContaining(renderer, "daily_logs: 13");

  await act(async () => {
    renderer.root.findByProps({ accessibilityLabel: "Retry local startup" }).props.onPress();
  });
  expect(importTransfer).toHaveBeenCalledTimes(1);
  expect(bootstrap).toHaveBeenCalledTimes(2);
  expect(renderer.root.findByProps({ children: "Transfer complete" })).toBeDefined();
  expect(renderer.root.findByProps({ children: TRANSFER_RESULT.overallDigest })).toBeDefined();
  await act(async () => {
    renderer.root.findByProps({ accessibilityLabel: "Continue to Nutrition App" }).props.onPress();
  });
  expect(renderer.root.findByProps({ children: "app-ready" })).toBeDefined();
  expect(remove).toHaveBeenCalledTimes(1);
  await act(async () => { renderer.unmount(); });
});

test("reported files over 64 MiB are rejected before cache contents or SQLite are read", async () => {
  const remove = jest.fn(async () => undefined);
  const readText = jest.fn(async () => "not read");
  const coordinator = {
    databaseHandle: databaseHandle(false),
    state: "requires_decision" as const,
    importTransfer: jest.fn(),
    startEmpty: jest.fn(),
    continueExisting: jest.fn(),
    retryLocalStartup: jest.fn(),
    close: jest.fn(async () => undefined),
  };
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(
      LocalFirstStartRuntimeBootstrap,
      {
        dependencies: {
          prepare: async () => coordinator,
          pickCachedTransfer: async () => ({
            name: "owner.nutrition-transfer.json",
            size: E2_15_MAXIMUM_TRANSFER_BYTES + 1,
            readText,
            remove,
          }),
        },
        children: () => null,
      },
    ));
  });
  await act(async () => {
    renderer.root.findByProps({ accessibilityLabel: "Import transfer file" }).props.onPress();
  });
  expect(renderer.root.findByProps({ accessibilityRole: "alert" }).props.children)
    .toBe("The transfer file exceeds the 64 MiB maximum.");
  expect(readText).not.toHaveBeenCalled();
  expect(coordinator.importTransfer).not.toHaveBeenCalled();
  expect(remove).toHaveBeenCalledTimes(1);
  await act(async () => { renderer.unmount(); });
});
