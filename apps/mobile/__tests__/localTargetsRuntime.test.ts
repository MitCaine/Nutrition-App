const { mkdtempSync, rmSync } = require("fs") as {
  mkdtempSync(prefix: string): string;
  rmSync(path: string, options: { recursive: boolean; force: boolean }): void;
};
const { tmpdir } = require("os") as { tmpdir(): string };
const { join } = require("path") as { join(...parts: string[]): string };

import {
  createLocalTargetsRuntime,
  type LocalTargetsRuntime,
} from "../src/runtime/local/localTargetsRuntime";
import { ensureLocalNutrientCatalog } from "../src/runtime/local/localNutrientsRuntime";
import {
  ExpoIsolatedSQLiteTestDatabase,
  LocalSQLiteTestDatabase,
  seedLocalOwner,
  type LocalSQLiteFixtureDatabase,
} from "./localSQLiteTestSupport";

const OWNER = "00000000-0000-4000-8000-000000000001";
const OTHER_OWNER = "00000000-0000-4000-8000-000000000002";
const FOOD = "00000000-0000-4000-8000-000000000101";

function targetInput(overrides: Partial<{
  calories: string | null;
  protein: string | null;
  total_carbohydrate: string | null;
  total_fat: string | null;
}> = {}) {
  return {
    profile: {
      birth_date: "1996-01-15",
      sex_for_equation: "male" as const,
      height_cm: "175",
      height_unit: "cm" as const,
      weight_kg: "70",
      weight_unit: "kg" as const,
      activity_level: "sedentary" as const,
      energy_estimation_context: "general_adult" as const,
    },
    manual_overrides: {
      calories: null,
      protein: null,
      total_carbohydrate: null,
      total_fat: null,
      ...overrides,
    },
  };
}

async function seedProfile(database: LocalSQLiteFixtureDatabase, ownerId: string, timeZone = "UTC") {
  await database.runAsync(
    `INSERT INTO "user_profiles"
      ("user_id", "authoritative_time_zone", "calendar_revision")
     VALUES (?, ?, 1)`,
    [ownerId, timeZone],
  );
}

async function fixtureDatabase(): Promise<LocalSQLiteTestDatabase> {
  const database = new LocalSQLiteTestDatabase();
  await database.initialize();
  await seedLocalOwner(database, OWNER);
  await ensureLocalNutrientCatalog(database.asExpoDatabase());
  await seedProfile(database, OWNER);
  return database;
}

function runtime(database: LocalSQLiteFixtureDatabase, options: ConstructorParameters<typeof LocalTargetsRuntime>[2] = {}) {
  return createLocalTargetsRuntime(database.asExpoDatabase(), OWNER, {
    now: () => new Date("2026-07-14T12:00:00.000Z"),
    ...options,
  });
}

function byId<T extends { nutrientId: string }>(items: readonly T[], nutrientId: string): T {
  const item = items.find((value) => value.nutrientId === nutrientId);
  if (!item) throw new Error(`Missing ${nutrientId}`);
  return item;
}

async function seedFoodAndSnapshot(
  database: LocalSQLiteFixtureDatabase,
  input: {
    ownerId: string;
    foodId: string;
    logId: string;
    snapshotId: string;
    date: string;
    nutrientId: string;
    amount: string | null;
    unit?: string;
    dataStatus?: "known" | "unknown" | "estimated" | "zero";
  },
) {
  await database.runAsync(
    `INSERT INTO "food_items" ("id", "user_id", "name", "source_type", "is_recipe")
     VALUES (?, ?, 'Snapshot Food', 'manual', 0)`,
    [input.foodId, input.ownerId],
  );
  await database.runAsync(
    `INSERT INTO "daily_logs"
      ("id", "user_id", "food_item_id", "logged_date", "amount_quantity", "amount_unit")
     VALUES (?, ?, ?, ?, '1.000000', 'serving')`,
    [input.logId, input.ownerId, input.foodId, input.date],
  );
  await database.runAsync(
    `INSERT INTO "daily_log_nutrient_snapshots"
      ("id", "daily_log_id", "source_food_item_id", "nutrient_id", "amount", "unit", "data_status",
       "consumed_amount_quantity", "consumed_amount_unit")
     VALUES (?, ?, ?, ?, ?, ?, ?, '1.000000', 'serving')`,
    [
      input.snapshotId,
      input.logId,
      input.foodId,
      input.nutrientId,
      input.amount,
      input.unit ?? "g",
      input.dataStatus ?? (input.amount === null ? "unknown" : "known"),
    ],
  );
}

