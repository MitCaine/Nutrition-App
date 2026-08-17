import React from "react";
import {
  Pressable,
  Text,
  TextInput,
} from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import type { TargetConfiguration } from "../src/features/targets/api/types";

let mockQueryData: TargetConfiguration;
const mockInvalidateQueries = jest.fn();
const mockUpdateConfiguration = jest.fn();
const mockResetOverride = jest.fn();

jest.mock("@tanstack/react-query", () => ({
  useQuery: () => ({
    data: mockQueryData,
    isLoading: false,
    isError: false,
  }),
  useQueryClient: () => ({
    invalidateQueries: mockInvalidateQueries,
  }),
}));

jest.mock("../src/runtime/NutritionRuntimeContext", () => ({
  useNutritionRuntime: () => ({
    targets: {
      updateConfiguration: mockUpdateConfiguration,
      resetOverride: mockResetOverride,
    },
  }),
}));

jest.mock("../src/shared/components/BackButton", () => {
  const React = require("react");
  const { Pressable, Text } = require("react-native");

  return {
    BackButton: ({
      accessibilityLabel,
      disabled,
      onPress,
    }: {
      accessibilityLabel: string;
      disabled?: boolean;
      onPress: () => void;
    }) =>
      React.createElement(
        Pressable,
        {
          accessibilityLabel,
          accessibilityRole: "button",
          accessibilityState: { disabled: Boolean(disabled) },
          disabled,
          onPress,
        },
        React.createElement(Text, null, "Back"),
      ),
  };
});


import { TargetSettingsScreen } from "../src/features/targets/TargetSettingsScreen";

function manualConfiguration(): TargetConfiguration {
  return {
    profile: null,
    estimatedMaintenanceCalories: {
      availability: "unavailable",
      amount: null,
      unit: "kcal",
      authority: "calculated_estimate",
      reasonCode: "target_profile_incomplete",
      equation: "mifflin_st_jeor_1990",
    },
    trackingPreferences: {},
    manualOverrides: [
      {
        nutrientId: "protein",
        amount: "90",
        unit: "g",
        authority: "manual_override",
        direction: "target",
        trackingMode: "custom",
        reasonCode: null,
        noteCode: null,
        referenceType: null,
        sourceVersion: null,
        sourceId: null,
        calculationBasis: null,
      },
    ],
    effectiveTargets: [
      {
        nutrientId: "protein",
        amount: "90",
        unit: "g",
        authority: "manual_override",
        direction: "target",
        trackingMode: "custom",
        reasonCode: null,
        noteCode: null,
        referenceType: null,
        sourceVersion: null,
        sourceId: null,
        calculationBasis: null,
      },
    ],
    dailyValueCatalogVersion: "fda_daily_values_2016_v1",
    dailyValueStandard:
      "FDA_NUTRITION_FACTS_ADULTS_AND_CHILDREN_4_PLUS",
    driDatasetVersion: "nasem_dri_adults_2026_v1",
    targetDirectionSemanticsVersion: "target_directions_2026_v1",
    dailyValues: [],
    driRecommendations: [],
    limitations: [],
    informationalNotice: "Estimate, not medical advice.",
  };
}

function automaticConfiguration(): TargetConfiguration {
  return {
    ...manualConfiguration(),
    manualOverrides: [],
    effectiveTargets: [
      {
        nutrientId: "protein",
        amount: "50",
        unit: "g",
        authority: "daily_value",
        direction: "target",
        trackingMode: "recommended",
        reasonCode: null,
        noteCode: null,
        referenceType: null,
        sourceVersion: null,
        sourceId: null,
        calculationBasis: null,
      },
    ],
  };
}

function input(
  renderer: TestRenderer.ReactTestRenderer,
  label: string,
) {
  return renderer.root
    .findAllByType(TextInput)
    .find((node) => node.props.accessibilityLabel === label)!;
}

function press(
  renderer: TestRenderer.ReactTestRenderer,
  label: string,
) {
  const node = renderer.root
    .findAllByType(Pressable)
    .find((item) => item.props.accessibilityLabel === label);

  if (!node) {
    throw new Error(`Missing pressable ${label}`);
  }

  node.props.onPress();
}

function visibleText(
  renderer: TestRenderer.ReactTestRenderer,
): string {
  const textValue = (value: unknown): string => {
    if (typeof value === "string" || typeof value === "number") {
      return String(value);
    }
    if (Array.isArray(value)) {
      return value.map(textValue).join("");
    }
    return "";
  };

  return renderer.root
    .findAllByType(Text)
    .map((node) => textValue(node.props.children))
    .join(" | ");
}

async function renderScreen(
  onDraftStateChange = jest.fn(),
) {
  let renderer!: TestRenderer.ReactTestRenderer;

  await act(async () => {
    renderer = TestRenderer.create(
      React.createElement(TargetSettingsScreen, {
        onBack: jest.fn(),
        draftStateKey: "targets-test",
        onDraftStateChange,
      }),
    );
  });

  return renderer;
}

