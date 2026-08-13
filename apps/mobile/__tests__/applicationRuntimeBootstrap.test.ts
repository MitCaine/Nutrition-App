import type { MobileRuntimeConfig } from "../config/runtimeConfig";
import type { NutritionRuntime } from "../src/runtime/NutritionRuntime";
import {
  ApplicationRuntimeSelectionManager,
  NUTRITION_RUNTIME_CAPABILITIES,
  bootstrapApplicationRuntime,
  type ApplicationRuntimeHandle,
} from "../src/runtime/applicationRuntimeBootstrap";

const LOCAL_CONFIG: MobileRuntimeConfig = {
  dataAuthority: "local",
  deploymentMode: "production",
};
const REMOTE_CONFIG: MobileRuntimeConfig = {
  dataAuthority: "remote",
  deploymentMode: "test",
  apiBaseUrl: "http://localhost:8000/api/v1",
};

function runtime(kind: "local" | "remote", suffix = kind): NutritionRuntime {
  const capability = () => Object.freeze({ marker: suffix });
  return {
    authority: Object.freeze({
      kind,
      recoveryScope: kind === "local"
        ? "local:00000000-0000-4000-8000-000000000001"
        : `test:http://localhost:8000/api/v1:${suffix}`,
    }),
    calendar: capability(),
    nutrients: capability(),
    foods: capability(),
    recipes: capability(),
    dailyLogs: capability(),
    targets: capability(),
    ocr: capability(),
    usda: capability(),
  } as unknown as NutritionRuntime;
}

test("local selection opens only the complete local registry", async () => {
  const local = Object.assign(runtime("local"), { close: jest.fn(async () => undefined) });
  const openLocalRuntime = jest.fn(async () => local);
  const loadRemoteRuntime = jest.fn(async () => {
    throw new Error("remote construction must not run");
  });
  const fetchSpy = jest.spyOn(global, "fetch");

  const handle = await bootstrapApplicationRuntime(LOCAL_CONFIG, {
    openLocalRuntime,
    loadRemoteRuntime,
  });

  expect(handle.runtime).toBe(local);
  expect(openLocalRuntime).toHaveBeenCalledTimes(1);
  expect(loadRemoteRuntime).not.toHaveBeenCalled();
  expect(fetchSpy).not.toHaveBeenCalled();
  expect(NUTRITION_RUNTIME_CAPABILITIES.every((name) => handle.runtime[name] === local[name])).toBe(true);
  await handle.close();
  expect(local.close).toHaveBeenCalledTimes(1);
  fetchSpy.mockRestore();
});

test("remote selection loads only the existing remote registry and never opens SQLite", async () => {
  const remote = runtime("remote");
  const openLocalRuntime = jest.fn(async () => {
    throw new Error("local persistence must not open");
  });
  const loadRemoteRuntime = jest.fn(async () => remote);

  const handle = await bootstrapApplicationRuntime(REMOTE_CONFIG, {
    openLocalRuntime,
    loadRemoteRuntime,
  });

  expect(handle.runtime).toBe(remote);
  expect(loadRemoteRuntime).toHaveBeenCalledTimes(1);
  expect(openLocalRuntime).not.toHaveBeenCalled();
});

test("a selected-authority failure stays visible and never probes the other authority", async () => {
  const openLocalRuntime = jest.fn(async () => {
    throw new Error("local SQLite bootstrap failed");
  });
  const loadRemoteRuntime = jest.fn(async () => {
    throw new Error("remote adapter bootstrap failed");
  });

  await expect(bootstrapApplicationRuntime(LOCAL_CONFIG, {
    openLocalRuntime,
    loadRemoteRuntime,
  })).rejects.toThrow("local SQLite bootstrap failed");
  expect(openLocalRuntime).toHaveBeenCalledTimes(1);
  expect(loadRemoteRuntime).not.toHaveBeenCalled();

  openLocalRuntime.mockClear();
  loadRemoteRuntime.mockClear();
  await expect(bootstrapApplicationRuntime(REMOTE_CONFIG, {
    openLocalRuntime,
    loadRemoteRuntime,
  })).rejects.toThrow("remote adapter bootstrap failed");
  expect(loadRemoteRuntime).toHaveBeenCalledTimes(1);
  expect(openLocalRuntime).not.toHaveBeenCalled();
});

test("a mismatched or incomplete registry fails instead of borrowing another authority", async () => {
  const wrong = Object.assign(runtime("remote"), { close: jest.fn(async () => undefined) });
  await expect(bootstrapApplicationRuntime(LOCAL_CONFIG, {
    openLocalRuntime: jest.fn(async () => wrong),
    loadRemoteRuntime: jest.fn(async () => runtime("remote")),
  })).rejects.toThrow("authority mismatch");
  expect(wrong.close).toHaveBeenCalledTimes(1);

  const incomplete = { ...runtime("remote"), targets: undefined } as unknown as NutritionRuntime;
  await expect(bootstrapApplicationRuntime(REMOTE_CONFIG, {
    openLocalRuntime: jest.fn(),
    loadRemoteRuntime: jest.fn(async () => incomplete),
  })).rejects.toThrow("missing the targets capability");
});

test("explicit authority switching closes the old authority before constructing the new one", async () => {
  const events: string[] = [];
  const local = runtime("local");
  const remote = runtime("remote");
  const handles: Record<string, ApplicationRuntimeHandle> = {
    local: {
      runtime: local,
      close: async () => { events.push("close:local"); },
    },
    remote: {
      runtime: remote,
      close: async () => { events.push("close:remote"); },
    },
  };
  const manager = new ApplicationRuntimeSelectionManager(async (configuration) => {
    events.push(`open:${configuration.dataAuthority}`);
    return handles[configuration.dataAuthority];
  });

  await manager.select(LOCAL_CONFIG);
  await manager.select(REMOTE_CONFIG);
  await manager.dispose();

  expect(events).toEqual([
    "open:local",
    "close:local",
    "open:remote",
    "close:remote",
  ]);
});