afterEach(() => {
  jest.restoreAllMocks();
});

test("local defaults, explicit overrides, precedence, and reset match remote Target semantics", async () => {
  const database = await fixtureDatabase();
  try {
    const targets = runtime(database);
    const defaults = await targets.getConfiguration();
    expect(defaults.profile).toBeNull();
    expect(defaults.estimatedMaintenanceCalories).toMatchObject({
      availability: "unavailable",
      reasonCode: "target_profile_incomplete",
    });
    expect(byId(defaults.effectiveTargets, "calories")).toMatchObject({
      amount: null,
      authority: "unavailable",
      reasonCode: "target_profile_incomplete",
    });
    expect(byId(defaults.effectiveTargets, "dietary_fiber")).toMatchObject({
      amount: "28",
      authority: "daily_value",
      direction: "minimum",
    });
    expect(byId(defaults.effectiveTargets, "protein")).toMatchObject({
      amount: "50",
      authority: "daily_value",
      direction: "reference",
    });
    expect(byId(defaults.effectiveTargets, "total_carbohydrate")).toMatchObject({
      amount: "275",
      authority: "daily_value",
      direction: "reference",
    });
    expect(byId(defaults.effectiveTargets, "total_fat")).toMatchObject({
      amount: "78",
      authority: "daily_value",
      direction: "reference",
    });

    const updated = await targets.updateConfiguration(targetInput({ calories: "2400", protein: "150" }));
    expect(updated.profile).toMatchObject({ heightCm: "175.000", weightKg: "70.000" });
    expect(updated.estimatedMaintenanceCalories.amount).toBe("2308");
    expect(byId(updated.effectiveTargets, "calories")).toMatchObject({ amount: "2400.000000", authority: "manual_override" });
    expect(byId(updated.effectiveTargets, "protein")).toMatchObject({ amount: "150.000000", authority: "manual_override" });

    const changedProfile = await targets.updateConfiguration(targetInput({ calories: "2400", protein: null }));
    expect(byId(changedProfile.effectiveTargets, "calories")).toMatchObject({ amount: "2400.000000", authority: "manual_override" });
    expect(byId(changedProfile.effectiveTargets, "protein")).toMatchObject({ amount: "56.000000", authority: "calculated_estimate" });
    expect(byId(changedProfile.effectiveTargets, "total_carbohydrate")).toMatchObject({
      amount: "317.350000",
      authority: "calculated_estimate",
      direction: "target",
    });
    expect(byId(changedProfile.effectiveTargets, "total_fat")).toMatchObject({
      amount: "70.522222",
      authority: "calculated_estimate",
      direction: "target",
    });

    const reset = await targets.resetOverride("calories");
    expect(byId(reset.effectiveTargets, "calories")).toMatchObject({ amount: "2308", authority: "calculated_estimate" });
    expect(reset.manualOverrides).toEqual([]);
  } finally {
    database.close();
  }
});

test("personalized iron follows adult age and sex while retaining FDA fallback", async () => {
  const database = await fixtureDatabase();
  try {
    const targets = runtime(database);

    const defaults = await targets.getConfiguration();
    expect(byId(defaults.effectiveTargets, "iron")).toMatchObject({
      amount: "18",
      authority: "daily_value",
      direction: "minimum",
    });

    const male = await targets.updateConfiguration(targetInput());
    expect(byId(male.effectiveTargets, "iron")).toMatchObject({
      amount: "8.000000",
      authority: "calculated_estimate",
      direction: "target",
    });

    const female = await targets.updateConfiguration({
      ...targetInput(),
      profile: {
        ...targetInput().profile,
        sex_for_equation: "female",
      },
    });
    expect(byId(female.effectiveTargets, "iron")).toMatchObject({
      amount: "18.000000",
      authority: "calculated_estimate",
      direction: "target",
    });

    const femaleAge51 = await targets.updateConfiguration({
      ...targetInput(),
      profile: {
        ...targetInput().profile,
        birth_date: "1975-07-14",
        sex_for_equation: "female",
      },
    });
    expect(byId(femaleAge51.effectiveTargets, "iron")).toMatchObject({
      amount: "8.000000",
      authority: "calculated_estimate",
      direction: "target",
    });
  } finally {
    database.close();
  }
});

