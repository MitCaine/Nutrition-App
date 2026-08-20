import React from "react";
import {
  Pressable,
  ScrollView,
  Text,
} from "react-native";
import TestRenderer, {
  act,
} from "react-test-renderer";

import type {
  Food,
} from "../src/features/foods/api/types";
import type {
  Recipe,
} from "../src/features/recipes/api/types";

const LONG_RECIPE_NAME =
  "A deliberately very long Recipe name that belongs in scrolling content instead of expanding fixed route chrome";

const mockPublishRecipe =
  jest.fn();

const mockDeleteRecipe =
  jest.fn();

let mockPublishPending = false;
let mockPublishError:
  unknown = null;

jest.mock(
  "../src/features/recipes/hooks/useRecipes",
  () => ({
    useRecipeNutrition: () => ({
      data: {
        totals: [],
        perServing: [],
        per100g: [],
      },
      isError: false,
      error: null,
      refetch: jest.fn(),
    }),
    useRecipeMutations: () => ({
      publishRecipe: {
        isPending:
          mockPublishPending,
        isError:
          mockPublishError !== null,
        error:
          mockPublishError,
        mutateAsync:
          mockPublishRecipe,
      },
      deleteRecipe: {
        isPending: false,
        mutateAsync:
          mockDeleteRecipe,
      },
    }),
  }),
);

jest.mock(
  "../src/features/logging/utils/clientRequestId",
  () => ({
    createClientRequestId: () =>
      "ui-134-request",
  }),
);

jest.mock(
  "@expo/vector-icons",
  () => ({
    Ionicons: "Ionicons",
  }),
);

jest.mock(
  "../src/app/theme/AppTheme",
  () => {
    const actual =
      jest.requireActual(
        "../src/app/theme/AppTheme",
      );

    return {
      ...actual,
      useAppTheme: () => ({
        ...actual.LIGHT_THEME,
        preference: "system",
        effectiveScheme: "light",
        setPreference:
          jest.fn(),
      }),
    };
  },
);

import {
  RecipeDetailScreen,
} from "../src/features/recipes/screens/RecipeDetailScreen";

const publishedFood: Food = {
  id: "published-food",
  name: "Published Recipe Food",
  brand: null,
  notes: null,
  source_type: "recipe",
  source_id: "recipe-ui-134",
  is_recipe: true,
  source_kind: "recipe",
  source_label: "Recipe",
  is_favorite: false,
  can_favorite: false,
  serving_definitions: [],
  nutrients: [],
};

function recipe(
  overrides:
    Partial<Recipe> = {},
): Recipe {
  return {
    id: "recipe-ui-134",
    user_id: "user-1",
    published_food_item_id:
      null,
    name: LONG_RECIPE_NAME,
    notes: "Recipe notes",
    serving_count_yield: "4",
    final_cooked_weight_grams:
      null,
    final_cooked_weight_display_quantity:
      null,
    final_cooked_weight_display_unit:
      null,
    needs_republish: false,
    created_at:
      "2026-08-19T00:00:00Z",
    updated_at:
      "2026-08-19T00:00:00Z",
    ingredients: [],
    ...overrides,
  };
}

function textContent(
  node:
    TestRenderer.ReactTestInstance
    | string,
): string {
  return typeof node === "string"
    ? node
    : node.children
        .map(
          (child) =>
            textContent(
              child as
                TestRenderer.ReactTestInstance
                | string,
            ),
        )
        .join("");
}

function allText(
  root:
    TestRenderer.ReactTestInstance,
): string[] {
  return root
    .findAllByType(
      Text,
    )
    .map(
      textContent,
    );
}

function pressablesByLabel(
  root:
    TestRenderer.ReactTestInstance,
  accessibilityLabel:
    string,
): TestRenderer.ReactTestInstance[] {
  return root
    .findAllByType(
      Pressable,
    )
    .filter(
      (node) =>
        node.props
          .accessibilityLabel
        === accessibilityLabel,
    );
}

function pressableByLabel(
  root:
    TestRenderer.ReactTestInstance,
  accessibilityLabel:
    string,
): TestRenderer.ReactTestInstance {
  const matches =
    pressablesByLabel(
      root,
      accessibilityLabel,
    );

  if (matches.length !== 1) {
    throw new Error(
      `Expected one Pressable labelled "${accessibilityLabel}", found ${matches.length}.`,
    );
  }

  return matches[0];
}

