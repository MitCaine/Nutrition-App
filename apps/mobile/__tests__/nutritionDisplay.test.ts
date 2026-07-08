import { formatAggregatedTotal } from "../src/shared/nutrition/display";

test("formats unknown contributors separately from known amount", () => {
  expect(
    formatAggregatedTotal({
      nutrientId: "sodium",
      amountKnown: "100",
      amountEstimated: "25",
      unit: "mg",
      hasUnknownContributors: true,
      unknownContributorCount: 2,
    }),
  ).toBe("100mg + 25 estimated + unknown from 2 items");
});
