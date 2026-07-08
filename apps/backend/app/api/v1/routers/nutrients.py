from fastapi import APIRouter

from app.domain.nutrients import NUTRIENT_CATALOG
from app.schemas.nutrition import NutrientDefinitionSchema

router = APIRouter()


@router.get("", response_model=list[NutrientDefinitionSchema])
def list_nutrients() -> list[NutrientDefinitionSchema]:
    return [NutrientDefinitionSchema.model_validate(item) for item in NUTRIENT_CATALOG]
