import { calendarMutationsEnabled, calendarStateLabel } from "../src/features/calendar/calendarModel";

describe("authoritative calendar state", () => {
  it("keeps Daily Log mutations unavailable until explicit confirmation", () => {
    expect(calendarMutationsEnabled(undefined)).toBe(false);
    expect(calendarMutationsEnabled({ is_established: false, authoritative_time_zone: null })).toBe(false);
    expect(calendarMutationsEnabled({ is_established: true, authoritative_time_zone: "America/Los_Angeles" })).toBe(true);
  });

  it("identifies a device zone as provisional and never treats it as confirmed", () => {
    expect(calendarStateLabel(undefined, "Europe/Berlin")).toBe(
      "Provisional device time zone: Europe/Berlin",
    );
    expect(calendarStateLabel({ is_established: true, authoritative_time_zone: "UTC" }, "Europe/Berlin")).toBe(
      "Authoritative time zone: UTC",
    );
  });
});
