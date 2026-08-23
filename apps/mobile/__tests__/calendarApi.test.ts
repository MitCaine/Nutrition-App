import { z } from "zod";

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

const mockedApiRequest =
  apiRequest as jest.MockedFunction<
    typeof apiRequest
  >;

const entryId =
  "11111111-1111-4111-8111-111111111111";

const unestablishedState = {
  is_established: false,
  authoritative_time_zone: null,
  calendar_revision: 0,
  today: null,
};

const establishedState = {
  is_established: true,
  authoritative_time_zone: "UTC",
  calendar_revision: 4,
  today: "2026-07-14",
};

const preview = {
  calendar_revision: 4,
  current_time_zone: "UTC",
  proposed_time_zone:
    "America/Los_Angeles",
  current_today: "2026-07-14",
  proposed_today: "2026-07-13",
  today_changes: true,
  affected_entry_count: 1,
  affected_dates: [
    "2026-07-14",
  ],
  affected_entries: [
    {
      id: entryId,
      logged_date: "2026-07-14",
      food_name_snapshot: "Food",
      meal_type: null,
      amount_quantity: "1.500000",
      amount_unit: "serving",
    },
  ],
  preview_token: "preview-token",
};

describe("calendar API", () => {
  beforeEach(() =>
    mockedApiRequest.mockReset()
  );

  it(
    "reads complete owner-scoped calendar authority",
    async () => {
      mockedApiRequest.mockResolvedValue(
        unestablishedState,
      );

      await expect(
        getCalendarState(),
      ).resolves.toEqual(
        unestablishedState,
      );

      expect(
        mockedApiRequest,
      ).toHaveBeenCalledWith(
        "/settings/calendar",
      );
    },
  );

  it(
    "sends explicit initial confirmation and validates the returned state",
    async () => {
      mockedApiRequest.mockResolvedValue(
        establishedState,
      );

      await expect(
        establishCalendarTimeZone("UTC"),
      ).resolves.toEqual(
        establishedState,
      );

      expect(
        mockedApiRequest,
      ).toHaveBeenCalledWith(
        "/settings/calendar",
        {
          method: "PUT",
          body: JSON.stringify({
            time_zone: "UTC",
          }),
        },
      );
    },
  );

  it(
    "validates owner-scoped impact preview including affected entries",
    async () => {
      mockedApiRequest.mockResolvedValue(
        preview,
      );

      await expect(
        previewCalendarTimeZoneChange(
          "America/Los_Angeles",
        ),
      ).resolves.toEqual(
        preview,
      );

      expect(
        mockedApiRequest,
      ).toHaveBeenCalledWith(
        "/settings/calendar/preview",
        {
          method: "POST",
          body: JSON.stringify({
            time_zone:
              "America/Los_Angeles",
          }),
        },
      );
    },
  );

  it(
    "confirms a reviewed revision and validates the returned state",
    async () => {
      const confirmed = {
        ...establishedState,
        authoritative_time_zone:
          "America/Los_Angeles",
        calendar_revision: 5,
        today: "2026-07-13",
      };

      mockedApiRequest.mockResolvedValue(
        confirmed,
      );

      await expect(
        confirmCalendarTimeZoneChange({
          timeZone:
            "America/Los_Angeles",
          calendarRevision: 4,
          previewToken:
            "preview-token",
        }),
      ).resolves.toEqual(
        confirmed,
      );

      expect(
        mockedApiRequest,
      ).toHaveBeenCalledWith(
        "/settings/calendar/confirm",
        {
          method: "POST",
          body: JSON.stringify({
            time_zone:
              "America/Los_Angeles",
            calendar_revision: 4,
            confirm_impacts: true,
            preview_token:
              "preview-token",
          }),
        },
      );
    },
  );

  it.each([
    [
      "missing calendar revision",
      {
        is_established: false,
        authoritative_time_zone: null,
        today: null,
      },
    ],
    [
      "missing today",
      {
        is_established: false,
        authoritative_time_zone: null,
        calendar_revision: 0,
      },
    ],
    [
      "invalid today",
      {
        ...unestablishedState,
        today: "2026-02-30",
      },
    ],
    [
      "fractional revision",
      {
        ...unestablishedState,
        calendar_revision: 1.5,
      },
    ],
    [
      "unexpected field",
      {
        ...unestablishedState,
        unexpected: true,
      },
    ],
  ])(
    "rejects malformed Calendar state: %s",
    async (_name, response) => {
      mockedApiRequest.mockResolvedValue(
        response,
      );

      await expect(
        getCalendarState(),
      ).rejects.toBeInstanceOf(
        z.ZodError,
      );
    },
  );

  it.each([
    [
      "invalid affected entry UUID",
      {
        ...preview,
        affected_entries: [
          {
            ...preview
              .affected_entries[0],
            id: "log-1",
          },
        ],
      },
    ],
    [
      "numeric affected amount",
      {
        ...preview,
        affected_entries: [
          {
            ...preview
              .affected_entries[0],
            amount_quantity: 1.5,
          },
        ],
      },
    ],
    [
      "invalid affected date",
      {
        ...preview,
        affected_dates: [
          "2026-02-30",
        ],
      },
    ],
    [
      "negative affected count",
      {
        ...preview,
        affected_entry_count: -1,
      },
    ],
    [
      "unexpected preview field",
      {
        ...preview,
        unexpected: true,
      },
    ],
  ])(
    "rejects malformed Calendar preview: %s",
    async (_name, response) => {
      mockedApiRequest.mockResolvedValue(
        response,
      );

      await expect(
        previewCalendarTimeZoneChange(
          "America/Los_Angeles",
        ),
      ).rejects.toBeInstanceOf(
        z.ZodError,
      );
    },
  );
});
