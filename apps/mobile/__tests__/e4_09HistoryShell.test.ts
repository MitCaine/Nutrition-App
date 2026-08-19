jest.mock(
  "@expo/vector-icons",
  () => ({
    Ionicons: () => null,
  }),
);

jest.mock(
  "../src/features/history/historyQuery",
  () => ({
    ...jest.requireActual(
      "../src/features/history/historyQuery",
    ),
    useHistoryRange: jest.fn(),
  }),
);

import React from "react";
import {
  Text,
} from "react-native";
import TestRenderer, {
  act,
} from "react-test-renderer";

import {
  addCalendarDays,
} from "../src/features/logging/utils/dailyLogDisplay";
import {
  historyRangeQueryKey,
  useHistoryRange,
} from "../src/features/history/historyQuery";
import type {
  HistoryRangeEvidence,
} from "../src/features/logging/api/types";
import {
  HistoryScreen,
} from "../src/features/history/screens/HistoryScreen";
import {
  authoritativeHistoryToday,
  canPageHistoryNext,
  canPageHistoryPrevious,
  effectiveHistoryProjectionMode,
  freshHistorySession,
  historyRange,
  nextHistorySession,
  previousHistorySession,
  withHistoryDenominatorPreference,
  withHistoryFirstLoggedDate,
  withHistoryRangeLength,
  type HistorySession,
} from "../src/features/history/historyRangeModel";
import type {
  RuntimeAuthorityIdentity,
} from "../src/runtime/authorityIdentity";

const mockUseHistoryRange =
  useHistoryRange as unknown as jest.Mock;

const LOCAL:
  RuntimeAuthorityIdentity = {
    kind: "local",
    recoveryScope: "local-sqlite",
  };

function datesBetween(
  startDate: string,
  endDate: string,
): string[] {
  const result: string[] = [];
  let current = startDate;

  while (current <= endDate) {
    result.push(current);
    current =
      addCalendarDays(
        current,
        1,
      );
  }

  return result;
}

function makeEvidence({
  startDate = "2026-08-12",
  endDate = "2026-08-18",
  firstLoggedDate = "2026-08-01",
  loggedDates = [
    "2026-08-16",
    "2026-08-17",
    "2026-08-18",
  ],
  completeDates = [],
}: {
  startDate?: string;
  endDate?: string;
  firstLoggedDate?: string | null;
  loggedDates?: readonly string[];
  completeDates?: readonly string[];
} = {}): HistoryRangeEvidence {
  const logged =
    new Set(loggedDates);
  const complete =
    new Set(completeDates);

  return {
    startDate,
    endDate,
    firstLoggedDate,
    days: datesBetween(
      startDate,
      endDate,
    ).map((date) => ({
      date,
      hasLogs:
        logged.has(date),
      isComplete:
        complete.has(date),
      nutrients: [],
    })),
  };
}

function successfulQuery(
  evidence: HistoryRangeEvidence,
) {
  return {
    data: evidence,
    error: null,
    isError: false,
    isFetching: false,
    isLoading: false,
    isRefetchError: false,
    refetch: jest.fn(),
  };
}

function textValue(
  value: unknown,
): string {
  if (
    typeof value === "string"
    || typeof value === "number"
  ) {
    return String(value);
  }

  if (Array.isArray(value)) {
    return value
      .map(textValue)
      .join(" ");
  }

  return "";
}

function screenText(
  renderer:
    TestRenderer.ReactTestRenderer,
): string {
  return renderer.root
    .findAllByType(Text)
    .map(
      (node) =>
        textValue(
          node.props.children,
        ),
    )
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
}

