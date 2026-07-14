from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import DecimalInput
from app.schemas.food import FoodResponse

DISPLAY_UNITS_TO_GRAMS = {
    "g": Decimal("1"),
    "oz": Decimal("28.349523125"),
    "lb": Decimal("453.59237"),
}
DECIMAL_PLACES = Decimal("0.000001")


def _quantize_grams(value: Decimal) -> Decimal:
    return value.quantize(DECIMAL_PLACES, rounding=ROUND_HALF_UP)


def _validate_display_metadata(
        *,
        quantity: Decimal | None,
        unit: str | None,
        normalized_grams: Decimal | None,
        field_name: str,
) -> tuple[Decimal | None, str | None]:
    if (quantity is None) != (unit is None):
        raise ValueError(
            f"{field_name} display quantity and unit must be provided together"
        )

    if quantity is None or unit is None:
        return None, None

    normalized_unit = unit.strip().lower()

    if normalized_unit not in DISPLAY_UNITS_TO_GRAMS:
        raise ValueError(f"{field_name} display unit must be g, oz, or lb")

    if quantity <= 0:
        raise ValueError(
            f"{field_name} display quantity must be greater than zero"
        )

    if normalized_grams is None:
        raise ValueError(
            f"{field_name} display metadata requires normalized grams"
        )

    expected_grams = _quantize_grams(
        quantity * DISPLAY_UNITS_TO_GRAMS[normalized_unit]
    )

    if _quantize_grams(normalized_grams) != expected_grams:
        raise ValueError(
            f"{field_name} display metadata does not match normalized grams"
        )

    return quantity, normalized_unit


def _validate_display_pair(
        *,
        quantity: Decimal | None,
        unit: str | None,
        field_name: str,
) -> tuple[Decimal | None, str | None]:
    if (quantity is None) != (unit is None):
        raise ValueError(
            f"{field_name} display quantity and unit must be provided together"
        )

    if quantity is None or unit is None:
        return None, None

    normalized_unit = unit.strip().lower()

    if normalized_unit not in DISPLAY_UNITS_TO_GRAMS:
        raise ValueError(f"{field_name} display unit must be g, oz, or lb")

    if quantity <= 0:
        raise ValueError(
            f"{field_name} display quantity must be greater than zero"
        )

    return quantity, normalized_unit


class RecipeIngredientInput(BaseModel):
    food_item_id: UUID
    position: int = Field(ge=0)
    amount_quantity: DecimalInput
    amount_unit: str = Field(pattern="^(serving|g)$")
    serving_definition_id: UUID | None = None
    preparation_note: str | None = None
    amount_display_quantity: DecimalInput = None
    amount_display_unit: str | None = None

    @model_validator(mode="after")
    def validate_amount(self) -> RecipeIngredientInput:
        if self.amount_quantity is None or self.amount_quantity <= 0:
            raise ValueError("ingredient amount_quantity must be greater than zero")
        if self.amount_unit == "g" and self.serving_definition_id is not None:
            raise ValueError("gram ingredients must not include serving_definition_id")
        if self.amount_unit == "serving" and self.serving_definition_id is None:
            raise ValueError("serving ingredients require serving_definition_id")
        if self.amount_unit == "serving":
            if self.amount_display_quantity is not None or self.amount_display_unit is not None:
                raise ValueError("serving ingredients must not include mass display metadata")
        else:
            self.amount_display_quantity, self.amount_display_unit = _validate_display_metadata(
                quantity=self.amount_display_quantity,
                unit=self.amount_display_unit,
                normalized_grams=self.amount_quantity,
                field_name="ingredient",
            )
        return self


class RecipeCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    notes: str | None = None
    serving_count_yield: DecimalInput = None
    final_cooked_weight_grams: DecimalInput = None
    final_cooked_weight_display_quantity: DecimalInput = None
    final_cooked_weight_display_unit: str | None = None
    ingredients: list[RecipeIngredientInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_yields(self) -> RecipeCreateRequest:
        if self.serving_count_yield is not None and self.serving_count_yield <= 0:
            raise ValueError("serving_count_yield must be greater than zero")
        if self.final_cooked_weight_grams is not None and self.final_cooked_weight_grams <= 0:
            raise ValueError("final_cooked_weight_grams must be greater than zero")
        self.final_cooked_weight_display_quantity, self.final_cooked_weight_display_unit = _validate_display_metadata(
            quantity=self.final_cooked_weight_display_quantity,
            unit=self.final_cooked_weight_display_unit,
            normalized_grams=self.final_cooked_weight_grams,
            field_name="final cooked weight",
        )
        return self


class RecipeUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    notes: str | None = None
    serving_count_yield: DecimalInput = None
    final_cooked_weight_grams: DecimalInput = None
    final_cooked_weight_display_quantity: DecimalInput = None
    final_cooked_weight_display_unit: str | None = None
    ingredients: list[RecipeIngredientInput] | None = None

    @model_validator(mode="after")
    def validate_yields(self) -> RecipeUpdateRequest:
        if self.serving_count_yield is not None and self.serving_count_yield <= 0:
            raise ValueError("serving_count_yield must be greater than zero")

        if (
                self.final_cooked_weight_grams is not None
                and self.final_cooked_weight_grams <= 0
        ):
            raise ValueError(
                "final_cooked_weight_grams must be greater than zero"
            )

        grams_field = "final_cooked_weight_grams"
        display_quantity_field = "final_cooked_weight_display_quantity"
        display_unit_field = "final_cooked_weight_display_unit"

        grams_supplied = grams_field in self.model_fields_set
        display_supplied = bool(
            {
                display_quantity_field,
                display_unit_field,
            }.intersection(self.model_fields_set)
        )

        if (
                grams_supplied
                and self.final_cooked_weight_grams is None
                and (
                self.final_cooked_weight_display_quantity is not None
                or self.final_cooked_weight_display_unit is not None
        )
        ):
            raise ValueError(
                "final cooked weight display metadata cannot be provided "
                "when final_cooked_weight_grams is null"
            )

        if display_supplied:
            if grams_supplied and self.final_cooked_weight_grams is not None:
                (
                    self.final_cooked_weight_display_quantity,
                    self.final_cooked_weight_display_unit,
                ) = _validate_display_metadata(
                    quantity=self.final_cooked_weight_display_quantity,
                    unit=self.final_cooked_weight_display_unit,
                    normalized_grams=self.final_cooked_weight_grams,
                    field_name="final cooked weight",
                )
            else:
                (
                    self.final_cooked_weight_display_quantity,
                    self.final_cooked_weight_display_unit,
                ) = _validate_display_pair(
                    quantity=self.final_cooked_weight_display_quantity,
                    unit=self.final_cooked_weight_display_unit,
                    field_name="final cooked weight",
                )

        return self


class RecipeIngredientResponse(BaseModel):
    id: UUID
    recipe_id: UUID
    food_item_id: UUID
    position: int
    amount_quantity: Decimal
    amount_unit: str
    serving_definition_id: UUID | None
    resolved_gram_amount: Decimal | None
    preparation_note: str | None
    amount_display_quantity: Decimal | None
    amount_display_unit: str | None

    model_config = ConfigDict(from_attributes=True)


class RecipeResponse(BaseModel):
    id: UUID
    user_id: UUID
    published_food_item_id: UUID | None
    name: str
    notes: str | None
    serving_count_yield: Decimal | None
    final_cooked_weight_grams: Decimal | None
    final_cooked_weight_display_quantity: Decimal | None
    final_cooked_weight_display_unit: str | None
    needs_republish: bool
    created_at: datetime
    updated_at: datetime
    ingredients: list[RecipeIngredientResponse]

    model_config = ConfigDict(from_attributes=True)


class RecipeListResponse(BaseModel):
    recipes: list[RecipeResponse]


class RecipeDeleteAffectedRecipeResponse(BaseModel):
    recipe_id: UUID
    recipe_name: str
    ingredient_occurrence_count: int
    is_published: bool
    will_require_republish: bool


class RecipeDeleteDependencyResponse(BaseModel):
    code: Literal["recipe_delete_dependencies_exist"] = (
        "recipe_delete_dependencies_exist"
    )
    message: str = (
        "This Recipe is used by other Recipes. Confirm deletion to remove it from those Recipes."
    )
    recipe_id: UUID
    projection_food_item_id: UUID
    active_dependent_recipe_count: int
    affected_recipes: list[RecipeDeleteAffectedRecipeResponse]
    total_ingredient_rows_affected: int


class RecipePublicationParentAmountConflictIngredientResponse(BaseModel):
    recipe_id: UUID
    recipe_name: str
    ingredient_positions: list[int]


class RecipePublicationParentAmountConflictResponse(BaseModel):
    code: Literal["recipe_publication_parent_amount_conflict"] = (
        "recipe_publication_parent_amount_conflict"
    )
    message: str = (
        "This Recipe cannot be republished because one or more parent Recipe "
        "ingredient amounts no longer have an equivalent serving. Update those "
        "parent Recipe ingredients before republishing."
    )
    recipe_id: UUID
    projection_food_item_id: UUID
    affected_recipes: list[RecipePublicationParentAmountConflictIngredientResponse]


class RecipeNutrientTotalResponse(BaseModel):
    nutrient_id: str
    amount_known: Decimal
    amount_estimated: Decimal
    unit: str
    has_unknown_contributors: bool
    unknown_contributor_count: int

    model_config = ConfigDict(from_attributes=True)


class RecipeNutritionResponse(BaseModel):
    totals: list[RecipeNutrientTotalResponse]
    per_serving: list[RecipeNutrientTotalResponse] | None
    per_100g: list[RecipeNutrientTotalResponse] | None


class RecipePublishResponse(BaseModel):
    recipe: RecipeResponse
    food: FoodResponse
