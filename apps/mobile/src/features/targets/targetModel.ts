import {
  isDecimalStringWithin,
  isPositiveDecimalString,
} from "../../shared/forms/decimalString";
import { NUTRIENT_CATALOG } from "../../shared/nutrition/catalog";
import type {
  TargetConfiguration,
  TargetConfigurationInput,
  TrackingMode,
  TrackingPreferenceMode,
} from "./api/types";
import {
  birthDateToCanonical,
  birthDateToDisplay,
  centimetersToInches,
  inchesToCentimeters,
  kilogramsToPounds,
  poundsToKilograms,
} from "./targetDisplay";

export type TargetDraft = {
  birthDate: string;
  sexForEquation: "female" | "male" | "";
  heightIn: string;
  weightLb: string;
  activityLevel:
    | "sedentary"
    | "lightly_active"
    | "active"
    | "very_active"
    | "";
  energyEstimationContext:
    | "general_adult"
    | "pregnant"
    | "lactating"
    | "specialized_medical";

  // Existing four fields remain first-class so #83 behavior and existing
  // form tests keep their established contract.
  calories: string;
  protein: string;
  totalCarbohydrate: string;
  totalFat: string;

  // All other canonical nutrient custom targets live here.
  additionalManualOverrides: Record<string, string>;

  // Only explicit persisted preferences belong here. A targetless nutrient
  // whose neutral default happens to be amount_only is deliberately absent.
  trackingPreferences: Record<
    string,
    TrackingPreferenceMode
  >;

  // Unsaved mode choices. This lets Custom exist as an editable draft before
  // an amount has been entered without inventing persisted preference state.
  modeSelections: Record<string, TrackingMode>;
};

export const EMPTY_TARGET_DRAFT: TargetDraft = {
  birthDate: "",
  sexForEquation: "",
  heightIn: "",
  weightLb: "",
  activityLevel: "",
  energyEstimationContext: "general_adult",
  calories: "",
  protein: "",
  totalCarbohydrate: "",
  totalFat: "",
  additionalManualOverrides: {},
  trackingPreferences: {},
  modeSelections: {},
};

export function compactTargetDecimalForEditing(
  value: string | null | undefined,
): string {
  if (!value) return "";

  if (!/^\d+(?:\.\d+)?$/.test(value)) {
    return value;
  }

  if (!value.includes(".")) {
    return value;
  }

  return value
    .replace(/0+$/, "")
    .replace(/\.$/, "");
}

export type PersonalTargetDraftKey =
  | "calories"
  | "protein"
  | "totalCarbohydrate"
  | "totalFat";

export function targetDraftKeyForNutrient(
  nutrientId: string,
): PersonalTargetDraftKey | null {
  if (nutrientId === "calories") {
    return "calories";
  }

  if (nutrientId === "protein") {
    return "protein";
  }

  if (
    nutrientId
    === "total_carbohydrate"
  ) {
    return "totalCarbohydrate";
  }

  if (nutrientId === "total_fat") {
    return "totalFat";
  }

  return null;
}

function canonicalRecord<T>(
  values: Readonly<Record<string, T>>,
): Record<string, T> {
  const result: Record<string, T> = {};

  for (const nutrient of NUTRIENT_CATALOG) {
    if (
      Object.prototype.hasOwnProperty.call(
        values,
        nutrient.id,
      )
    ) {
      result[nutrient.id] =
        values[nutrient.id]!;
    }
  }

  return result;
}

export function targetDraftOverrideValue(
  draft: TargetDraft,
  nutrientId: string,
): string {
  const legacy =
    targetDraftKeyForNutrient(
      nutrientId,
    );

  if (legacy) {
    return draft[legacy];
  }

  return (
    draft.additionalManualOverrides[
      nutrientId
    ] ?? ""
  );
}

function withTargetDraftOverride(
  draft: TargetDraft,
  nutrientId: string,
  value: string,
): TargetDraft {
  const legacy =
    targetDraftKeyForNutrient(
      nutrientId,
    );

  if (legacy) {
    return {
      ...draft,
      [legacy]: value,
    };
  }

  const next = {
    ...draft.additionalManualOverrides,
  };

  if (value === "") {
    delete next[nutrientId];
  } else {
    next[nutrientId] = value;
  }

  return {
    ...draft,
    additionalManualOverrides:
      canonicalRecord(next),
  };
}

