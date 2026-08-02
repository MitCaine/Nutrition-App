import { contextualActionLabel } from "../src/shared/accessibility/contextualActionLabels";

test("repeated actions receive distinct labels from structured record context", () => {
  expect(contextualActionLabel("edit", {
    subject: "oatmeal",
    meal: "breakfast",
    amount: "1 cup",
  })).toBe("Edit oatmeal, breakfast, 1 cup");
  expect(contextualActionLabel("repeat", {
    subject: "chicken breast",
    date: "July 28",
    meal: "dinner",
  })).toBe("Repeat chicken breast logged July 28, dinner");
  expect(contextualActionLabel("delete", {
    subject: "yogurt",
    meal: "snack",
    amount: "170 grams",
  })).toBe("Delete yogurt, snack, 170 grams");
});

test("missing context is omitted without punctuation artifacts", () => {
  expect(contextualActionLabel("show-more-notes", { subject: "chili" })).toBe("Show more notes for chili");
  expect(contextualActionLabel("edit", { subject: "  oatmeal  ", meal: "" })).toBe("Edit oatmeal");
});
