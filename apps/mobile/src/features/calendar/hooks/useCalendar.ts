import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNutritionRuntime } from "../../../runtime/NutritionRuntimeContext";

export const CALENDAR_QUERY_KEY = ["calendar", "state"] as const;

export function useCalendarState() {
  const runtime = useNutritionRuntime();
  return useQuery({
    queryKey: CALENDAR_QUERY_KEY,
    queryFn: () => runtime.calendar.getState(),
    // ``today`` is derived by the server at read time.  Refresh it so a
    // midnight rollover reclassifies the retained selected date without
    // navigating away from the user's active workflow.
    refetchInterval: 60_000,
  });
}

export function useEstablishCalendarTimeZone() {
  const runtime = useNutritionRuntime();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (timeZone: Parameters<typeof runtime.calendar.establishTimeZone>[0]) =>
      runtime.calendar.establishTimeZone(timeZone),
    onSuccess: (state) => {
      queryClient.setQueryData(CALENDAR_QUERY_KEY, state);
    },
  });
}

export function usePreviewCalendarTimeZoneChange() {
  const runtime = useNutritionRuntime();
  return useMutation({
    mutationFn: (timeZone: Parameters<typeof runtime.calendar.previewTimeZoneChange>[0]) =>
      runtime.calendar.previewTimeZoneChange(timeZone),
  });
}

export function useConfirmCalendarTimeZoneChange() {
  const runtime = useNutritionRuntime();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: Parameters<typeof runtime.calendar.confirmTimeZoneChange>[0]) =>
      runtime.calendar.confirmTimeZoneChange(input),
    onSuccess: (state) => {
      queryClient.setQueryData(CALENDAR_QUERY_KEY, state);
    },
  });
}
