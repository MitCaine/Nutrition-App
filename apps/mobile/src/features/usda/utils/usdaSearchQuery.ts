const LEAN_FAT_RATIO = /\b(\d{1,3})\/(\d{1,3})\b/g;

export function normalizeUsdaSearchQuery(query: string): string {
  return query.replace(LEAN_FAT_RATIO, (match, leanText: string, fatText: string) => {
    const lean = Number(leanText);
    const fat = Number(fatText);
    if (!isPlausibleLeanFatRatio(lean, fat)) {
      return match;
    }
    return `${lean}% lean ${fat}% fat`;
  });
}

function isPlausibleLeanFatRatio(lean: number, fat: number): boolean {
  return (
    Number.isInteger(lean) &&
    Number.isInteger(fat) &&
    lean > 0 &&
    fat > 0 &&
    lean >= 1 &&
    lean <= 99 &&
    fat >= 1 &&
    fat <= 99 &&
    lean + fat === 100
  );
}
