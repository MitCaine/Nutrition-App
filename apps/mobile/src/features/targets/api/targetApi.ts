import { z } from "zod";

import { apiRequest } from "../../../shared/api/client";
import type { TargetConfiguration, TargetConfigurationInput } from "./types";

const decimal = z.string();
const targetValue = z.object({
  nutrient_id: z.string(), amount: decimal.nullable(), unit: z.string(),
  authority: z.enum(["manual_override", "calculated_estimate", "daily_value", "unavailable"]),
  reason_code: z.string().nullable(),
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
  daily_values: z.array(z.object({ nutrient_id: z.string(), amount: decimal.nullable(), unit: z.string(), availability: z.enum(["available", "unavailable"]), note_code: z.string().nullable() }).strict()),
  limitations: z.array(z.string()), informational_notice: z.string(),
}).strict();

function mapConfiguration(raw: unknown): TargetConfiguration {
  const value = configurationSchema.parse(raw);
  const mapTarget = (item: z.infer<typeof targetValue>) => ({ nutrientId: item.nutrient_id, amount: item.amount, unit: item.unit, authority: item.authority, reasonCode: item.reason_code });
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
    limitations: value.limitations, informationalNotice: value.informational_notice,
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
