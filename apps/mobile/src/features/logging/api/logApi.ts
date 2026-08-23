import { apiRequest } from "../../../shared/api/client";
import {
  parseDailyLogCompletion,
  parseDailyLog,
  parseDailyLogList,
  parseDailyLogMutationStatus,
  parseDailyLogEditContext,
  parseDailySummaryResponse,
  parseHistoryRangeResponse,
  parseRecentEntryList,
} from "./logResponseSchemas";
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
  HistoryRangeEvidence,
  RecentEntry,
} from "./types";

export async function listLogs(date: string): Promise<DailyLog[]> {
  return parseDailyLogList(await apiRequest<unknown>(`/logs?date=${encodeURIComponent(date)}`));
}

export async function listFutureEntries(date: string): Promise<DailyLog[]> {
  return parseDailyLogList(await apiRequest<unknown>(
    `/logs/future-entries?date=${encodeURIComponent(date)}`,
  ));
}

export async function listRecentEntries(): Promise<RecentEntry[]> {
  return parseRecentEntryList(
    await apiRequest<unknown>("/logs/recent-entries"),
  );
}

export async function createLog(input: DailyLogCreateInput): Promise<DailyLog> {
  return parseDailyLog(await apiRequest<unknown>("/logs", {
    method: "POST",
    body: JSON.stringify(input),
  }));
}

export async function updateLog(logId: string, input: Partial<DailyLogUpdateInput>): Promise<DailyLog> {
  return parseDailyLog(await apiRequest<unknown>(`/logs/${logId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  }));
}

export async function getLogEditContext(logId: string): Promise<DailyLogEditContext> {
  return parseDailyLogEditContext(
    await apiRequest<unknown>(`/logs/${logId}/edit-context`),
  );
}

export function deleteLog(logId: string, input: DailyLogDeleteInput = {}): Promise<void> {
  const options: RequestInit = { method: "DELETE" };
  if (Object.keys(input).length > 0) {
    options.body = JSON.stringify(input);
  }
  return apiRequest<void>(`/logs/${logId}`, options);
}

export async function markDayComplete(input: DailyLogCompleteInput): Promise<DailyLogCompletion> {
  return parseDailyLogCompletion(await apiRequest<unknown>("/logs/complete", {
    method: "POST",
    body: JSON.stringify(input),
  }));
}

export async function getLogMutationStatus(
  clientRequestId: string,
  operation?: DailyLogMutationStatus["operation"],
): Promise<DailyLogMutationStatus> {
  const suffix = operation ? `?operation=${encodeURIComponent(operation)}` : "";
  return parseDailyLogMutationStatus(
    await apiRequest<unknown>(`/logs/mutations/${clientRequestId}${suffix}`),
  );
}

export async function getHistoryRange(
  startDate: string,
  endDate: string,
): Promise<HistoryRangeEvidence> {
  const response = parseHistoryRangeResponse(await apiRequest<unknown>(
    `/logs/history-range?start_date=${encodeURIComponent(startDate)}&end_date=${encodeURIComponent(endDate)}`,
  ));
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
  const response = parseDailySummaryResponse(await apiRequest<unknown>(
    `/logs/daily-summary?date=${encodeURIComponent(date)}`,
  ));
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
