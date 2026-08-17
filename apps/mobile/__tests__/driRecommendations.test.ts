import {
  ageOn,
  resolveDriRecommendation,
} from "../src/shared/nutrition/dri";

import {
  DRI_DATASET_VERSION,
  DRI_RECOMMENDATIONS,
} from "../src/shared/nutrition/driData";


const AS_OF = "2026-08-17";

function birthDateForAge(
  age: number,
): string {
  return `${2026 - age}-08-17`;
}

function resolve(
  nutrientId: string,
  options: Partial<{
    age: number;
    sex: "female" | "male" | null;
    lifeStage:
      | "general_adult"
      | "pregnant"
      | "lactating"
      | "specialized_medical";
    weightKg: string | null;
  }> = {},
) {
  return resolveDriRecommendation(
    nutrientId,
    {
      birthDate:
        birthDateForAge(
          options.age ?? 37,
        ),
      sex:
        options.sex === undefined
          ? "male"
          : options.sex,
      lifeStage:
        options.lifeStage
        ?? "general_adult",
      weightKg:
        options.weightKg === undefined
          ? "70"
          : options.weightKg,
      asOf: AS_OF,
    },
  );
}


test(
  "DRI generated dataset is explicitly versioned",
  () => {
    expect(
      DRI_DATASET_VERSION,
    ).toBe(
      "nasem_dri_adults_2026_v1",
    );

    expect(
      DRI_RECOMMENDATIONS,
    ).toHaveLength(134);
  },
);


test(
  "age calculation changes on the birthday",
  () => {
    expect(
      ageOn(
        "1989-08-17",
        "2026-08-16",
      ),
    ).toBe(36);

    expect(
      ageOn(
        "1989-08-17",
        "2026-08-17",
      ),
    ).toBe(37);
  },
);


test.each([
  ["magnesium", 30, "male", "400.000000", "RDA"],
  ["magnesium", 31, "male", "420.000000", "RDA"],
  ["magnesium", 30, "female", "310.000000", "RDA"],
  ["magnesium", 31, "female", "320.000000", "RDA"],
  ["calcium", 50, "female", "1000.000000", "RDA"],
  ["calcium", 51, "female", "1200.000000", "RDA"],
  ["vitamin_d", 70, "male", "15.000000", "RDA"],
  ["vitamin_d", 71, "male", "20.000000", "RDA"],
  ["chloride", 50, "male", "2300.000000", "AI"],
  ["chloride", 51, "male", "2000.000000", "AI"],
  ["chloride", 70, "male", "2000.000000", "AI"],
  ["chloride", 71, "male", "1800.000000", "AI"],
] as const)(
  "resolves %s at age %i for %s",
  (
    nutrientId,
    age,
    sex,
    expected,
    referenceType,
  ) => {
    const result = resolve(
      nutrientId,
      {
        age,
        sex,
      },
    );

    expect(
      result.availability,
    ).toBe("available");

    expect(result.amount).toBe(expected);

    expect(
      result.referenceType,
    ).toBe(referenceType);
  },
);


test(
  "RDA and AI identity remain distinct",
  () => {
    const vitaminC = resolve(
      "vitamin_c",
      {
        sex: "female",
      },
    );

    const potassium = resolve(
      "potassium",
      {
        sex: "female",
      },
    );

    expect(
      vitaminC.referenceType,
    ).toBe("RDA");

    expect(
      vitaminC.amount,
    ).toBe("75.000000");

    expect(
      potassium.referenceType,
    ).toBe("AI");

    expect(
      potassium.amount,
    ).toBe("2600.000000");
  },
);


test(
  "fixed micronutrients do not scale with weight",
  () => {
    const light = resolve(
      "vitamin_c",
      {
        sex: "female",
        weightKg: "50",
      },
    );

    const heavy = resolve(
      "vitamin_c",
      {
        sex: "female",
        weightKg: "120",
      },
    );

    expect(light.amount).toBe("75.000000");
    expect(heavy.amount).toBe("75.000000");

    expect(
      light.calculationBasis,
    ).toBe("fixed");

    expect(
      heavy.calculationBasis,
    ).toBe("fixed");

    expect(light.weightKg).toBeNull();
    expect(heavy.weightKg).toBeNull();
  },
);


test(
  "protein alone uses the weight-derived DRI calculation",
  () => {
    const seventy = resolve(
      "protein",
      {
        weightKg: "70",
      },
    );

    const eighty = resolve(
      "protein",
      {
        weightKg: "80",
      },
    );

    expect(
      seventy.amount,
    ).toBe("56.000000");

    expect(
      eighty.amount,
    ).toBe("64.000000");

    expect(
      seventy.calculationBasis,
    ).toBe("per_kg");

    expect(
      seventy.weightKg,
    ).toBe("70.000000");
  },
);