test("personalized calcium follows adult age and sex while retaining FDA fallback", async () => {
  const database = await fixtureDatabase();
  try {
    const targets = runtime(database);

    const defaults = await targets.getConfiguration();
    expect(byId(defaults.effectiveTargets, "calcium")).toMatchObject({
      amount: "1300",
      authority: "daily_value",
      direction: "minimum",
    });

    const adult = await targets.updateConfiguration(targetInput());
    expect(byId(adult.effectiveTargets, "calcium")).toMatchObject({
      amount: "1000.000000",
      authority: "calculated_estimate",
      direction: "target",
    });

    const femaleAge51 = await targets.updateConfiguration({
      ...targetInput(),
      profile: {
        ...targetInput().profile,
        birth_date: "1975-07-14",
        sex_for_equation: "female",
      },
    });
    expect(byId(femaleAge51.effectiveTargets, "calcium")).toMatchObject({
      amount: "1200.000000",
      authority: "calculated_estimate",
      direction: "target",
    });

    const maleAge70 = await targets.updateConfiguration({
      ...targetInput(),
      profile: {
        ...targetInput().profile,
        birth_date: "1956-07-14",
        sex_for_equation: "male",
      },
    });
    expect(byId(maleAge70.effectiveTargets, "calcium")).toMatchObject({
      amount: "1000.000000",
      authority: "calculated_estimate",
      direction: "target",
    });

    const maleAge71 = await targets.updateConfiguration({
      ...targetInput(),
      profile: {
        ...targetInput().profile,
        birth_date: "1955-07-14",
        sex_for_equation: "male",
      },
    });
    expect(byId(maleAge71.effectiveTargets, "calcium")).toMatchObject({
      amount: "1200.000000",
      authority: "calculated_estimate",
      direction: "target",
    });
  } finally {
    database.close();
  }
});

test("personalized vitamin D follows adult age while retaining FDA fallback", async () => {
  const database = await fixtureDatabase();
  try {
    const targets = runtime(database);

    const defaults = await targets.getConfiguration();
    expect(byId(defaults.effectiveTargets, "vitamin_d")).toMatchObject({
      amount: "20",
      authority: "daily_value",
      direction: "minimum",
    });

    const adult = await targets.updateConfiguration(targetInput());
    expect(byId(adult.effectiveTargets, "vitamin_d")).toMatchObject({
      amount: "15.000000",
      authority: "calculated_estimate",
      direction: "target",
    });

    const age70 = await targets.updateConfiguration({
      ...targetInput(),
      profile: {
        ...targetInput().profile,
        birth_date: "1956-07-14",
      },
    });
    expect(byId(age70.effectiveTargets, "vitamin_d")).toMatchObject({
      amount: "15.000000",
      authority: "calculated_estimate",
      direction: "target",
    });

    const age71 = await targets.updateConfiguration({
      ...targetInput(),
      profile: {
        ...targetInput().profile,
        birth_date: "1955-07-14",
      },
    });
    expect(byId(age71.effectiveTargets, "vitamin_d")).toMatchObject({
      amount: "20.000000",
      authority: "calculated_estimate",
      direction: "target",
    });
  } finally {
    database.close();
  }
});

