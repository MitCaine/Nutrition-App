import {
  calendarToday,
  calendarContextChanged,
  calendarMutationsEnabled,
  calendarStateLabel,
} from "../src/features/calendar/calendarModel";

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

  it("detects a calendar revision change without altering retained flow state", () => {
    expect(calendarContextChanged(4, 4)).toBe(false);
    expect(calendarContextChanged(4, 5)).toBe(true);
    expect(calendarContextChanged(null, 5)).toBe(false);
  });

  it("derives today from the authoritative zone and a provisional zone before confirmation", () => {
    const now = new Date("2026-01-01T10:00:00.000Z");
    expect(calendarToday(
      { is_established: true, authoritative_time_zone: "Pacific/Kiritimati", today: "2026-01-02" },
      "UTC",
      now,
    )).toBe("2026-01-02");
    expect(calendarToday(
      { is_established: true, authoritative_time_zone: "Pacific/Kiritimati" },
      "UTC",
      now,
    )).toBe("2026-01-02");
    expect(calendarToday(
      { is_established: false, authoritative_time_zone: null },
      "America/Los_Angeles",
      now,
    )).toBe("2026-01-01");
  });
});
