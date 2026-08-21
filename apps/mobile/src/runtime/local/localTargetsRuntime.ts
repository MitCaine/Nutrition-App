import * as Crypto from "expo-crypto";
import type { SQLiteDatabase } from "expo-sqlite";

import type {
  DailyTargetComparison,
  DailyTargetComparisonItem,
  TargetConfiguration,
  TargetConfigurationInput,
  TargetProfile,
  TargetValue,
  TrackingPreferenceMode,
} from "../../features/targets/api/types";
import {
  resolveDriRecommendation,
} from "../../shared/nutrition/dri";
import {
  DRI_DATASET_VERSION,
  DRI_NO_GOAL,
} from "../../shared/nutrition/driData";
import { todayInTimeZone } from "../../features/logging/utils/dailyLogDisplay";
import {
  parseDateOnly,
  parseIanaTimeZone,
  parseUuid,
  serializeInstant,
} from "../../shared/exact/canonicalValues";
import {
  addResponseDecimals,
  compareDecimals,
  divideResponseDecimalByPowerOfTen,
  divideResponseDecimals,
  multiplyResponseDecimalsInContext,
  NUMERIC_14_6,
  NUMERIC_8_3,
  parseDecimal,
  parseResponseDecimal,
  type ExactDecimal,
  type ResponseDecimal,
} from "../../shared/exact/decimal";
import {
  FDA_DAILY_VALUE_CATALOG_VERSION,
  FDA_DAILY_VALUE_STANDARD,
  NUTRIENT_CATALOG,
} from "../../shared/nutrition/catalog";
import {
  canonicalNutrientUnit,
  type NutrientDataStatus,
  type NutrientUnit,
} from "../../shared/nutrition/types";
import { SQLITE_NUTRIENT_SEED_ROWS } from "../../storage/sqlite/schema";
import type { TargetsRuntime } from "../NutritionRuntime";
import { LocalRuntimeError } from "./localErrors";
import { withLocalOrderedRead, withLocalWriteTransaction } from "./localWriteCoordinator";

const TARGET_DIRECTION_SEMANTICS_VERSION = "target_directions_2026_v1";
const INFORMATIONAL_NOTICE =
  "Estimated maintenance calories are general informational estimates, not medical advice.";

const NUTRIENT_BY_ID = new Map(
  NUTRIENT_CATALOG.map((nutrient) => [
    nutrient.id,
    nutrient,
  ] as const),
);

const MANUAL_TARGET_UNITS:
Readonly<Record<string, NutrientUnit>> =
  Object.fromEntries(
    NUTRIENT_CATALOG.map((nutrient) => [
      nutrient.id,
      nutrient.default_unit as NutrientUnit,
    ]),
  );

const TARGET_BOUNDS:
Readonly<Record<string, readonly [string, string]>> = {
  calories: ["500", "10000"],
  protein: ["1", "1000"],
  total_carbohydrate: ["1", "1500"],
  total_fat: ["1", "500"],
};

const GENERIC_TARGET_BOUNDS =
  ["0.000001", "99999999.999999"] as const;

const ACTIVITY_MULTIPLIERS: Readonly<Record<string, string>> = {
  sedentary: "1.4",
  lightly_active: "1.6",
  active: "1.8",
  very_active: "2.0",
};

const DAILY_VALUE_DIRECTION_OVERRIDES: Readonly<Record<
  string,
  "limit" | "minimum"
>> = {
  saturated_fat: "limit",
  cholesterol: "limit",
  sodium: "limit",
  dietary_fiber: "minimum",
  added_sugars: "limit",
  vitamin_d: "minimum",
  calcium: "minimum",
  iron: "minimum",
  potassium: "minimum",
};

const DAILY_VALUE_NOTE_CODES: Readonly<Record<string, string>> = {
  protein: "protein_percent_dv_labeling_caveat",
};

const MASS_UNITS = new Set<NutrientUnit>(["g", "mg", "mcg"]);
const NUTRIENT_STATUSES = new Set<NutrientDataStatus>(["known", "unknown", "estimated", "zero"]);
const DEFAULT_UNITS = new Map(
  SQLITE_NUTRIENT_SEED_ROWS.map(([id, , , unit]) => [id, unit as NutrientUnit]),
);

type ProfileRow = Readonly<{
  user_id: string;
  birth_date: string | null;
  height_cm: string | null;
  weight_kg: string | null;
  biological_sex_for_reference_calculations: string | null;
  activity_level: string | null;
  energy_estimation_context: string;
  authoritative_time_zone: string | null;
}>;

type TargetRow = Readonly<{
  id: string;
  user_id: string;
  target_type: string;
  nutrient_id: string;
  target_amount: string | null;
  unit: string;
  basis: string;
  source: string;
  metadata: string | null;
}>;

type SnapshotRow = Readonly<{
  nutrient_id: string;
  amount: string | null;
  unit: string;
  data_status: string;
  default_unit: string | null;
}>;

type NormalizedProfile = Readonly<{
  birthDate: string | null;
  heightCm: ExactDecimal | null;
  weightKg: ExactDecimal | null;
  sexForEquation: "female" | "male" | null;
  activityLevel: "sedentary" | "lightly_active" | "active" | "very_active" | null;
  energyEstimationContext: "general_adult" | "pregnant" | "lactating" | "specialized_medical";
  authoritativeTimeZone: string | null;
}>;

type NormalizedTargetInput = Readonly<{
  profile: Readonly<{
    birthDate: string | null;
    heightCm: ExactDecimal | null;
    weightKg: ExactDecimal | null;
    sexForEquation: "female" | "male" | null;
    activityLevel:
      | "sedentary"
      | "lightly_active"
      | "active"
      | "very_active"
      | null;
    energyEstimationContext:
      | "general_adult"
      | "pregnant"
      | "lactating"
      | "specialized_medical";
  }>;
  overrides: Readonly<
    Record<string, ExactDecimal | null>
  >;
  trackingPreferences:
    | Readonly<
        Record<
          string,
          TrackingPreferenceMode
        >
      >
    | null;
}>;

type Aggregate = {
  known: ResponseDecimal;
  estimated: ResponseDecimal;
  unit: NutrientUnit;
  unknown: number;
};

export type LocalTargetMutationStage = "after_reread" | "after_write";

export type LocalTargetsRuntimeOptions = Readonly<{
  /** Injectable clock keeps age and authoritative-date parity tests deterministic. */
  now?: () => Date;
  /** Focused tests may hold an uncommitted target mutation at a precise boundary. */
  onMutationStage?: (stage: LocalTargetMutationStage) => Promise<void> | void;
}>;

function targetError(
  kind: "validation" | "not_found" | "invalid_response" | "unknown",
  code: string,
  message: string,
  mutationOutcome: "not_applicable" | "confirmed_non_commit" = "not_applicable",
  field?: string,
  fieldErrorCode?: string,
): LocalRuntimeError {
  return new LocalRuntimeError({
    kind,
    code,
    message,
    field,
    fieldErrorCode,
    mutationOutcome,
    details: kind === "validation"
      ? {
        code,
        message,
        field_errors: field ? [{ field, code: fieldErrorCode ?? code, message }] : [],
      }
      : undefined,
  });
}

