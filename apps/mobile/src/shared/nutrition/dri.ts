import {
  DRI_DATASET_VERSION,
  DRI_NO_GOAL,
  DRI_RECOMMENDATIONS,
  DRI_UPPER_LIMITS,
  type DriLifeStage,
  type DriNoGoalData,
  type DriRecommendationDataRow,
  type DriUpperLimitDataRow,
} from "./driData";

import {
  multiplyResponseDecimalsInContext,
  NUMERIC_14_6,
  parseDecimal,
} from "../exact/decimal";


export type DriSex =
  | "female"
  | "male";

export type DriUpperLimit = Readonly<{
  amount: string;
  unit: string;
  sourceVersion: string;
  sourceId: string;
  scope: string;
  comparableToRecommendation: boolean;
}>;

export type DriRecommendation = Readonly<{
  nutrientId: string;
  availability: "available" | "unavailable";
  amount: string | null;
  unit: string | null;
  referenceType: "RDA" | "AI" | null;
  sourceVersion: string;
  sourceId: string | null;
  age: number | null;
  sex: DriSex | null;
  lifeStage: DriLifeStage | null;
  calculationBasis: "fixed" | "per_kg" | null;
  weightKg: string | null;
  upperLimit: DriUpperLimit | null;
  reasonCode: string | null;
}>;


function dateParts(
  value: string,
): Readonly<{
  year: number;
  month: number;
  day: number;
}> {
  const match =
    /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);

  if (!match) {
    throw new Error(
      "DRI dates must use canonical YYYY-MM-DD form.",
    );
  }

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);

  const check =
    new Date(Date.UTC(year, month - 1, day));

  if (
    check.getUTCFullYear() !== year
    || check.getUTCMonth() !== month - 1
    || check.getUTCDate() !== day
  ) {
    throw new Error(
      "DRI date is not a valid calendar date.",
    );
  }

  return {
    year,
    month,
    day,
  };
}


export function ageOn(
  birthDate: string,
  asOf: string,
): number {
  const birth = dateParts(birthDate);
  const current = dateParts(asOf);

  return (
    current.year
    - birth.year
    - (
      current.month < birth.month
      || (
        current.month === birth.month
        && current.day < birth.day
      )
        ? 1
        : 0
    )
  );
}


function unavailable(
  nutrientId: string,
  reasonCode: string,
  options: Readonly<{
    age?: number | null;
    sex?: DriSex | null;
    lifeStage?: DriLifeStage | null;
    sourceId?: string | null;
    upperLimit?: DriUpperLimit | null;
  }> = {},
): DriRecommendation {
  return {
    nutrientId,
    availability: "unavailable",
    amount: null,
    unit: null,
    referenceType: null,
    sourceVersion: DRI_DATASET_VERSION,
    sourceId: options.sourceId ?? null,
    age: options.age ?? null,
    sex: options.sex ?? null,
    lifeStage: options.lifeStage ?? null,
    calculationBasis: null,
    weightKg: null,
    upperLimit: options.upperLimit ?? null,
    reasonCode,
  };
}


function selectorMatches(
  row:
    | DriRecommendationDataRow
    | DriUpperLimitDataRow,
  age: number,
  sex: DriSex | null,
  lifeStage: DriLifeStage,
): boolean {
  return (
    row.life_stage === lifeStage
    && row.age_min <= age
    && (
      row.age_max === null
      || age <= row.age_max
    )
    && (
      row.sex === "any"
      || (
        sex !== null
        && row.sex === sex
      )
    )
  );
}


function matchingRecommendation(
  nutrientId: string,
  age: number,
  sex: DriSex | null,
  lifeStage: DriLifeStage,
): DriRecommendationDataRow | null {
  const matches =
    DRI_RECOMMENDATIONS.filter(
      (row) =>
        row.nutrient_id === nutrientId
        && selectorMatches(
          row,
          age,
          sex,
          lifeStage,
        ),
    );

  if (matches.length > 1) {
    throw new Error(
      "Canonical DRI recommendation data "
      + `resolved ambiguously for ${nutrientId}.`,
    );
  }

  return matches[0] ?? null;
}


function matchingUpperLimit(
  nutrientId: string,
  age: number,
  sex: DriSex | null,
  lifeStage: DriLifeStage,
): DriUpperLimitDataRow | null {
  const matches =
    DRI_UPPER_LIMITS.filter(
      (row) =>
        row.nutrient_id === nutrientId
        && selectorMatches(
          row,
          age,
          sex,
          lifeStage,
        ),
    );

  if (matches.length > 1) {
    throw new Error(
      "Canonical DRI UL data "
      + `resolved ambiguously for ${nutrientId}.`,
    );
  }

  return matches[0] ?? null;
}


function resolveUpperLimit(
  nutrientId: string,
  age: number,
  sex: DriSex | null,
  lifeStage: DriLifeStage,
): DriUpperLimit | null {
  const row = matchingUpperLimit(
    nutrientId,
    age,
    sex,
    lifeStage,
  );

  if (!row) {
    return null;
  }

  return {
    amount: parseDecimal(
      row.amount,
      NUMERIC_14_6,
    ),
    unit: row.unit,
    sourceVersion: DRI_DATASET_VERSION,
    sourceId: row.source_id,
    scope: row.scope,
    comparableToRecommendation:
      row.comparable_to_recommendation,
  };
}


