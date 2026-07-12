import { useEffect, useState } from "react";

export const SEARCH_DEBOUNCE_MS = 300;

export function effectiveSearchQuery(inputQuery: string, debouncedQuery: string): string {
  return inputQuery.trim() ? debouncedQuery : "";
}

export function scheduleDebouncedSearch(
  query: string,
  commit: (query: string) => void,
  delay = SEARCH_DEBOUNCE_MS,
): () => void {
  const timeout = setTimeout(() => commit(query), delay);
  return () => clearTimeout(timeout);
}

export function useDebouncedSearchQuery(inputQuery: string, delay = SEARCH_DEBOUNCE_MS): string {
  const trimmed = inputQuery.trim();
  const [debouncedQuery, setDebouncedQuery] = useState(trimmed);

  useEffect(() => {
    if (!trimmed) {
      setDebouncedQuery("");
      return;
    }
    return scheduleDebouncedSearch(trimmed, setDebouncedQuery, delay);
  }, [delay, trimmed]);

  return effectiveSearchQuery(inputQuery, debouncedQuery);
}
