from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies.database import get_db
from app.dependencies.user import get_current_user
from app.models.user import User
from app.schemas.calendar import (
    CalendarChangeConfirmRequest,
    CalendarChangePreviewRequest,
    CalendarImpactEntryResponse,
    CalendarImpactPreviewResponse,
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


@router.post("/preview", response_model=CalendarImpactPreviewResponse)
def preview_calendar_time_zone_change(
    payload: CalendarChangePreviewRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CalendarImpactPreviewResponse:
    try:
        preview = CalendarService(db).preview_change(user.id, payload.time_zone)
    except CalendarDomainError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.detail(),
        ) from exc
    return CalendarImpactPreviewResponse(
        calendar_revision=preview.calendar_revision,
        current_time_zone=preview.current_time_zone,
        proposed_time_zone=preview.proposed_time_zone,
        current_today=preview.current_today,
        proposed_today=preview.proposed_today,
        today_changes=preview.today_changes,
        affected_entry_count=len(preview.affected_entries),
        affected_dates=preview.affected_dates,
        affected_entries=[
            CalendarImpactEntryResponse.model_validate(entry) for entry in preview.affected_entries
        ],
        preview_token=preview.preview_token,
    )


@router.post("/confirm", response_model=CalendarStateResponse)
def confirm_calendar_time_zone_change(
    payload: CalendarChangeConfirmRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CalendarStateResponse:
    try:
        state = CalendarService(db).confirm_change(
            user.id,
            payload.time_zone,
            payload.calendar_revision,
            payload.preview_token,
        )
    except CalendarDomainError as exc:
        code_status = {
            "stale_calendar_preview": status.HTTP_409_CONFLICT,
            "time_zone_not_established": status.HTTP_409_CONFLICT,
        }.get(exc.code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        raise HTTPException(status_code=code_status, detail=exc.detail()) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
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
