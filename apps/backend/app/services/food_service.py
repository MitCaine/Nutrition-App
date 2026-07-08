from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.models.food import FoodItem, FoodNutrient, ServingDefinition
from app.repositories.food_repository import FoodRepository
from app.schemas.food import FoodCreateRequest, FoodUpdateRequest


class FoodService:
    def __init__(self, db: Session):
        self.db = db
        self.foods = FoodRepository(db)

    def create_manual_food(self, user_id: UUID, payload: FoodCreateRequest) -> FoodItem:
        food = FoodItem(
            id=uuid4(),
            user_id=user_id,
            name=payload.name.strip(),
            brand=payload.brand.strip() if payload.brand else None,
            notes=payload.notes,
            source_type="manual",
            source_id=None,
            is_recipe=False,
        )
        self._replace_servings(food, payload.serving_definitions)
        self._replace_nutrients(food, payload.nutrients)
        created = self.foods.add(food)
        self.db.commit()
        return created

    def list_foods(self, user_id: UUID, query: str | None = None) -> list[FoodItem]:
        return self.foods.list(user_id, query)

    def get_food(self, user_id: UUID, food_id: UUID) -> FoodItem:
        return self.foods.get_required(food_id, user_id)

    def update_food(self, user_id: UUID, food_id: UUID, payload: FoodUpdateRequest) -> FoodItem:
        food = self.foods.get_required(food_id, user_id)
        if payload.name is not None:
            food.name = payload.name.strip()
        if payload.brand is not None:
            food.brand = payload.brand.strip() if payload.brand else None
        if payload.notes is not None:
            food.notes = payload.notes
        if payload.serving_definitions is not None:
            food.serving_definitions.clear()
            self._replace_servings(food, payload.serving_definitions)
        if payload.nutrients is not None:
            food.nutrients.clear()
            self._replace_nutrients(food, payload.nutrients)
        food.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        return self.foods.get_required(food_id, user_id)

    def soft_delete_food(self, user_id: UUID, food_id: UUID) -> None:
        food = self.foods.get_required(food_id, user_id)
        food.deleted_at = datetime.now(timezone.utc)
        food.updated_at = datetime.now(timezone.utc)
        self.db.commit()

    def duplicate_food(self, user_id: UUID, food_id: UUID) -> FoodItem:
        source = self.foods.get_required(food_id, user_id)
        duplicate = FoodItem(
            id=uuid4(),
            user_id=user_id,
            name=f"{source.name} Copy",
            brand=source.brand,
            notes=source.notes,
            source_type="manual",
            source_id=str(source.id),
            is_recipe=False,
        )
        for serving in source.serving_definitions:
            duplicate.serving_definitions.append(
                ServingDefinition(
                    id=uuid4(),
                    label=serving.label,
                    quantity=serving.quantity,
                    unit=serving.unit,
                    gram_weight=serving.gram_weight,
                    is_default=serving.is_default,
                    source="manual",
                    is_user_confirmed=True,
                )
            )
        for nutrient in source.nutrients:
            duplicate.nutrients.append(
                FoodNutrient(
                    id=uuid4(),
                    nutrient_id=nutrient.nutrient_id,
                    amount=nutrient.amount,
                    unit=nutrient.unit,
                    basis=nutrient.basis,
                    data_status=nutrient.data_status,
                    source="manual",
                    is_user_confirmed=True,
                    original_amount=nutrient.original_amount,
                    original_unit=nutrient.original_unit,
                    original_text=nutrient.original_text,
                )
            )
        created = self.foods.add(duplicate)
        self.db.commit()
        return created

    def _replace_servings(self, food: FoodItem, servings) -> None:
        for serving in servings:
            food.serving_definitions.append(
                ServingDefinition(
                    id=uuid4(),
                    label=serving.label.strip(),
                    quantity=serving.quantity,
                    unit=serving.unit,
                    gram_weight=serving.gram_weight,
                    is_default=serving.is_default,
                    source="manual",
                    is_user_confirmed=True,
                )
            )

    def _replace_nutrients(self, food: FoodItem, nutrients) -> None:
        for nutrient in nutrients:
            original = nutrient.original
            food.nutrients.append(
                FoodNutrient(
                    id=uuid4(),
                    nutrient_id=nutrient.nutrient_id,
                    amount=nutrient.amount,
                    unit=nutrient.unit,
                    basis=nutrient.basis.value,
                    data_status=nutrient.data_status.value,
                    source="manual",
                    is_user_confirmed=True,
                    original_amount=original.amount if original else None,
                    original_unit=original.unit if original else None,
                    original_text=original.text if original else None,
                )
            )
