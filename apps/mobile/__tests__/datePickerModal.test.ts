import React from "react";
import { Platform, Pressable, Text } from "react-native";
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
  const date = "2026-07-14";
  const selected = new Date("2026-07-13T12:00:00.000Z");

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
  expect(mockDateTimePickerProps?.maximumDate).toEqual(new Date("2026-07-14T12:00:00.000Z"));
  expect(mockDateTimePickerProps?.timeZoneName).toBe("UTC");

  await act(async () => {
    pickerCallback<(event: unknown, value: Date) => void>("onValueChange")({}, selected);
  });
  expect(onChange).toHaveBeenCalledWith(selected.toISOString().slice(0, 10));
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
  const date = "2026-07-14";
  const selected = new Date("2026-07-12T12:00:00.000Z");

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
  expect(onChange).toHaveBeenCalledWith(selected.toISOString().slice(0, 10));
  expect(onConfirm).toHaveBeenCalledWith(selected.toISOString().slice(0, 10));

  await act(async () => {
    pickerCallback<() => void>("onDismiss")();
  });
  expect(onCancel).toHaveBeenCalledTimes(1);

  await act(async () => renderer.unmount());
});


test.each(["2011-12-29", "2011-12-30", "2011-12-31"])("native date-only UTC coordinate preserves %s on unchanged Done", async (date) => {
  setPlatform("ios");const onConfirm = jest.fn();let renderer!: TestRenderer.ReactTestRenderer;
  try {
    await act(async () => { renderer = TestRenderer.create(React.createElement(DatePickerModal, { date, visible: true, onChange: jest.fn(), onCancel: jest.fn(), onConfirm, maximumDate: "2026-07-14" })); });
    expect(mockDateTimePickerProps?.timeZoneName).toBe("UTC");expect((mockDateTimePickerProps?.value as Date).toISOString()).toBe(`${date}T12:00:00.000Z`);
    expect((mockDateTimePickerProps?.maximumDate as Date).toISOString()).toBe("2026-07-14T12:00:00.000Z");
    await act(async () => renderer.root.findAllByType(Pressable).find(node => node.props.accessibilityLabel === "Confirm selected date")!.props.onPress());
    expect(onConfirm).toHaveBeenCalledWith(date);
  } finally { if (renderer) await act(async () => renderer.unmount()); }
});

test("invalid native value is ignored and an unsupported initial date never becomes Today", async () => {
  setPlatform("ios");const onChange = jest.fn(), onConfirm = jest.fn(), onCancel = jest.fn();let renderer!: TestRenderer.ReactTestRenderer;
  try {
    await act(async () => { renderer = TestRenderer.create(React.createElement(DatePickerModal, { date: "2026-02-30", visible: true, onChange, onCancel, onConfirm })); });
    expect(mockDateTimePickerProps).toBeNull();expect(renderer.root.findAllByType(Text).some(node => String(node.props.children).includes("cannot be displayed"))).toBe(true);
    await act(async () => renderer.root.findAllByType(Pressable).find(node => node.props.accessibilityLabel === "Cancel date selection")!.props.onPress());expect(onCancel).toHaveBeenCalledTimes(1);expect(onConfirm).not.toHaveBeenCalled();
    await act(async () => renderer.update(React.createElement(DatePickerModal, { date: "2011-12-30", visible: true, onChange, onCancel, onConfirm })));
    await act(async () => pickerCallback<(event: unknown, value: Date) => void>("onValueChange")({}, new Date(NaN)));
    expect(onChange).not.toHaveBeenCalled();expect(onConfirm).not.toHaveBeenCalled();
  } finally { if (renderer) await act(async () => renderer.unmount()); }
});
