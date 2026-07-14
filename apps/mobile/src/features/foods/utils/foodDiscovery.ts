import type { Food, RecentFood } from "../api/types";

export function foodAccessibilityLabel(food: Food): string {
  return `${food.name}, ${food.source_label}${food.is_favorite ? ", favorite" : ""}`;
}

export function formatRecentUse(timestamp: string, now = new Date()): string {
  const used = new Date(timestamp);
  if (!Number.isFinite(used.getTime())) return "Recently used";
  if (
    used.getFullYear() === now.getFullYear()
    && used.getMonth() === now.getMonth()
    && used.getDate() === now.getDate()
  ) return "Used today";
  return `Used ${used.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    ...(used.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  })}`;
}

export function visibleDiscoveryRows<T>(items: T[] | undefined, limit = 5): T[] {
  return (items ?? []).slice(0, limit);
}

export function recentFoodsInOrder(items: RecentFood[] | undefined): RecentFood[] {
  return visibleDiscoveryRows(items);
}
