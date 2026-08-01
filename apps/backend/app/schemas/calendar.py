from __future__ import annotations

from pydantic import BaseModel


class CalendarStateResponse(BaseModel):
    """The owner-scoped calendar authority consumed by Daily Log clients."""

    is_established: bool
    authoritative_time_zone: str | None


class EstablishTimeZoneRequest(BaseModel):
    """An explicit initial confirmation of the client's proposed IANA zone."""

    time_zone: str
