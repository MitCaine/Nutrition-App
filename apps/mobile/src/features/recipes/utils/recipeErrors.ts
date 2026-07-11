const MESSAGE_REWRITES: Record<string, string> = {
  "serving ingredients must not include mass display metadata": "Serving ingredients cannot contain mass-unit information.",
  "serving ingredients require serving_definition_id": "Select a serving for this ingredient.",
  "ingredient amount_quantity must be greater than zero": "Ingredient amount must be greater than zero.",
};

function firstDetailMessage(detail: unknown): string | null {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    for (const item of detail) {
      if (typeof item === "object" && item && "msg" in item && typeof item.msg === "string") {
        return item.msg;
      }
    }
  }
  return null;
}

export function recipeApiErrorMessage(error: unknown): string {
  if (!(error instanceof Error)) {
    return "Could not save recipe.";
  }
  try {
    const parsed = JSON.parse(error.message) as { detail?: unknown };
    const message = firstDetailMessage(parsed.detail);
    if (message) {
      const normalized = message.replace(/^Value error, /, "");
      return MESSAGE_REWRITES[normalized] ?? normalized;
    }
  } catch {
    if (error.message.trim() && !error.message.trim().startsWith("{")) {
      return error.message.trim();
    }
  }
  return "Could not save recipe.";
}
