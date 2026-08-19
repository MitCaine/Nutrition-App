import type {
  DailyTargetComparisonItem,
} from "../../targets/api/types";
import {
  formatTargetAmount,
  formatTargetPercentage,
  targetAuthorityLabel,
  targetDirectionLabel,
} from "../../targets/targetProgress";
import {
  NUTRIENT_CATALOG_BY_ID,
} from "../../../shared/nutrition/catalog";
import {
  formatNutrientLabel,
} from "../../../shared/nutrition/display";
import {
  canonicalNutrientParentId,
  groupCanonicalNutrientsBySection,
  nutrientVisibleDepth,
  type NutrientSectionId,
} from "../../../shared/nutrition/nutrientSections";

export type DailyNutritionPresentationRow =
  Readonly<{
    nutrientId: string;
    label: string;
    value: string;
    percentage: string | null;
    context: string | null;
    accessibilityLabel: string;
    hierarchyDepth: number;
  }>;

export type DailyNutritionPresentationSection =
  Readonly<{
    id: NutrientSectionId;
    label: string;
    rows:
      readonly DailyNutritionPresentationRow[];
  }>;

function formattedAmount(
  amount: string | null,
  unit: string,
): string | null {
  if (amount === null) {
    return null;
  }

  return `${
    formatTargetAmount(
      amount,
      unit,
    )
  } ${unit}`;
}

function presentationContext(
  item: DailyTargetComparisonItem,
  hasMeaningfulTarget: boolean,
): string | null {
  if (
    item.trackingMode
      === "amount_only"
  ) {
    return null;
  }

  if (!hasMeaningfulTarget) {
    return null;
  }

  const authority =
    item.authority === "unavailable"
      ? null
      : targetAuthorityLabel(
          item.authority,
        );

  const direction =
    item.direction === "unavailable"
      ? null
      : targetDirectionLabel(
          item.direction,
        );

  const parts =
    [authority, direction]
      .filter(
        (part): part is string =>
          Boolean(part),
      );

  return parts.length > 0
    ? parts.join(" · ")
    : null;
}

function buildRow(
  item: DailyTargetComparisonItem,
  visibleNutrientIds:
    ReadonlySet<string>,
): DailyNutritionPresentationRow {
  const label =
    formatNutrientLabel(
      item.nutrientId,
      NUTRIENT_CATALOG_BY_ID.get(
        item.nutrientId,
      )?.display_name,
    );

  const consumed =
    formattedAmount(
      item.consumedAmount,
      item.unit,
    );

  const target =
    formattedAmount(
      item.targetAmount,
      item.unit,
    );

  const hasMeaningfulTarget =
    item.trackingMode
      !== "amount_only"
    && item.trackingMode
      !== "ignored"
    && target !== null;

  let value: string;

  if (
    item.trackingMode
      === "amount_only"
  ) {
    value = consumed ?? "—";
  } else if (
    consumed === null
    && target === null
  ) {
    value = "—";
  } else if (target !== null) {
    value =
      `${consumed ?? "—"} / ${target}`;
  } else {
    value = consumed ?? "—";
  }

  const percentage =
    hasMeaningfulTarget
    && item.percentage !== null
      ? formatTargetPercentage(
          item.percentage,
        )
      : null;

  const context =
    presentationContext(
      item,
      hasMeaningfulTarget,
    );

  const accessibilityLabel = [
    label,
    value,
    percentage,
    context,
  ]
    .filter(
      (part): part is string =>
        Boolean(part),
    )
    .join(", ");

  return {
    nutrientId: item.nutrientId,
    label,
    value,
    percentage,
    context,
    accessibilityLabel,
    hierarchyDepth:
      nutrientVisibleDepth(
        item.nutrientId,
        visibleNutrientIds,
        canonicalNutrientParentId,
      ),
  };
}

export function
buildDailyNutritionSections(
  comparisons:
    readonly DailyTargetComparisonItem[],
): readonly DailyNutritionPresentationSection[] {
  const visible =
    comparisons.filter(
      (item) =>
        item.trackingMode
        !== "ignored",
    );

  const visibleNutrientIds =
    new Set(
      visible.map(
        (item) =>
          item.nutrientId,
      ),
    );

  return groupCanonicalNutrientsBySection(
    visible,
    (item) => item.nutrientId,
  ).map((section) => ({
    id: section.id,
    label:
      section.label
      ?? "Nutrition Facts",
    rows:
      section.items.map(
        (item) =>
          buildRow(
            item,
            visibleNutrientIds,
          ),
      ),
  }));
}