function ownerNotFound(
  mutationOutcome: "not_applicable" | "confirmed_non_commit" = "not_applicable",
): LocalRuntimeError {
  return targetError("not_found", "user_not_found", "The local owner could not be found.", mutationOutcome);
}

function invalidStored(): LocalRuntimeError {
  return targetError(
    "invalid_response",
    "invalid_local_target_state",
    "The local Target data is invalid and cannot be used safely.",
  );
}

function mutationFailure(): LocalRuntimeError {
  return targetError(
    "unknown",
    "local_target_mutation_failed",
    "The local Target change could not be completed safely.",
    "confirmed_non_commit",
  );
}

function readFailure(): LocalRuntimeError {
  return invalidStored();
}

function validationFailure(message: string, field: string, code = "target_value_out_of_range"): never {
  throw targetError("validation", code, message, "confirmed_non_commit", field);
}

function structuralValidationFailure(
  message: string,
  field: string,
  fieldCode = "target_value_out_of_range",
  mutationOutcome: "not_applicable" | "confirmed_non_commit" = "confirmed_non_commit",
): never {
  throw targetError(
    "validation",
    "invalid_target_request",
    message,
    mutationOutcome,
    field,
    fieldCode,
  );
}

function readClock(now: () => Date): Date {
  const value = now();
  if (!(value instanceof Date) || !Number.isFinite(value.getTime())) {
    throw targetError("unknown", "invalid_clock", "The local calendar clock is unavailable.");
  }
  return new Date(value.getTime());
}

function comparePlainDecimals(left: string, right: string): number {
  const parts = (value: string) => {
    const [whole, fraction = ""] = value.split(".");
    return {
      whole: whole.replace(/^0+(?=\d)/, ""),
      fraction: fraction.replace(/0+$/, ""),
    };
  };
  const first = parts(left);
  const second = parts(right);
  if (first.whole.length !== second.whole.length) return first.whole.length < second.whole.length ? -1 : 1;
  if (first.whole !== second.whole) return first.whole < second.whole ? -1 : 1;
  const length = Math.max(first.fraction.length, second.fraction.length);
  const leftFraction = first.fraction.padEnd(length, "0");
  const rightFraction = second.fraction.padEnd(length, "0");
  return leftFraction === rightFraction ? 0 : leftFraction < rightFraction ? -1 : 1;
}

function parseTargetAmount(
  value: unknown,
  field: string,
  bounds: readonly [string, string],
  spec = NUMERIC_14_6,
): ExactDecimal | null {
  if (value === null) return null;
  if (typeof value !== "string" || !/^\d+(?:\.\d+)?$/.test(value)) {
    structuralValidationFailure("Target values must be plain nonnegative decimal strings.", field);
  }
  if (comparePlainDecimals(value, bounds[0]) < 0 || comparePlainDecimals(value, bounds[1]) > 0) {
    validationFailure(`Value must be between ${bounds[0]} and ${bounds[1]}.`, field);
  }
  try {
    return parseDecimal(value, spec);
  } catch {
    validationFailure("Target value exceeds the supported exact decimal range.", field);
  }
}

function parseOptionalDate(value: unknown, field: string): string | null {
  if (value === null) return null;
  if (typeof value !== "string") structuralValidationFailure("Birth date must use a valid YYYY-MM-DD date.", field);
  try {
    return parseDateOnly(value);
  } catch {
    structuralValidationFailure("Birth date must use a valid YYYY-MM-DD date.", field);
  }
}

function parseProfileEnum<T extends string>(
  value: unknown,
  allowed: readonly T[],
  field: string,
  nullable = true,
): T | null {
  if (value === null && nullable) return null;
  if (typeof value !== "string" || !allowed.includes(value as T)) {
    structuralValidationFailure("Target profile value is invalid.", field);
  }
  return value as T;
}

function normalizeInput(
  input: TargetConfigurationInput,
): NormalizedTargetInput {
  if (
    !input
    || typeof input !== "object"
    || !input.profile
    || !input.manual_overrides
    || typeof input.manual_overrides !== "object"
    || Array.isArray(input.manual_overrides)
  ) {
    structuralValidationFailure(
      "Review the target fields and try again.",
      "profile",
    );
  }

  const profile = input.profile;

  if (
    profile.height_unit !== undefined
    && profile.height_unit !== "cm"
  ) {
    structuralValidationFailure(
      "Target height uses an unsupported unit.",
      "profile.height_unit",
      "target_unit_invalid",
    );
  }

  if (
    profile.weight_unit !== undefined
    && profile.weight_unit !== "kg"
  ) {
    structuralValidationFailure(
      "Target weight uses an unsupported unit.",
      "profile.weight_unit",
      "target_unit_invalid",
    );
  }

  const birthDate = parseOptionalDate(
    profile.birth_date,
    "profile.birth_date",
  );

  const heightCm = parseTargetAmount(
    profile.height_cm,
    "profile.height_cm",
    ["100", "250"],
    NUMERIC_8_3,
  );

  const weightKg = parseTargetAmount(
    profile.weight_kg,
    "profile.weight_kg",
    ["30", "300"],
    NUMERIC_8_3,
  );

  const sexForEquation = parseProfileEnum(
    profile.sex_for_equation,
    ["female", "male"],
    "profile.sex_for_equation",
  );

  const activityLevel = parseProfileEnum(
    profile.activity_level,
    [
      "sedentary",
      "lightly_active",
      "active",
      "very_active",
    ],
    "profile.activity_level",
  );

  const energyEstimationContext = parseProfileEnum(
    profile.energy_estimation_context
      ?? "general_adult",
    [
      "general_adult",
      "pregnant",
      "lactating",
      "specialized_medical",
    ],
    "profile.energy_estimation_context",
    false,
  ) as NormalizedTargetInput[
    "profile"
  ]["energyEstimationContext"];

  const overrides:
  Record<string, ExactDecimal | null> = {};

  for (
    const [nutrientId, value]
    of Object.entries(
      input.manual_overrides,
    )
  ) {
    if (!NUTRIENT_BY_ID.has(nutrientId)) {
      validationFailure(
        "This nutrient is not part of the canonical nutrient catalog.",
        `manual_overrides.${nutrientId}`,
        "target_nutrient_invalid",
      );
    }

    overrides[nutrientId] =
      parseTargetAmount(
        value,
        `manual_overrides.${nutrientId}`,
        TARGET_BOUNDS[nutrientId]
          ?? GENERIC_TARGET_BOUNDS,
      );
  }

  let trackingPreferences:
    Record<
      string,
      TrackingPreferenceMode
    >
    | null = null;

  if (
    input.tracking_preferences
    !== undefined
  ) {
    if (
      input.tracking_preferences === null
      || typeof input.tracking_preferences
        !== "object"
      || Array.isArray(
        input.tracking_preferences,
      )
    ) {
      structuralValidationFailure(
        "Tracking preferences are invalid.",
        "tracking_preferences",
      );
    }

    trackingPreferences = {};

    for (
      const [nutrientId, mode]
      of Object.entries(
        input.tracking_preferences,
      )
    ) {
      if (!NUTRIENT_BY_ID.has(nutrientId)) {
        validationFailure(
          "This nutrient is not part of the canonical nutrient catalog.",
          `tracking_preferences.${nutrientId}`,
          "target_nutrient_invalid",
        );
      }

      if (
        mode !== "amount_only"
        && mode !== "ignored"
      ) {
        structuralValidationFailure(
          "Tracking preference is invalid.",
          `tracking_preferences.${nutrientId}`,
        );
      }

      if (
        overrides[nutrientId]
        !== undefined
        && overrides[nutrientId]
        !== null
      ) {
        validationFailure(
          "A nutrient cannot use a custom target and an amount-only or ignored preference at the same time.",
          `tracking_preferences.${nutrientId}`,
          "target_preference_conflict",
        );
      }

      trackingPreferences[
        nutrientId
      ] = mode;
    }
  }

  return {
    profile: {
      birthDate,
      heightCm,
      weightKg,
      sexForEquation,
      activityLevel,
      energyEstimationContext,
    },
    overrides,
    trackingPreferences,
  };
}

