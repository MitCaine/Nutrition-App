import {
  NUTRIENT_CATALOG_BY_ID,
  type CanonicalNutrientDefinition,
} from "./catalog";

export type NutrientSectionId =
  | "nutrition_facts"
  | "vitamins"
  | "minerals"
  | "fatty_acids"
  | "other";

export type NutrientSection<T> =
  Readonly<{
    id: NutrientSectionId;
    label: string | null;
    items: readonly T[];
  }>;

const NUTRITION_FACTS_ORDER = [
  "calories",
  "total_fat",
  "saturated_fat",
  "trans_fat",
  "cholesterol",
  "sodium",
  "total_carbohydrate",
  "dietary_fiber",
  "total_sugars",
  "added_sugars",
  "protein",
  "vitamin_d",
  "calcium",
  "iron",
  "potassium",
] as const;

const NUTRITION_FACTS_INDEX =
  new Map<string, number>(
    NUTRITION_FACTS_ORDER.map(
      (id, index) => [id, index],
    ),
  );

const NUTRITION_FACTS_IDS =
  new Set<string>(
    NUTRITION_FACTS_ORDER,
  );

const NUTRIENT_SECTIONS:
  readonly Readonly<{
    id: NutrientSectionId;
    label: string | null;
  }>[] = [
    {
      id: "nutrition_facts",
      label: null,
    },
    {
      id: "vitamins",
      label: "Vitamins",
    },
    {
      id: "minerals",
      label: "Minerals",
    },
    {
      id: "fatty_acids",
      label: "Fatty Acids",
    },
    {
      id: "other",
      label: "Other",
    },
  ];

function nutrientSectionId(
  nutrient:
    CanonicalNutrientDefinition
    | undefined,
): NutrientSectionId {
  if (!nutrient) {
    return "other";
  }

  if (
    NUTRITION_FACTS_IDS.has(
      nutrient.id,
    )
  ) {
    return "nutrition_facts";
  }

  if (
    nutrient.nutrient_kind
      === "fatty_acid"
  ) {
    return "fatty_acids";
  }

  if (
    nutrient.nutrient_kind
      === "vitamin"
  ) {
    return "vitamins";
  }

  if (
    nutrient.nutrient_kind
      === "mineral"
  ) {
    return "minerals";
  }

  return "other";
}

function nutrientDisplayOrder(
  sectionId: NutrientSectionId,
  nutrientId: string,
): number {
  if (
    sectionId === "nutrition_facts"
  ) {
    return (
      NUTRITION_FACTS_INDEX.get(
        nutrientId,
      )
      ?? Number.MAX_SAFE_INTEGER
    );
  }

  return (
    NUTRIENT_CATALOG_BY_ID.get(
      nutrientId,
    )?.display_order
    ?? Number.MAX_SAFE_INTEGER
  );
}

export function
groupCanonicalNutrientsBySection<T>(
  items: readonly T[],
  nutrientId: (item: T) => string,
): readonly NutrientSection<T>[] {
  const buckets:
    Record<NutrientSectionId, T[]> = {
      nutrition_facts: [],
      vitamins: [],
      minerals: [],
      fatty_acids: [],
      other: [],
    };

  for (const item of items) {
    const id = nutrientId(item);

    const sectionId =
      nutrientSectionId(
        NUTRIENT_CATALOG_BY_ID.get(id),
      );

    buckets[sectionId].push(item);
  }

  return NUTRIENT_SECTIONS
    .map((section) => ({
      ...section,
      items: [...buckets[section.id]]
        .sort((left, right) => {
          const leftId =
            nutrientId(left);

          const rightId =
            nutrientId(right);

          return (
            nutrientDisplayOrder(
              section.id,
              leftId,
            )
            - nutrientDisplayOrder(
              section.id,
              rightId,
            )
            || leftId.localeCompare(
              rightId,
            )
          );
        }),
    }))
    .filter(
      (section) =>
        section.items.length > 0,
    );
}

export function
nutrientVisibleDepth(
  nutrientId: string,
  visibleNutrientIds:
    ReadonlySet<string>,
  parentIdFor:
    (nutrientId: string) =>
      string | null,
): number {
  let depth = 0;
  let currentId = nutrientId;

  const visited =
    new Set<string>();

  while (true) {
    if (visited.has(currentId)) {
      return depth;
    }

    visited.add(currentId);

    const parentId =
      parentIdFor(currentId);

    if (
      parentId === null
      || !visibleNutrientIds.has(
        parentId,
      )
    ) {
      return depth;
    }

    depth += 1;
    currentId = parentId;
  }
}

export function
canonicalNutrientParentId(
  nutrientId: string,
): string | null {
  return (
    NUTRIENT_CATALOG_BY_ID.get(
      nutrientId,
    )?.parent_nutrient_id
    ?? null
  );
}

export function
canonicalNutrientIsChild(
  nutrientId: string,
): boolean {
  return (
    canonicalNutrientParentId(
      nutrientId,
    ) !== null
  );
}