export function setTargetDraftOverride(
  draft: TargetDraft,
  nutrientId: string,
  value: string,
): TargetDraft {
  if (
    !NUTRIENT_CATALOG.some(
      (nutrient) =>
        nutrient.id === nutrientId,
    )
  ) {
    return draft;
  }

  let next = withTargetDraftOverride(
    draft,
    nutrientId,
    value,
  );

  if (value !== "") {
    const preferences = {
      ...next.trackingPreferences,
    };
    delete preferences[nutrientId];

    next = {
      ...next,
      trackingPreferences:
        canonicalRecord(preferences),
      modeSelections:
        canonicalRecord({
          ...next.modeSelections,
          [nutrientId]: "custom",
        }),
    };
  }

  return next;
}

export function targetDraft(
  configuration: TargetConfiguration,
): TargetDraft {
  const overrides =
    Object.fromEntries(
      configuration.manualOverrides.map(
        (item) => [
          item.nutrientId,
          compactTargetDecimalForEditing(
            item.amount,
          ),
        ],
      ),
    );

  const additionalManualOverrides:
  Record<string, string> = {};

  for (
    const [
      nutrientId,
      value,
    ]
    of Object.entries(overrides)
  ) {
    if (
      targetDraftKeyForNutrient(
        nutrientId,
      ) === null
      && value
    ) {
      additionalManualOverrides[
        nutrientId
      ] = value;
    }
  }

  const sexForEquation =
    configuration.profile
      ?.sexForEquation ?? "";

  const energyEstimationContext =
    sexForEquation === "male"
      ? "general_adult"
      : (
          configuration.profile
            ?.energyEstimationContext
          ?? "general_adult"
        );

  return {
    birthDate:
      birthDateToDisplay(
        configuration.profile
          ?.birthDate ?? null,
      ),
    sexForEquation,
    heightIn:
      centimetersToInches(
        configuration.profile
          ?.heightCm ?? null,
      ),
    weightLb:
      kilogramsToPounds(
        configuration.profile
          ?.weightKg ?? null,
      ),
    activityLevel:
      configuration.profile
        ?.activityLevel ?? "",
    energyEstimationContext,

    calories:
      overrides.calories ?? "",
    protein:
      overrides.protein ?? "",
    totalCarbohydrate:
      overrides.total_carbohydrate
      ?? "",
    totalFat:
      overrides.total_fat ?? "",

    additionalManualOverrides:
      canonicalRecord(
        additionalManualOverrides,
      ),

    trackingPreferences:
      canonicalRecord(
        configuration
          .trackingPreferences,
      ),

    modeSelections: {},
  };
}

function persistedTrackingMode(
  configuration: TargetConfiguration,
  nutrientId: string,
): TrackingMode {
  const manual =
    configuration.manualOverrides
      .some(
        (item) =>
          item.nutrientId
          === nutrientId,
      );

  if (manual) {
    return "custom";
  }

  const explicit =
    configuration
      .trackingPreferences[
        nutrientId
      ];

  if (explicit) {
    return explicit;
  }

  return (
    configuration.effectiveTargets
      .find(
        (item) =>
          item.nutrientId
          === nutrientId,
      )
      ?.trackingMode
    ?? "recommended"
  );
}

export function targetDraftMode(
  draft: TargetDraft,
  configuration: TargetConfiguration,
  nutrientId: string,
): TrackingMode {
  const selected =
    draft.modeSelections[
      nutrientId
    ];

  if (selected) {
    return selected;
  }

  if (
    targetDraftOverrideValue(
      draft,
      nutrientId,
    )
  ) {
    return "custom";
  }

  const explicit =
    draft.trackingPreferences[
      nutrientId
    ];

  if (explicit) {
    return explicit;
  }

  return (
    configuration.effectiveTargets
      .find(
        (item) =>
          item.nutrientId
          === nutrientId,
      )
      ?.trackingMode
    ?? "recommended"
  );
}

