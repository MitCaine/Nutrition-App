export type CustomServingExpansionState = Record<string, boolean>;

export function isCustomServingExpanded(state: CustomServingExpansionState, localId: string): boolean {
  return state[localId] === true;
}

export function expandCustomServing(
  state: CustomServingExpansionState,
  localId: string,
): CustomServingExpansionState {
  return { ...state, [localId]: true };
}

export function collapseCustomServing(
  state: CustomServingExpansionState,
  localId: string,
): CustomServingExpansionState {
  const next = { ...state };
  delete next[localId];
  return next;
}