beforeEach(() => {
  mockPublishPending = false;
  mockPublishError = null;
  mockPublishRecipe.mockReset();
  mockDeleteRecipe.mockReset();
});

test(
  "unpublished Recipe keeps generic route identity and Publish/Edit fixed while the full name scrolls",
  async () => {
    const currentRecipe =
      recipe();

    const onOpenFood =
      jest.fn();

    mockPublishRecipe.mockResolvedValue({
      recipe: currentRecipe,
      food: publishedFood,
    });

    let renderer!:
      TestRenderer.ReactTestRenderer;

    await act(
      async () => {
        renderer =
          TestRenderer.create(
            React.createElement(
              RecipeDetailScreen,
              {
                recipe:
                  currentRecipe,
                onBack:
                  jest.fn(),
                onEdit:
                  jest.fn(),
                onOpenFood,
                onLogFood:
                  jest.fn(),
                onDeleted:
                  jest.fn(),
              },
            ),
          );
      },
    );

    const header =
      renderer.root.findByProps({
        testID:
          "route-screen-header",
      });

    expect(
      allText(
        header,
      ),
    ).toContain(
      "Recipe",
    );

    expect(
      allText(
        header,
      ),
    ).not.toContain(
      LONG_RECIPE_NAME,
    );

    expect(
      pressablesByLabel(
        header,
        "Back from Recipe details",
      ),
    ).toHaveLength(
      1,
    );

    const publish =
      pressableByLabel(
        header,
        "Publish Recipe as food",
      );

    expect(
      textContent(
        publish,
      ),
    ).toBe(
      "Publish",
    );

    expect(
      publish.props
        .accessibilityState,
    ).toMatchObject({
      busy: false,
      disabled: false,
    });

    expect(
      pressablesByLabel(
        header,
        "Edit Recipe",
      ),
    ).toHaveLength(
      1,
    );

    const scroll =
      renderer.root.findByProps({
        testID:
          "recipe-detail-scroll",
      });

    expect(
      scroll.type,
    ).toBe(
      ScrollView,
    );

    const name =
      scroll.findByProps({
        testID:
          "recipe-detail-name",
      });

    expect(
      textContent(
        name,
      ),
    ).toBe(
      LONG_RECIPE_NAME,
    );

    expect(
      name.props.numberOfLines,
    ).toBeUndefined();

    expect(
      name.props.ellipsizeMode,
    ).toBeUndefined();

    expect(
      pressablesByLabel(
        scroll,
        "Publish Recipe as food",
      ),
    ).toHaveLength(
      0,
    );

    expect(
      pressablesByLabel(
        scroll,
        "Delete Recipe",
      ),
    ).toHaveLength(
      1,
    );

    await act(
      async () => {
        await publish.props.onPress();
      },
    );

    expect(
      mockPublishRecipe,
    ).toHaveBeenCalledTimes(
      1,
    );

    expect(
      mockPublishRecipe,
    ).toHaveBeenCalledWith({
      recipeId:
        "recipe-ui-134",
      clientRequestId:
        "ui-134-request",
    });

    expect(
      onOpenFood,
    ).toHaveBeenCalledWith(
      "published-food",
    );

    await act(
      async () =>
        renderer.unmount(),
    );
  },
);

