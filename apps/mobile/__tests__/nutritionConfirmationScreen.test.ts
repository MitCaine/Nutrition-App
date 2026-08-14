import React from "react";
import { Modal, Pressable, Text, TextInput, View } from "react-native";
import TestRenderer, { act } from "react-test-renderer";
import * as Crypto from "expo-crypto";

const mockConfirm = jest.fn();
const mockInvalidate = jest.fn();
const mockNutrientDefinitions = [
  { id: "calories", display_name: "Calories", default_unit: "kcal", nutrient_kind: "energy", parent_nutrient_id: null, display_order: 10 },
  { id: "total_fat", display_name: "Total Fat", default_unit: "g", nutrient_kind: "fat", parent_nutrient_id: null, display_order: 20 },
  { id: "sodium", display_name: "Sodium", default_unit: "mg", nutrient_kind: "mineral", parent_nutrient_id: null, display_order: 40 },
  { id: "iron", display_name: "Iron", default_unit: "mg", nutrient_kind: "mineral", parent_nutrient_id: null, display_order: 90 },
  { id: "potassium", display_name: "Potassium", default_unit: "mg", nutrient_kind: "mineral", parent_nutrient_id: null, display_order: 100 },
];
let mockNutrientQuery: {
  data: ReadonlyArray<(typeof mockNutrientDefinitions)[number]> | undefined;
  isLoading: boolean;
  isError: boolean;
} = { data: mockNutrientDefinitions, isLoading: false, isError: false };

jest.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ invalidateQueries: (...args: unknown[]) => mockInvalidate(...args) }),
  useQuery: () => mockNutrientQuery,
}));
jest.mock("../src/features/ocr/api/ocrApi", () => ({
  confirmNutritionLabel: (...args: unknown[]) => mockConfirm(...args),
}));
jest.mock("../src/app/theme/AppTheme", () => {
  const actual = jest.requireActual("../src/app/theme/AppTheme");
  return { ...actual, useAppTheme: () => ({ ...actual.LIGHT_THEME, preference: "system", effectiveScheme: "light", setPreference: jest.fn() }) };
});
jest.mock("../src/shared/accessibility/focus", () => {
  const actual = jest.requireActual("../src/shared/accessibility/focus") as typeof import("../src/shared/accessibility/focus");
  const mockFocusAccessibilityElement = jest.fn(() => jest.fn());
  return {
    ...actual,
    focusAccessibilityElement: mockFocusAccessibilityElement,
    useAccessibilityScreenFocus: (options: Parameters<typeof actual.useAccessibilityScreenFocus>[0]) =>
      actual.useAccessibilityScreenFocus({ ...options, requestFocus: mockFocusAccessibilityElement }),
  };
});

import type { NutritionConfirmationDraft } from "../src/features/ocr/api/types";
import { NutritionConfirmationScreen } from "../src/features/ocr/screens/NutritionConfirmationScreen";
import { ApiError } from "../src/shared/api/client";
import * as focusModule from "../src/shared/accessibility/focus";
import { createNutritionTestRuntime, withNutritionRuntime } from "./nutritionRuntimeTestSupport";

const testRuntime = createNutritionTestRuntime();
const mockFocusAccessibilityElement = focusModule.focusAccessibilityElement as jest.Mock;

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

function confirmationScreenElement(initialDraft: NutritionConfirmationDraft, onCreated = jest.fn()) {
  return withNutritionRuntime(React.createElement(NutritionConfirmationScreen, {
    initialDraft,
    onCancel: jest.fn(),
    onCreated,
  }), testRuntime);
}

async function render(initialDraft = draft(), onCreated = jest.fn()) {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(confirmationScreenElement(initialDraft, onCreated), {
      createNodeMock: (element) => ({ ...(element.props as Record<string, unknown>), focus: jest.fn() }),
    });
  });
  return { renderer, onCreated };
}

function action(root: TestRenderer.ReactTestInstance, label: string) {
  return root.findAllByType(Pressable).find((item) => item.props.accessibilityLabel === label)!;
}

function input(root: TestRenderer.ReactTestInstance, label: string) {
  return root.findAllByType(TextInput).find((item) => item.props.accessibilityLabel === label)!;
}

function directedReview(root: TestRenderer.ReactTestInstance) {
  return root.findByProps({ testID: "nutrition-directed-review" });
}

function directedAction(root: TestRenderer.ReactTestInstance, label: string) {
  return directedReview(root).findAllByType(Pressable).find((item) => item.props.accessibilityLabel === label)!;
}

function directedInput(root: TestRenderer.ReactTestInstance, label: string) {
  return directedReview(root).findAllByType(TextInput).find((item) => item.props.accessibilityLabel === label)!;
}

function directedAmount(root: TestRenderer.ReactTestInstance) {
  return directedReview(root).findByProps({ testID: "nutrition-directed-review-amount" });
}

function validationMessages(root: TestRenderer.ReactTestInstance): string {
  return root.findAllByType(Text)
    .filter((item) => item.props.accessibilityRole === "alert")
    .map((item) => item.props.children)
    .filter((value): value is string => typeof value === "string")
    .join(" ");
}

function textValue(value: unknown): string {
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.map(textValue).join("");
  return "";
}

function visibleText(root: TestRenderer.ReactTestInstance): string {
  return root.findAllByType(Text)
    .map((item) => textValue(item.props.children))
    .join(" ");
}

