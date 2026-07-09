from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.integrations.usda.client import UsdaClient
from app.integrations.usda.mappers import USDA_SOURCE, map_food_preview, map_search_response
from app.integrations.usda.schemas import UsdaFoodPreview, UsdaSearchResponse
from app.models.food import FoodItem, FoodNutrient, FoodSource, ServingDefinition
from app.repositories.food_repository import FoodRepository


class UsdaService:
    def __init__(self, db: Session, client: UsdaClient):
        self.db = db
        self.client = client
        self.foods = FoodRepository(db)

    def search(self, query: str, *, page_size: int = 25, page_number: int = 1) -> UsdaSearchResponse:
        payload = self.client.search_foods(query=query, page_size=page_size, page_number=page_number)
        return map_search_response(payload, query=query, page_size=page_size, page_number=page_number)

    def preview(self, fdc_id: int) -> UsdaFoodPreview:
        payload = self.client.get_food(fdc_id)
        return map_food_preview(payload)

    def import_food(self, user_id: UUID, fdc_id: int) -> tuple[FoodItem, bool]:
        existing = self.foods.find_active_by_source(user_id, "usda", str(fdc_id))
        if existing is not None:
            return existing, True

        payload = self.client.get_food(fdc_id)
        preview = map_food_preview(payload)
        food = FoodItem(
            id=uuid4(),
            user_id=user_id,
            name=preview.name.strip(),
            brand=preview.brand.strip() if preview.brand else None,
            notes=None,
            source_type="usda",
            source_id=preview.external_id,
            is_recipe=False,
        )
        food.sources.append(
            FoodSource(
                id=uuid4(),
                source_type=USDA_SOURCE,
                external_id=preview.external_id,
                raw_payload=payload,
                source_metadata=preview.source_metadata | {"diagnostics": preview.diagnostics},
            )
        )
        for serving in preview.serving_definitions:
            food.serving_definitions.append(
                ServingDefinition(
                    id=uuid4(),
                    label=serving.label.strip(),
                    quantity=serving.quantity,
                    unit=serving.unit.strip().lower(),
                    gram_weight=serving.gram_weight,
                    is_default=serving.is_default,
                    source=USDA_SOURCE,
                    is_user_confirmed=False,
                )
            )
        for nutrient in preview.nutrients:
            food.nutrients.append(
                FoodNutrient(
                    id=uuid4(),
                    nutrient_id=nutrient.nutrient_id,
                    amount=nutrient.amount,
                    unit=nutrient.unit,
                    basis=nutrient.basis,
                    data_status=nutrient.data_status,
                    source=USDA_SOURCE,
                    is_user_confirmed=False,
                    original_amount=nutrient.original_amount,
                    original_unit=nutrient.original_unit,
                    original_text=nutrient.external_nutrient_id,
                )
            )

        try:
            created = self.foods.add(food)
            self.db.commit()
            return created, False
        except IntegrityError as exc:
            if not _is_source_identity_conflict(exc):
                raise
            self.db.rollback()
            existing_after_race = self.foods.find_active_by_source(user_id, "usda", str(fdc_id))
            if existing_after_race is None:
                raise
            return existing_after_race, True


def _is_source_identity_conflict(exc: IntegrityError) -> bool:
    orig = exc.orig
    constraint_name = getattr(getattr(orig, "diag", None), "constraint_name", None)
    if constraint_name == "ix_food_items_active_source_identity":
        return True
    if getattr(orig, "sqlstate", None) == "23505" and "ix_food_items_active_source_identity" in str(orig):
        return True
    return "ix_food_items_active_source_identity" in str(exc)
