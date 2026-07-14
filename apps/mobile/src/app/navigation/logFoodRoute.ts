import type { LogFoodInitialAmount } from "../../features/logging/utils/logFoodForm";

export type LogFoodRoute = {
  name: "log-food";
  foodId: string;
  initialAmount?: LogFoodInitialAmount;
};

export function logFoodRoute(
  foodId: string,
  initialAmount?: LogFoodInitialAmount,
): LogFoodRoute {
  return { name: "log-food", foodId, initialAmount };
}
