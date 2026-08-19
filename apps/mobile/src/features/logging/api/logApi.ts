import { apiRequest } from "../../../shared/api/client";
import type {
  DailyLog,
  DailyLogCompleteInput,
  DailyLogCompletion,
  DailyLogCreateInput,
  DailyLogDeleteInput,
  DailyLogEditContext,
  DailyLogMutationStatus,
  DailyLogUpdateInput,
  DailySummary,
  DailySummaryResponse,
  HistoryRangeEvidence,
  HistoryRangeResponse,
  RecentEntry,
} from "./types";

export async function listLogs(date: string): Promise<DailyLog[]> {
  const response = await apiRequest<{ logs: DailyLog[] }>(`/logs?date=${encodeURIComponent(date)}`);
  return response.logs;
}

export async function listFutureEntries(date: string): Promise<DailyLog[]> {
  const response = await apiRequest<{ logs: DailyLog[] }>(
    `/logs/future-entries?date=${encodeURIComponent(date)}`,
  );
  return response.logs;
}

export async function listRecentEntries(): Promise<RecentEntry[]> {
  const response = await apiRequest<{ entries: RecentEntry[] }>("/logs/recent-entries");
  return response.entries;
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

export function markDayComplete(input: DailyLogCompleteInput): Promise<DailyLogCompletion> {
  return apiRequest<DailyLogCompletion>("/logs/complete", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getLogMutationStatus(
  clientRequestId: string,
  operation?: DailyLogMutationStatus["operation"],
): Promise<DailyLogMutationStatus> {
  const suffix = operation ? `?operation=${encodeURIComponent(operation)}` : "";
  return apiRequest<DailyLogMutationStatus>(`/logs/mutations/${clientRequestId}${suffix}`);
}

export async function getHistoryRange(
  startDate: string,
  endDate: string,
): Promise<HistoryRangeEvidence> {
  const response = await apiRequest<HistoryRangeResponse>(
    `/logs/history-range?start_date=${encodeURIComponent(startDate)}&end_date=${encodeURIComponent(endDate)}`,
  );
  return {
    startDate: response.start_date,
    endDate: response.end_date,
    firstLoggedDate: response.first_logged_date,
    days: response.days.map((day) => ({
      date: day.date,
      hasLogs: day.has_logs,
      isComplete: day.is_complete,
      nutrients: day.nutrients.map((nutrient) => ({
        nutrientId: nutrient.nutrient_id,
        amountKnown: nutrient.amount_known,
        amountEstimated: nutrient.amount_estimated,
        unit: nutrient.unit,
        hasNumericEvidence: nutrient.has_numeric_evidence,
        isExplicitZeroTotal: nutrient.is_explicit_zero_total,
        hasUnknownContributors: nutrient.has_unknown_contributors,
        unknownContributorCount: nutrient.unknown_contributor_count,
      })),
    })),
  };
}

export async function getDailySummary(date: string): Promise<DailySummary> {
  const response = await apiRequest<DailySummaryResponse>(
    `/logs/daily-summary?date=${encodeURIComponent(date)}`,
  );
  return {
    logged_date: response.logged_date,
    is_complete: response.is_complete,
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
