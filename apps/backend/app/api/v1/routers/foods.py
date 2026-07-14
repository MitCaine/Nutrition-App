from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.dependencies.database import get_db
from app.dependencies.user import get_current_user
from app.domain.recipe_projection import RecipeProjectionMutationError
from app.models.user import User
from app.schemas.food import (
    FoodCreateRequest,
    FoodDeleteResultResponse,
    FoodListResponse,
    FoodResolvedNutritionResponse,
    RecentFoodListResponse,
    FoodResponse,
    FoodUpdateRequest,
    ServingDefinitionInput,
)
from app.services.food_service import FoodDependencyError, FoodService

router = APIRouter()


def _service(db: Session) -> FoodService:
    return FoodService(db)


@router.get("/favorites", response_model=FoodListResponse)
def list_favorites(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> FoodListResponse:
    return FoodListResponse(foods=_service(db).list_favorites(user.id))


@router.get("/recent", response_model=RecentFoodListResponse)
def list_recent_foods(
    limit: int = Query(default=10, ge=1, le=20),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RecentFoodListResponse:
    return RecentFoodListResponse(foods=_service(db).list_recent(user.id, limit))


@router.post("", response_model=FoodResponse, status_code=status.HTTP_201_CREATED)
def create_food(
    payload: FoodCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FoodResponse:
    service = _service(db)
    return FoodResponse.model_validate(
        service.present_food(user.id, service.create_manual_food(user.id, payload))
    )


@router.get("", response_model=FoodListResponse)
def list_foods(
    q: str | None = Query(default=None, min_length=1),
    view: Literal["saved"] | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FoodListResponse:
    return FoodListResponse(foods=_service(db).list_foods(user.id, q, saved_view=view == "saved"))


@router.get("/{food_id}", response_model=FoodResponse)
def get_food(
    food_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FoodResponse:
    try:
        return FoodResponse.model_validate(_service(db).get_food(user.id, food_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RecipeProjectionMutationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.detail()) from exc


@router.put("/{food_id}/favorite", response_model=FoodResponse)
def favorite_food(
    food_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FoodResponse:
    try:
        return FoodResponse.model_validate(
            _service(db).set_favorite(user.id, food_id, favorite=True)
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{food_id}/favorite", response_model=FoodResponse)
def unfavorite_food(
    food_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FoodResponse:
    try:
        return FoodResponse.model_validate(
            _service(db).set_favorite(user.id, food_id, favorite=False)
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{food_id}/resolved-nutrition", response_model=FoodResolvedNutritionResponse)
def resolved_food_nutrition(
    food_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FoodResolvedNutritionResponse:
    try:
        return _service(db).resolved_nutrition(user.id, food_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RecipeProjectionMutationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.detail()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{food_id}", response_model=FoodResponse)
def update_food(
    food_id: UUID,
    payload: FoodUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FoodResponse:
    try:
        service = _service(db)
        return FoodResponse.model_validate(
            service.present_food(user.id, service.update_food(user.id, food_id, payload))
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RecipeProjectionMutationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.detail()) from exc


@router.delete("/{food_id}", response_model=FoodDeleteResultResponse)
def delete_food(
    food_id: UUID,
    remove_from_recipes: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FoodDeleteResultResponse:
    try:
        return _service(db).soft_delete_food(
            user.id, food_id, remove_from_recipes=remove_from_recipes
        )
    except FoodDependencyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=exc.dependency.model_dump(mode="json")
        ) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RecipeProjectionMutationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.detail()) from exc


@router.post(
    "/{food_id}/duplicate", response_model=FoodResponse, status_code=status.HTTP_201_CREATED
)
def duplicate_food(
    food_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FoodResponse:
    try:
        service = _service(db)
        return FoodResponse.model_validate(
            service.present_food(user.id, service.duplicate_food(user.id, food_id))
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/{food_id}/serving-definitions",
    response_model=FoodResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_serving_definition(
    food_id: UUID,
    payload: ServingDefinitionInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FoodResponse:
    try:
        service = _service(db)
        return FoodResponse.model_validate(
            service.present_food(user.id, service.add_serving_definition(user.id, food_id, payload))
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RecipeProjectionMutationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.detail()) from exc