describe(
  "E4-09 History range/session model",
  () => {
    test(
      "History launch Today exists only for an established authoritative calendar",
      () => {
        expect(
          authoritativeHistoryToday(
            undefined,
          ),
        ).toBeNull();

        expect(
          authoritativeHistoryToday({
            is_established: false,
            authoritative_time_zone:
              null,
            today:
              "2026-08-19",
          }),
        ).toBeNull();

        expect(
          authoritativeHistoryToday({
            is_established: true,
            authoritative_time_zone:
              null,
            today:
              "2026-08-19",
          }),
        ).toBeNull();

        expect(
          authoritativeHistoryToday({
            is_established: true,
            authoritative_time_zone:
              "America/Los_Angeles",
            today:
              null,
          }),
        ).toBeNull();

        expect(
          authoritativeHistoryToday({
            is_established: true,
            authoritative_time_zone:
              "America/Los_Angeles",
            today:
              "2026-08-19",
          }),
        ).toBe(
          "2026-08-19",
        );
      },
    );

    test(
      "fresh 7-day and 30-day ranges end yesterday and never include Today",
      () => {
        const seven =
          freshHistorySession(
            "2026-08-19",
          );

        expect(seven).toEqual({
          rangeLength: 7,
          endDate: "2026-08-18",
          latestEndDate: "2026-08-18",
          denominatorPreference:
            null,
        });

        expect(
          historyRange(seven),
        ).toEqual({
          startDate: "2026-08-12",
          endDate: "2026-08-18",
        });

        const thirty =
          withHistoryRangeLength(
            seven,
            30,
          );

        expect(
          historyRange(thirty),
        ).toEqual({
          startDate: "2026-07-20",
          endDate: "2026-08-18",
        });

        expect(
          historyRange(thirty)
            .endDate,
        ).not.toBe(
          "2026-08-19",
        );
      },
    );

    test(
      "whole-period paging crosses month and year boundaries by calendar date",
      () => {
        const seven:
          HistorySession = {
            rangeLength: 7,
            endDate: "2026-01-03",
            latestEndDate: "2026-01-03",
            denominatorPreference:
              null,
          };

        const previous =
          previousHistorySession(
            seven,
          );

        expect(previous.endDate)
          .toBe("2025-12-27");

        expect(
          historyRange(previous),
        ).toEqual({
          startDate: "2025-12-21",
          endDate: "2025-12-27",
        });

        const thirty:
          HistorySession = {
            rangeLength: 30,
            endDate: "2026-03-01",
            latestEndDate: "2026-03-01",
            denominatorPreference:
              null,
          };

        expect(
          previousHistorySession(
            thirty,
          ).endDate,
        ).toBe("2026-01-30");
      },
    );

    test(
      "calendar paging remains date-exact across spring and fall DST boundaries",
      () => {
        const spring:
          HistorySession = {
            rangeLength: 7,
            endDate: "2026-03-10",
            latestEndDate: "2026-03-10",
            denominatorPreference:
              null,
          };

        expect(
          previousHistorySession(
            spring,
          ).endDate,
        ).toBe("2026-03-03");

        expect(
          historyRange(spring),
        ).toEqual({
          startDate: "2026-03-04",
          endDate: "2026-03-10",
        });

        const fall:
          HistorySession = {
            rangeLength: 7,
            endDate: "2026-11-03",
            latestEndDate: "2026-11-03",
            denominatorPreference:
              null,
          };

        expect(
          previousHistorySession(
            fall,
          ).endDate,
        ).toBe("2026-10-27");

        expect(
          historyRange(fall),
        ).toEqual({
          startDate: "2026-10-28",
          endDate: "2026-11-03",
        });
      },
    );

    test(
      "range-mode changes re-anchor to latest and next paging never performs a partial clamp",
      () => {
        const latest =
          freshHistorySession(
            "2026-08-19",
          );

        expect(
          canPageHistoryNext(
            latest,
          ),
        ).toBe(false);

        const thirtyLatest =
          withHistoryRangeLength(
            latest,
            30,
          );

        expect(
          historyRange(
            thirtyLatest,
          ),
        ).toEqual({
          startDate: "2026-07-20",
          endDate: "2026-08-18",
        });

        const thirtyOlder =
          previousHistorySession(
            thirtyLatest,
          );

        expect(
          thirtyOlder.endDate,
        ).toBe("2026-07-19");

        expect(
          canPageHistoryNext(
            thirtyOlder,
          ),
        ).toBe(true);

        expect(
          nextHistorySession(
            thirtyOlder,
          ).endDate,
        ).toBe("2026-08-18");

        const sevenOlder =
          previousHistorySession(
            latest,
          );

        expect(
          sevenOlder.endDate,
        ).toBe("2026-08-11");

        const switched =
          withHistoryRangeLength(
            sevenOlder,
            30,
          );

        expect(
          switched.endDate,
        ).toBe("2026-08-18");

        expect(
          switched.latestEndDate,
        ).toBe("2026-08-18");
      },
    );

    test(
      "first logged date keeps the earliest partial window reachable and stops older paging",
      () => {
        const latest =
          freshHistorySession(
            "2026-08-19",
          );

        expect(
          canPageHistoryPrevious(
            latest,
            "2026-08-10",
          ),
        ).toBe(true);

        const earliestPartial =
          previousHistorySession(
            latest,
          );

        expect(
          historyRange(
            earliestPartial,
          ),
        ).toEqual({
          startDate: "2026-08-05",
          endDate: "2026-08-11",
        });

        expect(
          canPageHistoryPrevious(
            earliestPartial,
            "2026-08-10",
          ),
        ).toBe(false);

        expect(
          canPageHistoryPrevious(
            latest,
            null,
          ),
        ).toBe(false);
      },
    );

    test(
      "coverage preference never changes raw range identity",
      () => {
        const session =
          freshHistorySession(
            "2026-08-19",
          );

        const complete =
          withHistoryDenominatorPreference(
            session,
            "complete_days",
          );

        const logged =
          withHistoryDenominatorPreference(
            session,
            "logged_days",
          );

        expect(
          historyRange(complete),
        ).toEqual(
          historyRange(logged),
        );

        const range =
          historyRange(session);

        expect(
          historyRangeQueryKey(
            LOCAL,
            range.startDate,
            range.endDate,
          ),
        ).toEqual([
          "history-range",
          "local",
          "local-sqlite",
          "2026-08-12",
          "2026-08-18",
        ]);
      },
    );

    test(
      "effective mode defaults to Complete only when Complete evidence exists",
      () => {
        expect(
          effectiveHistoryProjectionMode(
            0,
            null,
          ),
        ).toBe(
          "logged_days",
        );

        expect(
          effectiveHistoryProjectionMode(
            1,
            null,
          ),
        ).toBe(
          "complete_days",
        );

        expect(
          effectiveHistoryProjectionMode(
            2,
            "logged_days",
          ),
        ).toBe(
          "logged_days",
        );

        expect(
          effectiveHistoryProjectionMode(
            0,
            "complete_days",
          ),
        ).toBe(
          "logged_days",
        );
      },
    );
  },
);