function normalizeStoredProfile(row: ProfileRow | null): NormalizedProfile | null {
  if (!row) return null;
  try {
    const birthDate = row.birth_date === null ? null : parseDateOnly(row.birth_date);
    const heightCm = row.height_cm === null ? null : parseDecimal(row.height_cm, NUMERIC_8_3);
    const weightKg = row.weight_kg === null ? null : parseDecimal(row.weight_kg, NUMERIC_8_3);
    if (
      (heightCm !== null && (compareDecimals(heightCm, "100", NUMERIC_8_3) < 0 || compareDecimals(heightCm, "250", NUMERIC_8_3) > 0))
      || (weightKg !== null && (compareDecimals(weightKg, "30", NUMERIC_8_3) < 0 || compareDecimals(weightKg, "300", NUMERIC_8_3) > 0))
    ) {
      throw new Error("stored target profile is outside its contract");
    }
    const sexForEquation = row.biological_sex_for_reference_calculations === null
      ? null
      : row.biological_sex_for_reference_calculations;
    const activityLevel = row.activity_level === null ? null : row.activity_level;
    const context = row.energy_estimation_context;
    if (
      (sexForEquation !== null && sexForEquation !== "female" && sexForEquation !== "male")
      || (activityLevel !== null && !Object.prototype.hasOwnProperty.call(ACTIVITY_MULTIPLIERS, activityLevel))
      || !["general_adult", "pregnant", "lactating", "specialized_medical"].includes(context)
    ) {
      throw new Error("invalid target profile");
    }
    if (row.authoritative_time_zone !== null) parseIanaTimeZone(row.authoritative_time_zone);
    return {
      birthDate,
      heightCm,
      weightKg,
      sexForEquation: sexForEquation as NormalizedProfile["sexForEquation"],
      activityLevel: activityLevel as NormalizedProfile["activityLevel"],
      energyEstimationContext: context as NormalizedProfile["energyEstimationContext"],
      authoritativeTimeZone: row.authoritative_time_zone,
    };
  } catch {
    throw invalidStored();
  }
}

function hasTargetProfileValues(profile: NormalizedProfile | null): boolean {
  return Boolean(profile && (
    profile.birthDate !== null
    || profile.sexForEquation !== null
    || profile.heightCm !== null
    || profile.weightKg !== null
    || profile.activityLevel !== null
  ));
}

function targetDate(profile: NormalizedProfile | null, now: Date): string {
  if (profile?.authoritativeTimeZone) return todayInTimeZone(profile.authoritativeTimeZone, now);
  // Local and remote current Target calculations use explicit UTC only while
  // the owner has no established authoritative calendar time zone.
  return todayInTimeZone("UTC", now);
}

function dateParts(value: string): { year: number; month: number; day: number } {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) throw invalidStored();
  return { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]) };
}

function ageOn(birthDate: string, asOf: string): number {
  const birth = dateParts(birthDate);
  const current = dateParts(asOf);
  return current.year - birth.year - (
    current.month < birth.month || (current.month === birth.month && current.day < birth.day) ? 1 : 0
  );
}

type ResponseParts = Readonly<{ coefficient: bigint; scale: number }>;

function responseParts(value: string): ResponseParts {
  const canonical = parseResponseDecimal(value);
  const [whole, fraction = ""] = canonical.split(".");
  return { coefficient: BigInt(`${whole}${fraction}`), scale: fraction.length };
}

function formatResponseParts(value: ResponseParts, trim = true): ResponseDecimal {
  if (value.scale === 0) return value.coefficient.toString() as ResponseDecimal;
  const digits = value.coefficient.toString().padStart(value.scale + 1, "0");
  const whole = digits.slice(0, -value.scale);
  const fraction = trim ? digits.slice(-value.scale).replace(/0+$/, "") : digits.slice(-value.scale);
  return (fraction ? `${whole}.${fraction}` : whole) as ResponseDecimal;
}

function subtractResponseDecimals(left: string, right: string): ResponseDecimal {
  const first = responseParts(left);
  const second = responseParts(right);
  const scale = Math.max(first.scale, second.scale);
  const coefficient = first.coefficient * (10n ** BigInt(scale - first.scale))
    - second.coefficient * (10n ** BigInt(scale - second.scale));
  if (coefficient < 0n) throw invalidStored();
  return formatResponseParts({ coefficient, scale }, false);
}

function roundResponseHalfUp(value: string, scale: number, trim = true): ResponseDecimal {
  const parts = responseParts(value);
  if (parts.scale <= scale) {
    return formatResponseParts(
      { coefficient: parts.coefficient * (10n ** BigInt(scale - parts.scale)), scale },
      trim,
    );
  }
  const divisor = 10n ** BigInt(parts.scale - scale);
  let coefficient = parts.coefficient / divisor;
  if ((parts.coefficient % divisor) * 2n >= divisor) coefficient += 1n;
  return formatResponseParts({ coefficient, scale }, trim);
}

function isZeroResponse(value: string): boolean {
  return responseParts(value).coefficient === 0n;
}

