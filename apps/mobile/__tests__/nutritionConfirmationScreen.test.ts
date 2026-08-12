import React from "react";
import { Pressable, Text, TextInput, View } from "react-native";
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
import { ApiError } from "../src/shared/api/client";
import { createNutritionTestRuntime, withNutritionRuntime } from "./nutritionRuntimeTestSupport";

const testRuntime = createNutritionTestRuntime();

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

function unresolvedNutrient(
  nutrientId: string,
  label: string,
  value: string,
  confidence: number,
): NutritionConfirmationDraft["nutrients"][number] {
  return {
    fieldKey: `nutrient.${nutrientId}`,
    nutrientId,
    label,
    suggestedValue: value,
    confirmedValue: value,
    unit: "mg",
    decision: "unresolved",
    parseStatus: "parsed",
    comparison: null,
    confidence,
    sourceText: `${label} ${value}mg`,
    sourceObservationIds: [`obs-${nutrientId}`],
    warningCodes: [],
    resolution: null,
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
      withNutritionRuntime(React.createElement(NutritionConfirmationScreen, {
        initialDraft,
        onCancel: jest.fn(),
        onCreated,
      }), testRuntime),
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

function validationMessages(root: TestRenderer.ReactTestInstance): string {
  return root.findAllByType(Text)
    .filter((item) => item.props.accessibilityRole === "alert")
    .map((item) => item.props.children)
    .filter((value): value is string => typeof value === "string")
    .join(" ");
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

test("idempotency conflict retires the intent, preserves the draft, and guards the fresh retry", async () => {
  const retry = deferred<ReturnType<typeof foodResponse>>();
  (Crypto.randomUUID as jest.Mock)
    .mockReturnValueOnce("00000000-0000-4000-8000-000000000001")
    .mockReturnValueOnce("00000000-0000-4000-8000-000000000002");
  mockConfirm
    .mockRejectedValueOnce(new ApiError({
      status: 409,
      body: { detail: { code: "ocr_confirmation_idempotency_conflict" } },
      message: "conflict",
    }))
    .mockReturnValueOnce(retry.promise);
  const { renderer } = await render();

  await act(async () => action(renderer.root, "Create Food").props.onPress());
  expect(input(renderer.root, "Food name").props.value).toBe("Cereal");
  expect(renderer.root.findAllByType(Text).some((item) => item.props.accessibilityRole === "alert")).toBe(true);

  await act(async () => {
    void action(renderer.root, "Create Food").props.onPress();
    void action(renderer.root, "Create Food").props.onPress();
    await Promise.resolve();
  });
  expect(mockConfirm).toHaveBeenCalledTimes(2);
  expect(mockConfirm.mock.calls[0][0].client_request_id).toBe("00000000-0000-4000-8000-000000000001");
  expect(mockConfirm.mock.calls[1][0].client_request_id).toBe("00000000-0000-4000-8000-000000000002");
  expect(action(renderer.root, "Cancel confirmation").props.disabled).toBe(true);

  await act(async () => retry.resolve(foodResponse()));
  await act(async () => renderer.unmount());
});

test("editing after conflict creates one fresh intent reused by an unchanged network retry", async () => {
  (Crypto.randomUUID as jest.Mock)
    .mockReturnValueOnce("00000000-0000-4000-8000-000000000001")
    .mockReturnValueOnce("00000000-0000-4000-8000-000000000002");
  mockConfirm
    .mockRejectedValueOnce(new ApiError({
      status: 409,
      body: { detail: { code: "ocr_confirmation_idempotency_conflict" } },
      message: "conflict",
    }))
    .mockRejectedValue(new Error("offline"));
  const { renderer } = await render();

  await act(async () => action(renderer.root, "Create Food").props.onPress());
  await act(async () => input(renderer.root, "Food name").props.onChangeText("Edited after conflict"));
  await act(async () => action(renderer.root, "Create Food").props.onPress());
  await act(async () => action(renderer.root, "Create Food").props.onPress());

  expect(mockConfirm.mock.calls.map((call) => call[0].client_request_id)).toEqual([
    "00000000-0000-4000-8000-000000000001",
    "00000000-0000-4000-8000-000000000002",
    "00000000-0000-4000-8000-000000000002",
  ]);
  expect(input(renderer.root, "Food name").props.value).toBe("Edited after conflict");
  expect(Crypto.randomUUID).toHaveBeenCalledTimes(2);
  await act(async () => renderer.unmount());
});

test("validation failure does not bind an intent or issue a request", async () => {
  const invalid = { ...draft(), name: "" };
  const { renderer } = await render(invalid);
  await act(async () => action(renderer.root, "Create Food").props.onPress());
  expect(mockConfirm).not.toHaveBeenCalled();
  expect(Crypto.randomUUID).not.toHaveBeenCalled();
  expect(renderer.root.findAllByType(Text).some((item) => item.props.accessibilityRole === "alert")).toBe(true);
  expect(input(renderer.root, "Food name").props["aria-invalid"]).toBe(true);
  expect(input(renderer.root, "Food name").props["aria-describedby"]).toBeDefined();
  await act(async () => renderer.unmount());
});

test("low-confidence potassium validation names and highlights the unresolved nutrient", async () => {
  const initial = draft();
  initial.nutrients = [
    ...initial.nutrients,
    unresolvedNutrient("potassium", "Potassium", "35", 0.35),
  ];
  const { renderer } = await render(initial);

  await act(async () => action(renderer.root, "Create Food").props.onPress());

  expect(mockConfirm).not.toHaveBeenCalled();
  expect(validationMessages(renderer.root)).toContain("Potassium requires review");
  expect(input(renderer.root, "Potassium amount").props["aria-invalid"]).toBe(true);
  await act(async () => renderer.unmount());
});

test("multiple unresolved nutrients remain independently resolvable", async () => {
  const initial = draft();
  initial.nutrients = [
    ...initial.nutrients,
    unresolvedNutrient("potassium", "Potassium", "35", 0.35),
    unresolvedNutrient("iron", "Iron", "4", 0.36),
  ];
  const { renderer } = await render(initial);

  await act(async () => action(renderer.root, "Create Food").props.onPress());
  const firstError = validationMessages(renderer.root);
  expect(firstError).toContain("Potassium");
  expect(firstError).toContain("Iron");

  await act(async () => action(renderer.root, "Omit Potassium").props.onPress());
  await act(async () => action(renderer.root, "Create Food").props.onPress());
  expect(mockConfirm).not.toHaveBeenCalled();
  expect(validationMessages(renderer.root)).toContain("Iron requires review");
  expect(validationMessages(renderer.root)).not.toContain("Potassium");
  expect(input(renderer.root, "Iron amount").props["aria-invalid"]).toBe(true);

  mockConfirm.mockResolvedValue(foodResponse("food-reviewed"));
  await act(async () => input(renderer.root, "Iron amount").props.onChangeText("5"));
  await act(async () => action(renderer.root, "Create Food").props.onPress());
  expect(mockConfirm).toHaveBeenCalledTimes(1);
  const payload = mockConfirm.mock.calls[0][0];
  expect(payload.food.nutrients.some((item: { nutrient_id: string }) => item.nutrient_id === "potassium")).toBe(false);
  expect(payload.food.nutrients).toContainEqual(expect.objectContaining({ nutrient_id: "iron", amount: "5" }));
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
  for (const label of ["Cancel confirmation", "Omit Sodium", "Dismiss unknown nutrient Molybdenum", "Create Food"]) {
    expect(action(renderer.root, label)).toBeDefined();
  }
  expect(action(renderer.root, "Dismiss unknown nutrient Molybdenum").props.disabled).toBe(true);
  expect(input(renderer.root, "Sodium amount").props.accessibilityState.disabled).toBe(true);
  expect(renderer.root.findAll((item) => item.props.accessibilityLabel === "Calories, review state accepted").length).toBeGreaterThan(0);
  expect(renderer.root.findAll((item) => item.props.accessibilityLabel === "Sodium, review state omitted").length).toBeGreaterThan(0);
  expect(renderer.root.findAll((item) => item.props.accessibilityLabel === "Unknown nutrient Molybdenum, dismissed").length).toBeGreaterThan(0);
  expect(renderer.root.findAllByType(View).some((item) => item.props.accessibilityLabel?.includes("review state"))).toBe(false);
  expect(renderer.root.findAllByType(View).some((item) => item.props.accessibilityLabel?.startsWith("Unknown nutrient"))).toBe(false);
  expect(renderer.root.findAllByType(Text).find((item) => item.props.accessibilityLabel === "Calories, review state accepted")?.props.accessible).toBe(true);
  expect(renderer.root.findAllByType(Text).find((item) => item.props.accessibilityLabel === "Unknown nutrient Molybdenum, dismissed")?.props.accessible).toBe(true);
  expect(action(renderer.root, "Use Calories value")).toBeUndefined();
  expect(action(renderer.root, "Omit Sodium")).toBeDefined();
  expect(renderer.root.findByProps({ accessibilityRole: "header", children: "Confirm nutrition" })).toBeDefined();
  expect(action(renderer.root, "Create Food").props.accessibilityHint).toContain("logging confirmation");
  await act(async () => renderer.unmount());
});

test("unresolved review state is exposed to assistive technology", async () => {
  const initial = draft();
  initial.calories = { ...initial.calories, decision: "unresolved" };
  const { renderer } = await render(initial);
  expect(renderer.root.findAll((item) => item.props.accessibilityLabel === "Calories, review state unresolved").length).toBeGreaterThan(0);
  expect(action(renderer.root, "Use Calories value")).toBeDefined();
  await act(async () => renderer.unmount());
});

test("an unresolved unknown row exposes state without swallowing its dismissal action", async () => {
  const initial = draft();
  initial.unknownNutrients = initial.unknownNutrients.map((item) => ({ ...item, dismissed: false }));
  const { renderer } = await render(initial);
  expect(renderer.root.findAllByType(Text).some((item) => item.props.accessibilityLabel === "Unknown nutrient Molybdenum, unresolved")).toBe(true);
  expect(action(renderer.root, "Dismiss unknown nutrient Molybdenum").props.disabled).toBe(false);
  await act(async () => renderer.unmount());
});