test(
  "published Recipe exposes Republish in fixed chrome while published follow-up actions remain scrollable",
  async () => {
    const currentRecipe =
      recipe({
        published_food_item_id:
          "published-food",
        needs_republish: true,
      });

    const onOpenFood =
      jest.fn();

    const onLogFood =
      jest.fn();

    let renderer!:
      TestRenderer.ReactTestRenderer;

    await act(
      async () => {
        renderer =
          TestRenderer.create(
            React.createElement(
              RecipeDetailScreen,
              {
                recipe:
                  currentRecipe,
                onBack:
                  jest.fn(),
                onEdit:
                  jest.fn(),
                onOpenFood,
                onLogFood,
                onDeleted:
                  jest.fn(),
              },
            ),
          );
      },
    );

    const header =
      renderer.root.findByProps({
        testID:
          "route-screen-header",
      });

    const republish =
      pressableByLabel(
        header,
        "Republish Recipe food",
      );

    expect(
      textContent(
        republish,
      ),
    ).toBe(
      "Republish",
    );

    const scroll =
      renderer.root.findByProps({
        testID:
          "recipe-detail-scroll",
      });

    expect(
      pressablesByLabel(
        scroll,
        "Republish Recipe food",
      ),
    ).toHaveLength(
      0,
    );

    expect(
      pressablesByLabel(
        scroll,
        "View published Recipe food",
      ),
    ).toHaveLength(
      1,
    );

    expect(
      pressablesByLabel(
        scroll,
        "Log Recipe",
      ),
    ).toHaveLength(
      1,
    );

    expect(
      pressablesByLabel(
        scroll,
        "Delete Recipe",
      ),
    ).toHaveLength(
      1,
    );

    await act(
      async () => {
        pressableByLabel(
          scroll,
          "View published Recipe food",
        ).props.onPress();
      },
    );

    expect(
      onOpenFood,
    ).toHaveBeenCalledWith(
      "published-food",
    );

    await act(
      async () => {
        pressableByLabel(
          scroll,
          "Log Recipe",
        ).props.onPress();
      },
    );

    expect(
      onLogFood,
    ).toHaveBeenCalledWith(
      "published-food",
    );

    await act(
      async () =>
        renderer.unmount(),
    );
  },
);

test(
  "existing publication eligibility and Edit blocking remain authoritative in header actions",
  async () => {
    const currentRecipe =
      recipe({
        serving_count_yield:
          null,
        final_cooked_weight_grams:
          null,
      });

    let renderer!:
      TestRenderer.ReactTestRenderer;

    await act(
      async () => {
        renderer =
          TestRenderer.create(
            React.createElement(
              RecipeDetailScreen,
              {
                recipe:
                  currentRecipe,
                onBack:
                  jest.fn(),
                onEdit:
                  jest.fn(),
                onOpenFood:
                  jest.fn(),
                onLogFood:
                  jest.fn(),
                onDeleted:
                  jest.fn(),
                editBlockedMessage:
                  "Editing is blocked.",
              },
            ),
          );
      },
    );

    const header =
      renderer.root.findByProps({
        testID:
          "route-screen-header",
      });

    const publish =
      pressableByLabel(
        header,
        "Publish Recipe as food",
      );

    expect(
      publish.props
        .accessibilityState,
    ).toMatchObject({
      disabled: true,
    });

    expect(
      publish.props.onPress,
    ).toBeUndefined();

    const edit =
      pressableByLabel(
        header,
        "Edit Recipe",
      );

    expect(
      edit.props
        .accessibilityState,
    ).toMatchObject({
      disabled: true,
    });

    expect(
      edit.props.onPress,
    ).toBeUndefined();

    expect(
      allText(
        renderer.root,
      ),
    ).toContain(
      "Add portions or finished weight before publishing.",
    );

    expect(
      allText(
        renderer.root,
      ),
    ).toContain(
      "Editing is blocked.",
    );

    await act(
      async () =>
        renderer.unmount(),
    );
  },
);

test(
  "pending publication remains busy and disabled in fixed chrome",
  async () => {
    mockPublishPending = true;

    let renderer!:
      TestRenderer.ReactTestRenderer;

    await act(
      async () => {
        renderer =
          TestRenderer.create(
            React.createElement(
              RecipeDetailScreen,
              {
                recipe:
                  recipe(),
                onBack:
                  jest.fn(),
                onEdit:
                  jest.fn(),
                onOpenFood:
                  jest.fn(),
                onLogFood:
                  jest.fn(),
                onDeleted:
                  jest.fn(),
              },
            ),
          );
      },
    );

    const publish =
      pressableByLabel(
        renderer.root.findByProps({
          testID:
            "route-screen-header",
        }),
        "Publish Recipe as food",
      );

    expect(
      publish.props
        .accessibilityState,
    ).toMatchObject({
      busy: true,
      disabled: true,
    });

    expect(
      publish.props.onPress,
    ).toBeUndefined();

    await act(
      async () =>
        renderer.unmount(),
    );
  },
);