function estimateMaintenanceCalories(
  profile: NormalizedProfile | null,
  asOf: string,
): { availability: "available" | "unavailable"; amount: ResponseDecimal | null; reasonCode: string | null } {
  if (!profile) return { availability: "unavailable", amount: null, reasonCode: "target_profile_incomplete" };
  if (profile.energyEstimationContext !== "general_adult") {
    return { availability: "unavailable", amount: null, reasonCode: "target_estimate_unsupported_context" };
  }
  if (
    profile.birthDate === null
    || profile.sexForEquation === null
    || profile.heightCm === null
    || profile.weightKg === null
    || profile.activityLevel === null
  ) {
    return { availability: "unavailable", amount: null, reasonCode: "target_profile_incomplete" };
  }
  const age = ageOn(profile.birthDate, asOf);
  if (age < 19 || age > 78) {
    return { availability: "unavailable", amount: null, reasonCode: "target_estimate_unsupported_age" };
  }
  const weight = parseResponseDecimal(profile.weightKg);
  const height = parseResponseDecimal(profile.heightCm);
  const restingBeforeAge = addResponseDecimals(
    multiplyResponseDecimalsInContext("10", weight),
    multiplyResponseDecimalsInContext("6.25", height),
  );
  const restingAfterAge = subtractResponseDecimals(
    restingBeforeAge,
    multiplyResponseDecimalsInContext("5", String(age)),
  );
  const resting = profile.sexForEquation === "male"
    ? addResponseDecimals(restingAfterAge, "5")
    : subtractResponseDecimals(restingAfterAge, "161");
  const maintenance = multiplyResponseDecimalsInContext(
    resting,
    ACTIVITY_MULTIPLIERS[profile.activityLevel] as string,
  );
  const rounded = roundResponseHalfUp(maintenance, 0);
  return { availability: "available", amount: rounded, reasonCode: null };
}

function dailyValues(): TargetConfiguration["dailyValues"] {
  return NUTRIENT_CATALOG.map((nutrient) => {
    const dailyValue = nutrient.fda_daily_value;

    if (dailyValue === null) {
      return {
        nutrientId: nutrient.id,
        amount: null,
        unit: nutrient.default_unit,
        availability: "unavailable",
        direction: "unavailable",
        noteCode: nutrient.id === "calories"
          ? "calories_are_not_daily_value"
          : "daily_value_not_established",
      };
    }

    return {
      nutrientId: nutrient.id,
      amount: parseResponseDecimal(dailyValue.amount),
      unit: dailyValue.unit,
      availability: "available",
      direction: DAILY_VALUE_DIRECTION_OVERRIDES[nutrient.id] ?? "reference",
      noteCode: DAILY_VALUE_NOTE_CODES[nutrient.id] ?? null,
    };
  });
}

async function readProfile(database: SQLiteDatabase, ownerId: string): Promise<ProfileRow | null> {
  return database.getFirstAsync<ProfileRow>(
    `SELECT "user_id", "birth_date", "height_cm", "weight_kg",
            "biological_sex_for_reference_calculations", "activity_level",
            "energy_estimation_context", "authoritative_time_zone"
     FROM "user_profiles" WHERE "user_id" = ?`,
    [ownerId],
  );
}

async function assertOwner(
  database: SQLiteDatabase,
  ownerId: string,
  mutationOutcome: "not_applicable" | "confirmed_non_commit" = "not_applicable",
): Promise<void> {
  const row = await database.getFirstAsync<{ id: string }>(
    `SELECT "id" FROM "users" WHERE "id" = ?`,
    [ownerId],
  );
  if (!row) throw ownerNotFound(mutationOutcome);
}

async function readTargetRows(
  database: SQLiteDatabase,
  ownerId: string,
): Promise<TargetRow[]> {
  return database.getAllAsync<TargetRow>(
    `SELECT "id", "user_id", "target_type", "nutrient_id",
            "target_amount", "unit", "basis", "source", "metadata"
     FROM "nutrition_targets"
     WHERE "user_id" = ?
       AND "target_type" = 'manual_override'
     ORDER BY "nutrient_id"`,
    [ownerId],
  );
}

async function readPreferenceRows(
  database: SQLiteDatabase,
  ownerId: string,
): Promise<TargetRow[]> {
  return database.getAllAsync<TargetRow>(
    `SELECT "id", "user_id", "target_type", "nutrient_id",
            "target_amount", "unit", "basis", "source", "metadata"
     FROM "nutrition_targets"
     WHERE "user_id" = ?
       AND "target_type" = 'tracking_preference'
     ORDER BY "nutrient_id"`,
    [ownerId],
  );
}

function normalizedOverrides(
  rows: readonly TargetRow[],
): Map<string, TargetValue> {
  const result =
    new Map<string, TargetValue>();

  for (const row of rows) {
    const unit =
      MANUAL_TARGET_UNITS[
        row.nutrient_id
      ];

    if (
      !unit
      || row.target_amount === null
      || row.unit !== unit
      || row.basis !== "per_day"
      || row.source !== "user"
      || row.metadata !== null
    ) {
      throw invalidStored();
    }

    try {
      parseUuid(row.id);
      parseUuid(row.user_id);

      const amount = parseDecimal(
        row.target_amount,
        NUMERIC_14_6,
      );

      const bounds =
        TARGET_BOUNDS[row.nutrient_id]
        ?? GENERIC_TARGET_BOUNDS;

      if (
        compareDecimals(
          amount,
          parseDecimal(
            bounds[0],
            NUMERIC_14_6,
          ),
          NUMERIC_14_6,
        ) < 0
        || compareDecimals(
          amount,
          parseDecimal(
            bounds[1],
            NUMERIC_14_6,
          ),
          NUMERIC_14_6,
        ) > 0
      ) {
        throw invalidStored();
      }

      if (result.has(row.nutrient_id)) {
        throw invalidStored();
      }

      result.set(
        row.nutrient_id,
        {
          nutrientId:
            row.nutrient_id,
          amount,
          unit,
          authority:
            "manual_override",
          direction: "target",
          trackingMode: "custom",
          reasonCode: null,
          noteCode: null,
          referenceType: null,
          sourceVersion: null,
          sourceId: null,
          calculationBasis: null,
        },
      );
    } catch (error) {
      if (
        error
        instanceof LocalRuntimeError
      ) {
        throw error;
      }

      throw invalidStored();
    }
  }

  return result;
}

function normalizedPreferences(
  rows: readonly TargetRow[],
): Map<
  string,
  TrackingPreferenceMode
> {
  const result =
    new Map<
      string,
      TrackingPreferenceMode
    >();

  for (const row of rows) {
    const unit =
      MANUAL_TARGET_UNITS[
        row.nutrient_id
      ];

    if (
      !unit
      || row.target_amount !== null
      || row.unit !== unit
      || row.basis !== "tracking"
      || row.source !== "user"
      || row.metadata === null
    ) {
      throw invalidStored();
    }

    try {
      parseUuid(row.id);
      parseUuid(row.user_id);

      const metadata = (
        JSON.parse(row.metadata) as unknown
      );

      if (
        !metadata
        || typeof metadata !== "object"
        || Array.isArray(metadata)
      ) {
        throw invalidStored();
      }

      const mode = (
        metadata as { mode?: unknown }
      ).mode;

      if (
        mode !== "amount_only"
        && mode !== "ignored"
      ) {
        throw invalidStored();
      }

      if (result.has(row.nutrient_id)) {
        throw invalidStored();
      }

      result.set(
        row.nutrient_id,
        mode,
      );
    } catch (error) {
      if (
        error
        instanceof LocalRuntimeError
      ) {
        throw error;
      }

      throw invalidStored();
    }
  }

  return result;
}

