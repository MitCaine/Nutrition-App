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
