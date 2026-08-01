from datetime import date
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.dependencies.database import get_db
from app.dependencies.user import get_current_user
from app.domain.log_contracts import LogContractError
from app.domain.recipe_nutrition_validation import RecipeNutritionValidationError
from app.models.user import User
from app.schemas.log import (
    DailyLogCreateRequest,
    DailyLogDeleteRequest,
    DailyLogEditContextResponse,
    DailyLogListResponse,
    DailyLogMutationStatusResponse,
    DailyLogResponse,
    DailyLogUpdateRequest,
    DailySummaryResponse,
    RecentEntryListResponse,
)
from app.services.calendar_service import (
    AuthoritativeTimeZoneRequiredError,
    CalendarDomainError,
)
from app.services.log_service import (
    LogEditConflictError,
    LogIdempotencyConflictError,
    LogMutationPayloadConflictError,
    LogMutationResultUnavailableError,
    LogMutationReplay,
    LogSourceAmountChangedError,
    LogSourceChangedError,
    LogSourceUnavailableError,
    LogService,
    StaleLogMutationError,
)

_LOG_CONTRACT_ERROR_CODES = frozenset({"meal_invalid", "note_invalid", "note_too_long"})


class DailyLogValidationRoute(APIRoute):
    """Return stable field errors for meal and note contract violations."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError as exc:
                contract_errors = [
                    error for error in exc.errors() if error["type"] in _LOG_CONTRACT_ERROR_CODES
                ]
                if not contract_errors:
                    raise
                field_errors = [
                    {
                        "field": ".".join(str(item) for item in error["loc"] if item != "body"),
                        "code": error["type"],
                        "message": error["msg"],
                    }
                    for error in contract_errors
                ]
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={
                        "detail": {
                            "code": "invalid_daily_log_request",
                            "message": "Review the meal and note fields and try again.",
                            "field_errors": field_errors,
                        }
                    },
                )

        return handler


router = APIRouter(route_class=DailyLogValidationRoute)


def _service(db: Session) -> LogService:
    return LogService(db)


@router.post("", response_model=DailyLogResponse, status_code=status.HTTP_201_CREATED)
def create_log(
    payload: DailyLogCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DailyLogResponse:
    try:
        return DailyLogResponse.model_validate(_service(db).create_log(user.id, payload))
    except LogContractError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.detail()) from exc
    except AuthoritativeTimeZoneRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.detail(),
        ) from exc
    except CalendarDomainError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.detail(),
        ) from exc
    except LogIdempotencyConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except (LogSourceChangedError, LogSourceAmountChangedError, LogSourceUnavailableError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=DailyLogListResponse)
def list_logs(
    date: date = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DailyLogListResponse:
    return DailyLogListResponse(logs=_service(db).list_logs(user.id, date))


@router.get("/recent-entries", response_model=RecentEntryListResponse)
def list_recent_entries(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RecentEntryListResponse:
    try:
        return RecentEntryListResponse(
            entries=_service(db).list_recent_entries(user.id),
        )
    except AuthoritativeTimeZoneRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.detail(),
        ) from exc


@router.get("/daily-summary", response_model=DailySummaryResponse)
def daily_summary(
    date: date = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DailySummaryResponse:
    return DailySummaryResponse(logged_date=date, totals=_service(db).daily_summary(user.id, date))


@router.get(
    "/mutations/{client_request_id}",
    response_model=DailyLogMutationStatusResponse,
)
def mutation_status(
    client_request_id: UUID,
    operation: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DailyLogMutationStatusResponse:
    """Return an owner-scoped terminal or recoverable mutation outcome."""

    return _service(db).mutation_status(user.id, client_request_id, operation)


@router.get("/{log_id}/edit-context", response_model=DailyLogEditContextResponse)
def log_edit_context(
    log_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DailyLogEditContextResponse:
    try:
        return _service(db).edit_context(user.id, log_id)
    except RecipeNutritionValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.detail()) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{log_id}", response_model=DailyLogResponse)
def update_log(
    log_id: UUID,
    payload: DailyLogUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DailyLogResponse:
    try:
        result = _service(db).update_log(user.id, log_id, payload)
        if isinstance(result, LogMutationReplay):
            return DailyLogResponse.model_validate(result.snapshot)
        return DailyLogResponse.model_validate(result)
    except LogContractError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.detail()) from exc
    except AuthoritativeTimeZoneRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.detail(),
        ) from exc
    except CalendarDomainError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.detail(),
        ) from exc
    except LogEditConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except (LogMutationPayloadConflictError, StaleLogMutationError, LogMutationResultUnavailableError) as exc:
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
def delete_log(
    log_id: UUID,
    payload: DailyLogDeleteRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    try:
        _service(db).delete_log(user.id, log_id, payload)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except AuthoritativeTimeZoneRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.detail(),
        ) from exc
    except (LogMutationPayloadConflictError, StaleLogMutationError, LogMutationResultUnavailableError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
