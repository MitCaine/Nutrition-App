const GENERATED_COPY_SUFFIX = /^(.+) Copy(?: ([1-9][0-9]*))?$/u;
const MAX_GENERATED_ORDINAL = Number.MAX_SAFE_INTEGER - 1;

export function allocateDuplicateFoodName(
  sourceName: string,
  activeNames: readonly string[],
  sourceIsDuplicate: boolean,
): string {
  let baseName = sourceName;
  let startingOrdinal = 1;

  if (sourceIsDuplicate) {
    const match = GENERATED_COPY_SUFFIX.exec(sourceName);
    if (match) {
      const parsed = Number.parseInt(match[2] ?? "1", 10);
      if (Number.isSafeInteger(parsed) && parsed >= 1 && parsed <= MAX_GENERATED_ORDINAL) {
        baseName = match[1]!;
        startingOrdinal = parsed + 1;
      }
    }
  }

  const usedNames = new Set(activeNames);
  for (let ordinal = startingOrdinal; ordinal <= Number.MAX_SAFE_INTEGER; ordinal += 1) {
    const candidate = ordinal === 1 ? `${baseName} Copy` : `${baseName} Copy ${ordinal}`;
    if (!usedNames.has(candidate)) return candidate;
  }

  throw new Error("Duplicate Food name suffix exhausted the supported range.");
}