export function setTargetDraftMode(
  draft: TargetDraft,
  configuration: TargetConfiguration,
  nutrientId: string,
  mode: TrackingMode,
): TargetDraft {
  if (
    !NUTRIENT_CATALOG.some(
      (nutrient) =>
        nutrient.id === nutrientId,
    )
  ) {
    return draft;
  }

  const currentMode =
    targetDraftMode(
      draft,
      configuration,
      nutrientId,
    );

  if (currentMode === mode) {
    if (
      mode === "amount_only"
      && draft.trackingPreferences[
        nutrientId
      ] !== "amount_only"
    ) {
      return {
        ...draft,
        trackingPreferences:
          canonicalRecord({
            ...draft.trackingPreferences,
            [nutrientId]:
              "amount_only",
          }),
      };
    }

    return draft;
  }

  const persistedMode =
    persistedTrackingMode(
      configuration,
      nutrientId,
    );

  const persistedManual =
    configuration.manualOverrides
      .find(
        (item) =>
          item.nutrientId
          === nutrientId,
      );

  const persistedPreference =
    configuration
      .trackingPreferences[
        nutrientId
      ];

  // Choosing the saved state again is a real draft revert, not another
  // persistence operation. This keeps #82 dirty-state behavior deterministic.
  if (mode === persistedMode) {
    let next =
      withTargetDraftOverride(
        draft,
        nutrientId,
        persistedManual
          ? compactTargetDecimalForEditing(
              persistedManual.amount,
            )
          : "",
      );

    const preferences = {
      ...next.trackingPreferences,
    };

    if (persistedPreference) {
      preferences[nutrientId] =
        persistedPreference;
    } else {
      delete preferences[nutrientId];
    }

    const selections = {
      ...next.modeSelections,
    };
    delete selections[nutrientId];

    return {
      ...next,
      trackingPreferences:
        canonicalRecord(
          preferences,
        ),
      modeSelections:
        canonicalRecord(
          selections,
        ),
    };
  }

  let next = draft;

  if (mode !== "custom") {
    next =
      withTargetDraftOverride(
        next,
        nutrientId,
        "",
      );
  }

  const preferences = {
    ...next.trackingPreferences,
  };

  if (
    mode === "amount_only"
    || mode === "ignored"
  ) {
    preferences[nutrientId] =
      mode;
  } else {
    delete preferences[nutrientId];
  }

  return {
    ...next,
    trackingPreferences:
      canonicalRecord(preferences),
    modeSelections:
      canonicalRecord({
        ...next.modeSelections,
        [nutrientId]: mode,
      }),
  };
}

/**
 * #83 reset remains a draft operation. For every canonical nutrient it means
 * "remove the custom value and return to the dynamic default recommendation
 * state when Save is eventually chosen."
 */
export function resetTargetDraftOverride(
  draft: TargetDraft,
  nutrientId: string,
): TargetDraft {
  const current =
    targetDraftOverrideValue(
      draft,
      nutrientId,
    );

  if (current === "") {
    return draft;
  }

  const next =
    withTargetDraftOverride(
      draft,
      nutrientId,
      "",
    );

  const preferences = {
    ...next.trackingPreferences,
  };
  delete preferences[nutrientId];

  const selections = {
    ...next.modeSelections,
  };
  delete selections[nutrientId];

  return {
    ...next,
    trackingPreferences:
      canonicalRecord(preferences),
    modeSelections:
      canonicalRecord(selections),
  };
}

function validationBounds(
  nutrientId: string,
): readonly [
  string,
  string,
  string,
] {
  if (nutrientId === "calories") {
    return [
      "500",
      "10000",
      "Calorie target",
    ];
  }

  if (nutrientId === "protein") {
    return [
      "1",
      "1000",
      "Protein target",
    ];
  }

  if (
    nutrientId
    === "total_carbohydrate"
  ) {
    return [
      "1",
      "1500",
      "Carbohydrate target",
    ];
  }

  if (nutrientId === "total_fat") {
    return [
      "1",
      "500",
      "Fat target",
    ];
  }

  const nutrient =
    NUTRIENT_CATALOG.find(
      (item) =>
        item.id === nutrientId,
    );

  return [
    "0.000001",
    "99999999.999999",
    `${nutrient?.display_name ?? nutrientId} target`,
  ];
}

