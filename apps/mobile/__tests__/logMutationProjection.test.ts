import { QueryClient } from "@tanstack/react-query";

import { projectConfirmedDelete, projectConfirmedLog } from "../src/features/logging/hooks/useLogs";
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
