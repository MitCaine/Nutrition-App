from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class NutrientDefinitionSchema(BaseModel):
    id: str
    display_name: str
    default_unit: str
    nutrient_kind: str
    parent_nutrient_id: str | None
    display_order: int

    model_config = ConfigDict(from_attributes=True)


class AggregatedNutrientTotalSchema(BaseModel):
    nutrient_id: str
    amount_known: Decimal
    amount_estimated: Decimal
    unit: str
    has_unknown_contributors: bool
    unknown_contributor_count: int

    model_config = ConfigDict(from_attributes=True)
