import { formatServingFormNumber, servingPayloadNumber } from "../src/features/foods/hooks/useFoodForm";

test("serving form trims raw decimals for initial display", () => {
  expect(formatServingFormNumber("100.000000")).toBe("100");
  expect(formatServingFormNumber("85.000000")).toBe("85");
  expect(formatServingFormNumber("1.250000")).toBe("1.25");
  expect(formatServingFormNumber(null)).toBe("");
});

test("serving form preserves original precision for unchanged values", () => {
  expect(servingPayloadNumber("100", "100.000000")).toBe("100.000000");
  expect(servingPayloadNumber("85", "85.000000")).toBe("85.000000");
  expect(servingPayloadNumber("86", "85.000000")).toBe("86");
});
