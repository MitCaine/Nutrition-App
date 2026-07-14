from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import DecimalInput
from app.schemas.nutrition import AggregatedNutrientTotalSchema


class DailyLogCreateRequest(BaseModel):
    # Optional only for legacy callers. Current mobile creation always supplies this UUID.
    client_request_id: UUID | None = None
    food_item_id: UUID
    logged_date: date
    amount_quantity: DecimalInput
    amount_unit: str = Field(pattern="^(serving|g)$")
    serving_definition_id: UUID | None = None
    meal_type: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_amount(self) -> DailyLogCreateRequest:
        if self.amount_quantity is None or self.amount_quantity <= 0:
            raise ValueError("amount quantity must be greater than zero")
        return self


class DailyLogUpdateRequest(BaseModel):
    logged_date: date | None = None
    amount_quantity: DecimalInput = None
    amount_unit: str | None = Field(default=None, pattern="^(serving|g)$")
    serving_definition_id: UUID | None = None
    meal_type: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_amount(self) -> DailyLogUpdateRequest:
        if self.amount_quantity is not None and self.amount_quantity <= 0:
            raise ValueError("amount quantity must be greater than zero")
        return self


class DailyLogSnapshotResponse(BaseModel):
    id: UUID
    nutrient_id: str
    amount: Decimal | None
    unit: str
    data_status: str
    source_food_item_id: UUID
    source_food_nutrient_id: UUID | None
    serving_definition_id: UUID | None
    consumed_amount_quantity: Decimal
    consumed_amount_unit: str
    consumed_gram_amount: Decimal | None
    consumed_package_fraction: Decimal | None

    model_config = ConfigDict(from_attributes=True)


class DailyLogResponse(BaseModel):
    id: UUID
    food_item_id: UUID
    food_name_snapshot: str | None
    is_editable: bool
    source_food_available: bool
    edit_block_reason: str | None
    logged_date: date
    meal_type: str | None
    amount_quantity: Decimal
    amount_unit: str
    serving_definition_id: UUID | None
    gram_amount: Decimal | None
    package_fraction: Decimal | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    snapshots: list[DailyLogSnapshotResponse]

    model_config = ConfigDict(from_attributes=True)


class DailyLogEditAmountResponse(BaseModel):
    amount_definition_id: UUID
    display_label: str
    semantic_mode: str
    display_quantity: Decimal | None
    display_unit: str
    gram_equivalent: Decimal | None
    is_default: bool
    is_selected: bool


class DailyLogEditContextResponse(BaseModel):
    log_id: UUID
    source_food_available: bool
    is_revision_backed: bool
    recipe_publication_revision_id: UUID | None
    selected_amount_definition_id: UUID | None
    amount_choices: list[DailyLogEditAmountResponse]


class DailyLogListResponse(BaseModel):
    logs: list[DailyLogResponse]


class DailySummaryResponse(BaseModel):
    logged_date: date
    totals: list[AggregatedNutrientTotalSchema]
