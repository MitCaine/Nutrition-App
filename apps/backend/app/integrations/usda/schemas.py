from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class UsdaNutrientCandidate(BaseModel):
    nutrient_id: str
    amount: Decimal | None
    unit: str
    basis: str
    data_status: str
    source: str = "usda_fdc"
    external_nutrient_id: str | None = None
    external_nutrient_number: str | None = None
    original_amount: Decimal | None = None
    original_unit: str | None = None
    display_name: str | None = None


class UsdaSearchResult(BaseModel):
    fdc_id: int
    description: str
    data_type: str
    brand_owner: str | None = None
    food_category: str | None = None
    publication_date: str | None = None
    importable: bool = True
    nutrient_preview: list[UsdaNutrientCandidate] = Field(default_factory=list)


class UsdaServingCandidate(BaseModel):
    candidate_id: str
    label: str
    quantity: Decimal
    unit: str
    gram_weight: Decimal | None = None
    is_default: bool = False
    source: str = "usda_fdc"


class UsdaFoodPreview(BaseModel):
    source_type: str = "usda"
    external_id: str
    fdc_id: int
    name: str
    brand: str | None = None
    data_type: str
    food_category: str | None = None
    publication_date: str | None = None
    nutrients: list[UsdaNutrientCandidate]
    serving_definitions: list[UsdaServingCandidate]
    diagnostics: list[str] = Field(default_factory=list)
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class UsdaSearchResponse(BaseModel):
    query: str
    page_number: int
    page_size: int
    total_hits: int | None = None
    foods: list[UsdaSearchResult]


class UsdaImportResponse(BaseModel):
    imported: bool
    duplicate: bool
    food: Any

    model_config = ConfigDict(arbitrary_types_allowed=True)
