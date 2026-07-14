import React from "react";
import { Pressable, Text, TextInput } from "react-native";
import TestRenderer, { act, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";

import type { Food, FoodResolvedNutrition, ResolvedFoodAmount } from "../src/features/foods/api/types";
import type {
  DailyLog,
  DailyLogCreateInput,
  DailyLogEditContext,
  DailyLogUpdateInput,
} from "../src/features/logging/api/types";
import { LogFoodScreen } from "../src/features/logging/screens/LogFoodScreen";

type Deferred = {
  promise: Promise<unknown>;
  resolve: (value?: unknown) => void;
  reject: (reason?: unknown) => void;
};

let mockFoodQuery: Record<string, unknown>;
let mockResolvedQuery: Record<string, unknown>;
let mockEditContextQuery: Record<string, unknown>;
let mockCreateDeferred: Deferred;
let mockUpdateDeferred: Deferred;
let mockRequestIds: string[];
const mockCreateLog = jest.fn((_input: DailyLogCreateInput) => mockCreateDeferred.promise);
const mockUpdateLog = jest.fn((
  _params: { logId: string; input: Partial<DailyLogUpdateInput> },
) => mockUpdateDeferred.promise);
const mockCreateClientRequestId = jest.fn(() => mockRequestIds.shift() as string);

jest.mock("../src/features/foods/hooks/useFoods", () => ({
  useFood: () => mockFoodQuery,
  useFoodResolvedNutrition: () => mockResolvedQuery,
}));

jest.mock("../src/features/logging/hooks/useLogs", () => ({
  useLogEditContext: () => mockEditContextQuery,
  useLogMutations: () => ({
    createLog: { mutateAsync: mockCreateLog },
    updateLog: { mutateAsync: mockUpdateLog },
  }),
}));

jest.mock("../src/features/logging/utils/clientRequestId", () => ({
  createClientRequestId: () => mockCreateClientRequestId(),
}));

const food: Food = {
  id: "food-1",
  name: "Submission Food",
  source_type: "manual",
  source_id: null,
  is_recipe: false,
  source_kind: "manual", source_label: "Manual", is_favorite: false, can_favorite: true,
  serving_definitions: [
    {
      id: "default-serving",
      label: "Default serving",
      quantity: "1",
      unit: "serving",
      gram_weight: "100",
      is_default: true,
      source: "manual",
      is_user_confirmed: true,
    },
    {
      id: "selected-serving",
      label: "Selected serving",
      quantity: "1",
      unit: "serving",
      gram_weight: "150",
      is_default: false,
      source: "manual",
      is_user_confirmed: true,
    },
  ],
  nutrients: [],
};

function amount(id: string, quantity: string, isDefault = false): ResolvedFoodAmount {
  return {
    amount_definition_id: id,
    display_label: id === "default-serving" ? "Default serving" : "Selected serving",
    is_default: isDefault,
    entered_quantity: quantity,
    semantic_amount_mode: "serving",
    resolved_grams: "100",
    valid_for_logging: true,
    nutrients: [],
  };
}

const resolvedNutrition: FoodResolvedNutrition = {
  nutrition_authority: "food_item",
  recipe_id: null,
  recipe_publication_revision_id: null,
  amounts: [
    amount("default-serving", "1", true),
    amount("selected-serving", "2.5"),
  ],
};

function deferred(): Deferred {
  let resolve!: (value?: unknown) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<unknown>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  mockCreateDeferred = deferred();
  mockUpdateDeferred = deferred();
  mockCreateLog.mockClear();
  mockUpdateLog.mockClear();
  mockCreateClientRequestId.mockClear();
  mockRequestIds = [
    "00000000-0000-4000-8000-000000000001",
    "00000000-0000-4000-8000-000000000002",
    "00000000-0000-4000-8000-000000000003",
    "00000000-0000-4000-8000-000000000004",
  ];
  mockFoodQuery = {
    data: food,
    isLoading: false,
    isError: false,
    error: null,
  };
  mockResolvedQuery = {
    data: resolvedNutrition,
    isLoading: false,
    isFetching: false,
    isError: false,
    error: null,
  };
  mockEditContextQuery = {
    data: undefined,
    isLoading: false,
    isError: false,
    error: null,
  };
});

