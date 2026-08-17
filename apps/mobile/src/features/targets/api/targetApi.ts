import { z } from "zod";

import { apiRequest } from "../../../shared/api/client";
import type {
  DailyTargetComparison,
  TargetConfiguration,
  TargetConfigurationInput,
} from "./types";

const decimal =
  z.string().regex(/^\d+(?:\.\d+)?$/);

const direction = z.enum([
  "target",
  "limit",
  "minimum",
  "reference",
  "unavailable",
]);

const authority = z.enum([
  "manual_override",
  "calculated_estimate",
  "dri",
  "daily_value",
  "unavailable",
]);

const referenceType =
  z.enum(["RDA", "AI"]);

const calculationBasis =
  z.enum(["fixed", "per_kg"]);

const trackingPreferenceMode =
  z.enum(["amount_only", "ignored"]);

const trackingMode =
  z.enum([
    "recommended",
    "custom",
    "amount_only",
    "ignored",
  ]);

const targetValue = z.object({
  nutrient_id: z.string(),
  amount: decimal.nullable(),
  unit: z.string(),
  authority,
  direction,
  tracking_mode: trackingMode,
  reason_code: z.string().nullable(),
  note_code: z.string().nullable(),
  reference_type: referenceType.nullable(),
  source_version: z.string().nullable(),
  source_id: z.string().nullable(),
  calculation_basis:
    calculationBasis.nullable(),
}).strict();

const dailyValue = z.object({
  nutrient_id: z.string(),
  amount: decimal.nullable(),
  unit: z.string(),
  availability:
    z.enum(["available", "unavailable"]),
  direction,
  note_code: z.string().nullable(),
}).strict();

const upperLimit = z.object({
  amount: decimal,
  unit: z.string(),
  source_version: z.string(),
  source_id: z.string(),
  scope: z.string(),
  comparable_to_recommendation:
    z.boolean(),
}).strict();

const driRecommendation = z.object({
  nutrient_id: z.string(),
  availability:
    z.enum(["available", "unavailable"]),
  amount: decimal.nullable(),
  unit: z.string().nullable(),
  reference_type:
    referenceType.nullable(),
  source_version: z.string(),
  source_id: z.string().nullable(),
  age: z.number().int().nullable(),
  sex:
    z.enum(["female", "male"]).nullable(),
  life_stage:
    z.enum([
      "general_adult",
      "pregnant",
      "lactating",
    ]).nullable(),
  calculation_basis:
    calculationBasis.nullable(),
  weight_kg: decimal.nullable(),
  upper_limit: upperLimit.nullable(),
  reason_code: z.string().nullable(),
}).strict();

const profile = z.object({
  birth_date: z.string().nullable(),
  sex_for_equation:
    z.enum(["female", "male"]).nullable(),
  height_cm: decimal.nullable(),
  height_unit: z.literal("cm"),
  weight_kg: decimal.nullable(),
  weight_unit: z.literal("kg"),
  activity_level:
    z.enum([
      "sedentary",
      "lightly_active",
      "active",
      "very_active",
    ]).nullable(),
  energy_estimation_context:
    z.enum([
      "general_adult",
      "pregnant",
      "lactating",
      "specialized_medical",
    ]),
}).strict();

const configurationSchema = z.object({
  profile: profile.nullable(),
  estimated_maintenance_calories:
    z.object({
      availability:
        z.enum(["available", "unavailable"]),
      amount: decimal.nullable(),
      unit: z.string(),
      authority:
        z.literal("calculated_estimate"),
      reason_code: z.string().nullable(),
      equation: z.string(),
    }).strict(),
  manual_overrides:
    z.array(targetValue),
  tracking_preferences:
    z.record(trackingPreferenceMode),
  effective_targets:
    z.array(targetValue),
  daily_value_catalog_version:
    z.string(),
  daily_value_standard:
    z.string(),
  dri_dataset_version:
    z.string(),
  target_direction_semantics_version:
    z.string(),
  daily_values:
    z.array(dailyValue),
  dri_recommendations:
    z.array(driRecommendation),
  limitations:
    z.array(z.string()),
  informational_notice:
    z.string(),
}).strict();

function mapTarget(
  item: z.infer<typeof targetValue>,
) {
  return {
    nutrientId: item.nutrient_id,
    amount: item.amount,
    unit: item.unit,
    authority: item.authority,
    direction: item.direction,
    trackingMode: item.tracking_mode,
    reasonCode: item.reason_code,
    noteCode: item.note_code,
    referenceType: item.reference_type,
    sourceVersion: item.source_version,
    sourceId: item.source_id,
    calculationBasis:
      item.calculation_basis,
  };
}

