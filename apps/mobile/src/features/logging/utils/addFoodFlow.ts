import type { MealType } from "../validation/logContracts";

/**
 * Transient identity for a Daily Log Add Food workflow.
 *
 * The originating date is deliberately carried as data instead of being
 * reconstructed from the navigator's currently visible route.
 */
export type AddFoodFlowState = {
  originatingDate: string;
  initialMeal: MealType | null;
  /** One user-entered query drives both independent search sources. */
  query: string;
  /** Browse and search scroll sessions remain separate transient contexts. */
  browseScrollOffset: number;
  searchScrollOffset: number;
};

export function createAddFoodFlow(
  originatingDate: string,
  initialMeal: MealType | null = null,
): AddFoodFlowState {
  return {
    originatingDate,
    initialMeal,
    query: "",
    browseScrollOffset: 0,
    searchScrollOffset: 0,
  };
}

export function updateAddFoodFlow(
  flow: AddFoodFlowState,
  changes: Partial<Pick<AddFoodFlowState, "query" | "browseScrollOffset" | "searchScrollOffset">>,
): AddFoodFlowState {
  return { ...flow, ...changes };
}
