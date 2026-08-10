import React from "react";
import { Text } from "react-native";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import TestRenderer, { act } from "react-test-renderer";

import type { MobileRuntimeConfig } from "../config/runtimeConfig";
import type { NutritionRuntime } from "../src/runtime/NutritionRuntime";
import type { ApplicationRuntimeHandle } from "../src/runtime/applicationRuntimeBootstrap";

const mockRecoveryStops: jest.Mock[] = [];
const mockStartRecovery = jest.fn((_client: QueryClient, _dependencies: unknown) => {
  const stop = jest.fn();
  mockRecoveryStops.push(stop);
  return stop;
});

jest.mock("../src/features/logging/recovery/logMutationRecovery", () => ({
  startLogMutationRecovery: (client: QueryClient, dependencies: unknown) =>
    mockStartRecovery(client, dependencies),
}));

jest.mock("../src/app/theme/AppTheme", () => ({
  AppThemeProvider: ({ children }: { children: React.ReactNode }) => children,
}));

import { AppProviders } from "../src/app/providers/AppProviders";
import {
  ApplicationRuntimeBootstrap,
} from "../src/runtime/RuntimeBootstrapGate";

const LOCAL_CONFIG: MobileRuntimeConfig = {
  dataAuthority: "local",
  deploymentMode: "production",
};
const REMOTE_CONFIG: MobileRuntimeConfig = {
  dataAuthority: "remote",
  deploymentMode: "test",
  apiBaseUrl: "http://localhost:8000/api/v1",
};

function runtime(kind: "local" | "remote", suffix: string = kind): NutritionRuntime {
  const capability = {};
  return {
    authority: {
      kind,
      recoveryScope: kind === "local"
        ? "local:00000000-0000-4000-8000-000000000001"
        : `test:http://localhost:8000/api/v1:${suffix}`,
    },
    calendar: capability,
    nutrients: capability,
    foods: capability,
    recipes: capability,
    dailyLogs: capability,
    targets: capability,
    ocr: capability,
    usda: capability,
  } as unknown as NutritionRuntime;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  mockStartRecovery.mockClear();
  mockRecoveryStops.length = 0;
});

test("bootstrap keeps queries and providers unmounted until selection finishes and presents failure explicitly", async () => {
  const pending = deferred<ApplicationRuntimeHandle>();
  const failed = deferred<ApplicationRuntimeHandle>();
  const bootstrap = jest.fn((configuration: MobileRuntimeConfig) =>
    configuration.dataAuthority === "local" ? pending.promise : failed.promise);
  const local = runtime("local");
  let renderer!: TestRenderer.ReactTestRenderer;

  await act(async () => {
    renderer = TestRenderer.create(
      React.createElement(
        ApplicationRuntimeBootstrap,
        {
          configuration: LOCAL_CONFIG,
          bootstrap,
          children: () => React.createElement(Text, null, "feature-query-mounted"),
        },
      ),
    );
  });

  expect(renderer.root.findAllByProps({ children: "feature-query-mounted" })).toHaveLength(0);
  expect(renderer.root.findByProps({ children: "Starting local nutrition data…" })).toBeDefined();

  await act(async () => {
    pending.resolve({ runtime: local, close: async () => undefined });
    await pending.promise;
  });
  expect(renderer.root.findByProps({ children: "feature-query-mounted" })).toBeDefined();

  await act(async () => {
    renderer.update(
      React.createElement(
        ApplicationRuntimeBootstrap,
        {
          configuration: REMOTE_CONFIG,
          bootstrap,
          children: () => React.createElement(Text, null, "remote-feature-query-mounted"),
        },
      ),
    );
  });
  await act(async () => {
    failed.reject(new Error("Remote configuration failed closed"));
    try { await failed.promise; } catch { /* assertion is rendered below */ }
  });
  expect(renderer.root.findByProps({ children: "Remote configuration failed closed" })).toBeDefined();
  expect(renderer.root.findAllByProps({ children: "remote-feature-query-mounted" })).toHaveLength(0);

  await act(async () => { renderer.unmount(); });
});

test("an authority change retires the old Query cache and restarts recovery with only the new identity", async () => {
  const local = runtime("local");
  const remote = runtime("remote", "owner-b");
  const observedClients: QueryClient[] = [];

  function Observer() {
    const client = useQueryClient();
    if (!observedClients.includes(client)) observedClients.push(client);
    return null;
  }

  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(
      React.createElement(AppProviders, { runtime: local }, React.createElement(Observer)),
    );
  });
  const localClient = observedClients[0];
  localClient.setQueryData(["foods"], [{ id: "local-food" }]);
  expect(mockStartRecovery.mock.calls[0][1]).toEqual({
    authority: local.authority,
    dailyLogs: local.dailyLogs,
  });

  await act(async () => {
    renderer.update(
      React.createElement(AppProviders, { runtime: remote }, React.createElement(Observer)),
    );
  });

  const remoteClient = observedClients[1];
  expect(remoteClient).not.toBe(localClient);
  expect(localClient.getQueryData(["foods"])).toBeUndefined();
  expect(remoteClient.getQueryData(["foods"])).toBeUndefined();
  expect(mockRecoveryStops[0]).toHaveBeenCalledTimes(1);
  expect(mockStartRecovery.mock.calls[1][1]).toEqual({
    authority: remote.authority,
    dailyLogs: remote.dailyLogs,
  });

  await act(async () => { renderer.unmount(); });
  expect(mockRecoveryStops[1]).toHaveBeenCalledTimes(1);
});