test("personalized potassium follows adult sex while retaining FDA fallback", async () => {
  const database = await fixtureDatabase();
  try {
    const targets = runtime(database);

    const defaults = await targets.getConfiguration();
    expect(byId(defaults.effectiveTargets, "potassium")).toMatchObject({
      amount: "4700",
      authority: "daily_value",
      direction: "minimum",
    });

    const male = await targets.updateConfiguration(targetInput());
    expect(byId(male.effectiveTargets, "potassium")).toMatchObject({
      amount: "3400.000000",
      authority: "calculated_estimate",
      direction: "target",
    });

    const female = await targets.updateConfiguration({
      ...targetInput(),
      profile: {
        ...targetInput().profile,
        sex_for_equation: "female",
      },
    });
    expect(byId(female.effectiveTargets, "potassium")).toMatchObject({
      amount: "2600.000000",
      authority: "calculated_estimate",
      direction: "target",
    });
  } finally {
    database.close();
  }
});

test("personalized magnesium follows adult age and sex while retaining FDA fallback", async () => {
  const database = await fixtureDatabase();
  try {
    const targets = runtime(database);

    const defaults = await targets.getConfiguration();
    expect(byId(defaults.effectiveTargets, "magnesium")).toMatchObject({
      amount: "420",
      authority: "daily_value",
      direction: "reference",
    });

    const maleAge30 = await targets.updateConfiguration({
      ...targetInput(),
      profile: {
        ...targetInput().profile,
        birth_date: "1996-07-14",
        sex_for_equation: "male",
      },
    });
    expect(byId(maleAge30.effectiveTargets, "magnesium")).toMatchObject({
      amount: "400.000000",
      authority: "calculated_estimate",
      direction: "target",
    });

    const maleAge31 = await targets.updateConfiguration({
      ...targetInput(),
      profile: {
        ...targetInput().profile,
        birth_date: "1995-07-14",
        sex_for_equation: "male",
      },
    });
    expect(byId(maleAge31.effectiveTargets, "magnesium")).toMatchObject({
      amount: "420.000000",
      authority: "calculated_estimate",
      direction: "target",
    });

    const femaleAge30 = await targets.updateConfiguration({
      ...targetInput(),
      profile: {
        ...targetInput().profile,
        birth_date: "1996-07-14",
        sex_for_equation: "female",
      },
    });
    expect(byId(femaleAge30.effectiveTargets, "magnesium")).toMatchObject({
      amount: "310.000000",
      authority: "calculated_estimate",
      direction: "target",
    });

    const femaleAge31 = await targets.updateConfiguration({
      ...targetInput(),
      profile: {
        ...targetInput().profile,
        birth_date: "1995-07-14",
        sex_for_equation: "female",
      },
    });
    expect(byId(femaleAge31.effectiveTargets, "magnesium")).toMatchObject({
      amount: "320.000000",
      authority: "calculated_estimate",
      direction: "target",
    });
  } finally {
    database.close();
  }
});

test("personalized fiber follows adult age and sex while retaining FDA fallback", async () => {
  const database = await fixtureDatabase();
  try {
    const targets = runtime(database);

    const defaults = await targets.getConfiguration();
    expect(byId(defaults.effectiveTargets, "dietary_fiber")).toMatchObject({
      amount: "28",
      authority: "daily_value",
      direction: "minimum",
    });

    const maleAge50 = await targets.updateConfiguration({
      ...targetInput(),
      profile: {
        ...targetInput().profile,
        birth_date: "1976-07-14",
        sex_for_equation: "male",
      },
    });
    expect(byId(maleAge50.effectiveTargets, "dietary_fiber")).toMatchObject({
      amount: "38.000000",
      authority: "calculated_estimate",
      direction: "target",
    });

    const maleAge51 = await targets.updateConfiguration({
      ...targetInput(),
      profile: {
        ...targetInput().profile,
        birth_date: "1975-07-14",
        sex_for_equation: "male",
      },
    });
    expect(byId(maleAge51.effectiveTargets, "dietary_fiber")).toMatchObject({
      amount: "30.000000",
      authority: "calculated_estimate",
      direction: "target",
    });

    const femaleAge50 = await targets.updateConfiguration({
      ...targetInput(),
      profile: {
        ...targetInput().profile,
        birth_date: "1976-07-14",
        sex_for_equation: "female",
      },
    });
    expect(byId(femaleAge50.effectiveTargets, "dietary_fiber")).toMatchObject({
      amount: "25.000000",
      authority: "calculated_estimate",
      direction: "target",
    });

    const femaleAge51 = await targets.updateConfiguration({
      ...targetInput(),
      profile: {
        ...targetInput().profile,
        birth_date: "1975-07-14",
        sex_for_equation: "female",
      },
    });
    expect(byId(femaleAge51.effectiveTargets, "dietary_fiber")).toMatchObject({
      amount: "21.000000",
      authority: "calculated_estimate",
      direction: "target",
    });
  } finally {
    database.close();
  }
});