async function buildConfiguration(
  database: SQLiteDatabase,
  ownerId: string,
  profileRow: ProfileRow | null,
  asOf: string,
): Promise<TargetConfiguration> {
  const profile =
    normalizeStoredProfile(profileRow);

  const overrides =
    normalizedOverrides(
      await readTargetRows(
        database,
        ownerId,
      ),
    );

  const preferences =
    normalizedPreferences(
      await readPreferenceRows(
        database,
        ownerId,
      ),
    );

  const estimate =
    estimateMaintenanceCalories(
      profile,
      asOf,
    );

  const values = dailyValues();

  const dailyById =
    new Map(
      values.map(
        (value) => [
          value.nutrientId,
          value,
        ],
      ),
    );

  const driRecommendations =
    SQLITE_NUTRIENT_SEED_ROWS.map(
      ([nutrientId]) =>
        resolveDriRecommendation(
          nutrientId,
          {
            birthDate:
              profile?.birthDate
              ?? null,
            sex:
              profile?.sexForEquation
              ?? null,
            lifeStage:
              profile
                ?.energyEstimationContext
              ?? "general_adult",
            weightKg:
              profile?.weightKg
              ?? null,
            asOf,
          },
        ),
    );

  const driById =
    new Map(
      driRecommendations.map(
        (item) => [
          item.nutrientId,
          item,
        ],
      ),
    );

  const effectiveTargets:
    TargetValue[] = [];

  for (
    const [
      nutrientId,
      ,
      ,
      defaultUnit,
    ]
    of SQLITE_NUTRIENT_SEED_ROWS
  ) {
    const preference =
      preferences.get(nutrientId);

    const override =
      overrides.get(nutrientId);

    const dailyValue =
      dailyById.get(nutrientId);

    const dri =
      driById.get(nutrientId);

    if (!dailyValue || !dri) {
      throw invalidStored();
    }

    if (preference === "ignored") {
      effectiveTargets.push({
        nutrientId,
        amount: null,
        unit:
          (defaultUnit as NutrientUnit),
        authority: "unavailable",
        direction: "unavailable",
        trackingMode: "ignored",
        reasonCode:
          "target_ignored_preference",
        noteCode: null,
        referenceType: null,
        sourceVersion: null,
        sourceId: null,
        calculationBasis: null,
      });
      continue;
    }

    if (
      preference === "amount_only"
    ) {
      effectiveTargets.push({
        nutrientId,
        amount: null,
        unit:
          (defaultUnit as NutrientUnit),
        authority: "unavailable",
        direction: "unavailable",
        trackingMode: "amount_only",
        reasonCode:
          "target_amount_only_preference",
        noteCode: null,
        referenceType: null,
        sourceVersion: null,
        sourceId: null,
        calculationBasis: null,
      });
      continue;
    }

    if (override) {
      effectiveTargets.push(
        override,
      );
      continue;
    }

    if (
      nutrientId === "calories"
      && estimate.availability
        === "available"
    ) {
      effectiveTargets.push({
        nutrientId,
        amount: estimate.amount,
        unit: "kcal",
        authority:
          "calculated_estimate",
        direction: "target",
        trackingMode: "recommended",
        reasonCode: null,
        noteCode: null,
        referenceType: null,
        sourceVersion: null,
        sourceId: null,
        calculationBasis: null,
      });
      continue;
    }

    if (
      dri.availability
      === "available"
    ) {
      if (
        dri.amount === null
        || dri.unit === null
        || dri.referenceType === null
        || dri.calculationBasis === null
      ) {
        throw invalidStored();
      }

      effectiveTargets.push({
        nutrientId,
        amount: dri.amount,
        unit: dri.unit,
        authority: "dri",
        direction: "target",
        trackingMode:
          "recommended",
        reasonCode: null,
        noteCode: null,
        referenceType:
          dri.referenceType,
        sourceVersion:
          dri.sourceVersion,
        sourceId:
          dri.sourceId,
        calculationBasis:
          dri.calculationBasis,
      });
      continue;
    }

    if (
      dailyValue.availability
      === "available"
    ) {
      effectiveTargets.push({
        nutrientId,
        amount:
          dailyValue.amount,
        unit:
          dailyValue.unit,
        authority:
          "daily_value",
        direction:
          dailyValue.direction,
        trackingMode:
          "recommended",
        reasonCode: null,
        noteCode:
          dailyValue.noteCode,
        referenceType: null,
        sourceVersion: null,
        sourceId: null,
        calculationBasis: null,
      });
      continue;
    }

    if (
      nutrientId !== "calories"
      && Object.prototype
        .hasOwnProperty.call(
          DRI_NO_GOAL,
          nutrientId,
        )
    ) {
      effectiveTargets.push({
        nutrientId,
        amount: null,
        unit:
          (defaultUnit as NutrientUnit),
        authority: "unavailable",
        direction: "unavailable",
        trackingMode:
          "amount_only",
        reasonCode:
          "target_reference_not_established",
        noteCode:
          dailyValue.noteCode,
        referenceType: null,
        sourceVersion: null,
        sourceId: null,
        calculationBasis: null,
      });
      continue;
    }

    effectiveTargets.push({
      nutrientId,
      amount: null,
      unit:
        (
          dailyValue.unit
          ?? defaultUnit
        ) as NutrientUnit,
      authority: "unavailable",
      direction: "unavailable",
      trackingMode:
        "recommended",
      reasonCode:
        nutrientId === "calories"
          ? estimate.reasonCode
          : dri.reasonCode
            ?? dailyValue.noteCode,
      noteCode:
        dailyValue.noteCode,
      referenceType: null,
      sourceVersion: null,
      sourceId: null,
      calculationBasis: null,
    });
  }

  const targetProfile:
    TargetProfile | null =
    hasTargetProfileValues(profile)
      ? {
          birthDate:
            profile?.birthDate
            ?? null,
          sexForEquation:
            profile?.sexForEquation
            ?? null,
          heightCm:
            profile?.heightCm
            ?? null,
          weightKg:
            profile?.weightKg
            ?? null,
          activityLevel:
            profile?.activityLevel
            ?? null,
          energyEstimationContext:
            profile
              ?.energyEstimationContext
            ?? "general_adult",
        }
      : null;

  return {
    profile: targetProfile,
    estimatedMaintenanceCalories: {
      availability:
        estimate.availability,
      amount:
        estimate.amount,
      unit: "kcal",
      authority:
        "calculated_estimate",
      reasonCode:
        estimate.reasonCode,
      equation:
        "mifflin_st_jeor_1990",
    },
    manualOverrides:
      [...overrides.values()],
    trackingPreferences:
      Object.fromEntries(
        preferences.entries(),
      ),
    effectiveTargets,
    dailyValueCatalogVersion:
      FDA_DAILY_VALUE_CATALOG_VERSION,
    dailyValueStandard:
      FDA_DAILY_VALUE_STANDARD,
    driDatasetVersion:
      DRI_DATASET_VERSION,
    targetDirectionSemanticsVersion:
      TARGET_DIRECTION_SEMANTICS_VERSION,
    dailyValues:
      values,
    driRecommendations,
    limitations:
      estimate.availability
        === "available"
        || estimate.reasonCode
          === null
        ? []
        : [estimate.reasonCode],
    informationalNotice:
      INFORMATIONAL_NOTICE,
  };
}

