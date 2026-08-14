import { Ionicons } from "@expo/vector-icons";
import { useMemo } from "react";
import { Pressable, StyleSheet, Text, useWindowDimensions, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import Svg, { ClipPath, Defs, G, Line, Path, Rect } from "react-native-svg";

import { inactiveNavigationLabelColor, useAppTheme } from "../theme/AppTheme";
import { MAIN_TAB_ACCESSIBILITY_LABELS, type MainTab } from "./mainTabs";

const OUTER_GAP = 16;
const FRAME_TOP_GAP = 2;
const TOP_RADIUS = 8;
const TAB_HEIGHT = 44;
const NAVIGATION_TOP_REDUCTION = 14;
const SELECTED_BORDER_WIDTH = 1;
const SELECTED_CLIP_ID = "bottomNavigationSelectedThird";
const DEVICE_CORNER_WIDTH_RATIO = 0.15;
const QUARTER_CIRCLE_CONTROL_FACTOR = 4 / 3 * Math.tan(Math.PI / 8);

const TAB_ITEMS: Array<{
  id: MainTab;
  label: string;
  accessibilityLabel: string;
  icon: keyof typeof Ionicons.glyphMap;
  activeIcon: keyof typeof Ionicons.glyphMap;
}> = [
  {
    id: "foods",
    label: "Foods",
    accessibilityLabel: MAIN_TAB_ACCESSIBILITY_LABELS.foods,
    icon: "restaurant-outline",
    activeIcon: "restaurant",
  },
  {
    id: "daily-log",
    label: "Daily Log",
    accessibilityLabel: MAIN_TAB_ACCESSIBILITY_LABELS["daily-log"],
    icon: "calendar-outline",
    activeIcon: "calendar",
  },
  {
    id: "recipes",
    label: "Recipes",
    accessibilityLabel: MAIN_TAB_ACCESSIBILITY_LABELS.recipes,
    icon: "book-outline",
    activeIcon: "book",
  },
];

function formatCoordinate(value: number): string {
  return String(Number(value.toFixed(3)));
}

function buildDockGeometry(screenWidth: number, bottomSafeAreaInset: number) {
  const dockWidth = Math.max(screenWidth - OUTER_GAP * 2, 1);
  const safeAreaFill = Math.max(bottomSafeAreaInset - OUTER_GAP, 0);
  const previousDockHeight = TAB_HEIGHT + safeAreaFill;
  const previousTopRadius = Math.min(TOP_RADIUS, dockWidth / 2, previousDockHeight);
  const modeledScreenWidth = Math.max(screenWidth, OUTER_GAP * 2 + 1);
  const outerCornerExtent = Math.min(
    Math.max(modeledScreenWidth * DEVICE_CORNER_WIDTH_RATIO, OUTER_GAP),
    dockWidth / 2 + OUTER_GAP,
  );
  const lowerCurveExtent = Math.min(
    outerCornerExtent - OUTER_GAP,
    dockWidth / 2,
    previousDockHeight - previousTopRadius,
  );
  const maximumTopReduction = Math.min(
      Math.max(previousDockHeight - TAB_HEIGHT, 0),
      Math.max(previousDockHeight - previousTopRadius - lowerCurveExtent, 0),
  );
  const topReduction = Math.min(
      NAVIGATION_TOP_REDUCTION,
      maximumTopReduction,
  );
  const MIN_VISIBLE_DOCK_HEIGHT = 42;
  const dockHeight = Math.max(previousDockHeight - NAVIGATION_TOP_REDUCTION, MIN_VISIBLE_DOCK_HEIGHT,);
  const lowerCurveStartY = dockHeight - lowerCurveExtent;
  const topRadius = Math.min(previousTopRadius, Math.max(lowerCurveStartY, 0));
  const lowerCurveControlOffset = lowerCurveExtent * QUARTER_CIRCLE_CONTROL_FACTOR;
  const dockPath = [
    `M ${formatCoordinate(topRadius)} 0`,
    `H ${formatCoordinate(dockWidth - topRadius)}`,
    `Q ${formatCoordinate(dockWidth)} 0 ${formatCoordinate(dockWidth)} ${formatCoordinate(topRadius)}`,
    `V ${formatCoordinate(lowerCurveStartY)}`,
    lowerCurveExtent > 0
      ? [
          "C",
          formatCoordinate(dockWidth),
          formatCoordinate(lowerCurveStartY + lowerCurveControlOffset),
          formatCoordinate(dockWidth - lowerCurveExtent + lowerCurveControlOffset),
          formatCoordinate(dockHeight),
          formatCoordinate(dockWidth - lowerCurveExtent),
          formatCoordinate(dockHeight),
        ].join(" ")
      : "",
    `H ${formatCoordinate(lowerCurveExtent)}`,
    lowerCurveExtent > 0
      ? [
          "C",
          formatCoordinate(lowerCurveExtent - lowerCurveControlOffset),
          formatCoordinate(dockHeight),
          "0",
          formatCoordinate(lowerCurveStartY + lowerCurveControlOffset),
          "0",
          formatCoordinate(lowerCurveStartY),
        ].join(" ")
      : "",
    `V ${formatCoordinate(topRadius)}`,
    `Q 0 0 ${formatCoordinate(topRadius)} 0`,
    "Z",
  ].filter(Boolean).join(" ");

  return { dockHeight, dockPath, dockWidth };
}

export function BottomNavigation({
  activeTab,
  onSelect,
}: {
  activeTab: MainTab;
  onSelect: (tab: MainTab) => void;
}) {
  const theme = useAppTheme();
  const insets = useSafeAreaInsets();
  const { width: screenWidth } = useWindowDimensions();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const { dockHeight, dockPath, dockWidth } = useMemo(
    () => buildDockGeometry(screenWidth, insets.bottom),
    [insets.bottom, screenWidth],
  );
  const selectedTabIndex = TAB_ITEMS.findIndex((item) => item.id === activeTab);
  const tabWidth = dockWidth / TAB_ITEMS.length;
  const selectedStartX = tabWidth * selectedTabIndex;
  const selectedDividerXs = selectedTabIndex === 1
    ? [tabWidth, tabWidth * 2]
    : [selectedTabIndex === 0 ? tabWidth : tabWidth * 2];
  const selectedPathInset = SELECTED_BORDER_WIDTH / 2;
  const selectedPathTransform = [
    `translate(${selectedPathInset} ${selectedPathInset})`,
    `scale(${(dockWidth - SELECTED_BORDER_WIDTH) / dockWidth} ${(dockHeight - SELECTED_BORDER_WIDTH) / dockHeight})`,
  ].join(" ");
  const tabRowHeight = Math.max(TAB_HEIGHT, dockHeight);
  const tabRowTop = Math.max(
    0,
    FRAME_TOP_GAP + (dockHeight - tabRowHeight) / 2,
  );

  return (
    <View style={styles.frame}>
      <View
        style={[styles.dock, { height: dockHeight }]}
        testID="bottom-navigation-dock"
      >
        <Svg
          pointerEvents="none"
          style={StyleSheet.absoluteFill}
          testID="bottom-navigation-decoration"
          width={dockWidth}
          height={dockHeight}
          viewBox={`0 0 ${dockWidth} ${dockHeight}`}
        >
          <Path
            d={dockPath}
            fill={theme.colors.navigationSurface}
            testID="bottom-navigation-dock-surface"
          />
          <Defs>
            <ClipPath id={SELECTED_CLIP_ID}>
              <Rect
                height={dockHeight}
                testID="bottom-navigation-selected-clip"
                width={tabWidth}
                x={selectedStartX}
                y={0}
              />
            </ClipPath>
          </Defs>
          <G clipPath={`url(#${SELECTED_CLIP_ID})`}>
            <Path
              d={dockPath}
              fill={theme.colors.selectedNavigationBackground}
              stroke={theme.colors.primaryActionBorder}
              strokeWidth={SELECTED_BORDER_WIDTH}
              testID="bottom-navigation-selected-surface"
              transform={selectedPathTransform}
            />
          </G>
          {selectedDividerXs.map((dividerX, index) => (
            <Line
              key={dividerX}
              stroke={theme.colors.primaryActionBorder}
              strokeWidth={SELECTED_BORDER_WIDTH}
              testID={`bottom-navigation-selected-divider-${index}`}
              x1={dividerX}
              x2={dividerX}
              y1={0}
              y2={dockHeight}
            />
          ))}
        </Svg>
      </View>

      <View
        style={[styles.tabRow, { height: tabRowHeight, top: tabRowTop }]}
        accessibilityRole="tablist"
      >
        {TAB_ITEMS.map((item) => {
          const selected = item.id === activeTab;

          return (
            <Pressable
              key={item.id}
              accessibilityRole="tab"
              accessibilityLabel={item.accessibilityLabel}
              accessibilityState={{ selected }}
              onPress={() => onSelect(item.id)}
              style={styles.tab}
            >
              <Ionicons
                name={selected ? item.activeIcon : item.icon}
                size={18}
                color={
                  selected
                    ? theme.colors.selectedNavigationForeground
                    : theme.colors.inactiveForeground
                }
              />
              <Text
                maxFontSizeMultiplier={1.5}
                style={[
                  styles.label,
                  selected ? styles.activeLabel : styles.inactiveLabel,
                ]}
              >
                {item.label}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    activeLabel: {
      color: theme.colors.selectedNavigationForeground,
      fontWeight: "700",
    },

    dock: {
      position: "relative",
      width: "100%",
    },

    frame: {
      backgroundColor: theme.colors.background,
      paddingTop: FRAME_TOP_GAP,
      paddingHorizontal: OUTER_GAP,
      paddingBottom: OUTER_GAP,
      position: "relative",
    },

    inactiveLabel: {
      color: inactiveNavigationLabelColor(theme),
      fontWeight: "500",
    },

    label: {
      fontSize: 12,
    },

    tabRow: {
      flexDirection: "row",
      left: OUTER_GAP,
      position: "absolute",
      right: OUTER_GAP,
    },

    tab: {
      alignItems: "center",
      flex: 1,
      flexDirection: "row",
      gap: 6,
      justifyContent: "center",
      minHeight: TAB_HEIGHT,
      paddingHorizontal: 8,
    },
  });
}