test("personalized saturated fat uses ten percent of maintenance energy while retaining FDA fallback", async () => {
  const database = await fixtureDatabase();
  try {
    const targets = runtime(database);

    const defaults = await targets.getConfiguration();
    expect(byId(defaults.effectiveTargets, "saturated_fat")).toMatchObject({
      amount: "20",
      authority: "daily_value",
      direction: "limit",
    });

    const personalized = await targets.updateConfiguration(targetInput());
    expect(personalized.estimatedMaintenanceCalories.amount).toBe("2308");
    expect(byId(personalized.effectiveTargets, "saturated_fat")).toMatchObject({
      amount: "25.644444",
      authority: "calculated_estimate",
      direction: "limit",
    });
  } finally {
    database.close();
  }
});

test("sodium retains the FDA limit when general-adult personalization is available", async () => {
  const database = await fixtureDatabase();
  try {
    const targets = runtime(database);

    const defaults = await targets.getConfiguration();
    expect(byId(defaults.effectiveTargets, "sodium")).toMatchObject({
      amount: "2300",
      authority: "daily_value",
      direction: "limit",
    });

    const personalized = await targets.updateConfiguration(targetInput());
    expect(byId(personalized.effectiveTargets, "sodium")).toMatchObject({
      amount: "2300",
      authority: "daily_value",
      direction: "limit",
    });
  } finally {
    database.close();
  }
});

test("added sugars retain the FDA limit when general-adult personalization is available", async () => {
  const database = await fixtureDatabase();
  try {
    const targets = runtime(database);

    const defaults = await targets.getConfiguration();
    expect(byId(defaults.effectiveTargets, "added_sugars")).toMatchObject({
      amount: "50",
      authority: "daily_value",
      direction: "limit",
    });

    const personalized = await targets.updateConfiguration(targetInput());
    expect(byId(personalized.effectiveTargets, "added_sugars")).toMatchObject({
      amount: "50",
      authority: "daily_value",
      direction: "limit",
    });
  } finally {
    database.close();
  }
});

test("cholesterol retains the FDA limit when general-adult personalization is available", async () => {
  const database = await fixtureDatabase();
  try {
    const targets = runtime(database);

    const defaults = await targets.getConfiguration();
    expect(byId(defaults.effectiveTargets, "cholesterol")).toMatchObject({
      amount: "300",
      authority: "daily_value",
      direction: "limit",
    });

    const personalized = await targets.updateConfiguration(targetInput());
    expect(byId(personalized.effectiveTargets, "cholesterol")).toMatchObject({
      amount: "300",
      authority: "daily_value",
      direction: "limit",
    });
  } finally {
    database.close();
  }
});

test("trans fat and total sugars remain unavailable when personalization is available", async () => {
  const database = await fixtureDatabase();
  try {
    const targets = runtime(database);

    const defaults = await targets.getConfiguration();

    expect(byId(defaults.effectiveTargets, "trans_fat")).toMatchObject({
      amount: null,
      authority: "unavailable",
      direction: "unavailable",
      noteCode: "daily_value_not_established",
    });
    expect(byId(defaults.effectiveTargets, "total_sugars")).toMatchObject({
      amount: null,
      authority: "unavailable",
      direction: "unavailable",
      noteCode: "daily_value_not_established",
    });

    const personalized = await targets.updateConfiguration(targetInput());

    expect(byId(personalized.effectiveTargets, "trans_fat")).toMatchObject({
      amount: null,
      authority: "unavailable",
      direction: "unavailable",
      noteCode: "daily_value_not_established",
    });
    expect(byId(personalized.effectiveTargets, "total_sugars")).toMatchObject({
      amount: null,
      authority: "unavailable",
      direction: "unavailable",
      noteCode: "daily_value_not_established",
    });
  } finally {
    database.close();
  }
});

