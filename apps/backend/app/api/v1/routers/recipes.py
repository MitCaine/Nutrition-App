from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.dependencies.database import get_db
from app.dependencies.user import ensure_dev_user
from app.domain.recipe_nutrition_validation import RecipeNutritionValidationError
from app.domain.recipe_projection import RecipeProjectionMutationError
from app.schemas.recipe import (
    RecipeCreateRequest,
    RecipeListResponse,
    RecipeNutritionResponse,
    RecipePublishResponse,
    RecipeResponse,
    RecipeUpdateRequest,
)
from app.services.recipe_service import RecipeDependencyError, RecipeService

router = APIRouter()


def _service(db: Session) -> RecipeService:
    return RecipeService(db)


@router.post("", response_model=RecipeResponse, status_code=status.HTTP_201_CREATED)
def create_recipe(payload: RecipeCreateRequest, db: Session = Depends(get_db)) -> RecipeResponse:
    user = ensure_dev_user(db)
    try:
        return RecipeResponse.model_validate(_service(db).create_recipe(user.id, payload))
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=RecipeListResponse)
def list_recipes(
    q: str | None = Query(default=None, min_length=1),
    db: Session = Depends(get_db),
) -> RecipeListResponse:
    user = ensure_dev_user(db)
    return RecipeListResponse(recipes=_service(db).list_recipes(user.id, q))


@router.get("/{recipe_id}", response_model=RecipeResponse)
def get_recipe(recipe_id: UUID, db: Session = Depends(get_db)) -> RecipeResponse:
    user = ensure_dev_user(db)
    try:
        return RecipeResponse.model_validate(_service(db).get_recipe(user.id, recipe_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{recipe_id}", response_model=RecipeResponse)
def update_recipe(
    recipe_id: UUID,
    payload: RecipeUpdateRequest,
    db: Session = Depends(get_db),
) -> RecipeResponse:
    user = ensure_dev_user(db)
    try:
        return RecipeResponse.model_validate(_service(db).update_recipe(user.id, recipe_id, payload))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recipe(
    recipe_id: UUID,
    remove_from_recipes: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> None:
    user = ensure_dev_user(db)
    try:
        _service(db).soft_delete_recipe(
            user.id,
            recipe_id,
            remove_from_recipes=remove_from_recipes,
        )
    except RecipeDependencyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.dependency.model_dump(mode="json"),
        ) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RecipeProjectionMutationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.detail(),
        ) from exc


@router.get("/{recipe_id}/nutrition", response_model=RecipeNutritionResponse)
def recipe_nutrition(recipe_id: UUID, db: Session = Depends(get_db)) -> RecipeNutritionResponse:
    user = ensure_dev_user(db)
    try:
        return RecipeNutritionResponse(**_service(db).nutrition(user.id, recipe_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RecipeNutritionValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.detail()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{recipe_id}/publish", response_model=RecipePublishResponse)
def publish_recipe(recipe_id: UUID, db: Session = Depends(get_db)) -> RecipePublishResponse:
    user = ensure_dev_user(db)
    try:
        recipe, food = _service(db).publish(user.id, recipe_id)
        return RecipePublishResponse(
            recipe=RecipeResponse.model_validate(recipe),
            food=food,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RecipeNutritionValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.detail()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
