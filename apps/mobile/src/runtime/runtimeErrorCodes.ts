/**
 * Runtime-neutral error categories reserved by the cross-adapter contract.
 *
 * Remote responses may still carry feature-specific diagnostic codes through
 * RuntimeError.code.  These category values are the stable vocabulary a
 * future local adapter must use when it has no more specific wire code; this
 * additive catalogue does not change the E2-01 error object or current remote
 * mapping.
 */
export const RUNTIME_ERROR_CODES = Object.freeze({
  ownershipDenied: "ownership_denied",
  validationFailed: "validation_failed",
  conflict: "conflict",
  constraintFailed: "constraint_failed",
  dependencyUnavailable: "dependency_unavailable",
  mutationUnresolved: "mutation_unresolved",
} as const);

export type RuntimeErrorCode = (typeof RUNTIME_ERROR_CODES)[keyof typeof RUNTIME_ERROR_CODES];

export const RUNTIME_ERROR_CODE_VALUES = Object.freeze(
  Object.values(RUNTIME_ERROR_CODES),
);
