const UNSIGNED_DECIMAL = /^\d+(?:\.\d+)?$/;

export function isUnsignedDecimalString(value: string): boolean {
  return value.length > 0 && value === value.trim() && UNSIGNED_DECIMAL.test(value);
}

export function isZeroDecimalString(value: string): boolean {
  return isUnsignedDecimalString(value) && /^0+(?:\.0+)?$/.test(value);
}

export function isPositiveDecimalString(value: string): boolean {
  return isUnsignedDecimalString(value) && !isZeroDecimalString(value);
}

function compareUnsignedDecimalStrings(left: string, right: string): number {
  const parts = (value: string) => {
    const [integer, fraction = ""] = value.split(".");
    return { integer: integer.replace(/^0+(?=\d)/, ""), fraction: fraction.replace(/0+$/, "") };
  };
  const first = parts(left); const second = parts(right);
  if (first.integer.length !== second.integer.length) return first.integer.length < second.integer.length ? -1 : 1;
  if (first.integer !== second.integer) return first.integer < second.integer ? -1 : 1;
  const length = Math.max(first.fraction.length, second.fraction.length);
  const firstFraction = first.fraction.padEnd(length, "0"); const secondFraction = second.fraction.padEnd(length, "0");
  return firstFraction === secondFraction ? 0 : firstFraction < secondFraction ? -1 : 1;
}

export function isDecimalStringWithin(value: string, minimum: string, maximum: string): boolean {
  return isUnsignedDecimalString(value) && compareUnsignedDecimalStrings(value, minimum) >= 0 && compareUnsignedDecimalStrings(value, maximum) <= 0;
}