function sameUnitFamily(left: NutrientUnit, right: NutrientUnit): boolean {
  return left === right || (MASS_UNITS.has(left) && MASS_UNITS.has(right));
}

function normalizeNutrientUnit(
  value: string,
): NutrientUnit {
  const unit =
    canonicalNutrientUnit(value);

  if (unit === null) {
    throw invalidStored();
  }

  return unit;
}

function convertNutritionAmount(amount: ExactDecimal, from: NutrientUnit, to: NutrientUnit): ResponseDecimal {
  if (from === to) return parseResponseDecimal(amount);
  if (!sameUnitFamily(from, to)) throw invalidStored();
  const factors: Readonly<Record<"g" | "mg" | "mcg", ResponseDecimal>> = {
    g: parseResponseDecimal("1"),
    mg: parseResponseDecimal("0.001"),
    mcg: parseResponseDecimal("0.000001"),
  };
  const sourceFactor = factors[from as "g" | "mg" | "mcg"];
  const targetFactor = factors[to as "g" | "mg" | "mcg"];
  if (!sourceFactor || !targetFactor) throw invalidStored();
  return divideResponseDecimalByPowerOfTen(
    multiplyResponseDecimalsInContext(amount, sourceFactor),
    targetFactor,
  );
}

async function readDailyTotals(database: SQLiteDatabase, ownerId: string, date: string): Promise<Map<string, Aggregate>> {
  const rows = await database.getAllAsync<SnapshotRow>(
    `SELECT "snapshot"."nutrient_id", "snapshot"."amount", "snapshot"."unit", "snapshot"."data_status",
            "nutrient"."default_unit"
     FROM "daily_log_nutrient_snapshots" AS "snapshot"
     JOIN "daily_logs" AS "log" ON "log"."id" = "snapshot"."daily_log_id"
     LEFT JOIN "nutrients" AS "nutrient" ON "nutrient"."id" = "snapshot"."nutrient_id"
     WHERE "log"."user_id" = ? AND "log"."logged_date" = ?
     ORDER BY "snapshot"."nutrient_id", "snapshot"."id"`,
    [ownerId, date],
  );
  const totals = new Map<string, Aggregate>();
  for (const row of rows) {
    const defaultUnit = DEFAULT_UNITS.get(row.nutrient_id);
    if (!defaultUnit) throw invalidStored();
    const storedDefaultUnit = row.default_unit === null ? defaultUnit : normalizeNutrientUnit(row.default_unit);
    if (storedDefaultUnit !== defaultUnit) throw invalidStored();
    const sourceUnit = normalizeNutrientUnit(row.unit);
    if (!sameUnitFamily(sourceUnit, defaultUnit)) throw invalidStored();
    if (!NUTRIENT_STATUSES.has(row.data_status as NutrientDataStatus)) throw invalidStored();
    const status = row.data_status as NutrientDataStatus;
    const current = totals.get(row.nutrient_id) ?? {
      known: parseResponseDecimal("0"),
      estimated: parseResponseDecimal("0"),
      unit: defaultUnit,
      unknown: 0,
    };
    if (status === "unknown") {
      if (row.amount !== null) throw invalidStored();
      current.unknown += 1;
    } else {
      if (row.amount === null) throw invalidStored();
      const amount = parseDecimal(row.amount, NUMERIC_14_6);
      if (status === "zero" && compareDecimals(amount, "0", NUMERIC_14_6) !== 0) throw invalidStored();
      const converted = compareDecimals(amount, "0", NUMERIC_14_6) === 0
        ? parseResponseDecimal("0")
        : convertNutritionAmount(amount, sourceUnit, defaultUnit);
      if (status === "estimated") current.estimated = addResponseDecimals(current.estimated, converted);
      else current.known = addResponseDecimals(current.known, converted);
    }
    totals.set(row.nutrient_id, current);
  }
  return totals;
}

function compareTotals(
  configuration: TargetConfiguration,
  totals: Map<string, Aggregate>,
  date: string,
): DailyTargetComparison {
  const comparisons:
    DailyTargetComparisonItem[] = [];

  for (
    const target
    of configuration.effectiveTargets
  ) {
    if (
      target.trackingMode
      === "ignored"
    ) {
      continue;
    }

    const total =
      totals.get(target.nutrientId);

    const consumed =
      total
        ? addResponseDecimals(
            total.known,
            total.estimated,
          )
        : null;

    if (
      target.trackingMode
      === "amount_only"
    ) {
      const amountOnlyConsumed =
        !total
        || (
          total.unknown > 0
          && isZeroResponse(
            total.known,
          )
          && isZeroResponse(
            total.estimated,
          )
        )
          ? null
          : consumed;

      comparisons.push({
        nutrientId:
          target.nutrientId,
        consumedAmount:
          amountOnlyConsumed,
        targetAmount: null,
        unit: target.unit,
        percentage: null,
        authority:
          target.authority,
        direction: "unavailable",
        trackingMode:
          "amount_only",
        status: "amount_only",
        reasonCode:
          target.reasonCode,
        noteCode:
          target.noteCode,
        hasUnknownContributors:
          Boolean(total?.unknown),
        referenceType:
          target.referenceType,
        sourceVersion:
          target.sourceVersion,
        sourceId:
          target.sourceId,
        calculationBasis:
          target.calculationBasis,
      });

      continue;
    }

    if (target.amount === null) {
      comparisons.push({
        nutrientId:
          target.nutrientId,
        consumedAmount: consumed,
        targetAmount: null,
        unit: target.unit,
        percentage: null,
        authority: "unavailable",
        direction:
          target.direction,
        trackingMode:
          target.trackingMode,
        status:
          "target_unavailable",
        reasonCode:
          target.reasonCode,
        noteCode:
          target.noteCode,
        hasUnknownContributors:
          Boolean(total?.unknown),
        referenceType:
          target.referenceType,
        sourceVersion:
          target.sourceVersion,
        sourceId:
          target.sourceId,
        calculationBasis:
          target.calculationBasis,
      });

      continue;
    }

    if (
      !total
      || (
        total.unknown > 0
        && isZeroResponse(
          total.known,
        )
        && isZeroResponse(
          total.estimated,
        )
      )
    ) {
      comparisons.push({
        nutrientId:
          target.nutrientId,
        consumedAmount: null,
        targetAmount:
          target.amount,
        unit: target.unit,
        percentage: null,
        authority:
          target.authority,
        direction:
          target.direction,
        trackingMode:
          target.trackingMode,
        status:
          "consumed_unavailable",
        reasonCode:
          "consumed_value_unavailable",
        noteCode:
          target.noteCode,
        hasUnknownContributors:
          Boolean(total?.unknown),
        referenceType:
          target.referenceType,
        sourceVersion:
          target.sourceVersion,
        sourceId:
          target.sourceId,
        calculationBasis:
          target.calculationBasis,
      });

      continue;
    }

    const percentage =
      roundResponseHalfUp(
        multiplyResponseDecimalsInContext(
          divideResponseDecimals(
            (consumed as ResponseDecimal),
            target.amount,
          ),
          "100",
        ),
        4,
        false,
      );

    comparisons.push({
      nutrientId:
        target.nutrientId,
      consumedAmount: consumed,
      targetAmount:
        target.amount,
      unit: target.unit,
      percentage,
      authority:
        target.authority,
      direction:
        target.direction,
      trackingMode:
        target.trackingMode,
      status: "available",
      reasonCode: null,
      noteCode:
        target.noteCode,
      hasUnknownContributors:
        total.unknown > 0,
      referenceType:
        target.referenceType,
      sourceVersion:
        target.sourceVersion,
      sourceId:
        target.sourceId,
      calculationBasis:
        target.calculationBasis,
    });
  }

  return {
    date,
    dailyValueCatalogVersion:
      configuration
        .dailyValueCatalogVersion,
    driDatasetVersion:
      configuration
        .driDatasetVersion,
    targetDirectionSemanticsVersion:
      configuration
        .targetDirectionSemanticsVersion,
    comparisons,
  };
}

