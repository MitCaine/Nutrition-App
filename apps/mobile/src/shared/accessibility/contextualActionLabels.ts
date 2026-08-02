export type ContextualAction =
  | "edit"
  | "repeat"
  | "delete"
  | "move"
  | "view-source"
  | "add-food"
  | "retry"
  | "check-status"
  | "retry-exact"
  | "dismiss-recovery"
  | "review-recovery"
  | "start-separate-action"
  | "show-more-notes"
  | "show-less-notes";

export type RepeatedActionContext = {
  subject: string;
  meal?: string | null;
  amount?: string | null;
  date?: string | null;
  operation?: string | null;
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
  if (action === "view-source") return `View source for ${subject}`;
  if (action === "add-food") return `Add food to ${subject}`;
  if (action === "retry") return `Retry ${subject}`;
  const operation = present(context.operation) ?? "operation";
  const recoveryDate = present(context.date);
  const recoveryDetails = [present(context.meal), present(context.amount)]
    .filter((value): value is string => Boolean(value));
  const recoveryIdentity = `${subject}${recoveryDetails.length > 0 ? `, ${recoveryDetails.join(", ")}` : ""}`;
  const recoveryTarget = `${operation} for ${recoveryIdentity}${recoveryDate ? ` on ${recoveryDate}` : ""}`;
  if (action === "check-status") return `Check status of ${recoveryTarget}`;
  if (action === "retry-exact") return `Retry exact ${recoveryTarget}`;
  if (action === "dismiss-recovery") return `Dismiss ${operation} recovery for ${recoveryIdentity}`;
  if (action === "review-recovery") return `Review original ${operation} uncertainty for ${recoveryIdentity}`;
  if (action === "start-separate-action") return `Start separate ${operation} for ${recoveryIdentity}`;
  const verb = action.charAt(0).toUpperCase() + action.slice(1);
  const date = present(context.date);
  const main = action === "repeat" && date ? `${verb} ${subject} logged ${date}` : `${verb} ${subject}`;
  const details = [present(context.meal), present(context.amount)].filter((value): value is string => Boolean(value));
  return details.length > 0 ? `${main}, ${details.join(", ")}` : main;
}
