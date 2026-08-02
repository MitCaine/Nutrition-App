import React from "react";
import { Text, TextInput } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import { createAccessibilityAnnouncer } from "../src/shared/accessibility/announcements";
import { LabeledField } from "../src/shared/forms/LabeledField";
import { applyValidationIssue, validationIssue } from "../src/shared/forms/validation";

test("a structured validation issue targets focus, announces once, and leaves values intact", () => {
  const values = Object.freeze({ name: "", brand: "Kept brand" });
  const focusTarget = jest.fn(() => true);
  const announceNative = jest.fn();
  const announce = createAccessibilityAnnouncer({
    announceNative,
    now: () => 1000,
    schedule: (callback) => { callback(); return 0; },
    cancelScheduled: jest.fn(),
  });
  const issue = validationIssue({
    code: "food_name_required",
    message: "Food name is required.",
    target: "food.name",
    announce: true,
    moveFocus: true,
    valuesRemainValid: true,
  });

  applyValidationIssue(issue, { focusTarget, announce });
  applyValidationIssue(issue, { focusTarget, announce });

  expect(issue.target).toBe("food.name");
  expect(focusTarget).toHaveBeenCalledWith("food.name");
  expect(announceNative).toHaveBeenCalledTimes(1);
  expect(values).toEqual({ name: "", brand: "Kept brand" });
});

test("labeled field keeps visible and accessible labels after input and associates its error", async () => {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(LabeledField, {
      label: "Food name",
      validationTarget: "food.name",
      value: "Oatmeal",
      required: true,
      invalid: true,
      disabled: true,
      error: "Food name is required.",
      hint: "Enter the name shown in food lists.",
      onChangeText: jest.fn(),
    }));
  });
  const labels = renderer.root.findAllByType(Text);
  const textContent = (node: TestRenderer.ReactTestInstance | string): string =>
    typeof node === "string" ? node : node.children.map((child) => textContent(child as TestRenderer.ReactTestInstance | string)).join("");
  expect(labels.some((node) => textContent(node).includes("Food name"))).toBe(true);
  const input = renderer.root.findByType(TextInput);
  expect(input.props.accessibilityLabel).toBe("Food name");
  expect(input.props["aria-required"]).toBe(true);
  expect(input.props["aria-invalid"]).toBe(true);
  expect(input.props.accessibilityState).toEqual(expect.objectContaining({ disabled: true }));
  expect(input.props.editable).toBe(false);
  const error = labels.find((node) => node.props.accessibilityRole === "alert");
  expect(input.props["aria-describedby"]).toBe(error?.props.nativeID);
  await act(async () => renderer.unmount());
});

test.each([
  ["normal", {}, true, false, false, false, false],
  ["required", { required: true }, true, false, true, false, false],
  ["invalid", { invalid: true, error: "Review this value." }, true, false, false, true, false],
  ["disabled", { disabled: true }, false, true, false, false, false],
  ["read-only", { readOnly: true }, false, false, false, false, true],
  ["read-only invalid", { readOnly: true, invalid: true, error: "Displayed warning." }, false, false, false, true, true],
  ["disabled read-only", { disabled: true, readOnly: true }, false, true, false, false, true],
] as const)("labeled field exposes honest %s state", async (
  _name,
  state,
  expectedEditable,
  expectedDisabled,
  expectedRequired,
  expectedInvalid,
  expectReadOnlyHint,
) => {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(LabeledField, {
      label: "Notes",
      validationTarget: "food.notes",
      value: "Visible value",
      onChangeText: jest.fn(),
      ...state,
    }));
  });
  const input = renderer.root.findByType(TextInput);
  expect(input.props.editable).toBe(expectedEditable);
  expect(input.props.accessibilityState.disabled).toBe(expectedDisabled);
  expect(input.props["aria-required"]).toBe(expectedRequired);
  expect(input.props["aria-invalid"]).toBe(expectedInvalid);
  if (expectReadOnlyHint) {
    expect(input.props.accessibilityHint).toContain("Read only.");
  } else {
    expect(input.props.accessibilityHint ?? "").not.toContain("Read only.");
  }
  if ("error" in state) {
    const error = renderer.root.findAllByType(Text).find((node) => node.props.accessibilityRole === "alert");
    expect(input.props["aria-describedby"]).toBe(error?.props.nativeID);
  }
  await act(async () => renderer.unmount());
});