function mapConfiguration(
  raw: unknown,
): TargetConfiguration {
  const value =
    configurationSchema.parse(raw);

  return {
    profile: value.profile
      ? {
          birthDate:
            value.profile.birth_date,
          sexForEquation:
            value.profile.sex_for_equation,
          heightCm:
            value.profile.height_cm,
          weightKg:
            value.profile.weight_kg,
          activityLevel:
            value.profile.activity_level,
          energyEstimationContext:
            value.profile
              .energy_estimation_context,
        }
      : null,
    estimatedMaintenanceCalories: {
      availability:
        value
          .estimated_maintenance_calories
          .availability,
      amount:
        value
          .estimated_maintenance_calories
          .amount,
      unit:
        value
          .estimated_maintenance_calories
          .unit,
      authority:
        value
          .estimated_maintenance_calories
          .authority,
      reasonCode:
        value
          .estimated_maintenance_calories
          .reason_code,
      equation:
        value
          .estimated_maintenance_calories
          .equation,
    },
    manualOverrides:
      value.manual_overrides.map(
        mapTarget,
      ),
    trackingPreferences:
      value.tracking_preferences,
    effectiveTargets:
      value.effective_targets.map(
        mapTarget,
      ),
    dailyValueCatalogVersion:
      value.daily_value_catalog_version,
    dailyValueStandard:
      value.daily_value_standard,
    driDatasetVersion:
      value.dri_dataset_version,
    targetDirectionSemanticsVersion:
      value
        .target_direction_semantics_version,
    dailyValues:
      value.daily_values.map(
        (item) => ({
          nutrientId:
            item.nutrient_id,
          amount:
            item.amount,
          unit:
            item.unit,
          availability:
            item.availability,
          direction:
            item.direction,
          noteCode:
            item.note_code,
        }),
      ),
    driRecommendations:
      value.dri_recommendations.map(
        (item) => ({
          nutrientId:
            item.nutrient_id,
          availability:
            item.availability,
          amount:
            item.amount,
          unit:
            item.unit,
          referenceType:
            item.reference_type,
          sourceVersion:
            item.source_version,
          sourceId:
            item.source_id,
          age:
            item.age,
          sex:
            item.sex,
          lifeStage:
            item.life_stage,
          calculationBasis:
            item.calculation_basis,
          weightKg:
            item.weight_kg,
          upperLimit:
            item.upper_limit
              ? {
                  amount:
                    item.upper_limit.amount,
                  unit:
                    item.upper_limit.unit,
                  sourceVersion:
                    item.upper_limit
                      .source_version,
                  sourceId:
                    item.upper_limit
                      .source_id,
                  scope:
                    item.upper_limit.scope,
                  comparableToRecommendation:
                    item.upper_limit
                      .comparable_to_recommendation,
                }
              : null,
          reasonCode:
            item.reason_code,
        }),
      ),
    limitations:
      value.limitations,
    informationalNotice:
      value.informational_notice,
  };
}

const comparisonSchema = z.object({
  date:
    z.string().regex(
      /^\d{4}-\d{2}-\d{2}$/,
    ),
  daily_value_catalog_version:
    z.string(),
  dri_dataset_version:
    z.string(),
  target_direction_semantics_version:
    z.string(),
  comparisons: z.array(
    z.object({
      nutrient_id: z.string(),
      consumed_amount:
        decimal.nullable(),
      target_amount:
        decimal.nullable(),
      unit: z.string(),
      percentage:
        decimal.nullable(),
      authority,
      direction,
      status:
        z.enum([
          "available",
          "target_unavailable",
          "consumed_unavailable",
          "amount_only",
        ]),
      tracking_mode:
        trackingMode,
      reason_code:
        z.string().nullable(),
      note_code:
        z.string().nullable(),
      has_unknown_contributors:
        z.boolean(),
      reference_type:
        referenceType.nullable(),
      source_version:
        z.string().nullable(),
      source_id:
        z.string().nullable(),
      calculation_basis:
        calculationBasis.nullable(),
    }).strict(),
  ),
}).strict();

export async function getDailyTargetComparison(
  date: string,
): Promise<DailyTargetComparison> {
  const value =
    comparisonSchema.parse(
      await apiRequest<unknown>(
        `/targets/daily-comparison?date=${
          encodeURIComponent(date)
        }`,
      ),
    );

  return {
    date: value.date,
    dailyValueCatalogVersion:
      value.daily_value_catalog_version,
    driDatasetVersion:
      value.dri_dataset_version,
    targetDirectionSemanticsVersion:
      value
        .target_direction_semantics_version,
    comparisons:
      value.comparisons.map(
        (item) => ({
          nutrientId:
            item.nutrient_id,
          consumedAmount:
            item.consumed_amount,
          targetAmount:
            item.target_amount,
          unit:
            item.unit,
          percentage:
            item.percentage,
          authority:
            item.authority,
          direction:
            item.direction,
          status:
            item.status,
          trackingMode:
            item.tracking_mode,
          reasonCode:
            item.reason_code,
          noteCode:
            item.note_code,
          hasUnknownContributors:
            item
              .has_unknown_contributors,
          referenceType:
            item.reference_type,
          sourceVersion:
            item.source_version,
          sourceId:
            item.source_id,
          calculationBasis:
            item.calculation_basis,
        }),
      ),
  };
}

export async function getTargets():
Promise<TargetConfiguration> {
  return mapConfiguration(
    await apiRequest<unknown>(
      "/targets",
    ),
  );
}

export async function updateTargets(
  input: TargetConfigurationInput,
): Promise<TargetConfiguration> {
  return mapConfiguration(
    await apiRequest<unknown>(
      "/targets",
      {
        method: "PUT",
        body: JSON.stringify(input),
      },
    ),
  );
}

export async function resetTargetOverride(
  nutrientId: string,
): Promise<TargetConfiguration> {
  return mapConfiguration(
    await apiRequest<unknown>(
      `/targets/overrides/${
        encodeURIComponent(nutrientId)
      }`,
      {
        method: "DELETE",
      },
    ),
  );
}
