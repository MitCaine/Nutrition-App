from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

from app.domain.log_contracts import MealType, normalize_meal, normalize_note
from app.schemas.common import DecimalInput
from app.schemas.nutrition import AggregatedNutrientTotalSchema


def _validate_meal_field(value: object) -> str | None:
    try:
        return normalize_meal(value)
    except ValueError as exc:
        raise PydanticCustomError("meal_invalid", str(exc)) from exc


def _validate_note_field(value: object) -> str | None:
    try:
        return normalize_note(value)
    except ValueError as exc:
        code = getattr(exc, "code", "note_invalid")
        raise PydanticCustomError(code, str(exc)) from exc


class DailyLogCreateRequest(BaseModel):
    # Optional only for legacy callers. Current mobile creation always supplies this UUID.
    client_request_id: UUID | None = None
    # Active mobile flows send the calendar context they reviewed.  Legacy
    # callers may omit it and retain their existing compatibility behavior.
    calendar_revision: int | None = Field(default=None, ge=0)
    food_item_id: UUID
    logged_date: date
    amount_quantity: DecimalInput
    amount_unit: str = Field(pattern="^(serving|g)$")
    serving_definition_id: UUID | None = None
    # Commit-time source authority reviewed by the client.  These fields are
    # optional for older callers; current confirmation flows send the
    # applicable Food generation and/or active Recipe publication revision.
    source_food_updated_at: datetime | None = None
    source_recipe_publication_revision_id: UUID | None = None
    meal_type: MealType | None = None
    notes: str | None = None

    _meal_contract = field_validator("meal_type", mode="before")(_validate_meal_field)
    _note_contract = field_validator("notes", mode="before")(_validate_note_field)

    @model_validator(mode="after")
    def validate_amount(self) -> DailyLogCreateRequest:
        if self.amount_quantity is None or self.amount_quantity <= 0:
            raise ValueError("amount quantity must be greater than zero")
        return self


class DailyLogUpdateRequest(BaseModel):
    # Update and delete intents use the same owner-scoped request identity as
    # creates. The identity is optional for older API callers, but current
    # clients should provide it whenever a mutation may be retried.
    client_request_id: UUID | None = None
    # Captured from an authoritative Daily Log read and checked after the row
    # is locked, preventing a stale client from overwriting another client.
    expected_updated_at: datetime | None = None
    # See DailyLogCreateRequest.calendar_revision.
    calendar_revision: int | None = Field(default=None, ge=0)
    # Commit-time source authority reviewed by the edit confirmation.
    source_food_updated_at: datetime | None = None
    source_recipe_publication_revision_id: UUID | None = None
    logged_date: date | None = None
    amount_quantity: DecimalInput = None
    amount_unit: str | None = Field(default=None, pattern="^(serving|g)$")
    serving_definition_id: UUID | None = None
    meal_type: MealType | None = None
    notes: str | None = None

    _meal_contract = field_validator("meal_type", mode="before")(_validate_meal_field)
    _note_contract = field_validator("notes", mode="before")(_validate_note_field)

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


class DailyLogDeleteRequest(BaseModel):
    """Optional request body carrying delete intent and concurrency context."""

    client_request_id: UUID | None = None
    expected_updated_at: datetime | None = None
    # The originating Daily Log read's calendar generation. Deletion remains
    # valid for legacy future entries, so this checks calendar authority and
    # revision without applying the normal create/update future-date fence.
    calendar_revision: int | None = Field(default=None, ge=0)


class DailyLogCompleteRequest(BaseModel):
    """Deterministic intent to assert one authoritative Daily Log date Complete."""

    client_request_id: UUID
    calendar_revision: int = Field(ge=0)
    logged_date: date


class DailyLogCompleteResponse(BaseModel):
    logged_date: date
    completed_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DailyLogMutationStatusResponse(BaseModel):
    """Authoritative status of one owner-scoped Daily Log mutation intent."""

    operation: Literal["create", "update", "delete", "complete"]
    client_request_id: UUID
    status: Literal[
        "confirmed_success",
        "confirmed_non_commit",
        "conflict",
        "unresolved",
    ]
    log_id: UUID | None = None
    source_logged_date: date | None = None
    destination_logged_date: date | None = None
    result: DailyLogResponse | None = None
    completion: DailyLogCompleteResponse | None = None


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
    # Current authority used by E1-13 edits. Historical fields above remain
    # available for compatibility and audit presentation.
    current_source_food_updated_at: datetime | None = None
    current_recipe_publication_revision_id: UUID | None = None
    current_source_loggable: bool | None = None
    current_selected_amount_definition_id: UUID | None = None
    current_amount_choices: list[DailyLogEditAmountResponse] | None = None


class DailyLogListResponse(BaseModel):
    logs: list[DailyLogResponse]


class RecentEntryResponse(BaseModel):
    """Historical logging intent exposed by the Repeat discovery section."""

    id: UUID
    food_item_id: UUID
    food_name_snapshot: str | None
    logged_date: date
    meal_type: str | None
    amount_quantity: Decimal
    amount_unit: str
    serving_definition_id: UUID | None
    recipe_publication_revision_id: UUID | None
    recipe_publication_amount_definition_id: UUID | None
    historical_serving_label: str | None
    notes: str | None
    note_present: bool
    note_reference: str | None
    note_copy_allowed: bool
    created_at: datetime
    source_food_updated_at: datetime | None
    source_recipe_publication_revision_id: UUID | None
    current_source_loggable: bool
    current_amount_unit: Literal["serving", "g"] | None
    current_amount_definition_id: UUID | None
    current_amount_label: str | None
    reuse_status: Literal["exact", "equivalent", "ambiguous", "unavailable"]

    model_config = ConfigDict(from_attributes=True)


class RecentEntryListResponse(BaseModel):
    entries: list[RecentEntryResponse]


class DailySummaryResponse(BaseModel):
    logged_date: date
    totals: list[AggregatedNutrientTotalSchema]


class HistoryNutrientEvidenceResponse(BaseModel):
    nutrient_id: str
    amount_known: Decimal
    amount_estimated: Decimal
    unit: str
    has_numeric_evidence: bool
    is_explicit_zero_total: bool
    has_unknown_contributors: bool
    unknown_contributor_count: int


class HistoryDayEvidenceResponse(BaseModel):
    date: date
    has_logs: bool
    is_complete: bool
    nutrients: list[HistoryNutrientEvidenceResponse]


class HistoryRangeResponse(BaseModel):
    start_date: date
    end_date: date
    first_logged_date: date | None
    days: list[HistoryDayEvidenceResponse]