describe(
  "E4-09 History shell",
  () => {
    beforeEach(() => {
      mockUseHistoryRange
        .mockReset();
    });

    test(
      "publishes authority-global firstLoggedDate for AppNavigator session ownership",
      async () => {
        mockUseHistoryRange
          .mockReturnValue(
            successfulQuery(
              makeEvidence({
                firstLoggedDate:
                  "2026-06-14",
              }),
            ),
          );

        const onFirstLoggedDateChange =
          jest.fn();

        let renderer!:
          TestRenderer.ReactTestRenderer;

        await act(async () => {
          renderer =
            TestRenderer.create(
              React.createElement(
                HistoryScreen,
                {
                  session:
                    freshHistorySession(
                      "2026-08-19",
                    ),
                  onSessionChange:
                    jest.fn(),
                  onFirstLoggedDateChange,
                  onBack:
                    jest.fn(),
                },
              ),
            );
        });

        expect(
          onFirstLoggedDateChange,
        ).toHaveBeenCalledWith(
          "2026-06-14",
        );

        await act(async () => {
          renderer.unmount();
        });
      },
    );

    test(
      "retained firstLoggedDate keeps Previous available while the newly selected range is still loading",
      async () => {
        mockUseHistoryRange
          .mockReturnValue({
            data: undefined,
            error: null,
            isError: false,
            isFetching: true,
            isLoading: true,
            isRefetchError: false,
            refetch: jest.fn(),
          });

        const latest =
          freshHistorySession(
            "2026-08-19",
          );

        const selected =
          withHistoryFirstLoggedDate(
            previousHistorySession(
              latest,
            ),
            "2026-06-01",
          );

        const onSessionChange =
          jest.fn();

        let renderer!:
          TestRenderer.ReactTestRenderer;

        await act(async () => {
          renderer =
            TestRenderer.create(
              React.createElement(
                HistoryScreen,
                {
                  session: selected,
                  onSessionChange,
                  onFirstLoggedDateChange:
                    jest.fn(),
                  onBack:
                    jest.fn(),
                },
              ),
            );
        });

        const previous =
          renderer.root.findByProps({
            accessibilityLabel:
              "Previous History period",
          });

        expect(
          previous.props
            .accessibilityState.disabled,
        ).toBe(false);

        await act(async () => {
          previous.props.onPress();
        });

        expect(
          onSessionChange,
        ).toHaveBeenCalledWith(
          previousHistorySession(
            selected,
          ),
        );

        expect(
          mockUseHistoryRange,
        ).toHaveBeenCalledWith(
          "2026-08-05",
          "2026-08-11",
        );

        await act(async () => {
          renderer.unmount();
        });
      },
    );

    test(
      "reads the exact selected range and uses Logged days without a disabled Complete selector when no Complete dates exist",
      async () => {
        mockUseHistoryRange
          .mockReturnValue(
            successfulQuery(
              makeEvidence(),
            ),
          );

        const onSessionChange =
          jest.fn();

        let renderer!:
          TestRenderer.ReactTestRenderer;

        await act(async () => {
          renderer =
            TestRenderer.create(
              React.createElement(
                HistoryScreen,
                {
                  session:
                    freshHistorySession(
                      "2026-08-19",
                    ),
                  onSessionChange,
                  onFirstLoggedDateChange:
                    jest.fn(),
                  onBack: jest.fn(),
                },
              ),
            );
        });

        expect(
          mockUseHistoryRange,
        ).toHaveBeenCalledWith(
          "2026-08-12",
          "2026-08-18",
        );

        const text =
          screenText(renderer);

        expect(text).toContain(
          "History",
        );
        expect(text).toContain(
          "Coverage mode: Logged days",
        );
        expect(text).toContain(
          "3 logged days",
        );

        expect(
          renderer.root
            .findAllByProps({
              accessibilityLabel:
                "Use Complete days",
            }),
        ).toHaveLength(0);

        expect(
          renderer.root
            .findByProps({
              accessibilityLabel:
                "Next History period",
            })
            .props
            .accessibilityState
            .disabled,
        ).toBe(true);

        await act(async () => {
          renderer.unmount();
        });
      },
    );

    test(
      "Complete evidence defaults coverage to Complete days and allows an explicit Logged-day preference",
      async () => {
        mockUseHistoryRange
          .mockReturnValue(
            successfulQuery(
              makeEvidence({
                completeDates: [
                  "2026-08-17",
                  "2026-08-18",
                ],
              }),
            ),
          );

        const session =
          freshHistorySession(
            "2026-08-19",
          );

        const onSessionChange =
          jest.fn();

        let renderer!:
          TestRenderer.ReactTestRenderer;

        await act(async () => {
          renderer =
            TestRenderer.create(
              React.createElement(
                HistoryScreen,
                {
                  session,
                  onSessionChange,
                  onFirstLoggedDateChange:
                    jest.fn(),
                  onBack: jest.fn(),
                },
              ),
            );
        });

        expect(
          screenText(renderer),
        ).toContain(
          "Coverage mode: Complete days",
        );

        const completeControl =
          renderer.root.findByProps({
            accessibilityLabel:
              "Use Complete days",
          });

        expect(
          completeControl.props
            .accessibilityState.checked,
        ).toBe(true);

        await act(async () => {
          renderer.root
            .findByProps({
              accessibilityLabel:
                "Use Logged days",
            })
            .props.onPress();
        });

        expect(
          onSessionChange,
        ).toHaveBeenCalledWith({
          ...session,
          denominatorPreference:
            "logged_days",
        });

        await act(async () => {
          renderer.unmount();
        });
      },
    );

    test(
      "authority-global no-history metadata produces a dedicated empty state and disables Previous",
      async () => {
        mockUseHistoryRange
          .mockReturnValue(
            successfulQuery(
              makeEvidence({
                firstLoggedDate:
                  null,
                loggedDates: [],
              }),
            ),
          );

        let renderer!:
          TestRenderer.ReactTestRenderer;

        await act(async () => {
          renderer =
            TestRenderer.create(
              React.createElement(
                HistoryScreen,
                {
                  session:
                    freshHistorySession(
                      "2026-08-19",
                    ),
                  onSessionChange:
                    jest.fn(),
                  onFirstLoggedDateChange:
                    jest.fn(),
                  onBack:
                    jest.fn(),
                },
              ),
            );
        });

        expect(
          screenText(renderer),
        ).toContain(
          "No History yet",
        );

        expect(
          renderer.root
            .findByProps({
              accessibilityLabel:
                "Previous History period",
            })
            .props
            .accessibilityState
            .disabled,
        ).toBe(true);

        await act(async () => {
          renderer.unmount();
        });
      },
    );

    test(
      "initial failure and same-range refresh failure remain distinct",
      async () => {
        mockUseHistoryRange
          .mockReturnValueOnce({
            data: undefined,
            error:
              new Error("load"),
            isError: true,
            isFetching: false,
            isLoading: false,
            isRefetchError: false,
            refetch: jest.fn(),
          });

        let initial!:
          TestRenderer.ReactTestRenderer;

        await act(async () => {
          initial =
            TestRenderer.create(
              React.createElement(
                HistoryScreen,
                {
                  session:
                    freshHistorySession(
                      "2026-08-19",
                    ),
                  onSessionChange:
                    jest.fn(),
                  onFirstLoggedDateChange:
                    jest.fn(),
                  onBack:
                    jest.fn(),
                },
              ),
            );
        });

        expect(
          screenText(initial),
        ).toContain(
          "History could not load for this range.",
        );

        await act(async () => {
          initial.unmount();
        });

        const evidence =
          makeEvidence();

        mockUseHistoryRange
          .mockReturnValueOnce({
            ...successfulQuery(
              evidence,
            ),
            error:
              new Error("refresh"),
            isError: true,
            isRefetchError: true,
          });

        let refresh!:
          TestRenderer.ReactTestRenderer;

        await act(async () => {
          refresh =
            TestRenderer.create(
              React.createElement(
                HistoryScreen,
                {
                  session:
                    freshHistorySession(
                      "2026-08-19",
                    ),
                  onSessionChange:
                    jest.fn(),
                  onFirstLoggedDateChange:
                    jest.fn(),
                  onBack:
                    jest.fn(),
                },
              ),
            );
        });

        const refreshText =
          screenText(refresh);

        expect(
          refreshText,
        ).toContain(
          "History could not refresh.",
        );

        expect(
          refreshText,
        ).toContain(
          "3 logged days",
        );

        await act(async () => {
          refresh.unmount();
        });
      },
    );
  },
);
