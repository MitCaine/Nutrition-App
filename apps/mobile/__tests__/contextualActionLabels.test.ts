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

test("Daily Log, cleanup, and recovery actions describe their exact target", () => {
  expect(contextualActionLabel("view-source", { subject: "oatmeal" })).toBe("View source for oatmeal");
  expect(contextualActionLabel("add-food", { subject: "dinner" })).toBe("Add food to dinner");
  expect(contextualActionLabel("retry", { subject: "totals" })).toBe("Retry totals");
  expect(contextualActionLabel("check-status", {
    subject: "oatmeal",
    operation: "delete",
    date: "July 28",
  })).toBe("Check status of delete for oatmeal on July 28");
  expect(contextualActionLabel("retry-exact", {
    subject: "oatmeal",
    operation: "delete",
    date: "July 28",
  })).toBe("Retry exact delete for oatmeal on July 28");
  expect(contextualActionLabel("dismiss-recovery", {
    subject: "oatmeal",
    operation: "delete",
  })).toBe("Dismiss delete recovery for oatmeal");
  expect(contextualActionLabel("start-separate-action", {
    subject: "oatmeal",
    operation: "delete",
  })).toBe("Start separate delete for oatmeal");
});
