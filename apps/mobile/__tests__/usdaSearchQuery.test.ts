import { normalizeUsdaSearchQuery } from "../src/features/usda/utils/usdaSearchQuery";

test.each([
  ["ground beef 80/20", "ground beef 80% lean 20% fat"],
  ["80/20 ground beef", "80% lean 20% fat ground beef"],
  ["fresh ground beef 80/20 raw", "fresh ground beef 80% lean 20% fat raw"],
  ["ground beef 85/15", "ground beef 85% lean 15% fat"],
  ["ground beef 90/10", "ground beef 90% lean 10% fat"],
  ["ground beef 93/7", "ground beef 93% lean 7% fat"],
  ["ground beef 95/5", "ground beef 95% lean 5% fat"],
  ["ground beef 97/3", "ground beef 97% lean 3% fat"],
])("normalizes USDA lean/fat ratio query %s", (input, expected) => {
  expect(normalizeUsdaSearchQuery(input)).toBe(expected);
});

test.each([
  "ground beef",
  "1/2 cup milk",
  "80/10 ground beef",
  "120/20 ground beef",
  "80/ ground beef",
  "/20 ground beef",
  "80//20 ground beef",
  "vitamin b6/b12",
])("leaves non-lean/fat USDA query unchanged: %s", (input) => {
  expect(normalizeUsdaSearchQuery(input)).toBe(input);
});

test("normalization is deterministic and does not mutate the displayed input value", () => {
  const displayedQuery = "ground beef 80/20";
  const outboundQuery = normalizeUsdaSearchQuery(displayedQuery);

  expect(displayedQuery).toBe("ground beef 80/20");
  expect(outboundQuery).toBe("ground beef 80% lean 20% fat");
});
