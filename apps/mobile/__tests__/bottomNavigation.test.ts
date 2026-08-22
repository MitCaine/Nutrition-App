import React from "react";
import { Dimensions, Pressable, StyleSheet, Text, View } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import { BottomNavigation } from "../src/app/navigation/BottomNavigation";
import { DARK_THEME, LIGHT_THEME } from "../src/app/theme/AppTheme";

let mockBottomInset = 34;
let mockThemeMode: "light" | "dark" = "light";

const SCREEN_HEIGHT = 874;
const PREVIOUS_DOCK_HEIGHT = 54;
const COMPACT_DOCK_HEIGHT = 48;
const TOP_ONLY_REDUCTION = PREVIOUS_DOCK_HEIGHT - COMPACT_DOCK_HEIGHT;
const FIXED_DOCK_BOTTOM_Y = SCREEN_HEIGHT - 16;

type Point = { x: number; y: number };

function pointOnCubic(
  start: Point,
  controlOne: Point,
  controlTwo: Point,
  end: Point,
  progress: number,
): Point {
  const inverse = 1 - progress;
  return {
    x: inverse ** 3 * start.x
      + 3 * inverse ** 2 * progress * controlOne.x
      + 3 * inverse * progress ** 2 * controlTwo.x
      + progress ** 3 * end.x,
    y: inverse ** 3 * start.y
      + 3 * inverse ** 2 * progress * controlOne.y
      + 3 * inverse * progress ** 2 * controlTwo.y
      + progress ** 3 * end.y,
  };
}

jest.mock("@expo/vector-icons", () => ({ Ionicons: "Ionicons" }));
jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ bottom: mockBottomInset, left: 0, right: 0, top: 0 }),
}));
jest.mock("react-native-svg", () => ({
  __esModule: true,
  ClipPath: "ClipPath",
  default: "Svg",
  Defs: "Defs",
  G: "G",
  Line: "Line",
  Path: "Path",
  Rect: "Rect",
}));
jest.mock("../src/app/theme/AppTheme", () => {
  const actual = jest.requireActual("../src/app/theme/AppTheme");
  return {
    ...actual,
    useAppTheme: () => {
      const selectedTheme = mockThemeMode === "dark"
        ? actual.DARK_THEME
        : actual.LIGHT_THEME;

      return {
        ...selectedTheme,
        effectiveScheme: mockThemeMode,
        preference: "system",
        setPreference: jest.fn(),
      };
    },
  };
});

async function renderNavigation(
  activeTab: "foods" | "daily-log" | "recipes" = "daily-log",
  themeMode: "light" | "dark" = "light",
) {
  const onSelect = jest.fn();
  let renderer!: TestRenderer.ReactTestRenderer;

  mockThemeMode = themeMode;

  Dimensions.set({
    screen: { fontScale: 1, height: 874, scale: 3, width: 402 },
    window: { fontScale: 1, height: 874, scale: 3, width: 402 },
  });
  await act(async () => {
    renderer = TestRenderer.create(
      React.createElement(BottomNavigation, { activeTab, onSelect }),
    );
  });

  return { onSelect, renderer };
}

afterEach(() => {
  mockBottomInset = 34;
  mockThemeMode = "light";
});

test("preserves tab semantics, selection, routing, and 44 point targets", async () => {
  const { onSelect, renderer } = await renderNavigation();
  const tabs = renderer.root.findAllByType(Pressable).filter(
    (node) => node.props.accessibilityRole === "tab",
  );

  expect(tabs.map((tab) => tab.props.accessibilityLabel)).toEqual([
    "Foods tab",
    "Daily Log tab",
    "Recipes tab",
  ]);
  expect(tabs).toHaveLength(3);
  expect(tabs.map((tab) => tab.props.accessibilityState)).toEqual([
    { selected: false },
    { selected: true },
    { selected: false },
  ]);
  tabs.forEach((tab) => {
    const unpressedStyle = typeof tab.props.style === "function"
      ? tab.props.style({ pressed: false })
      : tab.props.style;
    const pressedStyle = typeof tab.props.style === "function"
      ? tab.props.style({ pressed: true })
      : tab.props.style;
    expect(StyleSheet.flatten(unpressedStyle)).toMatchObject({
      flex: 1,
      minHeight: 44,
    });
    expect(StyleSheet.flatten(pressedStyle)).toEqual(
      StyleSheet.flatten(unpressedStyle),
    );
    expect(StyleSheet.flatten(pressedStyle)).not.toHaveProperty("backgroundColor");
    expect(StyleSheet.flatten(pressedStyle)).not.toHaveProperty("borderRadius");
    tab.props.onPress();
  });
  expect(onSelect.mock.calls).toEqual([["foods"], ["daily-log"], ["recipes"]]);

  await act(async () => renderer.unmount());
});

