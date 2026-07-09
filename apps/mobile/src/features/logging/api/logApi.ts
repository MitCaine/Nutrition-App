import { apiRequest } from "../../../shared/api/client";
import type { DailyLog, DailyLogInput, DailySummary, DailySummaryResponse } from "./types";

export async function listLogs(date: string): Promise<DailyLog[]> {
  const response = await apiRequest<{ logs: DailyLog[] }>(`/logs?date=${encodeURIComponent(date)}`);
  return response.logs;
}

export function createLog(input: DailyLogInput): Promise<DailyLog> {
  return apiRequest<DailyLog>("/logs", { method: "POST", body: JSON.stringify(input) });
}

export function updateLog(logId: string, input: Partial<DailyLogInput>): Promise<DailyLog> {
  return apiRequest<DailyLog>(`/logs/${logId}`, { method: "PATCH", body: JSON.stringify(input) });
}

export function deleteLog(logId: string): Promise<void> {
  return apiRequest<void>(`/logs/${logId}`, { method: "DELETE" });
}

export async function getDailySummary(date: string): Promise<DailySummary> {
  const response = await apiRequest<DailySummaryResponse>(
    `/logs/daily-summary?date=${encodeURIComponent(date)}`,
  );
  return {
    logged_date: response.logged_date,
    totals: response.totals.map((total) => ({
      nutrientId: total.nutrient_id,
      amountKnown: total.amount_known,
      amountEstimated: total.amount_estimated,
      unit: total.unit,
      hasUnknownContributors: total.has_unknown_contributors,
      unknownContributorCount: total.unknown_contributor_count,
    })),
  };
}
