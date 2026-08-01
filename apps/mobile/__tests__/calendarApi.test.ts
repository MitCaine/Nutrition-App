jest.mock("../src/shared/api/client", () => ({
  apiRequest: jest.fn(),
}));

import { apiRequest } from "../src/shared/api/client";
import { establishCalendarTimeZone, getCalendarState } from "../src/features/calendar/api/calendarApi";

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
});
