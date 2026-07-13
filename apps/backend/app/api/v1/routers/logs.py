from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.dependencies.database import get_db
from app.dependencies.user import ensure_dev_user
from app.domain.recipe_nutrition_validation import RecipeNutritionValidationError
from app.schemas.log import (
    DailyLogCreateRequest,
    DailyLogListResponse,
    DailyLogResponse,
    DailyLogUpdateRequest,
    DailySummaryResponse,
)
from app.services.log_service import LogEditConflictError, LogService

router = APIRouter()


def _service(db: Session) -> LogService:
    return LogService(db)


@router.post("", response_model=DailyLogResponse, status_code=status.HTTP_201_CREATED)
def create_log(payload: DailyLogCreateRequest, db: Session = Depends(get_db)) -> DailyLogResponse:
    user = ensure_dev_user(db)
    try:
        return DailyLogResponse.model_validate(_service(db).create_log(user.id, payload))
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=DailyLogListResponse)
def list_logs(
    date: date = Query(...),
    db: Session = Depends(get_db),
) -> DailyLogListResponse:
    user = ensure_dev_user(db)
    return DailyLogListResponse(logs=_service(db).list_logs(user.id, date))


@router.get("/daily-summary", response_model=DailySummaryResponse)
def daily_summary(
    date: date = Query(...),
    db: Session = Depends(get_db),
) -> DailySummaryResponse:
    user = ensure_dev_user(db)
    return DailySummaryResponse(logged_date=date, totals=_service(db).daily_summary(user.id, date))


@router.patch("/{log_id}", response_model=DailyLogResponse)
def update_log(
    log_id: UUID,
    payload: DailyLogUpdateRequest,
    db: Session = Depends(get_db),
) -> DailyLogResponse:
    user = ensure_dev_user(db)
    try:
        return DailyLogResponse.model_validate(_service(db).update_log(user.id, log_id, payload))
    except LogEditConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except RecipeNutritionValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.detail()) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_log(log_id: UUID, db: Session = Depends(get_db)) -> None:
    user = ensure_dev_user(db)
    try:
        _service(db).delete_log(user.id, log_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
