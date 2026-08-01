from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies.database import get_db
from app.dependencies.user import get_current_user
from app.models.user import User
from app.schemas.calendar import (
    CalendarStateResponse,
    EstablishTimeZoneRequest,
)
from app.services.calendar_service import CalendarDomainError, CalendarService

router = APIRouter()


@router.get("", response_model=CalendarStateResponse)
def get_calendar_state(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CalendarStateResponse:
    state = CalendarService(db).state(user.id)
    return CalendarStateResponse.model_validate(state, from_attributes=True)


@router.put("", response_model=CalendarStateResponse)
def establish_calendar_time_zone(
    payload: EstablishTimeZoneRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CalendarStateResponse:
    try:
        state = CalendarService(db).establish(user.id, payload.time_zone)
    except CalendarDomainError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.detail(),
        ) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return CalendarStateResponse.model_validate(state, from_attributes=True)
