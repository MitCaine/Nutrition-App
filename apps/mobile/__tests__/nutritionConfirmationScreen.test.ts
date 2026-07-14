import React from "react";
import { Pressable, Text, TextInput } from "react-native";
import TestRenderer, { act } from "react-test-renderer";
import * as Crypto from "expo-crypto";

const mockConfirm = jest.fn();
const mockInvalidate = jest.fn();

jest.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ invalidateQueries: (...args: unknown[]) => mockInvalidate(...args) }),
}));
jest.mock("../src/features/ocr/api/ocrApi", () => ({
  confirmNutritionLabel: (...args: unknown[]) => mockConfirm(...args),
}));
jest.mock("../src/app/theme/AppTheme", () => {
  const actual = jest.requireActual("../src/app/theme/AppTheme");
  return { ...actual, useAppTheme: () => ({ ...actual.LIGHT_THEME, preference: "system", effectiveScheme: "light", setPreference: jest.fn() }) };
});

import type { NutritionConfirmationDraft } from "../src/features/ocr/api/types";
import { NutritionConfirmationScreen } from "../src/features/ocr/screens/NutritionConfirmationScreen";

function draft(): NutritionConfirmationDraft {
  return {
    parserVersion: "nutrition_label_v1", imageSourceType: "photo_library",
    name: "Cereal", brand: "Brand", notes: "", servingDisplay: "1 cup (30g)", servingQuantity: "1", servingUnit: "cup", gramWeight: "30",
    servingProvenance: { display: null, quantity: null, unit: null, gramWeight: null },
    calories: { fieldKey: "nutrient.calories", nutrientId: "calories", label: "Calories", suggestedValue: "120", confirmedValue: "120", unit: "kcal", decision: "accepted", parseStatus: "parsed", comparison: null, confidence: 0.98, sourceText: "Calories 120", sourceObservationIds: ["obs-1"], warningCodes: [], resolution: null },
    nutrients: [{ fieldKey: "nutrient.sodium", nutrientId: "sodium", label: "Sodium", suggestedValue: "10", confirmedValue: "", unit: "mg", decision: "omitted", parseStatus: "parsed", comparison: null, confidence: 0.9, sourceText: "Sodium 10mg", sourceObservationIds: ["obs-2"], warningCodes: [], resolution: null }],
    unknownNutrients: [{ originalName: "Molybdenum", sourceText: "Molybdenum 4mcg", sourceObservationIds: ["obs-3"], warningCodes: [], dismissed: true }],
    parserWarningCodes: [],
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => { resolve = resolvePromise; reject = rejectPromise; });
  return { promise, resolve, reject };
}

function foodResponse(id = "food-1") { return { food: { id }, trace_id: "trace-1" }; }

async function render(initialDraft = draft(), onCreated = jest.fn()) {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(
      React.createElement(NutritionConfirmationScreen, {
        initialDraft,
        onCancel: jest.fn(),
        onCreated,
      }),
    );
  });
  return { renderer, onCreated };
}

function action(root: TestRenderer.ReactTestInstance, label: string) {
  return root.findAllByType(Pressable).find((item) => item.props.accessibilityLabel === label)!;
}

function input(root: TestRenderer.ReactTestInstance, label: string) {
  return root.findAllByType(TextInput).find((item) => item.props.accessibilityLabel === label)!;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockInvalidate.mockResolvedValue(undefined);
});

test("unchanged failure retry reuses ID, while an edited retry rotates it and preserves the draft", async () => {
  (Crypto.randomUUID as jest.Mock).mockReturnValueOnce("00000000-0000-4000-8000-000000000001").mockReturnValueOnce("00000000-0000-4000-8000-000000000002");
  mockConfirm.mockRejectedValue(new Error("offline"));
  const { renderer } = await render();
  await act(async () => action(renderer.root, "Create Food").props.onPress());
  await act(async () => action(renderer.root, "Create Food").props.onPress());
  expect(mockConfirm.mock.calls[0][0].client_request_id).toBe("00000000-0000-4000-8000-000000000001");
  expect(mockConfirm.mock.calls[1][0].client_request_id).toBe("00000000-0000-4000-8000-000000000001");
  await act(async () => input(renderer.root, "Food name").props.onChangeText("Edited Cereal"));
  await act(async () => action(renderer.root, "Create Food").props.onPress());
  expect(mockConfirm.mock.calls[2][0].client_request_id).toBe("00000000-0000-4000-8000-000000000002");
  expect(input(renderer.root, "Food name").props.value).toBe("Edited Cereal");
  await act(async () => renderer.unmount());
});