async function render(element: React.ReactElement): Promise<ReactTestRenderer> {
  let renderer: ReactTestRenderer | undefined;
  await act(async () => {
    renderer = TestRenderer.create(element);
  });
  return renderer as ReactTestRenderer;
}

function textContent(node: ReactTestInstance): string {
  return node.children
    .map((child) => (typeof child === "string" ? child : textContent(child)))
    .join("");
}

function pressableWithText(root: ReactTestInstance, label: string): ReactTestInstance {
  return root.findAllByType(Pressable).find((node) => textContent(node) === label) as ReactTestInstance;
}

function pressableStartingWithText(root: ReactTestInstance, label: string): ReactTestInstance {
  return root.findAllByType(Pressable).find((node) => textContent(node).startsWith(label)) as ReactTestInstance;
}

function hasText(root: ReactTestInstance, label: string): boolean {
  return root.findAllByType(Text).some((node) => textContent(node) === label);
}

function createScreen(onSaved = jest.fn(), initialAmount = {
  amountDefinitionId: "selected-serving",
  amountQuantity: "2.5",
  amountUnit: "serving" as const,
}, onCancel = jest.fn()) {
  return React.createElement(LogFoodScreen, {
    foodId: food.id,
    date: "2026-07-13",
    initialAmount,
    onCancel,
    onSaved,
  });
}

const revisionLog: DailyLog = {
  id: "log-1",
  food_item_id: food.id,
  food_name_snapshot: "Published Recipe",
  source_food_available: true,
  logged_date: "2026-07-13",
  amount_quantity: "7",
  amount_unit: "serving",
  serving_definition_id: "revision-amount-id",
};

const revisionContext: DailyLogEditContext = {
  log_id: revisionLog.id,
  source_food_available: true,
  is_revision_backed: true,
  recipe_publication_revision_id: "revision-1",
  selected_amount_definition_id: "revision-amount-id",
  amount_choices: [{
    amount_definition_id: "revision-amount-id",
    display_label: "Published serving",
    semantic_mode: "serving",
    display_quantity: "1",
    display_unit: "serving",
    gram_equivalent: "250",
    is_default: true,
    is_selected: true,
  }],
};

function editScreen(onSaved = jest.fn()) {
  mockEditContextQuery = { ...mockEditContextQuery, data: revisionContext };
  return React.createElement(LogFoodScreen, {
    foodId: food.id,
    date: revisionLog.logged_date,
    log: revisionLog,
    initialAmount: {
      amountDefinitionId: "create-only-id",
      amountQuantity: "99",
      amountUnit: "g" as const,
    },
    onCancel: jest.fn(),
    onSaved,
  });
}