test("bottom inset changes the contour while the sixteen point app perimeter stays fixed", async () => {
  const { renderer } = await renderNavigation("foods");
  const initialSvg = renderer.root.findByProps({
    testID: "bottom-navigation-decoration",
  });
  const initialPath = renderer.root.findByProps({
    testID: "bottom-navigation-dock-surface",
  }).props.d;
  const frame = renderer.root.findAllByType(View).find(
    (node) => StyleSheet.flatten(node.props.style)?.paddingBottom === 16,
  )!;
  const dock = renderer.root.findByProps({ testID: "bottom-navigation-dock" });
  const frameStyle = StyleSheet.flatten(frame.props.style);
  const dockStyle = StyleSheet.flatten(dock.props.style);
  const previousTopY = FIXED_DOCK_BOTTOM_Y - PREVIOUS_DOCK_HEIGHT;
  const compactTopY = FIXED_DOCK_BOTTOM_Y - dockStyle.height;

  expect(initialSvg.props.width).toBe(370);
  expect(initialSvg.props.height).toBe(COMPACT_DOCK_HEIGHT);
  expect(initialPath).toMatch(/^M 3\.7 0 H 366\.3 Q 370 0 370 3\.7 /);
  expect(frameStyle).toMatchObject({
    paddingBottom: 16,
    paddingHorizontal: 16,
  });
  expect(dockStyle.height).toBe(COMPACT_DOCK_HEIGHT);
  expect(compactTopY - previousTopY).toBe(TOP_ONLY_REDUCTION);
  expect(compactTopY + dockStyle.height).toBe(FIXED_DOCK_BOTTOM_Y);
  expect(SCREEN_HEIGHT - FIXED_DOCK_BOTTOM_Y).toBe(16);
  expect(
    frameStyle.paddingTop + dockStyle.height + frameStyle.paddingBottom,
  ).toBe(66);
  expect(72 - (frameStyle.paddingTop + dockStyle.height + frameStyle.paddingBottom)).toBe(
    TOP_ONLY_REDUCTION,
  );

  mockBottomInset = 20;
  await act(async () => {
    renderer.update(React.createElement(BottomNavigation, {
      activeTab: "foods",
      onSelect: jest.fn(),
    }));
  });

  const updatedSvg = renderer.root.findByProps({
    testID: "bottom-navigation-decoration",
  });
  const updatedPath = renderer.root.findByProps({
    testID: "bottom-navigation-dock-surface",
  }).props.d;
  const updatedFrame = renderer.root.findAllByType(View).find(
    (node) => StyleSheet.flatten(node.props.style)?.paddingBottom === 16,
  )!;

  expect(updatedSvg.props.width).toBe(370);
  expect(updatedSvg.props.height).toBe(42);
  expect(updatedPath).not.toBe(initialPath);
  expect(StyleSheet.flatten(updatedFrame.props.style)).toMatchObject({
    paddingBottom: 16,
    paddingHorizontal: 16,
  });
  expect(
    StyleSheet.flatten(updatedFrame.props.style).paddingTop
      + updatedSvg.props.height
      + StyleSheet.flatten(updatedFrame.props.style).paddingBottom,
  ).toBe(60);
  const updatedTabRow = renderer.root.findByProps({ accessibilityRole: "tablist" });
  expect(StyleSheet.flatten(updatedTabRow.props.style)).toMatchObject({
    height: 44,
    position: "absolute",
  });
  renderer.root.findAllByType(Pressable).filter(
    (node) => node.props.accessibilityRole === "tab",
  ).forEach((tab) => {
    const style = StyleSheet.flatten(tab.props.style);
    expect(style.minHeight).toBe(44);
  });

  await act(async () => renderer.unmount());
});

