import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  confirmCalendarTimeZoneChange,
  establishCalendarTimeZone,
  getCalendarState,
  previewCalendarTimeZoneChange,
} from "../api/calendarApi";

export const CALENDAR_QUERY_KEY = ["calendar", "state"] as const;

export function useCalendarState() {
  return useQuery({
    queryKey: CALENDAR_QUERY_KEY,
    queryFn: getCalendarState,
  });
}

export function useEstablishCalendarTimeZone() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: establishCalendarTimeZone,
    onSuccess: (state) => {
      queryClient.setQueryData(CALENDAR_QUERY_KEY, state);
    },
  });
}

export function usePreviewCalendarTimeZoneChange() {
  return useMutation({ mutationFn: previewCalendarTimeZoneChange });
}

export function useConfirmCalendarTimeZoneChange() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: confirmCalendarTimeZoneChange,
    onSuccess: (state) => {
      queryClient.setQueryData(CALENDAR_QUERY_KEY, state);
    },
  });
}