function directedReviewVisible(root: TestRenderer.ReactTestInstance): boolean {
  return root.findByType(Modal).props.visible;
}

function focusTarget(index: number) {
  const target = mockFocusAccessibilityElement.mock.calls[index]?.[0] as {
    accessibilityLabel?: unknown;
    accessibilityRole?: unknown;
    children?: unknown;
    props?: {
      accessibilityLabel?: unknown;
      accessibilityRole?: unknown;
      children?: unknown;
      testID?: unknown;
    };
    testID?: unknown;
  } | undefined;
  const props = target?.props ?? target;
  return {
    accessibilityLabel: props?.accessibilityLabel,
    accessibilityRole: props?.accessibilityRole,
    children: props?.children,
    testID: props?.testID,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  mockNutrientQuery = { data: mockNutrientDefinitions, isLoading: false, isError: false };
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

test("unresolved potassium blocks final submission behind the directed review CTA", async () => {
  const initial = draft();
  initial.nutrients = [
    ...initial.nutrients,
    unresolvedNutrient("potassium", "Potassium", "35", 0.35),
  ];
  const { renderer } = await render(initial);

  expect(mockConfirm).not.toHaveBeenCalled();
  expect(action(renderer.root, "Review 1 item")).toBeDefined();
  expect(action(renderer.root, "Create Food")).toBeUndefined();
  expect(directedReviewVisible(renderer.root)).toBe(true);
  expect(directedInput(renderer.root, "Potassium amount").props["aria-invalid"]).toBe(false);
  await act(async () => renderer.unmount());
});

test.each([
  ["accepting", (renderer: TestRenderer.ReactTestRenderer) => directedAction(renderer.root, "Use Potassium value").props.onPress()],
  ["editing", (renderer: TestRenderer.ReactTestRenderer) => {
    directedInput(renderer.root, "Potassium amount").props.onChangeText("40");
    directedAction(renderer.root, "Use Potassium value").props.onPress();
  }],
  ["omitting", (renderer: TestRenderer.ReactTestRenderer) => directedAction(renderer.root, "Omit Potassium").props.onPress()],
] as const)("low-confidence Potassium stops saying review required after %s", async (_case, resolve) => {
  const initial = draft();
  initial.nutrients = [unresolvedNutrient("potassium", "Potassium", "35", 0.35)];
  const { renderer } = await render(initial);

  expect(action(renderer.root, "Review 1 item")).toBeDefined();
  expect(directedInput(renderer.root, "Potassium amount").props.accessibilityHint).toContain("Review required");
  expect(visibleText(renderer.root)).not.toContain("35% OCR confidence");
  await act(async () => resolve(renderer));

  expect(action(renderer.root, "Create Food")).toBeDefined();
  expect(input(renderer.root, "Potassium amount").props.accessibilityHint).not.toContain("Review required");
  expect(visibleText(renderer.root)).not.toContain("OCR confidence");
  await act(async () => renderer.unmount());
});

test("physical missing-unit Potassium displays catalog mg and omission submits canonical trace without a Food nutrient", async () => {
  const initial = draft();
  initial.nutrients = [{
    ...unresolvedNutrient("potassium", "Potassium", "35", 0.35),
    unit: null,
    parseStatus: "ambiguous",
    sourceText: "potassium",
    sourceObservationIds: ["physical-potassium"],
    warningCodes: ["nutrient_unit_unknown"],
  }];
  mockConfirm.mockResolvedValue(foodResponse("food-omitted-potassium"));
  const { renderer } = await render(initial);

  expect(visibleText(renderer.root)).toContain("Potassium mg");
  await act(async () => directedAction(renderer.root, "Omit Potassium").props.onPress());
  await act(async () => action(renderer.root, "Create Food").props.onPress());

  const payload = mockConfirm.mock.calls[0][0];
  expect(payload.food.nutrients.some((item: { nutrient_id: string }) => item.nutrient_id === "potassium")).toBe(false);
  expect(payload.field_decisions).toContainEqual(expect.objectContaining({
    field_key: "nutrient.potassium",
    nutrient_id: "potassium",
    confirmed_value: null,
    decision: "omitted",
    unit: "mg",
    parse_status: "ambiguous",
    source_text: "potassium",
    source_observation_ids: ["physical-potassium"],
    warning_codes: ["nutrient_unit_unknown"],
  }));
  await act(async () => renderer.unmount());
});

test("physical missing-unit Potassium edit retains catalog mg in Food and trace", async () => {
  const initial = draft();
  initial.nutrients = [{
    ...unresolvedNutrient("potassium", "Potassium", "35", 0.35),
    unit: null,
    parseStatus: "ambiguous",
    sourceText: "potassium",
    warningCodes: ["nutrient_unit_unknown"],
  }];
  mockConfirm.mockResolvedValue(foodResponse("food-edited-potassium"));
  const { renderer } = await render(initial);

  expect(visibleText(renderer.root)).toContain("Potassium mg");
  await act(async () => directedInput(renderer.root, "Potassium amount").props.onChangeText("15.125"));
  await act(async () => directedAction(renderer.root, "Use Potassium value").props.onPress());
  await act(async () => action(renderer.root, "Create Food").props.onPress());

  const payload = mockConfirm.mock.calls[0][0];
  expect(payload.food.nutrients).toContainEqual(expect.objectContaining({ nutrient_id: "potassium", amount: "15.125", unit: "mg" }));
  expect(payload.field_decisions).toContainEqual(expect.objectContaining({
    field_key: "nutrient.potassium", confirmed_value: "15.125", decision: "edited", unit: "mg",
  }));
  await act(async () => renderer.unmount());
});

test("catalog arrival hydrates a canonical unit without losing an earlier user edit or changing its decision", async () => {
  const initial = draft();
  initial.nutrients = [{
    ...unresolvedNutrient("potassium", "Potassium", "35", 0.35),
    unit: null,
    parseStatus: "ambiguous",
    sourceText: "potassium",
    warningCodes: ["nutrient_unit_unknown"],
  }];
  mockNutrientQuery = { data: [], isLoading: true, isError: false };
  mockConfirm.mockResolvedValue(foodResponse("food-late-catalog"));
  const { renderer } = await render(initial);

  expect(visibleText(renderer.root)).not.toContain("Potassium mg");
  await act(async () => directedInput(renderer.root, "Potassium amount").props.onChangeText("15"));
  expect(input(renderer.root, "Potassium amount").props.accessibilityLabel).toBe("Potassium amount");
  await act(async () => directedAction(renderer.root, "Use Potassium value").props.onPress());
  await act(async () => action(renderer.root, "Create Food").props.onPress());
  expect(mockConfirm).not.toHaveBeenCalled();
  expect(validationMessages(renderer.root)).toContain("nutrient catalog is still loading");

  mockNutrientQuery = { data: mockNutrientDefinitions, isLoading: false, isError: false };
  await act(async () => renderer.update(confirmationScreenElement(initial)));

  expect(visibleText(renderer.root)).toContain("Potassium mg");
  expect(input(renderer.root, "Potassium amount").props.value).toBe("15");
  expect(input(renderer.root, "Potassium amount").props.accessibilityLabel).toBe("Potassium amount");
  await act(async () => action(renderer.root, "Create Food").props.onPress());
  expect(mockConfirm.mock.calls[0][0].food.nutrients).toContainEqual(expect.objectContaining({
    nutrient_id: "potassium", amount: "15", unit: "mg",
  }));
  await act(async () => renderer.unmount());
});

test.each([
  [
    "pending",
    { data: [], isLoading: true, isError: false },
    "The nutrient catalog is still loading. Try again when canonical units are available.",
  ],
  [
    "error",
    { data: undefined, isLoading: false, isError: true },
    "The nutrient catalog could not be loaded. Try again.",
  ],
  [
    "loaded but incomplete",
    { data: mockNutrientDefinitions.filter(({ id }) => id !== "potassium"), isLoading: false, isError: false },
    "The canonical nutrient catalog is incomplete. This food cannot be confirmed safely.",
  ],
] as const)("%s nutrient catalog has a distinct bounded submission error", async (_case, queryState, expected) => {
  const initial = draft();
  initial.nutrients = [{ ...unresolvedNutrient("potassium", "Potassium", "35", 0.35), unit: null, decision: "omitted" }];
  mockNutrientQuery = queryState;
  const { renderer } = await render(initial);

  await act(async () => action(renderer.root, "Create Food").props.onPress());

  expect(mockConfirm).not.toHaveBeenCalled();
  expect(validationMessages(renderer.root)).toContain(expected);
  await act(async () => renderer.unmount());
});

test.each([
  ["edited", "5"],
  ["omitted", ""],
] as const)("resolved less-than ambiguous nutrient in %s state has no non-actionable metadata", async (decision, confirmedValue) => {
  const initial = draft();
  initial.nutrients = [{
    ...unresolvedNutrient("potassium", "Potassium", "1", 0.5),
    confirmedValue,
    decision,
    parseStatus: "ambiguous",
    comparison: "less_than",
    warningCodes: ["less_than_amount"],
  }];
  const { renderer } = await render(initial);

  expect(visibleText(renderer.root)).not.toContain("requires an exact replacement or omission");
  expect(visibleText(renderer.root)).not.toContain("Review required");
  expect(visibleText(renderer.root)).not.toContain("OCR value was less than the detected amount");
  expect(visibleText(renderer.root)).not.toContain("less-than");
  await act(async () => renderer.unmount());
});

test("all blocking fields stay marked while resolving the first blocker", async () => {
  const initial = draft();
  initial.name = "";
  initial.gramWeight = "0";
  initial.calories = { ...initial.calories, confirmedValue: "", decision: "accepted" };
  initial.nutrients = [
    ...initial.nutrients,
    unresolvedNutrient("potassium", "Potassium", "35", 0.35),
  ];
  const { renderer } = await render(initial);

  expect(action(renderer.root, "Review 1 item")).toBeDefined();
  await act(async () => directedAction(renderer.root, "Omit Potassium").props.onPress());
  await act(async () => action(renderer.root, "Create Food").props.onPress());

  expect(input(renderer.root, "Food name").props["aria-invalid"]).toBe(true);
  expect(input(renderer.root, "Serving grams").props["aria-invalid"]).toBe(true);
  expect(input(renderer.root, "Calories amount").props["aria-invalid"]).toBe(true);
  expect(input(renderer.root, "Potassium amount").props["aria-invalid"]).toBe(false);
  expect(validationMessages(renderer.root)).toEqual(expect.stringMatching(/Food name.*Serving grams.*Calories/s));

  await act(async () => input(renderer.root, "Food name").props.onChangeText("Resolved name"));

  expect(input(renderer.root, "Food name").props["aria-invalid"]).toBe(false);
  expect(input(renderer.root, "Serving grams").props["aria-invalid"]).toBe(true);
  expect(input(renderer.root, "Calories amount").props["aria-invalid"]).toBe(true);
  expect(input(renderer.root, "Potassium amount").props["aria-invalid"]).toBe(false);
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

  expect(action(renderer.root, "Review 2 items")).toBeDefined();
  expect(visibleText(renderer.root)).toContain("Review 2 items");
  expect(action(renderer.root, "Create Food")).toBeUndefined();
  expect(directedReviewVisible(renderer.root)).toBe(true);

  await act(async () => directedAction(renderer.root, "Omit Potassium").props.onPress());
  expect(action(renderer.root, "Review 1 item")).toBeDefined();
  expect(visibleText(renderer.root)).toContain("Review 1 item");
  expect(directedReviewVisible(renderer.root)).toBe(true);
  expect(directedInput(renderer.root, "Iron amount").props.accessibilityHint).toContain("Review required");

  await act(async () => directedInput(renderer.root, "Iron amount").props.onChangeText("5"));
  expect(action(renderer.root, "Create Food")).toBeUndefined();
  await act(async () => directedAction(renderer.root, "Use Iron value").props.onPress());
  expect(action(renderer.root, "Create Food")).toBeDefined();
  expect(mockConfirm).not.toHaveBeenCalled();

  mockConfirm.mockResolvedValue(foodResponse("food-reviewed"));
  await act(async () => action(renderer.root, "Create Food").props.onPress());
  expect(mockConfirm).toHaveBeenCalledTimes(1);
  const payload = mockConfirm.mock.calls[0][0];
  expect(payload.food.nutrients.some((item: { nutrient_id: string }) => item.nutrient_id === "potassium")).toBe(false);
  expect(payload.food.nutrients).toContainEqual(expect.objectContaining({ nutrient_id: "iron", amount: "5" }));
  await act(async () => renderer.unmount());
});

test("a canonical nutrient missed by OCR can be added once and persists with unambiguous provenance", async () => {
  mockConfirm.mockResolvedValue(foodResponse("food-manual-iron"));
  const { renderer } = await render();

  await act(async () => action(renderer.root, "Add missing nutrient").props.onPress());
  expect(action(renderer.root, "Add Iron")).toBeDefined();
  await act(async () => action(renderer.root, "Add Iron").props.onPress());
  expect(input(renderer.root, "Iron amount").props.accessibilityState.disabled).toBe(false);

  await act(async () => input(renderer.root, "Iron amount").props.onChangeText("4"));
  await act(async () => action(renderer.root, "Create Food").props.onPress());

  expect(mockConfirm).toHaveBeenCalledTimes(1);
  expect(mockConfirm.mock.calls[0][0].food.nutrients).toContainEqual(expect.objectContaining({
    nutrient_id: "iron",
    amount: "4",
    unit: "mg",
  }));
  expect(mockConfirm.mock.calls[0][0].field_decisions).toContainEqual(expect.objectContaining({
    field_key: "nutrient.iron",
    suggested_value: null,
    confirmed_value: "4",
    decision: "edited",
    resolution: "manually added because OCR did not provide it",
  }));
  await act(async () => renderer.unmount());
});

test("missing zero-confidence calories remain editable instead of becoming an irreversible omission", async () => {
  const initial = draft();
  initial.calories = {
    ...initial.calories,
    suggestedValue: null,
    confirmedValue: "",
    decision: "unresolved",
    parseStatus: "missing",
    confidence: 0,
    sourceText: "",
    sourceObservationIds: [],
  };
  initial.nutrients = [
    ...initial.nutrients,
    { ...unresolvedNutrient("potassium", "Potassium", "35", 0.35), confirmedValue: "", decision: "omitted" },
  ];
  mockConfirm.mockResolvedValue(foodResponse("food-physical-label"));
  const { renderer } = await render(initial);

  expect(input(renderer.root, "Calories amount").props.accessibilityState.disabled).toBe(false);
  expect(action(renderer.root, "Review 1 item")).toBeDefined();
  await act(async () => directedInput(renderer.root, "Calories amount").props.onChangeText("70"));
  await act(async () => directedAction(renderer.root, "Use Calories value").props.onPress());
  await act(async () => action(renderer.root, "Create Food").props.onPress());

  expect(mockConfirm).toHaveBeenCalledTimes(1);
  expect(mockConfirm.mock.calls[0][0].food.nutrients).toContainEqual(expect.objectContaining({ nutrient_id: "calories", amount: "70" }));
  expect(mockConfirm.mock.calls[0][0].food.nutrients.some((item: { nutrient_id: string }) => item.nutrient_id === "potassium")).toBe(false);
  await act(async () => renderer.unmount());
});

test("missing zero-confidence calories can be omitted and then restored without rescanning", async () => {
  const initial = draft();
  initial.calories = {
    ...initial.calories,
    suggestedValue: null,
    confirmedValue: "",
    decision: "unresolved",
    parseStatus: "missing",
    confidence: 0,
    sourceText: "",
    sourceObservationIds: [],
  };
  mockConfirm.mockResolvedValue(foodResponse("food-restored-calories"));
  const { renderer } = await render(initial);

  await act(async () => directedAction(renderer.root, "Omit Calories").props.onPress());
  expect(input(renderer.root, "Calories amount").props.accessibilityState.disabled).toBe(false);
  await act(async () => input(renderer.root, "Calories amount").props.onChangeText("70"));
  await act(async () => action(renderer.root, "Create Food").props.onPress());

  expect(mockConfirm).toHaveBeenCalledTimes(1);
  expect(mockConfirm.mock.calls[0][0].food.nutrients).toContainEqual(expect.objectContaining({
    nutrient_id: "calories",
    amount: "70",
    unit: "kcal",
  }));
  expect(mockConfirm.mock.calls[0][0].field_decisions).toContainEqual(expect.objectContaining({
    field_key: "nutrient.calories",
    decision: "edited",
    confirmed_value: "70",
  }));
  await act(async () => renderer.unmount());
});

test("omitted low- and high-confidence nutrients can be manually restored and retained", async () => {
  const initial = draft();
  initial.nutrients = [
    unresolvedNutrient("potassium", "Potassium", "35", 0.35),
    { ...unresolvedNutrient("iron", "Iron", "4", 0.95), decision: "accepted" },
  ];
  mockConfirm.mockResolvedValue(foodResponse("food-restored-nutrients"));
  const { renderer } = await render(initial);

  await act(async () => directedAction(renderer.root, "Omit Potassium").props.onPress());
  await act(async () => action(renderer.root, "Omit Iron").props.onPress());
  await act(async () => input(renderer.root, "Potassium amount").props.onChangeText("40"));
  await act(async () => input(renderer.root, "Iron amount").props.onChangeText("5"));
  await act(async () => action(renderer.root, "Create Food").props.onPress());

  expect(mockConfirm).toHaveBeenCalledTimes(1);
  expect(mockConfirm.mock.calls[0][0].food.nutrients).toEqual(expect.arrayContaining([
    expect.objectContaining({ nutrient_id: "potassium", amount: "40", unit: "mg" }),
    expect.objectContaining({ nutrient_id: "iron", amount: "5", unit: "mg" }),
  ]));
  await act(async () => renderer.unmount());
});

test("manual nutrient origin survives add, edit, omit, and re-edit", async () => {
  mockConfirm.mockResolvedValue(foodResponse("food-manual-iron-restored"));
  const { renderer } = await render();

  await act(async () => action(renderer.root, "Add missing nutrient").props.onPress());
  await act(async () => action(renderer.root, "Add Iron").props.onPress());
  await act(async () => input(renderer.root, "Iron amount").props.onChangeText("4"));
  await act(async () => action(renderer.root, "Omit Iron").props.onPress());
  expect(input(renderer.root, "Iron amount").props.accessibilityState.disabled).toBe(false);
  await act(async () => input(renderer.root, "Iron amount").props.onChangeText("5"));
  await act(async () => action(renderer.root, "Create Food").props.onPress());

  expect(mockConfirm.mock.calls[0][0].food.nutrients).toContainEqual(expect.objectContaining({
    nutrient_id: "iron",
    amount: "5",
    unit: "mg",
  }));
  expect(mockConfirm.mock.calls[0][0].field_decisions).toContainEqual(expect.objectContaining({
    field_key: "nutrient.iron",
    suggested_value: null,
    confirmed_value: "5",
    decision: "edited",
    parse_status: "missing",
    confidence: "0",
    resolution: "manually added because OCR did not provide it",
  }));
  await act(async () => renderer.unmount());
});

test.each([
  ["Sodium", "sodium", "15", null, "mg"],
  ["Total Fat", "total_fat", "8", "oz", "g"],
] as const)("%s with an unusable OCR unit resolves through the canonical catalog", async (label, nutrientId, amount, unit, canonicalUnit) => {
  const initial = draft();
  initial.nutrients = [{
    ...unresolvedNutrient(nutrientId, label, amount, 0.5),
    unit,
    sourceText: `${label} ${amount}`,
    warningCodes: ["nutrient_unit_unknown"],
  }];
  mockConfirm.mockResolvedValue(foodResponse(`food-${nutrientId}`));
  const { renderer } = await render(initial);

  expect(action(renderer.root, "Review 1 item")).toBeDefined();
  await act(async () => directedInput(renderer.root, `${label} amount`).props.onChangeText(amount));
  await act(async () => directedAction(renderer.root, `Use ${label} value`).props.onPress());
  await act(async () => action(renderer.root, "Create Food").props.onPress());

  expect(mockConfirm).toHaveBeenCalledTimes(1);
  expect(mockConfirm.mock.calls[0][0].food.nutrients).toContainEqual(expect.objectContaining({
    nutrient_id: nutrientId,
    amount,
    unit: canonicalUnit,
  }));
  expect(mockConfirm.mock.calls[0][0].field_decisions).toContainEqual(expect.objectContaining({
    field_key: `nutrient.${nutrientId}`,
    confirmed_value: amount,
    unit: canonicalUnit,
    source_text: `${label} ${amount}`,
    warning_codes: ["nutrient_unit_unknown"],
  }));
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
  for (const label of ["Cancel confirmation", "Omit Calories", "Omit Sodium", "Add missing nutrient", "Dismiss unknown nutrient Molybdenum", "Create Food"]) {
    expect(action(renderer.root, label)).toBeDefined();
  }
  expect(action(renderer.root, "Dismiss unknown nutrient Molybdenum").props.disabled).toBe(true);
  expect(input(renderer.root, "Sodium amount").props.accessibilityState.disabled).toBe(false);
  expect(input(renderer.root, "Calories amount").props.accessibilityLabel).toBe("Calories amount");
  expect(input(renderer.root, "Sodium amount").props.accessibilityLabel).toBe("Sodium amount");
  const caloriesInput = input(renderer.root, "Calories amount");
  expect(caloriesInput.parent?.findAllByType(Text).some((item) => item.props.children === "kcal")).toBe(true);
  expect(caloriesInput.parent?.findAllByType(Text).some((item) => item.props.children === "Calories")).toBe(false);
  expect(caloriesInput.parent?.findAllByType(Pressable).some((item) => item.props.accessibilityLabel === "Omit Calories")).toBe(true);
  expect(visibleText(renderer.root)).not.toMatch(/Review state:|OCR confidence|Low OCR confidence|OCR result was ambiguous/);
  expect(visibleText(renderer.root)).not.toContain("Calories 120");
  expect(visibleText(renderer.root)).not.toContain("Sodium 10mg");
  expect(renderer.root.findAll((item) => item.props.accessibilityLabel === "Unknown nutrient Molybdenum, dismissed").length).toBeGreaterThan(0);
  expect(renderer.root.findAllByType(View).some((item) => item.props.accessibilityLabel?.includes("review state"))).toBe(false);
  expect(renderer.root.findAllByType(View).some((item) => item.props.accessibilityLabel?.startsWith("Unknown nutrient"))).toBe(false);
  expect(renderer.root.findAllByType(Text).find((item) => item.props.accessibilityLabel === "Unknown nutrient Molybdenum, dismissed")?.props.accessible).toBe(true);
  expect(action(renderer.root, "Use Calories value")).toBeUndefined();
  expect(action(renderer.root, "Omit Sodium")).toBeDefined();
  expect(renderer.root.findByProps({ accessibilityRole: "header", children: "Confirm nutrition" })).toBeDefined();
  expect(action(renderer.root, "Create Food").props.accessibilityHint).toContain("logging confirmation");
  await act(async () => renderer.unmount());
});

test("ordinary screen focus owns initial entry when no directed review is required", async () => {
  const { renderer } = await render();

  expect(directedReviewVisible(renderer.root)).toBe(false);
  expect(mockFocusAccessibilityElement).toHaveBeenCalledTimes(1);
  expect(focusTarget(0)).toEqual(expect.objectContaining({
    accessibilityRole: "header",
    children: "Confirm nutrition",
  }));
  expect(mockFocusAccessibilityElement.mock.calls[0][1]).toMatchObject({ focusKeyboardTarget: false });
  await act(async () => renderer.unmount());
});

test("unresolved review opens a focused card without exposing internal state", async () => {
  const initial = draft();
  initial.calories = { ...initial.calories, decision: "unresolved" };
  const { renderer } = await render(initial);
  expect(directedInput(renderer.root, "Calories amount").props.accessibilityLabel).toBe("Calories amount");
  expect(directedInput(renderer.root, "Calories amount").props.accessibilityHint).toContain("Review required");
  expect(action(renderer.root, "Review 1 item")).toBeDefined();
  expect(visibleText(renderer.root)).toContain("Review 1 item");
  expect(directedReviewVisible(renderer.root)).toBe(true);
  expect(visibleText(renderer.root)).not.toContain("review state");
  expect(directedAction(renderer.root, "Use Calories value")).toBeDefined();
  expect(mockFocusAccessibilityElement).not.toHaveBeenCalled();
  await act(async () => renderer.root.findByType(Modal).props.onShow());
  expect(mockFocusAccessibilityElement).toHaveBeenCalledTimes(1);
  expect(focusTarget(0)).toEqual(expect.objectContaining({ accessibilityLabel: "Calories amount" }));
  expect(mockFocusAccessibilityElement.mock.calls[0][1]).toEqual({ delayMs: 60, focusKeyboardTarget: false });
  await act(async () => directedAction(renderer.root, "Close nutrition review").props.onPress());
  expect(directedReviewVisible(renderer.root)).toBe(false);
  expect(action(renderer.root, "Review 1 item")).toBeDefined();
  expect(mockFocusAccessibilityElement).toHaveBeenCalledTimes(2);
  expect(focusTarget(1).accessibilityLabel).toBe("Review 1 item");
  expect(focusTarget(1).children).not.toBe("Confirm nutrition");
  await act(async () => renderer.unmount());
});

test("directed review keeps incremental edits unresolved until explicit confirmation", async () => {
  const initial = draft();
  initial.nutrients = [unresolvedNutrient("potassium", "Potassium", "35", 0.35)];
  mockConfirm.mockResolvedValue(foodResponse("food-incremental-edit"));
  const { renderer } = await render(initial);

  await act(async () => renderer.root.findByType(Modal).props.onShow());
  await act(async () => directedInput(renderer.root, "Potassium amount").props.onChangeText("4"));
  expect(directedReviewVisible(renderer.root)).toBe(true);
  expect(directedInput(renderer.root, "Potassium amount").props.value).toBe("4");
  expect(directedInput(renderer.root, "Potassium amount").props.accessibilityHint).toContain("Review required");
  expect(action(renderer.root, "Review 1 item")).toBeDefined();
  expect(directedAction(renderer.root, "Use Potassium value")).toBeDefined();

  await act(async () => directedInput(renderer.root, "Potassium amount").props.onChangeText("40"));
  expect(directedReviewVisible(renderer.root)).toBe(true);
  expect(directedInput(renderer.root, "Potassium amount").props.value).toBe("40");
  expect(directedInput(renderer.root, "Potassium amount").props.accessibilityHint).toContain("Review required");
  expect(action(renderer.root, "Create Food")).toBeUndefined();
  expect(mockConfirm).not.toHaveBeenCalled();

  await act(async () => directedAction(renderer.root, "Use Potassium value").props.onPress());
  expect(directedReviewVisible(renderer.root)).toBe(false);
  expect(action(renderer.root, "Create Food")).toBeDefined();
  expect(focusTarget(1).accessibilityLabel).toBe("Create Food");

  await act(async () => action(renderer.root, "Create Food").props.onPress());
  expect(mockConfirm.mock.calls[0][0].field_decisions).toContainEqual(expect.objectContaining({
    field_key: "nutrient.potassium",
    confirmed_value: "40",
    decision: "edited",
    resolution: "entered exact value after review",
  }));
  await act(async () => renderer.unmount());
});

test("directed review explicitly accepting the original value preserves accepted semantics", async () => {
  const initial = draft();
  initial.nutrients = [unresolvedNutrient("potassium", "Potassium", "35", 0.35)];
  mockConfirm.mockResolvedValue(foodResponse("food-accepted-original"));
  const { renderer } = await render(initial);

  await act(async () => directedInput(renderer.root, "Potassium amount").props.onChangeText("3"));
  await act(async () => directedInput(renderer.root, "Potassium amount").props.onChangeText("35"));
  expect(directedReviewVisible(renderer.root)).toBe(true);
  expect(directedInput(renderer.root, "Potassium amount").props.value).toBe("35");
  await act(async () => directedAction(renderer.root, "Use Potassium value").props.onPress());
  expect(action(renderer.root, "Create Food")).toBeDefined();

  await act(async () => action(renderer.root, "Create Food").props.onPress());
  expect(mockConfirm.mock.calls[0][0].field_decisions).toContainEqual(expect.objectContaining({
    field_key: "nutrient.potassium",
    confirmed_value: "35",
    decision: "accepted",
    resolution: "accepted OCR suggestion after review",
  }));
  await act(async () => renderer.unmount());
});

test("a manually added nutrient remains reviewable until its entered value is explicitly confirmed", async () => {
  mockConfirm.mockResolvedValue(foodResponse("food-manual-directed"));
  const { renderer } = await render();

  await act(async () => action(renderer.root, "Add missing nutrient").props.onPress());
  await act(async () => action(renderer.root, "Add Iron").props.onPress());
  expect(action(renderer.root, "Review 1 item")).toBeDefined();
  await act(async () => action(renderer.root, "Review 1 item").props.onPress());
  expect(directedAction(renderer.root, "Use Iron value")).toBeUndefined();

  await act(async () => directedInput(renderer.root, "Iron amount").props.onChangeText("4"));
  expect(directedReviewVisible(renderer.root)).toBe(true);
  expect(directedInput(renderer.root, "Iron amount").props.value).toBe("4");
  expect(directedInput(renderer.root, "Iron amount").props.accessibilityHint).toContain("Review required");
  expect(directedAction(renderer.root, "Use Iron value")).toBeDefined();
  await act(async () => directedInput(renderer.root, "Iron amount").props.onChangeText("40"));
  expect(directedReviewVisible(renderer.root)).toBe(true);
  expect(directedInput(renderer.root, "Iron amount").props.value).toBe("40");
  expect(directedInput(renderer.root, "Iron amount").props.accessibilityHint).toContain("Review required");

  await act(async () => directedAction(renderer.root, "Use Iron value").props.onPress());
  expect(directedReviewVisible(renderer.root)).toBe(false);
  await act(async () => action(renderer.root, "Create Food").props.onPress());
  expect(mockConfirm.mock.calls[0][0].field_decisions).toContainEqual(expect.objectContaining({
    field_key: "nutrient.iron",
    suggested_value: null,
    confirmed_value: "40",
    decision: "edited",
    resolution: "manually added because OCR did not provide it",
  }));
  await act(async () => renderer.unmount());
});

test("explicit directed value confirmation advances focus to the next item", async () => {
  const initial = draft();
  initial.nutrients = [
    unresolvedNutrient("potassium", "Potassium", "35", 0.35),
    unresolvedNutrient("iron", "Iron", "4", 0.36),
  ];
  const { renderer } = await render(initial);

  await act(async () => renderer.root.findByType(Modal).props.onShow());
  await act(async () => directedInput(renderer.root, "Potassium amount").props.onChangeText("3"));
  expect(directedInput(renderer.root, "Potassium amount").props.value).toBe("3");
  expect(mockFocusAccessibilityElement).toHaveBeenCalledTimes(1);
  await act(async () => directedInput(renderer.root, "Potassium amount").props.onChangeText("35"));
  expect(directedInput(renderer.root, "Potassium amount").props.value).toBe("35");
  expect(mockFocusAccessibilityElement).toHaveBeenCalledTimes(1);

  await act(async () => directedAction(renderer.root, "Use Potassium value").props.onPress());
  expect(directedReviewVisible(renderer.root)).toBe(true);
  expect(directedInput(renderer.root, "Iron amount").props.value).toBe("4");
  expect(mockFocusAccessibilityElement).toHaveBeenCalledTimes(2);
  expect(focusTarget(1)).toEqual(expect.objectContaining({
    accessibilityLabel: "Iron amount",
    testID: "nutrition-directed-review-amount",
  }));
  expect(mockFocusAccessibilityElement.mock.calls[1][1]).toEqual({ delayMs: 60, focusKeyboardTarget: false });
  const transitionCancel = mockFocusAccessibilityElement.mock.results[1]?.value as jest.Mock;

  await act(async () => directedInput(renderer.root, "Iron amount").props.onChangeText("5"));
  expect(directedReviewVisible(renderer.root)).toBe(true);
  expect(action(renderer.root, "Create Food")).toBeUndefined();
  await act(async () => directedAction(renderer.root, "Use Iron value").props.onPress());
  expect(directedReviewVisible(renderer.root)).toBe(false);
  expect(transitionCancel).toHaveBeenCalledTimes(1);
  expect(focusTarget(2).accessibilityLabel).toBe("Create Food");
  await act(async () => renderer.unmount());
});

test("directed review uses modal controls, transitions focus, and preserves payload semantics", async () => {
  const initial = draft();
  initial.nutrients = [
    unresolvedNutrient("potassium", "Potassium", "35", 0.35),
    unresolvedNutrient("iron", "Iron", "4", 0.36),
  ];
  mockConfirm.mockResolvedValue(foodResponse("food-directed-review"));
  const { renderer } = await render(initial);

  expect(action(renderer.root, "Review 2 items")).toBeDefined();
  expect(directedReviewVisible(renderer.root)).toBe(true);
  expect(visibleText(renderer.root)).toContain("2 items remaining");
  expect(visibleText(renderer.root)).not.toContain("Review item 1 of");
  const background = renderer.root.findAllByType(View).find((item) => item.props.accessibilityElementsHidden === true);
  expect(background?.props.importantForAccessibility).toBe("no-hide-descendants");
  await act(async () => renderer.root.findByType(Modal).props.onShow());
  expect(mockFocusAccessibilityElement).toHaveBeenCalledTimes(1);
  expect(mockFocusAccessibilityElement.mock.calls[0][1]).toEqual({ delayMs: 60, focusKeyboardTarget: false });

  await act(async () => directedAction(renderer.root, "Omit Potassium").props.onPress());
  expect(action(renderer.root, "Review 1 item")).toBeDefined();
  expect(directedReviewVisible(renderer.root)).toBe(true);
  expect(visibleText(renderer.root)).toContain("1 item remaining");
  expect(directedAmount(renderer.root).props.value).toBe("4");
  expect(mockFocusAccessibilityElement).toHaveBeenCalledTimes(2);
  expect(focusTarget(1)).toEqual(expect.objectContaining({
    accessibilityLabel: "Iron amount",
    testID: "nutrition-directed-review-amount",
  }));
  expect(mockFocusAccessibilityElement.mock.calls[1][1]).toEqual({ delayMs: 60, focusKeyboardTarget: false });
  const transitionCancel = mockFocusAccessibilityElement.mock.results[1]?.value as jest.Mock;

  await act(async () => directedInput(renderer.root, "Iron amount").props.onChangeText("5"));
  expect(action(renderer.root, "Create Food")).toBeUndefined();
  await act(async () => directedAction(renderer.root, "Use Iron value").props.onPress());
  expect(action(renderer.root, "Create Food")).toBeDefined();
  expect(directedReviewVisible(renderer.root)).toBe(false);
  expect(transitionCancel).toHaveBeenCalledTimes(1);
  expect(mockFocusAccessibilityElement).toHaveBeenCalledTimes(3);
  expect(focusTarget(2).accessibilityLabel).toBe("Create Food");
  expect(mockFocusAccessibilityElement.mock.calls[2][1]).toEqual({ delayMs: 60, focusKeyboardTarget: false });

  await act(async () => action(renderer.root, "Create Food").props.onPress());
  expect(mockConfirm).toHaveBeenCalledTimes(1);
  expect(mockConfirm.mock.calls[0][0].field_decisions).toContainEqual(expect.objectContaining({
    field_key: "nutrient.potassium", decision: "omitted", confirmed_value: null,
    source_text: "Potassium 35mg", source_observation_ids: ["obs-potassium"],
  }));
  expect(mockConfirm.mock.calls[0][0].field_decisions).toContainEqual(expect.objectContaining({
    field_key: "nutrient.iron", decision: "edited", confirmed_value: "5",
  }));
  await act(async () => renderer.unmount());
});

test("an unresolved unknown row exposes state without swallowing its dismissal action", async () => {
  const initial = draft();
  initial.unknownNutrients = initial.unknownNutrients.map((item) => ({ ...item, dismissed: false }));
  const { renderer } = await render(initial);
  expect(renderer.root.findAllByType(Text).some((item) => item.props.accessibilityLabel === "Unknown nutrient Molybdenum, unresolved")).toBe(true);
  expect(directedAction(renderer.root, "Dismiss unknown nutrient Molybdenum").props.disabled).toBe(false);
  expect(action(renderer.root, "Review 1 item")).toBeDefined();
  await act(async () => renderer.root.findByType(Modal).props.onShow());
  expect(mockFocusAccessibilityElement).toHaveBeenCalledTimes(1);
  expect(focusTarget(0)).toEqual(expect.objectContaining({
    accessibilityRole: "header",
    children: "Molybdenum",
  }));
  expect(mockFocusAccessibilityElement.mock.calls[0][1]).toEqual({ delayMs: 60, focusKeyboardTarget: false });
  await act(async () => directedAction(renderer.root, "Dismiss unknown nutrient Molybdenum").props.onPress());
  expect(action(renderer.root, "Create Food")).toBeDefined();
  await act(async () => renderer.unmount());
});