test("create claims synchronously, disables submitted controls, and succeeds once", async () => {
  const onSaved = jest.fn();
  const renderer = await render(createScreen(onSaved));
  const save = pressableWithText(renderer.root, "Save Log");
  expect(save.props.accessibilityRole).toBe("button");
  expect(pressableWithText(renderer.root, "Cancel").props.accessibilityLabel).toBe("Cancel logging");
  expect(renderer.root.findByType(TextInput).props.accessibilityLabel).toBe("Amount quantity");
  expect(pressableWithText(renderer.root, "Servings").props.accessibilityState).toEqual({
    checked: true,
    disabled: false,
    selected: true,
  });
  expect(pressableStartingWithText(renderer.root, "Selected serving").props.accessibilityState).toEqual({
    checked: true,
    disabled: false,
    selected: true,
  });
  act(() => {
    void save.props.onPress();
    void save.props.onPress();
    void save.props.onPress();
  });

  expect(mockCreateLog).toHaveBeenCalledTimes(1);
  expect(mockCreateLog).toHaveBeenCalledWith(expect.objectContaining({
    client_request_id: "00000000-0000-4000-8000-000000000001",
    amount_quantity: "2.5",
    amount_unit: "serving",
    serving_definition_id: "selected-serving",
  }));
  const pendingSave = pressableWithText(renderer.root, "Saving...");
  expect(pendingSave.props.disabled).toBe(true);
  expect(pendingSave.props.accessibilityState).toEqual({ disabled: true, busy: true });
  expect(renderer.root.findByType(TextInput).props.editable).toBe(false);
  expect(pressableWithText(renderer.root, "Servings").props.disabled).toBe(true);
  expect(pressableWithText(renderer.root, "Grams").props.disabled).toBe(true);
  expect(pressableStartingWithText(renderer.root, "Selected serving").props.disabled).toBe(true);
  expect(pressableWithText(renderer.root, "Cancel").props.disabled).toBe(true);
  expect(hasText(
    renderer.root,
    "Could not save this log. Check your connection and try again.",
  )).toBe(false);

  await act(async () => {
    mockCreateDeferred.resolve();
    await mockCreateDeferred.promise;
  });
  expect(onSaved).toHaveBeenCalledTimes(1);
  expect(mockCreateLog).toHaveBeenCalledTimes(1);
  expect(mockCreateClientRequestId).toHaveBeenCalledTimes(1);
});

test("edit claims synchronously, preserves revision amount identity, and succeeds once", async () => {
  const onSaved = jest.fn();
  const renderer = await render(editScreen(onSaved));
  const save = pressableWithText(renderer.root, "Save Changes");
  expect(pressableWithText(renderer.root, "Cancel").props.accessibilityLabel).toBe("Cancel editing");
  act(() => {
    void save.props.onPress();
    void save.props.onPress();
  });

  expect(mockUpdateLog).toHaveBeenCalledTimes(1);
  expect(mockUpdateLog).toHaveBeenCalledWith({
    logId: revisionLog.id,
    input: expect.objectContaining({
      amount_quantity: "7",
      amount_unit: "serving",
      serving_definition_id: "revision-amount-id",
    }),
  });
  expect(mockUpdateLog.mock.calls[0][0].input).not.toHaveProperty("client_request_id");
  expect(mockCreateClientRequestId).not.toHaveBeenCalled();
  const pendingSave = pressableWithText(renderer.root, "Updating...");
  expect(pendingSave.props.accessibilityState).toEqual({ disabled: true, busy: true });
  expect(renderer.root.findByType(TextInput).props.editable).toBe(false);

  await act(async () => {
    mockUpdateDeferred.resolve();
    await mockUpdateDeferred.promise;
  });
  expect(onSaved).toHaveBeenCalledTimes(1);
  expect(mockUpdateLog).toHaveBeenCalledTimes(1);
});

