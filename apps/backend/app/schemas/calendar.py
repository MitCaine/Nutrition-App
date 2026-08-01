from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from typing import Literal


class CalendarStateResponse(BaseModel):
    """The owner-scoped calendar authority consumed by Daily Log clients."""

    is_established: bool
    authoritative_time_zone: str | None
    calendar_revision: int = 0
    today: date | None = None


class EstablishTimeZoneRequest(BaseModel):
    """An explicit initial confirmation of the client's proposed IANA zone."""

    time_zone: str


class CalendarImpactEntryResponse(BaseModel):
    """Minimal owner-scoped identifying data for one reclassified entry."""

    id: UUID
    logged_date: date
    food_name_snapshot: str | None
    meal_type: str | None
    amount_quantity: Decimal
    amount_unit: str

    model_config = ConfigDict(from_attributes=True)


class CalendarImpactPreviewResponse(BaseModel):
    """The consequences of changing one owner's authoritative calendar."""

    calendar_revision: int
    current_time_zone: str
    proposed_time_zone: str
    current_today: date
    proposed_today: date
    today_changes: bool
    affected_entry_count: int
    affected_dates: list[date]
    affected_entries: list[CalendarImpactEntryResponse]
    preview_token: str


class CalendarChangePreviewRequest(BaseModel):
    """A proposed IANA zone to review against the current owner calendar."""

    time_zone: str


class CalendarChangeConfirmRequest(BaseModel):
    """Explicit confirmation of a previously reviewed calendar change."""

    time_zone: str
    calendar_revision: int = Field(ge=0)
    confirm_impacts: Literal[True]
    preview_token: str | None = Field(default=None, min_length=1)
