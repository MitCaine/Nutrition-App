import type { AccessibilityAnnouncer, CancelAccessibilityAnnouncement } from "../accessibility/announcements";

export type ValidationIssue<TTarget extends string = string> = {
  code: string;
  message: string;
  target: TTarget;
  announce: boolean;
  moveFocus: boolean;
  valuesRemainValid: boolean;
};

export function validationIssue<TTarget extends string>(
  issue: ValidationIssue<TTarget>,
): ValidationIssue<TTarget> {
  return issue;
}

export function applyValidationIssue<TTarget extends string>(
  issue: ValidationIssue<TTarget>,
  dependencies: {
    focusTarget: (target: TTarget) => boolean;
    announce: AccessibilityAnnouncer;
  },
): { focused: boolean; cancelAnnouncement: CancelAccessibilityAnnouncement } {
  const focused = issue.moveFocus ? dependencies.focusTarget(issue.target) : false;
  const cancelAnnouncement = issue.announce
    ? dependencies.announce(issue.message, {
        key: `validation:${issue.code}:${issue.target}`,
        kind: "error",
        priority: "assertive",
        delayMs: focused ? 80 : 0,
      })
    : () => undefined;
  return { focused, cancelAnnouncement };
}