test("incomplete, unsupported, and age-limited profiles remain explicitly unavailable", async () => {
  const database = await fixtureDatabase();
  try {
    const targets = runtime(database);
    const unsupported = await targets.updateConfiguration({
      ...targetInput(),
      profile: { ...targetInput().profile, energy_estimation_context: "pregnant" },
    });
    expect(unsupported.estimatedMaintenanceCalories).toMatchObject({
      availability: "unavailable",
      amount: null,
      reasonCode: "target_estimate_unsupported_context",
    });
    expect(byId(unsupported.effectiveTargets, "protein")).toMatchObject({
      amount: "50",
      authority: "daily_value",
      direction: "reference",
    });

    const ageLimited = await targets.updateConfiguration({
      ...targetInput(),
      profile: { ...targetInput().profile, birth_date: "2010-01-01" },
    });
    expect(ageLimited.estimatedMaintenanceCalories.reasonCode).toBe("target_estimate_unsupported_age");
    expect(byId(ageLimited.effectiveTargets, "calories")).toMatchObject({ authority: "unavailable", reasonCode: "target_estimate_unsupported_age" });
    expect(byId(ageLimited.effectiveTargets, "protein")).toMatchObject({
      amount: "50",
      authority: "daily_value",
      direction: "reference",
    });
  } finally {
    database.close();
  }
});

test("target validation preserves remote structural and domain error contracts", async () => {
  const database = await fixtureDatabase();
  try {
    const targets = runtime(database);
    await expect(targets.updateConfiguration(targetInput({ calories: "1e3" }))).rejects.toMatchObject({
      kind: "validation",
      code: "invalid_target_request",
      details: {
        code: "invalid_target_request",
        field_errors: [{ field: "manual_overrides.calories", code: "target_value_out_of_range" }],
      },
      fieldErrors: [{ field: "manual_overrides.calories", code: "target_value_out_of_range" }],
    });

    const invalidUnit = {
      ...targetInput(),
      profile: { ...targetInput().profile, height_unit: "in" },
    } as unknown as Parameters<LocalTargetsRuntime["updateConfiguration"]>[0];
    await expect(targets.updateConfiguration(invalidUnit)).rejects.toMatchObject({
      code: "invalid_target_request",
      details: {
        code: "invalid_target_request",
        field_errors: [{ field: "profile.height_unit", code: "target_unit_invalid" }],
      },
      fieldErrors: [{ field: "profile.height_unit", code: "target_unit_invalid" }],
    });

    await expect(targets.updateConfiguration({
      ...targetInput(),
      profile: { ...targetInput().profile, height_cm: "99" },
    })).rejects.toMatchObject({
      code: "target_value_out_of_range",
      details: {
        code: "target_value_out_of_range",
        field_errors: [{ field: "profile.height_cm", code: "target_value_out_of_range" }],
      },
    });

    await expect(targets.getDailyComparison("2026-02-30")).rejects.toMatchObject({
      kind: "validation",
      code: "invalid_target_request",
      details: {
        code: "invalid_target_request",
        field_errors: [{ field: "date", code: "target_value_out_of_range" }],
      },
      fieldErrors: [{ field: "date", code: "target_value_out_of_range" }],
    });
  } finally {
    database.close();
  }
});

