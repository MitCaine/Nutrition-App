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
  query: string;
  scrollOffset: number;
};

export function createAddFoodFlow(
  originatingDate: string,
  initialMeal: MealType | null = null,
): AddFoodFlowState {
  return {
    originatingDate,
    initialMeal,
    query: "",
    scrollOffset: 0,
  };
}

export function updateAddFoodFlow(
  flow: AddFoodFlowState,
  changes: Partial<Pick<AddFoodFlowState, "query" | "scrollOffset">>,
): AddFoodFlowState {
  return { ...flow, ...changes };
}