function validateBirthDateAgainstClock(
  birthDate: string | null,
  asOf: string,
  mutationOutcome: "confirmed_non_commit",
): void {
  if (!birthDate) return;
  if (birthDate > asOf) {
    throw targetError("validation", "target_value_out_of_range", "Birth date cannot be in the future.", mutationOutcome, "profile.birth_date");
  }
  if (dateParts(asOf).year - dateParts(birthDate).year > 120) {
    throw targetError("validation", "target_value_out_of_range", "Birth date is outside the supported input range.", mutationOutcome, "profile.birth_date");
  }
}

async function ensureProfile(database: SQLiteDatabase, ownerId: string): Promise<ProfileRow> {
  let profile = await readProfile(database, ownerId);
  if (!profile) {
    await database.runAsync(`INSERT INTO "user_profiles" ("user_id") VALUES (?)`, [ownerId]);
    profile = await readProfile(database, ownerId);
  }
  if (!profile) throw invalidStored();
  return profile;
}

async function allocateTargetId(reservedIds: Set<string>): Promise<string> {
  const candidate = parseUuid(Crypto.randomUUID());
  if (!reservedIds.has(candidate)) {
    reservedIds.add(candidate);
    return candidate;
  }
  for (let sequence = 1; sequence < 0x100000; sequence += 1) {
    const suffix = sequence.toString(16).padStart(12, "0");
    const fallback = parseUuid(`${candidate.slice(0, -12)}${suffix}`);
    if (!reservedIds.has(fallback)) {
      reservedIds.add(fallback);
      return fallback;
    }
  }
  throw new Error("Unable to allocate a unique local Target identifier.");
}

async function updateTargets(
  database: SQLiteDatabase,
  ownerId: string,
  normalized: NormalizedTargetInput,
  now: Date,
  onMutationStage?: LocalTargetsRuntimeOptions["onMutationStage"],
): Promise<TargetConfiguration> {
  await assertOwner(database, ownerId, "confirmed_non_commit");
  const currentProfile = await ensureProfile(database, ownerId);
  const currentNormalized = normalizeStoredProfile(currentProfile);
  validateBirthDateAgainstClock(normalized.profile.birthDate, targetDate(currentNormalized, now), "confirmed_non_commit");
  await onMutationStage?.("after_reread");
  const updatedAt = serializeInstant(now.toISOString());
  await database.runAsync(
    `UPDATE "user_profiles"
     SET "birth_date" = ?, "height_cm" = ?, "weight_kg" = ?,
         "biological_sex_for_reference_calculations" = ?, "activity_level" = ?,
         "energy_estimation_context" = ?, "updated_at" = ?
     WHERE "user_id" = ?`,
    [
      normalized.profile.birthDate,
      normalized.profile.heightCm,
      normalized.profile.weightKg,
      normalized.profile.sexForEquation,
      normalized.profile.activityLevel,
      normalized.profile.energyEstimationContext,
      updatedAt,
      ownerId,
    ],
  );
  const existing = new Map(
    (
      await readTargetRows(
        database,
        ownerId,
      )
    ).map(
      (row) => [
        row.nutrient_id,
        row,
      ],
    ),
  );

  const existingPreferences =
    new Map(
      (
        await readPreferenceRows(
          database,
          ownerId,
        )
      ).map(
        (row) => [
          row.nutrient_id,
          row,
        ],
      ),
    );

  const reservedIds = new Set(
    (
      await database.getAllAsync<{
        id: string;
      }>(
        `SELECT "id"
         FROM "nutrition_targets"`,
      )
    ).map((row) => row.id),
  );

  for (
    const [nutrientId, amount]
    of Object.entries(
      normalized.overrides,
    )
  ) {
    const unit =
      MANUAL_TARGET_UNITS[
        nutrientId
      ];

    if (!unit) {
      throw invalidStored();
    }

    const row =
      existing.get(nutrientId);

    if (amount === null) {
      if (row) {
        await database.runAsync(
          `DELETE FROM "nutrition_targets"
           WHERE "user_id" = ?
             AND "target_type" = 'manual_override'
             AND "nutrient_id" = ?`,
          [ownerId, nutrientId],
        );

        existing.delete(
          nutrientId,
        );
      }

      continue;
    }

    const preferenceRow =
      existingPreferences.get(
        nutrientId,
      );

    if (preferenceRow) {
      await database.runAsync(
        `DELETE FROM "nutrition_targets"
         WHERE "user_id" = ?
           AND "target_type" = 'tracking_preference'
           AND "nutrient_id" = ?`,
        [ownerId, nutrientId],
      );

      existingPreferences.delete(
        nutrientId,
      );
    }

    if (row) {
      await database.runAsync(
        `UPDATE "nutrition_targets"
         SET "target_amount" = ?,
             "unit" = ?,
             "basis" = 'per_day',
             "source" = 'user',
             "metadata" = NULL,
             "updated_at" = ?
         WHERE "user_id" = ?
           AND "target_type" = 'manual_override'
           AND "nutrient_id" = ?`,
        [
          amount,
          unit,
          updatedAt,
          ownerId,
          nutrientId,
        ],
      );
    } else {
      const id =
        await allocateTargetId(
          reservedIds,
        );

      await database.runAsync(
        `INSERT INTO "nutrition_targets"
          ("id", "user_id", "target_type",
           "nutrient_id", "target_amount",
           "unit", "basis", "source",
           "metadata")
         VALUES (
           ?, ?, 'manual_override',
           ?, ?, ?, 'per_day',
           'user', NULL
         )`,
        [
          id,
          ownerId,
          nutrientId,
          amount,
          unit,
        ],
      );

      existing.set(
        nutrientId,
        {
          id,
          user_id: ownerId,
          target_type:
            "manual_override",
          nutrient_id:
            nutrientId,
          target_amount: amount,
          unit,
          basis: "per_day",
          source: "user",
          metadata: null,
        },
      );
    }
  }

  if (
    normalized.trackingPreferences
    !== null
  ) {
    for (
      const [nutrientId]
      of existingPreferences
    ) {
      if (
        !Object.prototype
          .hasOwnProperty.call(
            normalized
              .trackingPreferences,
            nutrientId,
          )
      ) {
        await database.runAsync(
          `DELETE FROM "nutrition_targets"
           WHERE "user_id" = ?
             AND "target_type" = 'tracking_preference'
             AND "nutrient_id" = ?`,
          [ownerId, nutrientId],
        );

        existingPreferences.delete(
          nutrientId,
        );
      }
    }

    for (
      const [nutrientId, mode]
      of Object.entries(
        normalized
          .trackingPreferences,
      )
    ) {
      const unit =
        MANUAL_TARGET_UNITS[
          nutrientId
        ];

      if (!unit) {
        throw invalidStored();
      }

      const manualRow =
        existing.get(nutrientId);

      if (manualRow) {
        await database.runAsync(
          `DELETE FROM "nutrition_targets"
           WHERE "user_id" = ?
             AND "target_type" = 'manual_override'
             AND "nutrient_id" = ?`,
          [ownerId, nutrientId],
        );

        existing.delete(
          nutrientId,
        );
      }

      const metadata =
        JSON.stringify({ mode });

      const row =
        existingPreferences.get(
          nutrientId,
        );

      if (row) {
        await database.runAsync(
          `UPDATE "nutrition_targets"
           SET "target_amount" = NULL,
               "min_amount" = NULL,
               "max_amount" = NULL,
               "unit" = ?,
               "basis" = 'tracking',
               "source" = 'user',
               "metadata" = ?,
               "updated_at" = ?
           WHERE "user_id" = ?
             AND "target_type" = 'tracking_preference'
             AND "nutrient_id" = ?`,
          [
            unit,
            metadata,
            updatedAt,
            ownerId,
            nutrientId,
          ],
        );
      } else {
        await database.runAsync(
          `INSERT INTO "nutrition_targets"
            ("id", "user_id", "target_type",
             "nutrient_id", "target_amount",
             "unit", "basis", "source",
             "metadata")
           VALUES (
             ?, ?, 'tracking_preference',
             ?, NULL, ?, 'tracking',
             'user', ?
           )`,
          [
            await allocateTargetId(
              reservedIds,
            ),
            ownerId,
            nutrientId,
            unit,
            metadata,
          ],
        );
      }
    }
  }

  await onMutationStage?.("after_write");
  const profile = await readProfile(database, ownerId);
  const normalizedProfile = normalizeStoredProfile(profile);
  return buildConfiguration(database, ownerId, profile, targetDate(normalizedProfile, now));
}

