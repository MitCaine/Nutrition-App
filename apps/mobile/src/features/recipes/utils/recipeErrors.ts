import { RuntimeError } from "../../../runtime/RuntimeError";

const MESSAGE_REWRITES: Record<string, string> = {
  "serving ingredients must not include mass display metadata": "Serving ingredients cannot contain mass-unit information.",
  "serving ingredients require serving_definition_id": "Select a serving for this ingredient.",
  "ingredient amount_quantity must be greater than zero": "Ingredient amount must be greater than zero.",
};

export function recipeApiErrorMessage(error: unknown): string {
  if (error instanceof RuntimeError) {
    const normalized = error.message.replace(/^Value error, /, "");
    return MESSAGE_REWRITES[normalized] ?? normalized;
  }
  if (!(error instanceof Error)) {
    return "Could not save recipe.";
  }
  if (error.message.trim() && !error.message.trim().startsWith("{")) {
    return error.message.trim();
  }
  return "Could not save recipe.";
}
