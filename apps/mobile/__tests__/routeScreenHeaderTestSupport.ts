import {
  ScrollView,
  Text,
} from "react-native";
import type {
  ReactTestInstance,
} from "react-test-renderer";

function textContent(
  node: ReactTestInstance | string,
): string {
  return typeof node === "string"
    ? node
    : node.children
        .map((child) =>
          textContent(
            child as ReactTestInstance | string,
          ),
        )
        .join("");
}

export function expectFixedRouteHeader(
  root: ReactTestInstance,
  routeTitle: string,
): ReactTestInstance {
  const header = root.findByProps({
    testID: "route-screen-header",
  });

  const scrolls = root.findAllByType(
    ScrollView,
  );

  expect(scrolls.length).toBeGreaterThan(0);

  for (const scroll of scrolls) {
    expect(
      scroll.findAllByProps({
        testID: "route-screen-header",
      }),
    ).toHaveLength(0);
  }

  const routeHeadings = root
    .findAllByType(Text)
    .filter(
      (node) =>
        node.props.accessibilityRole === "header"
        && textContent(node) === routeTitle,
    );

  expect(routeHeadings).toHaveLength(1);
  expect(
    routeHeadings[0].props
      .maxFontSizeMultiplier,
  ).toBe(1.5);

  return header;
}
