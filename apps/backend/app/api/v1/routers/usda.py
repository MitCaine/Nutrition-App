from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.dependencies.database import get_db
from app.dependencies.user import get_current_user
from app.integrations.usda.client import UsdaClient, UsdaConfigurationError, UsdaUpstreamError
from app.integrations.usda.schemas import UsdaFoodPreview, UsdaSearchResponse
from app.models.user import User
from app.schemas.food import FoodResponse
from app.services.food_service import FoodService
from app.services.usda_service import UsdaService

router = APIRouter()


def get_usda_service(db: Session = Depends(get_db)) -> UsdaService:
    api_key = settings.usda_api_key.get_secret_value() if settings.usda_api_key else None
    return UsdaService(db, UsdaClient(api_key))


@router.get("/foods/search", response_model=UsdaSearchResponse)
def search_usda_foods(
    query: str = Query(min_length=1),
    page_size: int = Query(default=25, ge=1, le=50),
    page_number: int = Query(default=1, ge=1),
    service: UsdaService = Depends(get_usda_service),
    _user: User = Depends(get_current_user),
) -> UsdaSearchResponse:
    try:
        return service.search(query.strip(), page_size=page_size, page_number=page_number)
    except UsdaConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except UsdaUpstreamError as exc:
        if exc.status_code == status.HTTP_400_BAD_REQUEST:
            return UsdaSearchResponse(
                query=query.strip(),
                page_number=page_number,
                page_size=page_size,
                total_hits=0,
                foods=[],
            )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/foods/{fdc_id}", response_model=UsdaFoodPreview)
def preview_usda_food(
    fdc_id: int,
    service: UsdaService = Depends(get_usda_service),
    _user: User = Depends(get_current_user),
) -> UsdaFoodPreview:
    try:
        return service.preview(fdc_id)
    except UsdaConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except UsdaUpstreamError as exc:
        status_code = (
            status.HTTP_404_NOT_FOUND if exc.status_code == 404 else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.post(
    "/foods/{fdc_id}/import", response_model=FoodResponse, status_code=status.HTTP_201_CREATED
)
def import_usda_food(
    fdc_id: int,
    response: Response,
    db: Session = Depends(get_db),
    service: UsdaService = Depends(get_usda_service),
    user: User = Depends(get_current_user),
) -> FoodResponse:
    try:
        food, duplicate = service.import_food(user.id, fdc_id)
    except UsdaConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except UsdaUpstreamError as exc:
        status_code = (
            status.HTTP_404_NOT_FOUND if exc.status_code == 404 else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    if duplicate:
        response.status_code = status.HTTP_200_OK
        response.headers["X-Nutrition-App-Duplicate-Import"] = "true"
        return FoodResponse.model_validate(FoodService(db).present_food(user.id, food))
    return FoodResponse.model_validate(FoodService(db).present_food(user.id, food))