test(
  "protein requires weight while fixed recommendations do not",
  () => {
    const protein = resolve(
      "protein",
      {
        weightKg: null,
      },
    );

    const vitaminC = resolve(
      "vitamin_c",
      {
        weightKg: null,
      },
    );

    expect(
      protein.availability,
    ).toBe("unavailable");

    expect(
      protein.reasonCode,
    ).toBe("dri_weight_required");

    expect(
      vitaminC.availability,
    ).toBe("available");
  },
);


test(
  "pregnancy and lactation are explicit selections",
  () => {
    const pregnant = resolve(
      "iron",
      {
        sex: "female",
        lifeStage: "pregnant",
      },
    );

    const lactating = resolve(
      "iron",
      {
        sex: "female",
        lifeStage: "lactating",
      },
    );

    const ordinary = resolve(
      "iron",
      {
        sex: "female",
        lifeStage: "general_adult",
      },
    );

    expect(
      pregnant.amount,
    ).toBe("27.000000");

    expect(
      lactating.amount,
    ).toBe("9.000000");

    expect(
      ordinary.amount,
    ).toBe("18.000000");
  },
);


test(
  "pregnancy and lactation protein use their own per-kg factors",
  () => {
    const pregnant = resolve(
      "protein",
      {
        sex: "female",
        lifeStage: "pregnant",
        weightKg: "70",
      },
    );

    const lactating = resolve(
      "protein",
      {
        sex: "female",
        lifeStage: "lactating",
        weightKg: "70",
      },
    );

    expect(
      pregnant.amount,
    ).toBe("77.000000");

    expect(
      lactating.amount,
    ).toBe("91.000000");
  },
);


test(
  "unsupported pregnancy reference states fail closed",
  () => {
    expect(
      resolve(
        "folate",
        {
          sex: "male",
          lifeStage: "pregnant",
        },
      ).reasonCode,
    ).toBe(
      "dri_unsupported_life_stage",
    );

    expect(
      resolve(
        "folate",
        {
          age: 51,
          sex: "female",
          lifeStage: "pregnant",
        },
      ).reasonCode,
    ).toBe(
      "dri_unsupported_life_stage",
    );

    expect(
      resolve(
        "folate",
        {
          sex: null,
          lifeStage: "pregnant",
        },
      ).reasonCode,
    ).toBe(
      "dri_reference_sex_required",
    );
  },
);


test(
  "missing sex only blocks a sex-specific table",
  () => {
    const folate = resolve(
      "folate",
      {
        sex: null,
      },
    );

    const vitaminA = resolve(
      "vitamin_a",
      {
        sex: null,
      },
    );

    expect(
      folate.amount,
    ).toBe("400.000000");

    expect(
      vitaminA.reasonCode,
    ).toBe(
      "dri_reference_sex_required",
    );
  },
);


test(
  "ALA has an AI while EPA and DHA remain without a fabricated goal",
  () => {
    const male = resolve(
      "alpha_linolenic_acid",
      {
        sex: "male",
      },
    );

    const female = resolve(
      "alpha_linolenic_acid",
      {
        sex: "female",
      },
    );

    const epa = resolve("epa");
    const dha = resolve("dha");

    expect(
      male.referenceType,
    ).toBe("AI");

    expect(male.amount).toBe("1.600000");
    expect(female.amount).toBe("1.100000");

    expect(
      epa.reasonCode,
    ).toBe(
      "rda_or_ai_not_established",
    );

    expect(
      dha.reasonCode,
    ).toBe(
      "rda_or_ai_not_established",
    );
  },
);


test(
  "UL remains metadata and is not substituted for the recommendation",
  () => {
    const vitaminA = resolve(
      "vitamin_a",
      {
        sex: "male",
      },
    );

    expect(
      vitaminA.amount,
    ).toBe("900.000000");

    expect(
      vitaminA.upperLimit?.amount,
    ).toBe("3000.000000");

    expect(
      vitaminA.upperLimit?.scope,
    ).toBe(
      "preformed_vitamin_a_only",
    );

    expect(
      vitaminA.upperLimit
        ?.comparableToRecommendation,
    ).toBe(false);
  },
);


test(
  "unsupported age and medical context fail closed",
  () => {
    const child = resolve(
      "folate",
      {
        age: 18,
        sex: "female",
      },
    );

    const medical = resolve(
      "folate",
      {
        sex: "female",
        lifeStage:
          "specialized_medical",
      },
    );

    expect(
      child.reasonCode,
    ).toBe("dri_unsupported_age");

    expect(
      medical.reasonCode,
    ).toBe(
      "dri_unsupported_medical_context",
    );
  },
);


test(
  "missing birth date fails closed",
  () => {
    const result =
      resolveDriRecommendation(
        "folate",
        {
          birthDate: null,
          sex: "female",
          lifeStage:
            "general_adult",
          weightKg: "70",
          asOf: AS_OF,
        },
      );

    expect(
      result.reasonCode,
    ).toBe(
      "dri_birth_date_required",
    );
  },
);