test("daily comparison uses immutable snapshots, date isolation, unknown semantics, and exact percentages", async () => {
  const database = await fixtureDatabase();
  try {
    await seedFoodAndSnapshot(database, {
      ownerId: OWNER,
      foodId: FOOD,
      logId: "00000000-0000-4000-8000-000000000201",
      snapshotId: "00000000-0000-4000-8000-000000000301",
      date: "2026-07-14",
      nutrientId: "protein",
      amount: "75.123456",
    });
    await seedFoodAndSnapshot(database, {
      ownerId: OWNER,
      foodId: "00000000-0000-4000-8000-000000000103",
      logId: "00000000-0000-4000-8000-000000000202",
      snapshotId: "00000000-0000-4000-8000-000000000302",
      date: "2026-07-15",
      nutrientId: "protein",
      amount: "999.000000",
    });
    await seedFoodAndSnapshot(database, {
      ownerId: OWNER,
      foodId: "00000000-0000-4000-8000-000000000104",
      logId: "00000000-0000-4000-8000-000000000203",
      snapshotId: "00000000-0000-4000-8000-000000000303",
      date: "2026-07-14",
      nutrientId: "sodium",
      amount: null,
      unit: "mg",
    });
    await seedFoodAndSnapshot(database, {
      ownerId: OWNER,
      foodId: "00000000-0000-4000-8000-000000000105",
      logId: "00000000-0000-4000-8000-000000000204",
      snapshotId: "00000000-0000-4000-8000-000000000304",
      date: "2026-07-16",
      nutrientId: "protein",
      amount: "0.000000",
      dataStatus: "zero",
    });
    await seedFoodAndSnapshot(database, {
      ownerId: OWNER,
      foodId: "00000000-0000-4000-8000-000000000106",
      logId: "00000000-0000-4000-8000-000000000205",
      snapshotId: "00000000-0000-4000-8000-000000000305",
      date: "2026-07-17",
      nutrientId: "protein",
      amount: "25.000000",
    });
    const targets = runtime(database);
    await targets.updateConfiguration(targetInput({ protein: "50" }));

    const comparison = await targets.getDailyComparison("2026-07-14");
    const protein = byId(comparison.comparisons, "protein");
    expect(protein).toMatchObject({
      consumedAmount: "75.123456",
      targetAmount: "50.000000",
      percentage: "150.2469",
      status: "available",
      authority: "manual_override",
    });
    expect(protein.hasUnknownContributors).toBe(false);
    expect(byId(comparison.comparisons, "sodium")).toMatchObject({
      consumedAmount: null,
      targetAmount: "2300",
      percentage: null,
      status: "consumed_unavailable",
      reasonCode: "consumed_value_unavailable",
      hasUnknownContributors: true,
    });
    expect(byId(comparison.comparisons, "total_sugars")).toMatchObject({
      targetAmount: null,
      status: "target_unavailable",
      authority: "unavailable",
    });

    const otherDate = await targets.getDailyComparison("2026-07-15");
    expect(byId(otherDate.comparisons, "protein").consumedAmount).toBe("999.000000");
    expect(byId(otherDate.comparisons, "protein").percentage).toBe("1998.0000");

    const zeroDate = await targets.getDailyComparison("2026-07-16");
    expect(byId(zeroDate.comparisons, "protein").percentage).toBe("0.0000");

    const halfTargetDate = await targets.getDailyComparison("2026-07-17");
    expect(byId(halfTargetDate.comparisons, "protein").percentage).toBe("50.0000");
  } finally {
    database.close();
  }
});

test("target reads and mutations are owner-scoped and mutation failures roll back completely", async () => {
  const database = await fixtureDatabase();
  try {
    await seedLocalOwner(database, OTHER_OWNER);
    await seedProfile(database, OTHER_OWNER);
    const ownerTargets = runtime(database);
    const otherTargets = createLocalTargetsRuntime(database.asExpoDatabase(), OTHER_OWNER, {
      now: () => new Date("2026-07-14T12:00:00.000Z"),
    });
    await ownerTargets.updateConfiguration(targetInput({ protein: "90" }));
    await otherTargets.updateConfiguration({ ...targetInput(), manual_overrides: { calories: null, protein: "110", total_carbohydrate: null, total_fat: null } });
    expect(byId((await ownerTargets.getConfiguration()).manualOverrides, "protein").amount).toBe("90.000000");
    expect(byId((await otherTargets.getConfiguration()).manualOverrides, "protein").amount).toBe("110.000000");

    let fail = true;
    const failing = createLocalTargetsRuntime(database.asExpoDatabase(), OWNER, {
      now: () => new Date("2026-07-14T12:00:00.000Z"),
      onMutationStage: async (stage) => {
        if (stage === "after_write" && fail) {
          fail = false;
          throw new Error("forced target rollback");
        }
      },
    });
    await expect(failing.updateConfiguration(targetInput({ protein: "333" }))).rejects.toMatchObject({
      code: "local_target_mutation_failed",
      mutationOutcome: "confirmed_non_commit",
    });
    expect(byId((await ownerTargets.getConfiguration()).manualOverrides, "protein").amount).toBe("90.000000");
    expect(byId((await otherTargets.getConfiguration()).manualOverrides, "protein").amount).toBe("110.000000");
  } finally {
    database.close();
  }
});