export function targetDraftError(
  draft: TargetDraft,
): string | null {
  if (draft.birthDate) {
    let canonicalBirthDate:
      string | null = null;

    try {
      canonicalBirthDate =
        birthDateToCanonical(
          draft.birthDate,
        );
    } catch {
      return (
        "Birth date must use a valid "
        + "MM-DD-YYYY date."
      );
    }

    const match =
      canonicalBirthDate
        ? /^(\d{4})-(\d{2})-(\d{2})$/
            .exec(
              canonicalBirthDate,
            )
        : null;

    const parsed = match
      ? new Date(
          Date.UTC(
            Number(match[1]),
            Number(match[2]) - 1,
            Number(match[3]),
          ),
        )
      : null;

    if (
      !match
      || !parsed
      || parsed
        .toISOString()
        .slice(0, 10)
        !== canonicalBirthDate
    ) {
      return (
        "Birth date must use a valid "
        + "MM-DD-YYYY date."
      );
    }
  }

  for (
    const [
      label,
      value,
      toCanonical,
      minimum,
      maximum,
      range,
    ]
    of [
      [
        "Height",
        draft.heightIn,
        inchesToCentimeters,
        "100.000",
        "250.000",
        "39.37 and 98.43 inches",
      ],
      [
        "Weight",
        draft.weightLb,
        poundsToKilograms,
        "30.000",
        "300.000",
        "66.14 and 661.39 pounds",
      ],
    ] as const
  ) {
    if (
      value
      && !isPositiveDecimalString(
        value,
      )
    ) {
      return (
        `${label} must be a `
        + "positive plain decimal."
      );
    }

    if (value) {
      try {
        const canonical =
          toCanonical(value);

        if (
          !canonical
          || !isDecimalStringWithin(
            canonical,
            minimum,
            maximum,
          )
        ) {
          return (
            `${label} must be between `
            + `${range}.`
          );
        }
      } catch {
        return (
          `${label} must be a `
          + "positive plain decimal."
        );
      }
    }
  }

  for (
    const nutrient
    of NUTRIENT_CATALOG
  ) {
    const value =
      targetDraftOverrideValue(
        draft,
        nutrient.id,
      );

    const selectedMode =
      draft.modeSelections[
        nutrient.id
      ];

    if (
      selectedMode === "custom"
      && value === ""
    ) {
      return (
        `${nutrient.display_name} `
        + "custom target is required."
      );
    }

    if (!value) {
      continue;
    }

    if (
      !isPositiveDecimalString(
        value,
      )
    ) {
      return (
        `${nutrient.display_name} `
        + "target must be a positive "
        + "plain decimal."
      );
    }

    const fraction =
      value.split(".")[1] ?? "";

    if (fraction.length > 6) {
      return (
        `${nutrient.display_name} `
        + "target supports at most "
        + "six decimal places."
      );
    }

    const [
      minimum,
      maximum,
      label,
    ] = validationBounds(
      nutrient.id,
    );

    if (
      !isDecimalStringWithin(
        value,
        minimum,
        maximum,
      )
    ) {
      return (
        `${label} must be between `
        + `${minimum} and ${maximum}.`
      );
    }
  }

  return null;
}

export function targetInput(
  draft: TargetDraft,
): TargetConfigurationInput {
  const energyEstimationContext =
    draft.sexForEquation === "male"
      ? "general_adult"
      : draft.energyEstimationContext;

  const manualOverrides:
  Record<string, string | null> = {};

  for (
    const nutrient
    of NUTRIENT_CATALOG
  ) {
    const value =
      targetDraftOverrideValue(
        draft,
        nutrient.id,
      );

    const selected =
      draft.modeSelections[
        nutrient.id
      ];

    const mode =
      selected
      ?? (
        value
          ? "custom"
          : draft
              .trackingPreferences[
                nutrient.id
              ]
            ?? "recommended"
      );

    manualOverrides[
      nutrient.id
    ] =
      mode === "custom"
        ? value || null
        : null;
  }

  const trackingPreferences = {
    ...draft.trackingPreferences,
  };

  for (
    const [
      nutrientId,
      mode,
    ]
    of Object.entries(
      draft.modeSelections,
    )
  ) {
    if (
      mode === "amount_only"
      || mode === "ignored"
    ) {
      trackingPreferences[
        nutrientId
      ] = mode;
    } else {
      delete trackingPreferences[
        nutrientId
      ];
    }
  }

  return {
    profile: {
      birth_date:
        birthDateToCanonical(
          draft.birthDate,
        ),
      sex_for_equation:
        draft.sexForEquation
        || null,
      height_cm:
        inchesToCentimeters(
          draft.heightIn,
        ),
      height_unit: "cm",
      weight_kg:
        poundsToKilograms(
          draft.weightLb,
        ),
      weight_unit: "kg",
      activity_level:
        draft.activityLevel
        || null,
      energy_estimation_context:
        energyEstimationContext,
    },

    // The #103-capable client intentionally sends every canonical identity.
    // Older clients still send their smaller patch-shaped map and therefore
    // cannot erase newer custom targets they do not understand.
    manual_overrides:
      manualOverrides,

    tracking_preferences:
      canonicalRecord(
        trackingPreferences,
      ),
  };
}

export function targetUnavailableMessage(
  code: string | null,
): string {
  if (
    code
    === "target_estimate_unsupported_age"
  ) {
    return (
      "Estimate unavailable: the equation "
      + "supports adults ages 19–78."
    );
  }

  if (
    code
    === "target_estimate_unsupported_context"
  ) {
    return (
      "Estimate unavailable for this context. "
      + "A qualified professional can provide "
      + "specialized guidance."
    );
  }

  return (
    "Complete birth date, equation sex, "
    + "height, weight, and activity to "
    + "estimate maintenance calories."
  );
}