test("failed create preserves form and warning dismissal, then permits one retry", async () => {
  const onSaved = jest.fn();
  const renderer = await render(createScreen(onSaved, {
    amountDefinitionId: "stale-serving",
    amountQuantity: "4",
    amountUnit: "serving",
  }));
  const warning = "That amount is no longer available. The current default was selected.";
  expect(hasText(renderer.root, warning)).toBe(true);
  await act(async () => renderer.root.findByProps({
    accessibilityLabel: "Dismiss amount notice",
  }).props.onPress());
  await act(async () => renderer.root.findByType(TextInput).props.onChangeText("6"));
  await act(async () => pressableStartingWithText(renderer.root, "Selected serving").props.onPress());

  act(() => {
    void pressableWithText(renderer.root, "Save Log").props.onPress();
  });
  await act(async () => {
    mockCreateDeferred.reject(new Error("network failed"));
    try {
      await mockCreateDeferred.promise;
    } catch {
      // The screen converts this rejection into its existing actionable error state.
    }
  });

  expect(renderer.root.findByType(TextInput).props.value).toBe("6");
  expect(renderer.root.findByType(TextInput).props.editable).toBe(true);
  expect(hasText(renderer.root, warning)).toBe(false);
  expect(hasText(
    renderer.root,
    "Could not save this log. Check your connection and try again.",
  )).toBe(true);
  const error = renderer.root.findAllByProps({ accessibilityRole: "alert" }).find(
    (node) => textContent(node) === "Could not save this log. Check your connection and try again.",
  ) as ReactTestInstance;
  expect(error.props.accessibilityLiveRegion).toBe("assertive");
  expect(pressableWithText(renderer.root, "Save Log").props.disabled).toBe(false);

  mockCreateDeferred = deferred();
  act(() => {
    const retry = pressableWithText(renderer.root, "Save Log");
    void retry.props.onPress();
    void retry.props.onPress();
  });
  expect(mockCreateLog).toHaveBeenCalledTimes(2);
  expect(mockCreateLog.mock.calls[0][0].client_request_id).toBe(
    mockCreateLog.mock.calls[1][0].client_request_id,
  );
  expect(mockCreateLog).toHaveBeenLastCalledWith(expect.objectContaining({
    amount_quantity: "6",
    serving_definition_id: "selected-serving",
  }));
  await act(async () => {
    mockCreateDeferred.resolve();
    await mockCreateDeferred.promise;
  });
  expect(onSaved).toHaveBeenCalledTimes(1);
});

test("failed edit restores controls and permits one retry without changing revision state", async () => {
  const onSaved = jest.fn();
  const renderer = await render(editScreen(onSaved));
  await act(async () => renderer.root.findByType(TextInput).props.onChangeText("8"));
  act(() => {
    void pressableWithText(renderer.root, "Save Changes").props.onPress();
  });
  await act(async () => {
    mockUpdateDeferred.reject(new Error("network failed"));
    try {
      await mockUpdateDeferred.promise;
    } catch {
      // The screen owns the displayed retry error.
    }
  });

  expect(renderer.root.findByType(TextInput).props.value).toBe("8");
  expect(renderer.root.findByType(TextInput).props.editable).toBe(true);
  expect(pressableStartingWithText(renderer.root, "Published serving").props.disabled).toBe(false);
  mockUpdateDeferred = deferred();
  act(() => {
    const retry = pressableWithText(renderer.root, "Save Changes");
    void retry.props.onPress();
    void retry.props.onPress();
  });
  expect(mockUpdateLog).toHaveBeenCalledTimes(2);
  expect(mockUpdateLog).toHaveBeenLastCalledWith({
    logId: revisionLog.id,
    input: expect.objectContaining({
      amount_quantity: "8",
      serving_definition_id: "revision-amount-id",
    }),
  });
  await act(async () => {
    mockUpdateDeferred.resolve();
    await mockUpdateDeferred.promise;
  });
  expect(onSaved).toHaveBeenCalledTimes(1);
});

test("late success after an external unmount cannot invoke a stale navigation callback", async () => {
  const onSaved = jest.fn();
  const renderer = await render(createScreen(onSaved));
  act(() => {
    void pressableWithText(renderer.root, "Save Log").props.onPress();
  });
  act(() => renderer.unmount());
  await act(async () => {
    mockCreateDeferred.resolve();
    await mockCreateDeferred.promise;
  });
  expect(onSaved).not.toHaveBeenCalled();
});