test("reset failures roll back the deleted override completely", async () => {
  const database = await fixtureDatabase();
  try {
    const targets = runtime(database);
    await targets.updateConfiguration(targetInput({ protein: "90" }));
    let fail = true;
    const failing = createLocalTargetsRuntime(database.asExpoDatabase(), OWNER, {
      now: () => new Date("2026-07-14T12:00:00.000Z"),
      onMutationStage: async (stage) => {
        if (stage === "after_write" && fail) {
          fail = false;
          throw new Error("forced reset rollback");
        }
      },
    });

    await expect(failing.resetOverride("protein")).rejects.toMatchObject({
      code: "local_target_mutation_failed",
      mutationOutcome: "confirmed_non_commit",
    });
    expect(byId((await targets.getConfiguration()).manualOverrides, "protein").amount).toBe("90.000000");
  } finally {
    database.close();
  }
});

test("overlapping local updates serialize and ordered reads wait for the uncommitted writer", async () => {
  const directory = mkdtempSync(join(tmpdir(), "nutrition-e2-12-targets-"));
  const path = join(directory, "targets.sqlite");
  const database = new ExpoIsolatedSQLiteTestDatabase(path);
  try {
    await database.initialize();
    await seedLocalOwner(database, OWNER);
    await ensureLocalNutrientCatalog(database.asExpoDatabase());
    await seedProfile(database, OWNER);
    let held = false;
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const targets = runtime(database, {
      onMutationStage: async (stage) => {
        if (stage === "after_write" && !held) {
          held = true;
          await gate;
        }
      },
    });
    const first = targets.updateConfiguration(targetInput({ protein: "90" }));
    for (let attempt = 0; attempt < 100 && !held; attempt += 1) {
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    }
    expect(held).toBe(true);
    const second = targets.updateConfiguration(targetInput({ protein: "110" }));
    let readSettled = false;
    const read = targets.getConfiguration().then(() => { readSettled = true; });
    await Promise.resolve();
    expect(readSettled).toBe(false);
    release();
    await first;
    await second;
    await read;
    expect(byId((await targets.getConfiguration()).manualOverrides, "protein").amount).toBe("110.000000");
  } finally {
    database.close();
    rmSync(directory, { recursive: true, force: true });
  }
});

test("reset and update share the serialized local write coordinator", async () => {
  const directory = mkdtempSync(join(tmpdir(), "nutrition-e2-12-targets-reset-"));
  const path = join(directory, "targets.sqlite");
  const database = new ExpoIsolatedSQLiteTestDatabase(path);
  try {
    await database.initialize();
    await seedLocalOwner(database, OWNER);
    await ensureLocalNutrientCatalog(database.asExpoDatabase());
    await seedProfile(database, OWNER);
    const seeded = runtime(database);
    await seeded.updateConfiguration(targetInput({ protein: "90" }));

    let held = false;
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const resetter = createLocalTargetsRuntime(database.asExpoDatabase(), OWNER, {
      now: () => new Date("2026-07-14T12:00:00.000Z"),
      onMutationStage: async (stage) => {
        if (stage === "after_write" && !held) {
          held = true;
          await gate;
        }
      },
    });
    const updater = runtime(database);
    const reset = resetter.resetOverride("protein");
    for (let attempt = 0; attempt < 100 && !held; attempt += 1) {
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    }
    expect(held).toBe(true);

    const update = updater.updateConfiguration(targetInput({ protein: "110" }));
    let updateSettled = false;
    void update.then(() => { updateSettled = true; });
    await Promise.resolve();
    expect(updateSettled).toBe(false);

    release();
    await reset;
    await update;
    expect(byId((await updater.getConfiguration()).manualOverrides, "protein").amount).toBe("110.000000");
  } finally {
    database.close();
    rmSync(directory, { recursive: true, force: true });
  }
});
