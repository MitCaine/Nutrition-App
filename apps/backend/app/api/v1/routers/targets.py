from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.dependencies.database import get_db
from app.dependencies.user import get_current_user
from app.models.user import User
from app.schemas.target import (
    DailyTargetComparisonResponse,
    TargetConfigurationResponse,
    TargetConfigurationUpdate,
)
from app.services.target_service import TargetDomainError, TargetService


class TargetValidationRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError as exc:
                field_errors = []
                for error in exc.errors():
                    field = ".".join(str(item) for item in error["loc"] if item != "body")
                    code = "target_unit_invalid" if field.endswith("_unit") else "target_value_out_of_range"
                    field_errors.append(
                        {
                            "field": field,
                            "code": code,
                            "message": error["msg"],
                        }
                    )
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={
                        "detail": {
                            "code": "invalid_target_request",
                            "message": "Review the target fields and try again.",
                            "field_errors": field_errors,
                        }
                    },
                )

        return handler


router = APIRouter(route_class=TargetValidationRoute)


def _service(db: Session) -> TargetService:
    return TargetService(db)


def _domain_error(exc: TargetDomainError) -> HTTPException:
    return HTTPException(status_code=400, detail=exc.detail())


@router.get("", response_model=TargetConfigurationResponse)
def get_targets(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> TargetConfigurationResponse:
    return TargetConfigurationResponse.model_validate(
        _service(db).configuration(user.id, date.today())
    )


@router.put("", response_model=TargetConfigurationResponse)
def update_targets(
    payload: TargetConfigurationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TargetConfigurationResponse:
    try:
        result = _service(db).update(user.id, payload, date.today())
    except TargetDomainError as exc:
        raise _domain_error(exc) from exc
    return TargetConfigurationResponse.model_validate(result)


@router.delete("/overrides/{nutrient_id}", response_model=TargetConfigurationResponse)
def reset_target_override(
    nutrient_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TargetConfigurationResponse:
    try:
        result = _service(db).reset_override(user.id, nutrient_id, date.today())
    except TargetDomainError as exc:
        raise _domain_error(exc) from exc
    return TargetConfigurationResponse.model_validate(result)


@router.get("/daily-comparison", response_model=DailyTargetComparisonResponse)
def daily_target_comparison(
    date: date = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DailyTargetComparisonResponse:
    return DailyTargetComparisonResponse.model_validate(
        _service(db).daily_comparison(user.id, date)
    )