test("Cancel claims navigation before save, while pending Cancel is ignored", async () => {
  const beforeSaveCancel = jest.fn();
  const first = await render(createScreen(jest.fn(), undefined, beforeSaveCancel));
  const cancel = pressableWithText(first.root, "Cancel");
  const save = pressableWithText(first.root, "Save Log");
  act(() => {
    cancel.props.onPress();
    void save.props.onPress();
  });
  expect(beforeSaveCancel).toHaveBeenCalledTimes(1);
  expect(mockCreateLog).not.toHaveBeenCalled();
  act(() => first.unmount());

  const pendingCancel = jest.fn();
  const second = await render(createScreen(jest.fn(), undefined, pendingCancel));
  const pendingSave = pressableWithText(second.root, "Save Log");
  const staleCancelHandler = pressableWithText(second.root, "Cancel").props.onPress;
  act(() => {
    void pendingSave.props.onPress();
    staleCancelHandler();
  });
  expect(mockCreateLog).toHaveBeenCalledTimes(1);
  expect(pendingCancel).not.toHaveBeenCalled();
  expect(pressableWithText(second.root, "Cancel").props.disabled).toBe(true);
});

test("a fresh screen after failure starts unlocked", async () => {
  const first = await render(createScreen());
  act(() => {
    void pressableWithText(first.root, "Save Log").props.onPress();
  });
  await act(async () => {
    mockCreateDeferred.reject(new Error("network failed"));
    try {
      await mockCreateDeferred.promise;
    } catch {
      // Expected failure before remount.
    }
  });
  act(() => first.unmount());

  mockCreateDeferred = deferred();
  const reopened = await render(createScreen());
  expect(pressableWithText(reopened.root, "Save Log").props.disabled).toBe(false);
  expect(reopened.root.findByType(TextInput).props.editable).toBe(true);
  act(() => {
    void pressableWithText(reopened.root, "Save Log").props.onPress();
  });
  expect(mockCreateLog).toHaveBeenCalledTimes(2);
  expect(mockCreateLog.mock.calls[0][0].client_request_id).not.toBe(
    mockCreateLog.mock.calls[1][0].client_request_id,
  );
});

test.each(["amount", "serving", "unit"] as const)(
  "changing %s after a failed create starts a new request intent",
  async (change) => {
    const renderer = await render(createScreen());
    act(() => {
      void pressableWithText(renderer.root, "Save Log").props.onPress();
    });
    await act(async () => {
      mockCreateDeferred.reject(new Error("network failed"));
      try {
        await mockCreateDeferred.promise;
      } catch {
        // The failed intent remains available only while its payload is unchanged.
      }
    });

    if (change === "amount") {
      await act(async () => renderer.root.findByType(TextInput).props.onChangeText("4"));
    } else if (change === "serving") {
      await act(async () => pressableStartingWithText(
        renderer.root,
        "Default serving",
      ).props.onPress());
    } else {
      await act(async () => pressableWithText(renderer.root, "Grams").props.onPress());
    }
    mockCreateDeferred = deferred();
    act(() => {
      void pressableWithText(renderer.root, "Save Log").props.onPress();
    });

    expect(mockCreateLog).toHaveBeenCalledTimes(2);
    expect(mockCreateLog.mock.calls[0][0].client_request_id).toBe(
      "00000000-0000-4000-8000-000000000001",
    );
    expect(mockCreateLog.mock.calls[1][0].client_request_id).toBe(
      "00000000-0000-4000-8000-000000000002",
    );
  },
);

test("a successful log followed by a fresh screen uses a new request ID", async () => {
  const first = await render(createScreen());
  act(() => {
    void pressableWithText(first.root, "Save Log").props.onPress();
  });
  await act(async () => {
    mockCreateDeferred.resolve();
    await mockCreateDeferred.promise;
  });
  act(() => first.unmount());

  mockCreateDeferred = deferred();
  const second = await render(createScreen());
  act(() => {
    void pressableWithText(second.root, "Save Log").props.onPress();
  });
  expect(mockCreateLog.mock.calls[0][0].client_request_id).not.toBe(
    mockCreateLog.mock.calls[1][0].client_request_id,
  );
});
