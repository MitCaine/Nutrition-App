export const USDA_MIN_QUERY_LENGTH = 2;

export type UnifiedFoodSearchSections = {
  showSavedHeading: boolean;
  showUsdaSection: boolean;
  showNoFoodsFound: boolean;
};

export function isCurrentSearchQuery(inputQuery: string, searchQuery: string): boolean {
  return inputQuery.trim() === searchQuery;
}

export function restoredSearchOffset(
  inputQuery: string,
  session: { query: string; offset: number },
): number {
  return session.query === inputQuery ? session.offset : 0;
}

export function unifiedFoodSearchSections({
  query,
  savedCount,
  usdaCount,
  savedLoading,
  usdaLoading,
  savedError,
  usdaError,
  isCurrent = true,
}: {
  query: string;
  savedCount: number;
  usdaCount: number;
  savedLoading: boolean;
  usdaLoading: boolean;
  savedError: boolean;
  usdaError: boolean;
  isCurrent?: boolean;
}): UnifiedFoodSearchSections {
  const trimmed = query.trim();
  if (!isCurrent) {
    return {
      showSavedHeading: false,
      showUsdaSection: false,
      showNoFoodsFound: false,
    };
  }
  const showUsdaSection = trimmed.length >= USDA_MIN_QUERY_LENGTH;
  return {
    showSavedHeading: trimmed.length > 0 && savedCount > 0,
    showUsdaSection,
    showNoFoodsFound:
      trimmed.length > 0 &&
      savedCount === 0 &&
      (!showUsdaSection || usdaCount === 0) &&
      !savedLoading &&
      !usdaLoading &&
      !savedError &&
      !usdaError,
  };
}
