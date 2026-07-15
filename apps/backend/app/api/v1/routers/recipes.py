from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.dependencies.database import get_db
from app.dependencies.user import get_current_user
from app.domain.recipe_nutrition_validation import RecipeNutritionValidationError
from app.domain.recipe_projection import RecipeProjectionMutationError
from app.models.user import User
from app.schemas.recipe import (
    RecipeCreateRequest,
    RecipeListResponse,
    RecipeNutritionResponse,
    RecipePublishResponse,
    RecipePublishRequest,
    RecipeResponse,
    RecipeUpdateRequest,
)
from app.services.create_idempotency import (
    CreateOperationIdempotencyConflictError,
    CreateOperationResultUnavailableError,
)
from app.services.recipe_service import (
    RecipeDependencyError,
    RecipeGraphCycleError,
    RecipePublicationDependenciesUnstableError,
    RecipePublicationParentAmountConflictError,
    RecipeService,
)

router = APIRouter()


def _service(db: Session) -> RecipeService:
    return RecipeService(db)


@router.post("", response_model=RecipeResponse, status_code=status.HTTP_201_CREATED)
def create_recipe(
    payload: RecipeCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RecipeResponse:
    try:
        return _service(db).create_recipe(user.id, payload)
    except RecipeGraphCycleError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.detail()) from exc
    except CreateOperationIdempotencyConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.detail()) from exc
    except CreateOperationResultUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.detail()) from exc
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=RecipeListResponse)
def list_recipes(
    q: str | None = Query(default=None, min_length=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RecipeListResponse:
    return RecipeListResponse(recipes=_service(db).list_recipes(user.id, q))


@router.get("/{recipe_id}", response_model=RecipeResponse)
def get_recipe(
    recipe_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RecipeResponse:
    try:
        return RecipeResponse.model_validate(_service(db).get_recipe(user.id, recipe_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{recipe_id}", response_model=RecipeResponse)
def update_recipe(
    recipe_id: UUID,
    payload: RecipeUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RecipeResponse:
    try:
        return RecipeResponse.model_validate(
            _service(db).update_recipe(user.id, recipe_id, payload)
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RecipeGraphCycleError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.detail()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recipe(
    recipe_id: UUID,
    remove_from_recipes: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
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
def recipe_nutrition(
    recipe_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RecipeNutritionResponse:
    try:
        return RecipeNutritionResponse(**_service(db).nutrition(user.id, recipe_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RecipeNutritionValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.detail()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{recipe_id}/publish", response_model=RecipePublishResponse)
def publish_recipe(
    recipe_id: UUID,
    payload: RecipePublishRequest | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RecipePublishResponse:
    try:
        result = _service(db).publish(
            user.id,
            recipe_id,
            payload.client_request_id if payload is not None else None,
        )
        return result.response
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RecipeNutritionValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.detail()) from exc
    except RecipePublicationParentAmountConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.conflict.model_dump(mode="json"),
        ) from exc
    except RecipePublicationDependenciesUnstableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.detail(),
        ) from exc
    except CreateOperationIdempotencyConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.detail()) from exc
    except CreateOperationResultUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.detail()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
