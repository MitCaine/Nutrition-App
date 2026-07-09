from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.catalog.nutrients import NUTRIENT_CATALOG
from app.domain.nutrition import NutrientBasis, NutrientDataStatus
from app.nutrition.units import SUPPORTED_NUTRITION_UNITS, normalize_unit, nutrient_unit_is_compatible
from app.schemas.common import DecimalInput

VALID_NUTRIENT_IDS = {nutrient.id for nutrient in NUTRIENT_CATALOG}
NUTRIENTS_BY_ID = {nutrient.id: nutrient for nutrient in NUTRIENT_CATALOG}


class OriginalNutrientValueSchema(BaseModel):
    amount: DecimalInput = None
    unit: str | None = None
    text: str | None = None


class FoodNutrientInput(BaseModel):
    nutrient_id: str
    amount: DecimalInput = None
    unit: str
    basis: NutrientBasis
    data_status: NutrientDataStatus
    source: str = "manual"
    is_user_confirmed: bool = True
    original: OriginalNutrientValueSchema | None = None

    @model_validator(mode="after")
    def validate_nutrient(self) -> FoodNutrientInput:
        if self.nutrient_id not in VALID_NUTRIENT_IDS:
            raise ValueError(f"Unsupported nutrient ID: {self.nutrient_id}")

        self.unit = normalize_unit(self.unit)
        if self.unit not in SUPPORTED_NUTRITION_UNITS:
            raise ValueError(f"Unsupported nutrient unit: {self.unit}")
        nutrient = NUTRIENTS_BY_ID[self.nutrient_id]
        if not nutrient_unit_is_compatible(nutrient.default_unit, self.unit):
            raise ValueError(f"Unit {self.unit} is not compatible with nutrient {self.nutrient_id}")

        if self.data_status in {NutrientDataStatus.KNOWN, NutrientDataStatus.ESTIMATED}:
            if self.amount is None:
                raise ValueError(f"{self.data_status.value} nutrients require an amount")
            if self.data_status == NutrientDataStatus.KNOWN and self.amount == 0:
                raise ValueError("Use data_status zero for explicit zero nutrient values")
        elif self.data_status == NutrientDataStatus.ZERO:
            self.amount = Decimal("0")
        elif self.data_status == NutrientDataStatus.UNKNOWN:
            if self.amount is not None:
                raise ValueError("unknown nutrients must not include an amount")

        return self


class ServingDefinitionInput(BaseModel):
    label: str = Field(min_length=1)
    quantity: DecimalInput
    unit: str = Field(min_length=1)
    gram_weight: DecimalInput = None
    is_default: bool = False

    @model_validator(mode="after")
    def validate_serving(self) -> ServingDefinitionInput:
        if self.quantity is None or self.quantity <= 0:
            raise ValueError("serving quantity must be greater than zero")
        if self.gram_weight is not None and self.gram_weight <= 0:
            raise ValueError("gram weight must be greater than zero when provided")
        self.unit = self.unit.strip().lower()
        return self


class FoodCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    brand: str | None = None
    notes: str | None = None
    serving_definitions: list[ServingDefinitionInput] = Field(min_length=1)
    nutrients: list[FoodNutrientInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_defaults(self) -> FoodCreateRequest:
        default_count = sum(1 for serving in self.serving_definitions if serving.is_default)
        if default_count != 1:
            raise ValueError("foods with serving definitions must have exactly one default serving")
        return self


class FoodUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    brand: str | None = None
    notes: str | None = None
    serving_definitions: list[ServingDefinitionInput] | None = None
    nutrients: list[FoodNutrientInput] | None = None

    @model_validator(mode="after")
    def validate_defaults(self) -> FoodUpdateRequest:
        if self.serving_definitions is not None:
            default_count = sum(1 for serving in self.serving_definitions if serving.is_default)
            if default_count != 1:
                raise ValueError("foods with serving definitions must have exactly one default serving")
        return self


class ServingDefinitionResponse(BaseModel):
    id: UUID
    label: str
    quantity: Decimal
    unit: str
    gram_weight: Decimal | None
    is_default: bool
    source: str
    is_user_confirmed: bool

    model_config = ConfigDict(from_attributes=True)


class FoodNutrientResponse(BaseModel):
    id: UUID
    nutrient_id: str
    amount: Decimal | None
    unit: str
    basis: str
    data_status: str
    source: str
    is_user_confirmed: bool
    original_amount: Decimal | None
    original_unit: str | None
    original_text: str | None

    model_config = ConfigDict(from_attributes=True)


class FoodResponse(BaseModel):
    id: UUID
    name: str
    brand: str | None
    notes: str | None
    source_type: str
    source_id: str | None
    is_recipe: bool
    created_at: datetime
    updated_at: datetime
    serving_definitions: list[ServingDefinitionResponse]
    nutrients: list[FoodNutrientResponse]

    model_config = ConfigDict(from_attributes=True)


class FoodListResponse(BaseModel):
    foods: list[FoodResponse]