test("lower contour is deterministic, mirrored, and concentric at a sixteen point offset", async () => {
  const { renderer } = await renderNavigation("recipes");
  const path = renderer.root.findByProps({
    testID: "bottom-navigation-dock-surface",
  }).props.d as string;
  const lowerContour = path.match(
    /V ([\d.]+) C ([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) H ([\d.]+) C ([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) V/,
  );

  expect(lowerContour).not.toBeNull();
  const coordinates = lowerContour!.slice(1).map(Number);
  expect(coordinates[1] + coordinates[12]).toBeCloseTo(370, 3);
  expect(coordinates[3] + coordinates[8]).toBeCloseTo(370, 3);
  expect(coordinates[5] + coordinates[7]).toBeCloseTo(370, 3);
  expect(coordinates[2]).toBe(coordinates[11]);
  expect(coordinates[4]).toBe(coordinates[9]);
  expect(coordinates[6]).toBe(COMPACT_DOCK_HEIGHT);

  const rightCurve = {
    start: { x: 370, y: coordinates[0] },
    controlOne: { x: coordinates[1], y: coordinates[2] },
    controlTwo: { x: coordinates[3], y: coordinates[4] },
    end: { x: coordinates[5], y: coordinates[6] },
  };
  const leftCurve = {
    start: { x: coordinates[7], y: coordinates[6] },
    controlOne: { x: coordinates[8], y: coordinates[9] },
    controlTwo: { x: coordinates[10], y: coordinates[11] },
    end: { x: coordinates[12], y: coordinates[13] },
  };
  const innerRadius = rightCurve.start.x - rightCurve.end.x;
  const modeledOuterRadius = 402 * 0.15;
  const compactTopY = FIXED_DOCK_BOTTOM_Y - COMPACT_DOCK_HEIGHT;
  const previousTopY = FIXED_DOCK_BOTTOM_Y - PREVIOUS_DOCK_HEIGHT;
  const previousCurveStartY = PREVIOUS_DOCK_HEIGHT - innerRadius;
  const curveControlOffset = innerRadius * 4 / 3 * Math.tan(Math.PI / 8);
  const rightCenter = { x: rightCurve.end.x, y: rightCurve.start.y };
  const leftCenter = { x: leftCurve.start.x, y: leftCurve.end.y };

  expect(innerRadius).toBeCloseTo(modeledOuterRadius - 16, 2);
  expect(compactTopY + rightCurve.start.y).toBeCloseTo(
    previousTopY + previousCurveStartY,
    3,
  );
  expect(compactTopY + rightCurve.controlOne.y).toBeCloseTo(
    previousTopY + previousCurveStartY + curveControlOffset,
    3,
  );
  expect(compactTopY + rightCurve.controlTwo.y).toBe(FIXED_DOCK_BOTTOM_Y);
  expect(compactTopY + rightCurve.end.y).toBe(FIXED_DOCK_BOTTOM_Y);
  expect(compactTopY + leftCurve.start.y).toBe(FIXED_DOCK_BOTTOM_Y);
  expect(compactTopY + leftCurve.controlOne.y).toBe(FIXED_DOCK_BOTTOM_Y);
  expect(compactTopY + leftCurve.controlTwo.y).toBeCloseTo(
    previousTopY + previousCurveStartY + curveControlOffset,
    3,
  );
  expect(compactTopY + leftCurve.end.y).toBeCloseTo(
    previousTopY + previousCurveStartY,
    3,
  );
  [0, 0.25, 0.5, 0.75, 1].forEach((progress) => {
    const rightPoint = pointOnCubic(
      rightCurve.start,
      rightCurve.controlOne,
      rightCurve.controlTwo,
      rightCurve.end,
      progress,
    );
    const leftPoint = pointOnCubic(
      leftCurve.start,
      leftCurve.controlOne,
      leftCurve.controlTwo,
      leftCurve.end,
      progress,
    );
    const rightGap = modeledOuterRadius - Math.hypot(
      rightPoint.x - rightCenter.x,
      rightPoint.y - rightCenter.y,
    );
    const leftGap = modeledOuterRadius - Math.hypot(
      leftPoint.x - leftCenter.x,
      leftPoint.y - leftCenter.y,
    );

    expect(rightGap).toBeGreaterThanOrEqual(15.98);
    expect(rightGap).toBeLessThanOrEqual(16.01);
    expect(leftGap).toBeGreaterThanOrEqual(15.98);
    expect(leftGap).toBeLessThanOrEqual(16.01);
  });

  await act(async () => {
    renderer.update(React.createElement(BottomNavigation, {
      activeTab: "recipes",
      onSelect: jest.fn(),
    }));
  });
  expect(renderer.root.findByProps({
    testID: "bottom-navigation-dock-surface",
  }).props.d).toBe(path);

  await act(async () => renderer.unmount());
});

test.each([
  ["light", LIGHT_THEME, "foods", 0, 1, [370 / 3], "restaurant"],
  [
    "light",
    LIGHT_THEME,
    "daily-log",
    1,
    1,
    [370 / 3, 370 * 2 / 3],
    "calendar",
  ],
  ["light", LIGHT_THEME, "recipes", 2, 1, [370 * 2 / 3], "book"],
  ["dark", DARK_THEME, "foods", 0, 1, [370 / 3], "restaurant"],
  [
    "dark",
    DARK_THEME,
    "daily-log",
    1,
    1,
    [370 / 3, 370 * 2 / 3],
    "calendar",
  ],
  ["dark", DARK_THEME, "recipes", 2, 1, [370 * 2 / 3], "book"],
] as const)(
  "%s %s selection owns one exact dock third with universal Daily Log identity",
  async (
    themeMode,
    expectedTheme,
    activeTab,
    thirdIndex,
    expectedStrokeWidth,
    expectedDividers,
    expectedActiveIcon,
  ) => {
    const { renderer } = await renderNavigation(activeTab, themeMode);
    const decoration = renderer.root.findByProps({
      testID: "bottom-navigation-decoration",
    });
    const dockSurface = renderer.root.findByProps({
      testID: "bottom-navigation-dock-surface",
    });
    const selectedClip = renderer.root.findByProps({
      testID: "bottom-navigation-selected-clip",
    });
    const selectedSurface = renderer.root.findByProps({
      testID: "bottom-navigation-selected-surface",
    });
    const selectedDividers = renderer.root.findAll(
      (node) => typeof node.props.testID === "string"
        && node.props.testID.startsWith("bottom-navigation-selected-divider-"),
    );
    const tabs = renderer.root.findAllByType(Pressable).filter(
      (node) => node.props.accessibilityRole === "tab",
    );
    const selectedTab = tabs[thirdIndex];
    const selectedIcon = selectedTab.findAll(
      (node) => typeof node.props.name === "string" && node.props.size === 18,
    )[0];
    const selectedLabel = selectedTab.findByType(Text);
    const tabWidth = 370 / 3;
    const expectedColors = {
      background: expectedTheme.colors.dailyLogBackground,
      foreground: expectedTheme.colors.dailyLogForeground,
    };

    expect(decoration.props.pointerEvents).toBe("none");
    expect(selectedClip.props).toMatchObject({
      height: COMPACT_DOCK_HEIGHT,
      width: tabWidth,
      x: tabWidth * thirdIndex,
      y: 0,
    });
    expect(selectedClip.props.x + selectedClip.props.width).toBe(
      tabWidth * (thirdIndex + 1),
    );
    expect(selectedSurface.props).toMatchObject({
      d: dockSurface.props.d,
      fill: expectedColors.background,
      stroke: expectedColors.foreground,
      strokeWidth: expectedStrokeWidth,
    });
    expect(selectedDividers.map((divider) => divider.props.x1)).toEqual(
      expectedDividers,
    );
    selectedDividers.forEach((divider) => {
      expect(divider.props).toMatchObject({
        stroke: expectedColors.foreground,
        strokeWidth: expectedStrokeWidth,
        x2: divider.props.x1,
        y1: 0,
        y2: COMPACT_DOCK_HEIGHT,
      });
    });

    expect(selectedTab.props.accessibilityState).toEqual({
      selected: true,
    });
    expect(selectedIcon).toBeDefined();
    expect(selectedIcon.props).toMatchObject({
      color: expectedColors.foreground,
      name: expectedActiveIcon,
      size: 18,
    });
    expect(StyleSheet.flatten(selectedLabel.props.style)).toMatchObject({
      color: expectedColors.foreground,
      fontWeight: "700",
    });

    tabs.forEach((tab, index) => {
      if (index === thirdIndex) {
        return;
      }

      const inactiveIcon = tab.findAll(
        (node) => typeof node.props.name === "string" && node.props.size === 18,
      )[0];
      const inactiveLabel = tab.findByType(Text);

      expect(tab.props.accessibilityState).toEqual({
        selected: false,
      });
      expect(inactiveIcon.props.color).toBe(
        expectedTheme.colors.inactiveForeground,
      );
      expect(StyleSheet.flatten(inactiveLabel.props.style)).toMatchObject({
        fontWeight: "500",
      });
    });

    await act(async () => renderer.unmount());
  },
);

test("Foods and Recipes selected geometry mirror the same unchanged dock contour", async () => {
  const { renderer: foodsRenderer } = await renderNavigation("foods");
  const foodsClip = foodsRenderer.root.findByProps({
    testID: "bottom-navigation-selected-clip",
  });
  const foodsPath = foodsRenderer.root.findByProps({
    testID: "bottom-navigation-selected-surface",
  }).props.d;

  const { renderer: recipesRenderer } = await renderNavigation("recipes");
  const recipesClip = recipesRenderer.root.findByProps({
    testID: "bottom-navigation-selected-clip",
  });
  const recipesPath = recipesRenderer.root.findByProps({
    testID: "bottom-navigation-selected-surface",
  }).props.d;

  expect(foodsClip.props.width).toBe(recipesClip.props.width);
  expect(foodsClip.props.x).toBe(0);
  expect(recipesClip.props.x + recipesClip.props.width).toBe(370);
  expect(foodsPath).toBe(recipesPath);

  await act(async () => {
    foodsRenderer.unmount();
    recipesRenderer.unmount();
  });
});

test("uses explicit safe-area geometry without core React Native SafeAreaView", () => {
  const source = jest.requireActual("fs").readFileSync(
    "src/app/navigation/BottomNavigation.tsx",
    "utf8",
  );

  expect(source).toContain("const OUTER_GAP = 16");
  expect(source).toContain("const TOP_RADIUS = 8");
  expect(source).toContain("outerCornerExtent - OUTER_GAP");
  expect(source).toContain("useSafeAreaInsets");
  expect(source).not.toContain("SafeAreaView");
});

test("selected navigation consumes only the universal Daily Log semantic pair", () => {
  const source = jest.requireActual("fs").readFileSync(
    "src/app/navigation/BottomNavigation.tsx",
    "utf8",
  );

  expect(source.match(/theme\.colors\.dailyLogBackground/g)).toHaveLength(1);
  expect(source.match(/theme\.colors\.dailyLogForeground/g)).toHaveLength(4);

  [
    "selectedNavigationBackground",
    "selectedNavigationForeground",
    "primaryActionBorder",
    "foodsBackground",
    "foodsForeground",
    "recipesBackground",
    "recipesForeground",
    "historyBackground",
    "historyForeground",
    "encouragementBackground",
    "encouragementForeground",
    "nutritionCaloriesSeries",
    "nutritionProteinSeries",
    "nutritionCarbohydrateSeries",
    "nutritionFatSeries",
  ].forEach((token) => {
    expect(source).not.toContain(`theme.colors.${token}`);
  });
});
