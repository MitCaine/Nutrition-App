import {
  Pressable,
  ScrollView,
  StyleSheet,
  View,
} from "react-native";
import Svg, {
  Circle,
  Line,
  Rect,
} from "react-native-svg";

import type {
  HistoryProjectedDailyValue,
} from "../types";

const CHART_VIEWPORT_WIDTH = 300;
const CHART_HEIGHT = 96;
const PLOT_TOP = 8;
const BASELINE = 86;
const PLOT_HEIGHT =
  BASELINE - PLOT_TOP;
const SCROLLING_SLOT_WIDTH = 44;

export type HistoryDailyBarGeometryPoint =
  Readonly<{
    date: string;
    state:
      HistoryProjectedDailyValue["state"];
    numericValue: number | null;
    explicitZero: boolean;
    slotX: number;
    slotWidth: number;
    barX: number;
    barWidth: number;
    barHeight: number;
    barY: number;
  }>;

export type HistoryDailyBarGeometry =
  Readonly<{
    width: number;
    viewportWidth: number;
    height: number;
    baseline: number;
    maxNumericValue: number;
    scaleMaximum: number;
    referenceValue: number | null;
    referenceY: number | null;
    isScrollable: boolean;
    points:
      readonly HistoryDailyBarGeometryPoint[];
  }>;

function normalizedReferenceValue(
  referenceValue:
    number | null | undefined,
): number | null {
  if (
    referenceValue === null
    || referenceValue === undefined
    || !Number.isFinite(
      referenceValue,
    )
    || referenceValue < 0
  ) {
    return null;
  }

  return referenceValue;
}

export function historyDailyBarGeometry(
  days:
    readonly HistoryProjectedDailyValue[],
  referenceValue?:
    number | null,
): HistoryDailyBarGeometry {
  const width =
    days.length > 7
      ? days.length
        * SCROLLING_SLOT_WIDTH
      : CHART_VIEWPORT_WIDTH;

  const numericValues =
    days.flatMap((day) => {
      if (
        day.state !== "numeric"
        || day.numericAmount === null
      ) {
        return [];
      }

      const numeric =
        Number(day.numericAmount);

      if (
        !Number.isFinite(numeric)
        || numeric < 0
      ) {
        return [];
      }

      return [numeric];
    });

  const maxNumericValue =
    numericValues.length > 0
      ? Math.max(
          ...numericValues,
          0,
        )
      : 0;

  const normalizedReference =
    normalizedReferenceValue(
      referenceValue,
    );

  const scaleMaximum =
    Math.max(
      maxNumericValue,
      normalizedReference ?? 0,
    );

  const slotWidth =
    days.length > 0
      ? width / days.length
      : width;

  const barWidth =
    Math.max(
      2,
      slotWidth * 0.62,
    );

  const points =
    days.map(
      (
        day,
        index,
      ) => {
        const parsed =
          day.state === "numeric"
          && day.numericAmount
            !== null
            ? Number(
                day.numericAmount,
              )
            : null;

        const numericValue =
          parsed !== null
          && Number.isFinite(
            parsed,
          )
          && parsed >= 0
            ? parsed
            : null;

        const barHeight =
          numericValue !== null
          && numericValue > 0
          && scaleMaximum > 0
            ? (
                numericValue
                / scaleMaximum
              ) * PLOT_HEIGHT
            : 0;

        const slotX =
          index * slotWidth;

        return {
          date:
            day.date,
          state:
            day.state,
          numericValue,
          explicitZero:
            day.isExplicitZeroTotal,
          slotX,
          slotWidth,
          barX:
            slotX
            + (
              slotWidth
              - barWidth
            ) / 2,
          barWidth,
          barHeight,
          barY:
            BASELINE
            - barHeight,
        };
      },
    );

  const referenceY =
    normalizedReference === null
      ? null
      : scaleMaximum > 0
        ? (
            BASELINE
            - (
              normalizedReference
              / scaleMaximum
            ) * PLOT_HEIGHT
          )
        : BASELINE;

  return {
    width,
    viewportWidth:
      CHART_VIEWPORT_WIDTH,
    height:
      CHART_HEIGHT,
    baseline:
      BASELINE,
    maxNumericValue,
    scaleMaximum,
    referenceValue:
      normalizedReference,
    referenceY,
    isScrollable:
      width
      > CHART_VIEWPORT_WIDTH,
    points,
  };
}

