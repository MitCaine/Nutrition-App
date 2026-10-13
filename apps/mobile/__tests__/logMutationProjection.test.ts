import React from "react";
import TestRenderer, { act } from "react-test-renderer";
import { QueryClientProvider } from "@tanstack/react-query";
import { localAuthorityIdentity, remoteAuthorityIdentity } from "../src/runtime/authorityIdentity";
import { createNutritionTestRuntime, withNutritionRuntime } from "./nutritionRuntimeTestSupport";
import { QueryClient } from "@tanstack/react-query";

import { dailyLogReadState, projectConfirmedDelete, projectConfirmedLog, useLogMutations } from "../src/features/logging/hooks/useLogs";
import type { DailyLog } from "../src/features/logging/api/types";

const entry = (id: string, date: string, notes = "before"): DailyLog => ({
  id,
  food_item_id: "food-1",
  source_food_available: true,
  logged_date: date,
  amount_quantity: "1",
  amount_unit: "serving",
  notes,
});

test("confirmed move projects to the destination and removes the source entry", () => {
  const client = new QueryClient();
  client.setQueryData(["logs", "2026-07-08"], [entry("log-1", "2026-07-08")]);

  projectConfirmedLog(client, "2026-07-08", entry("log-1", "2026-07-09", "updated"));

  expect(client.getQueryData(["logs", "2026-07-08"])).toEqual([]);
  expect(client.getQueryData(["logs", "2026-07-09"])).toEqual([
    entry("log-1", "2026-07-09", "updated"),
  ]);
  client.clear();
});

test("confirmed deletion remains projected when reads are refreshed independently", () => {
  const client = new QueryClient();
  client.setQueryData(["logs", "2026-07-08"], [entry("log-1", "2026-07-08"), entry("log-2", "2026-07-08")]);

  projectConfirmedDelete(client, "2026-07-08", "log-1");

  expect(client.getQueryData(["logs", "2026-07-08"])).toEqual([entry("log-2", "2026-07-08")]);
  client.clear();
});

test("confirmed create and edit project immediately into the visible date", () => {
  const client = new QueryClient();
  client.setQueryData(["logs", "2026-07-08"], []);
  projectConfirmedLog(client, "2026-07-08", entry("log-1", "2026-07-08", "created"));
  expect(client.getQueryData(["logs", "2026-07-08"])).toEqual([
    entry("log-1", "2026-07-08", "created"),
  ]);

  projectConfirmedLog(client, "2026-07-08", entry("log-1", "2026-07-08", "edited"));
  expect(client.getQueryData(["logs", "2026-07-08"])).toEqual([
    entry("log-1", "2026-07-08", "edited"),
  ]);
  client.clear();
});

test("a projected confirmed delete remains after a refresh invalidation", () => {
  const client = new QueryClient();
  client.setQueryData(["logs", "2026-07-08"], [entry("log-1", "2026-07-08"), entry("log-2", "2026-07-08")]);
  projectConfirmedDelete(client, "2026-07-08", "log-1");
  client.invalidateQueries({ queryKey: ["logs", "2026-07-08"] });
  expect(client.getQueryData(["logs", "2026-07-08"])).toEqual([entry("log-2", "2026-07-08")]);
  client.clear();
});

test("daily log read states distinguish initial, empty, success, refresh, and failures", () => {
  const retry = jest.fn();
  const base = { isError: false, isFetching: false, isLoading: false, refetch: retry };
  expect(dailyLogReadState({ ...base, data: undefined, isLoading: true }).kind).toBe("initial-loading");
  expect(dailyLogReadState({ ...base, data: undefined, isError: true, error: new Error("offline") }).kind).toBe("initial-failure");
  expect(dailyLogReadState({ ...base, data: [] }).kind).toBe("empty");
  expect(dailyLogReadState({ ...base, data: [entry("log-1", "2026-07-08")] }).kind).toBe("success");
  expect(dailyLogReadState({ ...base, data: [entry("log-1", "2026-07-08")], isFetching: true }).kind).toBe("refreshing");
  expect(dailyLogReadState({ ...base, data: [entry("log-1", "2026-07-08")], isError: true, isRefetchError: true, error: new Error("offline") }).kind).toBe("refresh-failure");
  dailyLogReadState({ ...base, data: undefined, isLoading: true }).retry();
  expect(retry).toHaveBeenCalled();
});

test.each(["local", "remote"] as const)("normal %s create success preserves its selected cache policy", async (kind) => {
  const client = new QueryClient({ defaultOptions: { mutations: { gcTime: Infinity }, queries: { gcTime: Infinity } } });
  const date = "2026-07-08";
  const historical = entry("deleted-log", date);
  const current = [entry("remaining-log", date)];
  client.setQueryData(["logs", date], current);
  const runtime = createNutritionTestRuntime({ authority: kind === "local" ? localAuthorityIdentity("00000000-0000-4000-8000-000000000001") : remoteAuthorityIdentity("remote-projection-control"), dailyLogs: { ...createNutritionTestRuntime().dailyLogs, create: async () => historical } });
  let mutations!: ReturnType<typeof useLogMutations>;
  function Probe() { mutations = useLogMutations(date); return null; }
  let renderer!: TestRenderer.ReactTestRenderer;
  try {
    await act(async () => { renderer = TestRenderer.create(React.createElement(QueryClientProvider, { client }, withNutritionRuntime(React.createElement(Probe), runtime))); });
    await act(async () => { await mutations.createLog.mutateAsync({ client_request_id: "request-id", food_item_id: "food-1", logged_date: date, amount_quantity: "1", amount_unit: "serving" }); });
    expect(client.getQueryData(["logs", date])).toEqual(kind === "local" ? current : [...current, historical]);
    expect(client.getQueryState(["logs", date])?.isInvalidated).toBe(true);
  } finally { if (renderer) await act(async () => renderer.unmount()); client.clear(); }
});
