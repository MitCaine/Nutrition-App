import { usdaSearchMessage } from "../src/features/usda/utils/usdaDisplay";

test("USDA search directs an unconfigured local credential to Settings", () => {
  expect(usdaSearchMessage({
    query: "banana",
    isLoading: false,
    isError: true,
    errorCode: "usda_credentials_unconfigured",
  })).toBe("USDA search needs a personal API key. Add it in Settings and try again.");
});
