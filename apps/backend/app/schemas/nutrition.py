from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class NutrientReferenceValueSchema(BaseModel):
    amount: Decimal
    unit: str
    source_version: str
    standard: str

    model_config = ConfigDict(from_attributes=True)


class NutrientDefinitionSchema(BaseModel):
    id: str
    display_name: str
    default_unit: str
    nutrient_kind: str
    parent_nutrient_id: str | None
    display_order: int
    fda_daily_value: NutrientReferenceValueSchema | None
    dri_reference_kinds: tuple[str, ...]

    model_config = ConfigDict(from_attributes=True)


class AggregatedNutrientTotalSchema(BaseModel):
    nutrient_id: str
    amount_known: Decimal
    amount_estimated: Decimal
    unit: str
    has_unknown_contributors: bool
    unknown_contributor_count: int

    model_config = ConfigDict(from_attributes=True)
