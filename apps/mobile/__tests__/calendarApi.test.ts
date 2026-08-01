jest.mock("../src/shared/api/client", () => ({
  apiRequest: jest.fn(),
}));

import { apiRequest } from "../src/shared/api/client";
import {
  confirmCalendarTimeZoneChange,
  establishCalendarTimeZone,
  getCalendarState,
  previewCalendarTimeZoneChange,
} from "../src/features/calendar/api/calendarApi";

const mockedApiRequest = apiRequest as jest.MockedFunction<typeof apiRequest>;

describe("calendar API", () => {
  beforeEach(() => mockedApiRequest.mockReset());

  it("reads owner-scoped calendar authority", async () => {
    mockedApiRequest.mockResolvedValue({ is_established: false, authoritative_time_zone: null });
    await getCalendarState();
    expect(mockedApiRequest).toHaveBeenCalledWith("/settings/calendar");
  });

  it("sends explicit confirmation rather than silently adopting a device zone", async () => {
    mockedApiRequest.mockResolvedValue({ is_established: true, authoritative_time_zone: "UTC" });
    await establishCalendarTimeZone("UTC");
    expect(mockedApiRequest).toHaveBeenCalledWith("/settings/calendar", {
      method: "PUT",
      body: JSON.stringify({ time_zone: "UTC" }),
    });
  });

  it("requests an owner-scoped impact preview", async () => {
    mockedApiRequest.mockResolvedValue({
      calendar_revision: 4,
      current_time_zone: "UTC",
      proposed_time_zone: "America/Los_Angeles",
      current_today: "2026-07-14",
      proposed_today: "2026-07-13",
      today_changes: true,
      affected_entry_count: 1,
      affected_dates: ["2026-07-14"],
      affected_entries: [],
      preview_token: "preview-token",
    });
    await previewCalendarTimeZoneChange("America/Los_Angeles");
    expect(mockedApiRequest).toHaveBeenCalledWith("/settings/calendar/preview", {
      method: "POST",
      body: JSON.stringify({ time_zone: "America/Los_Angeles" }),
    });
  });

  it("confirms a reviewed revision explicitly", async () => {
    mockedApiRequest.mockResolvedValue({
      is_established: true,
      authoritative_time_zone: "America/Los_Angeles",
      calendar_revision: 5,
    });
    await confirmCalendarTimeZoneChange({
      timeZone: "America/Los_Angeles",
      calendarRevision: 4,
      previewToken: "preview-token",
    });
    expect(mockedApiRequest).toHaveBeenCalledWith("/settings/calendar/confirm", {
      method: "POST",
      body: JSON.stringify({
        time_zone: "America/Los_Angeles",
        calendar_revision: 4,
        confirm_impacts: true,
        preview_token: "preview-token",
      }),
    });
  });
});