export function resolveDriRecommendation(
  nutrientId: string,
  input: Readonly<{
    birthDate: string | null;
    sex: DriSex | null;
    lifeStage:
      | DriLifeStage
      | "specialized_medical"
      | string;
    weightKg: string | null;
    asOf: string;
  }>,
): DriRecommendation {
  const noGoal = (
    DRI_NO_GOAL as Readonly<
      Record<string, DriNoGoalData>
    >
  )[nutrientId];

  if (noGoal) {
    return unavailable(
      nutrientId,
      noGoal.reason_code,
      {
        sourceId: noGoal.source_id,
      },
    );
  }

  if (
    input.lifeStage ===
    "specialized_medical"
  ) {
    return unavailable(
      nutrientId,
      "dri_unsupported_medical_context",
    );
  }

  if (
    input.lifeStage !== "general_adult"
    && input.lifeStage !== "pregnant"
    && input.lifeStage !== "lactating"
  ) {
    return unavailable(
      nutrientId,
      "dri_unsupported_life_stage",
    );
  }

  const lifeStage: DriLifeStage =
    input.lifeStage;

  if (input.birthDate === null) {
    return unavailable(
      nutrientId,
      "dri_birth_date_required",
      {
        sex: input.sex,
        lifeStage,
      },
    );
  }

  const age = ageOn(
    input.birthDate,
    input.asOf,
  );

  if (age < 19 || age > 120) {
    return unavailable(
      nutrientId,
      "dri_unsupported_age",
      {
        age,
        sex: input.sex,
        lifeStage,
      },
    );
  }

  if (
    lifeStage === "pregnant"
    || lifeStage === "lactating"
  ) {
    if (input.sex === null) {
      return unavailable(
        nutrientId,
        "dri_reference_sex_required",
        {
          age,
          sex: null,
          lifeStage,
        },
      );
    }

    if (
      input.sex !== "female"
      || age > 50
    ) {
      return unavailable(
        nutrientId,
        "dri_unsupported_life_stage",
        {
          age,
          sex: input.sex,
          lifeStage,
        },
      );
    }
  }

  const upperLimit = resolveUpperLimit(
    nutrientId,
    age,
    input.sex,
    lifeStage,
  );

  const row = matchingRecommendation(
    nutrientId,
    age,
    input.sex,
    lifeStage,
  );

  if (!row) {
    const candidates =
      DRI_RECOMMENDATIONS.filter(
        (candidate) =>
          candidate.nutrient_id === nutrientId
          && candidate.life_stage === lifeStage
          && candidate.age_min <= age
          && (
            candidate.age_max === null
            || age <= candidate.age_max
          ),
      );

    if (
      input.sex === null
      && candidates.some(
        (candidate) =>
          candidate.sex !== "any",
      )
    ) {
      return unavailable(
        nutrientId,
        "dri_reference_sex_required",
        {
          age,
          sex: null,
          lifeStage,
          upperLimit,
        },
      );
    }

    return unavailable(
      nutrientId,
      "dri_recommendation_not_established",
      {
        age,
        sex: input.sex,
        lifeStage,
        upperLimit,
      },
    );
  }

  let amount: string;
  let calculationBasis:
    | "fixed"
    | "per_kg";
  let usedWeight: string | null = null;

  if (row.calculation.kind === "fixed") {
    amount = parseDecimal(
      row.calculation.amount,
      NUMERIC_14_6,
    );

    calculationBasis = "fixed";

  } else {
    if (input.weightKg === null) {
      return unavailable(
        nutrientId,
        "dri_weight_required",
        {
          age,
          sex: input.sex,
          lifeStage,
          sourceId: row.source_id,
          upperLimit,
        },
      );
    }

    let weight: string;

    try {
      weight = parseDecimal(
        input.weightKg,
        NUMERIC_14_6,
      );
    } catch {
      return unavailable(
        nutrientId,
        "dri_weight_invalid",
        {
          age,
          sex: input.sex,
          lifeStage,
          sourceId: row.source_id,
          upperLimit,
        },
      );
    }

    if (
      /^0(?:\.0+)?$/.test(weight)
    ) {
      return unavailable(
        nutrientId,
        "dri_weight_invalid",
        {
          age,
          sex: input.sex,
          lifeStage,
          sourceId: row.source_id,
          upperLimit,
        },
      );
    }

    amount = parseDecimal(
      multiplyResponseDecimalsInContext(
        weight,
        row.calculation.factor,
      ),
      NUMERIC_14_6,
    );

    calculationBasis = "per_kg";
    usedWeight = weight;
  }

  return {
    nutrientId,
    availability: "available",
    amount,
    unit: row.unit,
    referenceType: row.reference_type,
    sourceVersion: DRI_DATASET_VERSION,
    sourceId: row.source_id,
    age,
    sex: input.sex,
    lifeStage,
    calculationBasis,
    weightKg: usedWeight,
    upperLimit,
    reasonCode: null,
  };
}