test("validation failure does not bind an intent or issue a request", async () => {
  const invalid = { ...draft(), name: "" };
  const { renderer } = await render(invalid);
  await act(async () => action(renderer.root, "Create Food").props.onPress());
  expect(mockConfirm).not.toHaveBeenCalled();
  expect(Crypto.randomUUID).not.toHaveBeenCalled();
  expect(renderer.root.findAllByType(Text).some((item) => item.props.accessibilityRole === "alert")).toBe(true);
  await act(async () => renderer.unmount());
});

test("rapid Create presses issue one request and disable Cancel while pending", async () => {
  const pending = deferred<ReturnType<typeof foodResponse>>();
  mockConfirm.mockReturnValue(pending.promise);
  const { renderer } = await render();
  await act(async () => {
    void action(renderer.root, "Create Food").props.onPress();
    void action(renderer.root, "Create Food").props.onPress();
    await Promise.resolve();
  });
  expect(mockConfirm).toHaveBeenCalledTimes(1);
  expect(action(renderer.root, "Cancel confirmation").props.disabled).toBe(true);
  expect(action(renderer.root, "Creating Food").props.accessibilityState).toMatchObject({ busy: true, disabled: true });
  await act(async () => pending.resolve(foodResponse()));
  await act(async () => renderer.unmount());
});

test("unmount before resolution suppresses stale navigation", async () => {
  const pending = deferred<ReturnType<typeof foodResponse>>();
  mockConfirm.mockReturnValue(pending.promise);
  const onCreated = jest.fn();
  const { renderer } = await render(draft(), onCreated);
  await act(async () => { void action(renderer.root, "Create Food").props.onPress(); await Promise.resolve(); });
  await act(async () => renderer.unmount());
  await act(async () => pending.resolve(foodResponse()));
  expect(onCreated).not.toHaveBeenCalled();
});

test("success invokes onCreated once", async () => {
  mockConfirm.mockResolvedValue(foodResponse("food-success"));
  const onCreated = jest.fn();
  const { renderer } = await render(draft(), onCreated);
  await act(async () => action(renderer.root, "Create Food").props.onPress());
  expect(onCreated).toHaveBeenCalledTimes(1);
  expect(onCreated).toHaveBeenCalledWith("food-success");
  await act(async () => renderer.unmount());
});

test("all confirmation controls expose specific accessibility labels and review semantics", async () => {
  const { renderer } = await render();
  for (const label of ["Food name", "Brand", "Notes", "Serving label", "Serving quantity", "Serving unit", "Serving grams", "Calories amount", "Sodium amount"]) {
    expect(input(renderer.root, label)).toBeDefined();
  }
  for (const label of ["Cancel confirmation", "Use Calories value", "Omit Sodium", "Dismiss unknown nutrient Molybdenum", "Create Food"]) {
    expect(action(renderer.root, label)).toBeDefined();
  }
  expect(action(renderer.root, "Dismiss unknown nutrient Molybdenum").props.disabled).toBe(true);
  expect(input(renderer.root, "Sodium amount").props.accessibilityState.disabled).toBe(true);
  expect(renderer.root.findAll((item) => item.props.accessibilityLabel === "Calories, review state accepted").length).toBeGreaterThan(0);
  expect(renderer.root.findAll((item) => item.props.accessibilityLabel === "Sodium, review state omitted").length).toBeGreaterThan(0);
  expect(renderer.root.findAll((item) => item.props.accessibilityLabel === "Unknown nutrient Molybdenum, dismissed").length).toBeGreaterThan(0);
  await act(async () => renderer.unmount());
});

test("unresolved review state is exposed to assistive technology", async () => {
  const initial = draft();
  initial.calories = { ...initial.calories, decision: "unresolved" };
  const { renderer } = await render(initial);
  expect(renderer.root.findAll((item) => item.props.accessibilityLabel === "Calories, review state unresolved").length).toBeGreaterThan(0);
  await act(async () => renderer.unmount());
});