beforeEach(() => {
  mockQueryData = manualConfiguration();
  mockInvalidateQueries.mockReset().mockResolvedValue(undefined);
  mockUpdateConfiguration
    .mockReset()
    .mockResolvedValue(automaticConfiguration());
  mockResetOverride.mockReset();
});

test("Reset changes only the editable target draft until Save", async () => {
  const onDraftStateChange = jest.fn();
  const renderer = await renderScreen(onDraftStateChange);

  expect(
    input(renderer, "Protein personal target").props.value,
  ).toBe("90");

  onDraftStateChange.mockClear();

  await act(async () =>
    press(renderer, "Reset Protein target"),
  );

  expect(
    input(renderer, "Protein personal target").props.value,
  ).toBe("");

  expect(mockResetOverride).not.toHaveBeenCalled();
  expect(mockUpdateConfiguration).not.toHaveBeenCalled();

  expect(visibleText(renderer)).toContain(
    "Reset pending · Save targets to apply.",
  );
  expect(visibleText(renderer)).toContain(
    "Current saved effective: 90 g/day · Custom target",
  );

  expect(onDraftStateChange).toHaveBeenCalledWith(
    "targets-test",
    {
      dirty: true,
      busy: false,
    },
  );

  await act(async () => renderer.unmount());
});

test("Save persists a pending Reset through updateConfiguration", async () => {
  const onDraftStateChange = jest.fn();
  const renderer = await renderScreen(onDraftStateChange);

  await act(async () =>
    press(renderer, "Reset Protein target"),
  );

  await act(async () =>
    press(renderer, "Save nutrition targets"),
  );

  expect(mockResetOverride).not.toHaveBeenCalled();
  expect(mockUpdateConfiguration).toHaveBeenCalledTimes(1);

  expect(
    mockUpdateConfiguration.mock.calls[0][0].manual_overrides.protein,
  ).toBeNull();

  expect(
    input(renderer, "Protein personal target").props.value,
  ).toBe("");

  expect(visibleText(renderer)).not.toContain(
    "Reset pending · Save targets to apply.",
  );
  expect(visibleText(renderer)).toContain(
    "Current saved effective: 50 g/day · FDA Daily Value",
  );

  expect(mockInvalidateQueries).toHaveBeenCalledWith({
    queryKey: ["targets"],
  });
  expect(mockInvalidateQueries).toHaveBeenCalledWith({
    queryKey: ["target-comparison"],
  });

  await act(async () => renderer.unmount());
});

test("failed Save keeps a pending Reset dirty and retryable", async () => {
  const onDraftStateChange = jest.fn();

  mockUpdateConfiguration.mockRejectedValueOnce(
    new Error("temporary failure"),
  );

  const renderer = await renderScreen(onDraftStateChange);

  await act(async () =>
    press(renderer, "Reset Protein target"),
  );

  await act(async () =>
    press(renderer, "Save nutrition targets"),
  );

  expect(
    input(renderer, "Protein personal target").props.value,
  ).toBe("");

  expect(visibleText(renderer)).toContain(
    "Reset pending · Save targets to apply.",
  );

  expect(
    onDraftStateChange.mock.calls.some(
      ([key, status]) =>
        key === "targets-test"
        && status?.dirty === true
        && status?.busy === false,
    ),
  ).toBe(true);

  mockUpdateConfiguration.mockResolvedValueOnce(
    automaticConfiguration(),
  );

  await act(async () =>
    press(renderer, "Save nutrition targets"),
  );

  expect(mockUpdateConfiguration).toHaveBeenCalledTimes(2);
  expect(visibleText(renderer)).not.toContain(
    "Reset pending · Save targets to apply.",
  );

  await act(async () => renderer.unmount());
});

test("a draft-only manual target can be reset back to pristine without persistence", async () => {
  mockQueryData = automaticConfiguration();

  const onDraftStateChange = jest.fn();
  const renderer = await renderScreen(onDraftStateChange);

  await act(async () =>
    input(renderer, "Protein personal target")
      .props.onChangeText("120"),
  );

  expect(
    renderer.root.findByProps({
      accessibilityLabel: "Reset Protein target",
    }),
  ).toBeDefined();

  await act(async () =>
    press(renderer, "Reset Protein target"),
  );

  expect(
    input(renderer, "Protein personal target").props.value,
  ).toBe("");

  expect(mockResetOverride).not.toHaveBeenCalled();
  expect(mockUpdateConfiguration).not.toHaveBeenCalled();

  expect(
    onDraftStateChange.mock.calls.some(
      ([key, status]) =>
        key === "targets-test"
        && status?.dirty === false
        && status?.busy === false,
    ),
  ).toBe(true);

  await act(async () => renderer.unmount());
});
