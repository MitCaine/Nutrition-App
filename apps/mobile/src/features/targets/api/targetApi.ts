import { z } from "zod";

import { apiRequest } from "../../../shared/api/client";
import type { DailyTargetComparison, TargetConfiguration, TargetConfigurationInput } from "./types";

const decimal = z.string().regex(/^\d+(?:\.\d+)?$/);
const direction = z.enum(["target", "limit", "minimum", "reference", "unavailable"]);
const authority = z.enum(["manual_override", "calculated_estimate", "daily_value", "unavailable"]);
const targetValue = z.object({
  nutrient_id: z.string(), amount: decimal.nullable(), unit: z.string(),
  authority, direction, reason_code: z.string().nullable(), note_code: z.string().nullable(),
}).strict();
const dailyValue = z.object({
  nutrient_id: z.string(), amount: decimal.nullable(), unit: z.string(),
  availability: z.enum(["available", "unavailable"]), direction, note_code: z.string().nullable(),
}).strict();
const configurationSchema = z.object({
  profile: z.object({
    birth_date: z.string().nullable(), sex_for_equation: z.enum(["female", "male"]).nullable(),
    height_cm: decimal.nullable(), height_unit: z.literal("cm"),
    weight_kg: decimal.nullable(), weight_unit: z.literal("kg"),
    activity_level: z.enum(["sedentary", "lightly_active", "active", "very_active"]).nullable(),
    energy_estimation_context: z.enum(["general_adult", "pregnant", "lactating", "specialized_medical"]),
  }).strict().nullable(),
  estimated_maintenance_calories: z.object({
    availability: z.enum(["available", "unavailable"]), amount: decimal.nullable(), unit: z.string(),
    authority: z.literal("calculated_estimate"), reason_code: z.string().nullable(), equation: z.string(),
  }).strict(),
  manual_overrides: z.array(targetValue), effective_targets: z.array(targetValue),
  daily_value_catalog_version: z.string(), daily_value_standard: z.string(),
  target_direction_semantics_version: z.string(), daily_values: z.array(dailyValue),
  limitations: z.array(z.string()), informational_notice: z.string(),
}).strict();

function mapConfiguration(raw: unknown): TargetConfiguration {
  const value = configurationSchema.parse(raw);
  const mapTarget = (item: z.infer<typeof targetValue>) => ({ nutrientId: item.nutrient_id, amount: item.amount, unit: item.unit, authority: item.authority, direction: item.direction, reasonCode: item.reason_code, noteCode: item.note_code });
  return {
    profile: value.profile ? {
      birthDate: value.profile.birth_date, sexForEquation: value.profile.sex_for_equation,
      heightCm: value.profile.height_cm, weightKg: value.profile.weight_kg,
      activityLevel: value.profile.activity_level, energyEstimationContext: value.profile.energy_estimation_context,
    } : null,
    estimatedMaintenanceCalories: {
      availability: value.estimated_maintenance_calories.availability,
      amount: value.estimated_maintenance_calories.amount,
      unit: value.estimated_maintenance_calories.unit,
      authority: value.estimated_maintenance_calories.authority,
      reasonCode: value.estimated_maintenance_calories.reason_code,
      equation: value.estimated_maintenance_calories.equation,
    },
    manualOverrides: value.manual_overrides.map(mapTarget), effectiveTargets: value.effective_targets.map(mapTarget),
    dailyValueCatalogVersion: value.daily_value_catalog_version, dailyValueStandard: value.daily_value_standard,
    targetDirectionSemanticsVersion: value.target_direction_semantics_version,
    dailyValues: value.daily_values.map((item) => ({
      nutrientId: item.nutrient_id, amount: item.amount, unit: item.unit,
      availability: item.availability, direction: item.direction, noteCode: item.note_code,
    })),
    limitations: value.limitations, informationalNotice: value.informational_notice,
  };
}

const comparisonSchema = z.object({
  date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/), daily_value_catalog_version: z.string(),
  target_direction_semantics_version: z.string(),
  comparisons: z.array(z.object({
    nutrient_id: z.string(), consumed_amount: decimal.nullable(), target_amount: decimal.nullable(),
    unit: z.string(), percentage: decimal.nullable(), authority, direction,
    status: z.enum(["available", "target_unavailable", "consumed_unavailable"]),
    reason_code: z.string().nullable(), note_code: z.string().nullable(),
    has_unknown_contributors: z.boolean(),
  }).strict()),
}).strict();

export async function getDailyTargetComparison(date: string): Promise<DailyTargetComparison> {
  const value = comparisonSchema.parse(await apiRequest<unknown>(`/targets/daily-comparison?date=${encodeURIComponent(date)}`));
  return {
    date: value.date,
    dailyValueCatalogVersion: value.daily_value_catalog_version,
    targetDirectionSemanticsVersion: value.target_direction_semantics_version,
    comparisons: value.comparisons.map((item) => ({
      nutrientId: item.nutrient_id, consumedAmount: item.consumed_amount,
      targetAmount: item.target_amount, unit: item.unit, percentage: item.percentage,
      authority: item.authority, direction: item.direction, status: item.status,
      reasonCode: item.reason_code, noteCode: item.note_code,
      hasUnknownContributors: item.has_unknown_contributors,
    })),
  };
}

export async function getTargets(): Promise<TargetConfiguration> {
  return mapConfiguration(await apiRequest<unknown>("/targets"));
}

export async function updateTargets(input: TargetConfigurationInput): Promise<TargetConfiguration> {
  return mapConfiguration(await apiRequest<unknown>("/targets", { method: "PUT", body: JSON.stringify(input) }));
}

export async function resetTargetOverride(nutrientId: string): Promise<TargetConfiguration> {
  return mapConfiguration(await apiRequest<unknown>(`/targets/overrides/${encodeURIComponent(nutrientId)}`, { method: "DELETE" }));
}