type Props = {
  days:
    readonly HistoryProjectedDailyValue[];
  seriesLabel: string;
  selectedDate: string | null;
  onSelectDate: (
    date: string,
  ) => void;
  barColor: string;
  selectedBarColor: string;
  referenceValue?:
    number | null;
  referenceLineColor?: string;
};

export function HistoryDailyBarChart({
  days,
  seriesLabel,
  selectedDate,
  onSelectDate,
  barColor,
  selectedBarColor,
  referenceValue,
  referenceLineColor,
}: Props) {
  const geometry =
    historyDailyBarGeometry(
      days,
      referenceValue,
    );

  const plot = (
    <View
      style={[
        styles.plot,
        {
          width:
            geometry.width,
        },
      ]}
    >
      <Svg
        height={
          CHART_HEIGHT
        }
        viewBox={
          `0 0 ${geometry.width} ${CHART_HEIGHT}`
        }
        width={
          geometry.width
        }
      >
        {geometry.referenceY
          !== null
          && referenceLineColor
            ? (
            <Line
              stroke={
                referenceLineColor
              }
              strokeWidth={1.5}
              x1={0}
              x2={
                geometry.width
              }
              y1={
                geometry.referenceY
              }
              y2={
                geometry.referenceY
              }
            />
          ) : null}

        {geometry.points.map(
          (point) => {
            if (
              point.state
                !== "numeric"
              || point.numericValue
                === null
            ) {
              return null;
            }

            const height =
              point.barHeight > 0
                ? point.barHeight
                : 2;

            return (
              <Rect
                key={
                  `bar-${point.date}`
                }
                fill={
                  selectedDate
                    === point.date
                    ? selectedBarColor
                    : barColor
                }
                height={
                  height
                }
                width={
                  point.barWidth
                }
                x={
                  point.barX
                }
                y={
                  geometry.baseline
                  - height
                }
              />
            );
          },
        )}

        {geometry.points.map(
          (point) => {
            if (
              selectedDate
                !== point.date
              || point.state
                === "numeric"
            ) {
              return null;
            }

            return (
              <Circle
                key={
                  `selected-marker-${point.date}`
                }
                cx={
                  point.slotX
                  + point.slotWidth / 2
                }
                cy={
                  geometry.baseline
                  - 4
                }
                fill={
                  selectedBarColor
                }
                r={3}
              />
            );
          },
        )}
      </Svg>

      <View
        pointerEvents="box-none"
        style={
          styles.hitLayer
        }
      >
        {geometry.points.map(
          (point) => (
            <Pressable
              key={
                `hit-${point.date}`
              }
              accessibilityLabel={
                `Select ${seriesLabel} History date ${point.date}`
              }
              accessibilityRole="button"
              accessibilityState={{
                selected:
                  selectedDate
                  === point.date,
              }}
              onPress={() =>
                onSelectDate(
                  point.date,
                )
              }
              style={{
                width:
                  point.slotWidth,
              }}
            />
          ),
        )}
      </View>
    </View>
  );

  if (
    !geometry.isScrollable
  ) {
    return (
      <View
        style={
          styles.viewport
        }
      >
        {plot}
      </View>
    );
  }

  return (
    <ScrollView
      accessibilityLabel={
        `${seriesLabel} 30-day History chart`
      }
      horizontal
      showsHorizontalScrollIndicator
      style={
        styles.scroll
      }
      contentContainerStyle={
        styles.scrollContent
      }
    >
      {plot}
    </ScrollView>
  );
}

const styles =
  StyleSheet.create({
    viewport: {
      height:
        CHART_HEIGHT,
      overflow:
        "hidden",
      width:
        "100%",
    },
    scroll: {
      height:
        CHART_HEIGHT,
      width:
        "100%",
    },
    scrollContent: {
      height:
        CHART_HEIGHT,
    },
    plot: {
      height:
        CHART_HEIGHT,
      position:
        "relative",
    },
    hitLayer: {
      ...StyleSheet.absoluteFill,
      flexDirection:
        "row",
    },
  });