export class LocalTargetsRuntime implements TargetsRuntime {
  private readonly ownerId: string;
  private readonly now: () => Date;
  private readonly onMutationStage?: LocalTargetsRuntimeOptions["onMutationStage"];

  constructor(
    private readonly database: SQLiteDatabase,
    ownerId: string,
    options: LocalTargetsRuntimeOptions = {},
  ) {
    try {
      this.ownerId = parseUuid(ownerId);
    } catch {
      throw ownerNotFound();
    }
    this.now = options.now ?? (() => new Date());
    this.onMutationStage = options.onMutationStage;
  }

  async getConfiguration(): Promise<TargetConfiguration> {
    try {
      return await withLocalOrderedRead(this.database, async () => {
        await assertOwner(this.database, this.ownerId);
        const profile = await readProfile(this.database, this.ownerId);
        const normalized = normalizeStoredProfile(profile);
        return buildConfiguration(this.database, this.ownerId, profile, targetDate(normalized, readClock(this.now)));
      });
    } catch (error) {
      if (error instanceof LocalRuntimeError) throw error;
      throw readFailure();
    }
  }

  async updateConfiguration(input: TargetConfigurationInput): Promise<TargetConfiguration> {
    const normalized = normalizeInput(input);
    try {
      return await withLocalWriteTransaction(this.database, (transaction) =>
        updateTargets(transaction, this.ownerId, normalized, readClock(this.now), this.onMutationStage));
    } catch (error) {
      if (error instanceof LocalRuntimeError) throw error;
      throw mutationFailure();
    }
  }

  async resetOverride(nutrientId: string): Promise<TargetConfiguration> {
    if (!Object.prototype.hasOwnProperty.call(MANUAL_TARGET_UNITS, nutrientId)) {
      throw targetError(
        "validation",
        "target_unit_invalid",
        "This nutrient does not support a personal override.",
        "confirmed_non_commit",
        "nutrient_id",
      );
    }
    try {
      return await withLocalWriteTransaction(this.database, async (transaction) => {
        await assertOwner(transaction, this.ownerId, "confirmed_non_commit");
        const now = readClock(this.now);
        const profile = await ensureProfile(transaction, this.ownerId);
        const normalizedProfile = normalizeStoredProfile(profile);
        await this.onMutationStage?.("after_reread");
        await transaction.runAsync(
          `DELETE FROM "nutrition_targets"
           WHERE "user_id" = ? AND "target_type" = 'manual_override' AND "nutrient_id" = ?`,
          [this.ownerId, nutrientId],
        );
        await this.onMutationStage?.("after_write");
        const updatedProfile = await readProfile(transaction, this.ownerId);
        const updatedNormalized = normalizeStoredProfile(updatedProfile);
        return buildConfiguration(
          transaction,
          this.ownerId,
          updatedProfile,
          targetDate(updatedNormalized ?? normalizedProfile, now),
        );
      });
    } catch (error) {
      if (error instanceof LocalRuntimeError) throw error;
      throw mutationFailure();
    }
  }

  async getDailyComparison(date: string): Promise<DailyTargetComparison> {
    let loggedDate: string;
    try {
      loggedDate = parseDateOnly(date);
    } catch {
      throw structuralValidationFailure(
        "Target comparison dates must use YYYY-MM-DD.",
        "date",
        "target_value_out_of_range",
        "not_applicable",
      );
    }
    try {
      return await withLocalOrderedRead(this.database, async () => {
        await assertOwner(this.database, this.ownerId);
        const profile = await readProfile(this.database, this.ownerId);
        const configuration = await buildConfiguration(this.database, this.ownerId, profile, loggedDate);
        const totals = await readDailyTotals(this.database, this.ownerId, loggedDate);
        return compareTotals(configuration, totals, loggedDate);
      });
    } catch (error) {
      if (error instanceof LocalRuntimeError) throw error;
      throw readFailure();
    }
  }
}

export function createLocalTargetsRuntime(
  database: SQLiteDatabase,
  ownerId: string,
  options: LocalTargetsRuntimeOptions = {},
): LocalTargetsRuntime {
  return new LocalTargetsRuntime(database, ownerId, options);
}
