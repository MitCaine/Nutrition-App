import { apiRequest } from "../../../shared/api/client";
import type {
  DailyLog,
  DailyLogCreateInput,
  DailyLogDeleteInput,
  DailyLogEditContext,
  DailyLogMutationStatus,
  DailyLogUpdateInput,
  DailySummary,
  DailySummaryResponse,
} from "./types";

export async function listLogs(date: string): Promise<DailyLog[]> {
  const response = await apiRequest<{ logs: DailyLog[] }>(`/logs?date=${encodeURIComponent(date)}`);
  return response.logs;
}

export function createLog(input: DailyLogCreateInput): Promise<DailyLog> {
  return apiRequest<DailyLog>("/logs", { method: "POST", body: JSON.stringify(input) });
}

export function updateLog(logId: string, input: Partial<DailyLogUpdateInput>): Promise<DailyLog> {
  return apiRequest<DailyLog>(`/logs/${logId}`, { method: "PATCH", body: JSON.stringify(input) });
}

export function getLogEditContext(logId: string): Promise<DailyLogEditContext> {
  return apiRequest<DailyLogEditContext>(`/logs/${logId}/edit-context`);
}

export function deleteLog(logId: string, input: DailyLogDeleteInput = {}): Promise<void> {
  const options: RequestInit = { method: "DELETE" };
  if (Object.keys(input).length > 0) {
    options.body = JSON.stringify(input);
  }
  return apiRequest<void>(`/logs/${logId}`, options);
}

export function getLogMutationStatus(
  clientRequestId: string,
  operation?: DailyLogMutationStatus["operation"],
): Promise<DailyLogMutationStatus> {
  const suffix = operation ? `?operation=${encodeURIComponent(operation)}` : "";
  return apiRequest<DailyLogMutationStatus>(`/logs/mutations/${clientRequestId}${suffix}`);
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
