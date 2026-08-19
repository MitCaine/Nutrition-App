import type {
  TargetConfiguration,
  TargetValue,
} from "../targets/api/types";
import {
  formatTargetAmount,
  targetAuthorityLabel,
  targetDirectionLabel,
} from "../targets/targetProgress";
import {
  NUTRIENT_CATALOG_BY_ID,
} from "../../shared/nutrition/catalog";
import {
  formatNutrientLabel,
} from "../../shared/nutrition/display";
import {
  canonicalNutrientParentId,
  nutrientVisibleDepth,
  type NutrientSectionId,
} from "../../shared/nutrition/nutrientSections";
import type {
  HistoryProjectedNutrient,
  HistoryProjection,
  HistoryProjectionMode,
} from "./types";

export type HistoryNutritionDetailRow =
  Readonly<{
    nutrientId: string;
    label: string;
    unit: string;
    value: string;
    denominatorContext: string;
    usableDayCount: number;
    targetContext: string | null;
    hierarchyDepth: number;
  }>;

export type HistoryNutritionDetailSection =
  Readonly<{
    id: NutrientSectionId;
    label: string;
    rows:
      readonly HistoryNutritionDetailRow[];
  }>;

function formattedHistoryAmount(
  value: string,
  unit: string,
): string {
  return `${
    formatTargetAmount(
      value,
      unit,
    )
  } ${unit}`;
}

function denominatorContext(
  mode: HistoryProjectionMode,
  usableDayCount: number,
): string {
  const modeLabel =
    mode === "complete_days"
      ? "Complete-day average"
      : "Logged-day average";

  const dayLabel =
    usableDayCount === 1
      ? "day"
      : "days";

  return (
    `${modeLabel} · `
    + `${usableDayCount} ${dayLabel} used`
  );
}

function meaningfulCurrentTarget(
  target:
    TargetValue | undefined,
): target is TargetValue & Readonly<{
  amount: string;
}> {
  return (
    target !== undefined
    && target.amount !== null
    && (
      target.trackingMode
        === "recommended"
      || target.trackingMode
        === "custom"
    )
    && target.authority
      !== "unavailable"
    && target.direction
      !== "unavailable"
  );
}

function currentTargetContext(
  configuration:
    TargetConfiguration | undefined,
  nutrientId: string,
): string | null {
  const target =
    configuration
      ?.effectiveTargets
      .find(
        (candidate) =>
          candidate.nutrientId
          === nutrientId,
      );

  if (
    !meaningfulCurrentTarget(
      target,
    )
  ) {
    return null;
  }

  return [
    `Current ${
      targetAuthorityLabel(
        target.authority,
      )
    }`,
    formattedHistoryAmount(
      target.amount,
      target.unit,
    ),
    targetDirectionLabel(
      target.direction,
    ),
  ].join(" · ");
}

function sectionLabel(
  sectionId: NutrientSectionId,
  label: string | null,
): string {
  if (
    sectionId
      === "nutrition_facts"
  ) {
    return "Nutrition Facts";
  }

  return (
    label
    ?? (
      sectionId === "other"
        ? "Other"
        : sectionId
    )
  );
}

function detailRow(
  nutrient: HistoryProjectedNutrient,
  projectionMode:
    HistoryProjectionMode,
  allNutrientIds:
    ReadonlySet<string>,
  configuration:
    TargetConfiguration | undefined,
): HistoryNutritionDetailRow {
  const catalog =
    NUTRIENT_CATALOG_BY_ID.get(
      nutrient.nutrientId,
    );

  const label =
    formatNutrientLabel(
      nutrient.nutrientId,
      catalog?.display_name,
    );

  return {
    nutrientId:
      nutrient.nutrientId,
    label,
    unit:
      nutrient.unit,
    value:
      nutrient.average === null
        ? "—"
        : formattedHistoryAmount(
            nutrient.average,
            nutrient.unit,
          ),
    denominatorContext:
      denominatorContext(
        projectionMode,
        nutrient.usableDayCount,
      ),
    usableDayCount:
      nutrient.usableDayCount,
    targetContext:
      currentTargetContext(
        configuration,
        nutrient.nutrientId,
      ),
    hierarchyDepth:
      nutrientVisibleDepth(
        nutrient.nutrientId,
        allNutrientIds,
        canonicalNutrientParentId,
      ),
  };
}

export function
buildHistoryNutritionDetailSections(
  projection: HistoryProjection,
  configuration?:
    TargetConfiguration,
): readonly HistoryNutritionDetailSection[] {
  const allNutrientIds =
    new Set(
      projection.nutrients.map(
        (nutrient) =>
          nutrient.nutrientId,
      ),
    );

  const seen =
    new Set<string>();

  const sections =
    projection.groupedRows.map(
      (section) => ({
        id:
          section.id,
        label:
          sectionLabel(
            section.id,
            section.label,
          ),
        rows:
          section.items.map(
            (nutrient) => {
              if (
                seen.has(
                  nutrient.nutrientId,
                )
              ) {
                throw new Error(
                  `History detail contains duplicate canonical nutrient ${nutrient.nutrientId}.`,
                );
              }

              seen.add(
                nutrient.nutrientId,
              );

              return detailRow(
                nutrient,
                projection.mode,
                allNutrientIds,
                configuration,
              );
            },
          ),
      }),
    );

  if (
    seen.size
    !== projection.nutrients.length
  ) {
    const missing =
      projection.nutrients
        .map(
          (nutrient) =>
            nutrient.nutrientId,
        )
        .filter(
          (nutrientId) =>
            !seen.has(
              nutrientId,
            ),
        );

    throw new Error(
      `History detail grouping omitted canonical nutrients: ${missing.join(", ")}.`,
    );
  }

  return sections;
}
