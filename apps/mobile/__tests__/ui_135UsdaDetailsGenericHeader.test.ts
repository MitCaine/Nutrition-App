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

let mockPreview:
  Record<string, unknown>;

let mockImporter:
  Record<string, unknown>;

const LONG_USDA_NAME =
  "A deliberately very long USDA food description that must remain ordinary scrolling entity content instead of expanding the fixed route header";

const importedFood = {
  id: "imported-usda-food",
} as unknown as Food;

jest.mock(
  "../src/features/usda/hooks/useUsda",
  () => ({
    useUsdaPreview: () =>
      mockPreview,
    useUsdaImport: () =>
      mockImporter,
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
  UsdaPreviewScreen,
} from "../src/features/usda/screens/UsdaPreviewScreen";

function readyPreview() {
  return {
    data: {
      name: LONG_USDA_NAME,
      data_type: "Branded",
      brand: "Example Foods",
      food_category: "Prepared Foods",
      serving_definitions: [
        {
          candidate_id:
            "serving-one",
          label:
            "1 container",
          gram_weight:
            "250",
        },
      ],
      nutrients: [],
      diagnostics: [
        "Example import diagnostic",
      ],
    },
    isLoading: false,
    isError: false,
    refetch: jest.fn(),
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

function headerText(
  root:
    TestRenderer.ReactTestInstance,
): string {
  const header =
    root.findByProps({
      testID:
        "route-screen-header",
    });

  return header
    .findAllByType(
      Text,
    )
    .map(
      textContent,
    )
    .join(" ");
}

function pressableByLabel(
  root:
    TestRenderer.ReactTestInstance,
  accessibilityLabel:
    string,
): TestRenderer.ReactTestInstance {
  const matches =
    root
      .findAllByType(
        Pressable,
      )
      .filter(
        (node) =>
          node.props
            .accessibilityLabel
          === accessibilityLabel,
      );

  if (matches.length !== 1) {
    throw new Error(
      `Expected one Pressable labelled "${accessibilityLabel}", found ${matches.length}.`,
    );
  }

  return matches[0];
}

beforeEach(() => {
  mockPreview =
    readyPreview();

  mockImporter = {
    isPending: false,
    isError: false,
    mutate: jest.fn(),
  };
});

test(
  "loading USDA Food Details uses the stable route title",
  async () => {
    mockPreview = {
      data: undefined,
      isLoading: true,
      isError: false,
      refetch: jest.fn(),
    };

    let renderer!:
      TestRenderer.ReactTestRenderer;

    await act(
      async () => {
        renderer =
          TestRenderer.create(
            React.createElement(
              UsdaPreviewScreen,
              {
                fdcId: 555000,
                onBack:
                  jest.fn(),
                onImported:
                  jest.fn(),
              },
            ),
          );
      },
    );

    expect(
      headerText(
        renderer.root,
      ),
    ).toContain(
      "USDA food details",
    );

    await act(
      async () =>
        renderer.unmount(),
    );
  },
);

test(
  "error USDA Food Details retains the same stable route title",
  async () => {
    mockPreview = {
      data: undefined,
      isLoading: false,
      isError: true,
      error:
        new Error(
          "Preview unavailable",
        ),
      refetch: jest.fn(),
    };

    let renderer!:
      TestRenderer.ReactTestRenderer;

    await act(
      async () => {
        renderer =
          TestRenderer.create(
            React.createElement(
              UsdaPreviewScreen,
              {
                fdcId: 555000,
                onBack:
                  jest.fn(),
                onImported:
                  jest.fn(),
              },
            ),
          );
      },
    );

    expect(
      headerText(
        renderer.root,
      ),
    ).toContain(
      "USDA food details",
    );

    await act(
      async () =>
        renderer.unmount(),
    );
  },
);

test(
  "ready USDA Food Details keeps stable chrome while complete entity identity and details scroll",
  async () => {
    let renderer!:
      TestRenderer.ReactTestRenderer;

    await act(
      async () => {
        renderer =
          TestRenderer.create(
            React.createElement(
              UsdaPreviewScreen,
              {
                fdcId: 555000,
                onBack:
                  jest.fn(),
                onImported:
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
      headerText(
        renderer.root,
      ),
    ).toContain(
      "USDA food details",
    );

    expect(
      header
        .findAllByType(
          Text,
        )
        .map(
          textContent,
        ),
    ).not.toContain(
      LONG_USDA_NAME,
    );

    const scroll =
      renderer.root.findByProps({
        testID:
          "usda-preview-scroll",
      });

    expect(
      scroll.type,
    ).toBe(
      ScrollView,
    );

    const name =
      scroll.findByProps({
        testID:
          "usda-preview-name",
      });

    expect(
      name.props
        .accessibilityRole,
    ).toBe(
      "header",
    );

    expect(
      textContent(
        name,
      ),
    ).toBe(
      LONG_USDA_NAME,
    );

    expect(
      name.props
        .numberOfLines,
    ).toBeUndefined();

    expect(
      name.props
        .ellipsizeMode,
    ).toBeUndefined();

    const bodyText =
      scroll
        .findAllByType(
          Text,
        )
        .map(
          textContent,
        )
        .join(" ");

    expect(
      bodyText,
    ).toContain(
      "USDA Branded - Example Foods",
    );

    expect(
      bodyText,
    ).toContain(
      "Prepared Foods",
    );

    expect(
      bodyText,
    ).toContain(
      "Servings",
    );

    expect(
      bodyText,
    ).toContain(
      "Nutrients per 100 g",
    );

    expect(
      bodyText,
    ).toContain(
      "Import Notes",
    );

    expect(
      bodyText,
    ).toContain(
      "Example import diagnostic",
    );

    expect(
      pressableByLabel(
        scroll,
        `Import ${LONG_USDA_NAME}`,
      ),
    ).toBeDefined();

    await act(
      async () =>
        renderer.unmount(),
    );
  },
);

test(
  "pending import preserves fixed Back blocking and body Import busy state",
  async () => {
    mockImporter = {
      isPending: true,
      isError: false,
      mutate: jest.fn(),
    };

    let renderer!:
      TestRenderer.ReactTestRenderer;

    await act(
      async () => {
        renderer =
          TestRenderer.create(
            React.createElement(
              UsdaPreviewScreen,
              {
                fdcId: 555000,
                onBack:
                  jest.fn(),
                onImported:
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

    const back =
      pressableByLabel(
        header,
        "Back from USDA food details",
      );

    expect(
      back.props
        .accessibilityState,
    ).toMatchObject({
      busy: true,
      disabled: true,
    });

    expect(
      back.props.onPress,
    ).toBeUndefined();

    const scroll =
      renderer.root.findByProps({
        testID:
          "usda-preview-scroll",
      });

    const importing =
      pressableByLabel(
        scroll,
        `Importing ${LONG_USDA_NAME}`,
      );

    expect(
      importing.props
        .accessibilityState,
    ).toMatchObject({
      busy: true,
      disabled: true,
    });

    expect(
      importing.props.onPress,
    ).toBeUndefined();

    await act(
      async () =>
        renderer.unmount(),
    );
  },
);

test(
  "Import Food preserves fdcId mutation identity and success handoff",
  async () => {
    const onImported =
      jest.fn();

    const mutate =
      jest.fn(
        (
          fdcId: number,
          options: {
            onSuccess:
              (food: Food) => void;
          },
        ) => {
          options.onSuccess(
            importedFood,
          );
        },
      );

    mockImporter = {
      isPending: false,
      isError: false,
      mutate,
    };

    let renderer!:
      TestRenderer.ReactTestRenderer;

    await act(
      async () => {
        renderer =
          TestRenderer.create(
            React.createElement(
              UsdaPreviewScreen,
              {
                fdcId: 555000,
                onBack:
                  jest.fn(),
                onImported,
              },
            ),
          );
      },
    );

    const scroll =
      renderer.root.findByProps({
        testID:
          "usda-preview-scroll",
      });

    await act(
      async () => {
        pressableByLabel(
          scroll,
          `Import ${LONG_USDA_NAME}`,
        ).props.onPress();
      },
    );

    expect(
      mutate,
    ).toHaveBeenCalledTimes(
      1,
    );

    expect(
      mutate.mock.calls[0][0],
    ).toBe(
      555000,
    );

    expect(
      onImported,
    ).toHaveBeenCalledWith(
      importedFood,
    );

    await act(
      async () =>
        renderer.unmount(),
    );
  },
);
