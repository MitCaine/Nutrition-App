export type ServingFocusField = "label" | "quantity" | "unit" | "gramWeight";

export function foodFocusKey(field: "name" | "brand" | "notes"): string {
  return `food:${field}`;
}

export function servingFocusKey(servingKey: string, field: ServingFocusField): string {
  return `serving:${servingKey}:${field}`;
}

export function nutrientFocusKey(nutrientId: string): string {
  return `nutrient:${nutrientId}:amount`;
}

export function recipeFocusKey(field: "name" | "notes"): string {
  return `recipe:${field}`;
}

export function createFocusTargetRegistry<T>() {
  const targets = new Map<string, T>();
  return {
    assign(key: string, target: T | null): boolean {
      const overwritten = target !== null && targets.has(key) && targets.get(key) !== target;
      if (target === null) {
        targets.delete(key);
      } else {
        targets.set(key, target);
      }
      return overwritten;
    },
    resolve(key: string): T | undefined {
      return targets.get(key);
    },
    withTarget(key: string, callback: (target: T) => void): boolean {
      const target = targets.get(key);
      if (target === undefined) {
        return false;
      }
      callback(target);
      return true;
    },
  };
}
