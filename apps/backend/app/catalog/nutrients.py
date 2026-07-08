from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class NutrientDefinition:
    id: str
    display_name: str
    default_unit: str
    nutrient_kind: str
    parent_nutrient_id: str | None
    display_order: int


NUTRIENT_CATALOG: tuple[NutrientDefinition, ...] = (
    NutrientDefinition("calories", "Calories", "kcal", "energy", None, 10),
    NutrientDefinition("total_fat", "Total Fat", "g", "macro", None, 20),
    NutrientDefinition("saturated_fat", "Saturated Fat", "g", "macro", "total_fat", 21),
    NutrientDefinition("trans_fat", "Trans Fat", "g", "macro", "total_fat", 22),
    NutrientDefinition("cholesterol", "Cholesterol", "mg", "other", None, 30),
    NutrientDefinition("sodium", "Sodium", "mg", "mineral", None, 40),
    NutrientDefinition("total_carbohydrate", "Total Carbohydrate", "g", "macro", None, 50),
    NutrientDefinition("dietary_fiber", "Dietary Fiber", "g", "macro", "total_carbohydrate", 51),
    NutrientDefinition("total_sugars", "Total Sugars", "g", "macro", "total_carbohydrate", 52),
    NutrientDefinition("added_sugars", "Added Sugars", "g", "macro", "total_sugars", 53),
    NutrientDefinition("protein", "Protein", "g", "macro", None, 60),
    NutrientDefinition("vitamin_d", "Vitamin D", "mcg", "vitamin", None, 70),
    NutrientDefinition("calcium", "Calcium", "mg", "mineral", None, 80),
    NutrientDefinition("iron", "Iron", "mg", "mineral", None, 90),
    NutrientDefinition("potassium", "Potassium", "mg", "mineral", None, 100),
    NutrientDefinition("magnesium", "Magnesium", "mg", "mineral", None, 110),
)


def nutrient_seed_rows() -> list[dict[str, Any]]:
    return [asdict(nutrient) for nutrient in NUTRIENT_CATALOG]
