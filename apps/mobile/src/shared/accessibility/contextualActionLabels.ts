export type ContextualAction = "edit" | "repeat" | "delete" | "move" | "show-more-notes" | "show-less-notes";

export type RepeatedActionContext = {
  subject: string;
  meal?: string | null;
  amount?: string | null;
  date?: string | null;
};

function present(value: string | null | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}

/** Central English construction for repeated Epic 1 row/card actions. */
export function contextualActionLabel(action: ContextualAction, context: RepeatedActionContext): string {
  const subject = present(context.subject) ?? "item";
  if (action === "show-more-notes") return `Show more notes for ${subject}`;
  if (action === "show-less-notes") return `Show less notes for ${subject}`;
  const verb = action.charAt(0).toUpperCase() + action.slice(1);
  const date = present(context.date);
  const main = action === "repeat" && date ? `${verb} ${subject} logged ${date}` : `${verb} ${subject}`;
  const details = [present(context.meal), present(context.amount)].filter((value): value is string => Boolean(value));
  return details.length > 0 ? `${main}, ${details.join(", ")}` : main;
}
