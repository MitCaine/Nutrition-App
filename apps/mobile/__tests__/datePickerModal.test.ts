import React from "react";
import { Platform } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import { DatePickerModal } from "../src/features/logging/screens/DatePickerModal";

let mockDateTimePickerProps: Record<string, unknown> | null = null;

jest.mock("@react-native-community/datetimepicker", () => ({
  __esModule: true,
  default: (props: Record<string, unknown>) => {
    mockDateTimePickerProps = props;
    return null;
  },
}));

jest.mock("../src/shared/accessibility/AccessibleModal", () => {
  const mockReact = require("react");
  return {
    AccessibleModal: ({ visible, children }: { visible: boolean; children: React.ReactNode }) => (
      visible ? mockReact.createElement(mockReact.Fragment, null, children) : null
    ),
  };
});

jest.mock("../src/app/theme/AppTheme", () => {
  const actual = jest.requireActual("../src/app/theme/AppTheme");
  return {
    ...actual,
    useAppTheme: () => ({
      ...actual.LIGHT_THEME,
      preference: "system",
      effectiveScheme: "light",
      setPreference: jest.fn(),
    }),
  };
});

const originalPlatform = Platform.OS;

function setPlatform(os: "ios" | "android") {
  Object.defineProperty(Platform, "OS", { configurable: true, value: os });
}

function pickerCallback<T extends (...args: never[]) => unknown>(name: string): T {
  const callback = mockDateTimePickerProps?.[name];
  expect(typeof callback).toBe("function");
  return callback as T;
}

afterEach(() => {
  Object.defineProperty(Platform, "OS", { configurable: true, value: originalPlatform });
  mockDateTimePickerProps = null;
});

test("iOS uses the supported value and dismissal callbacks without auto-confirming", async () => {
  setPlatform("ios");
  const onChange = jest.fn();
  const onCancel = jest.fn();
  const onConfirm = jest.fn();
  const date = new Date(2026, 6, 14, 12);
  const selected = new Date(2026, 6, 13, 12);

  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(DatePickerModal, {
      date,
      visible: true,
      onChange,
      onCancel,
      onConfirm,
      maximumDate: date,
    }));
  });

  expect(mockDateTimePickerProps?.onChange).toBeUndefined();
  expect(mockDateTimePickerProps?.maximumDate).toBe(date);

  await act(async () => {
    pickerCallback<(event: unknown, value: Date) => void>("onValueChange")({}, selected);
  });
  expect(onChange).toHaveBeenCalledWith(selected);
  expect(onConfirm).not.toHaveBeenCalled();

  await act(async () => {
    pickerCallback<() => void>("onDismiss")();
  });
  expect(onCancel).toHaveBeenCalledTimes(1);

  await act(async () => renderer.unmount());
});

test("Android preserves immediate selection confirmation and dismissal cancellation", async () => {
  setPlatform("android");
  const onChange = jest.fn();
  const onCancel = jest.fn();
  const onConfirm = jest.fn();
  const date = new Date(2026, 6, 14, 12);
  const selected = new Date(2026, 6, 12, 12);

  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(DatePickerModal, {
      date,
      visible: true,
      onChange,
      onCancel,
      onConfirm,
    }));
  });

  expect(mockDateTimePickerProps?.onChange).toBeUndefined();
  await act(async () => {
    pickerCallback<(event: unknown, value: Date) => void>("onValueChange")({}, selected);
  });
  expect(onChange).toHaveBeenCalledWith(selected);
  expect(onConfirm).toHaveBeenCalledWith(selected);

  await act(async () => {
    pickerCallback<() => void>("onDismiss")();
  });
  expect(onCancel).toHaveBeenCalledTimes(1);

  await act(async () => renderer.unmount());
});
