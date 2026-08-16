from __future__ import annotations

from decimal import Decimal
import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.food import FoodItem, FoodNutrient
from tests.postgres_test_support import isolated_postgres_session_factory


pytestmark = pytest.mark.postgres_concurrency

POSTGRES_URL = os.getenv(
    "NUTRITION_TEST_POSTGRES_URL",
    "postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app",
)


@pytest.fixture()
def postgres_sessions():
    with isolated_postgres_session_factory(
        database_url=POSTGRES_URL,
        schema_prefix="test_food_nutrient_integrity",
    ) as factory:
        yield factory


def _seed_food(postgres_sessions) -> tuple:
    food_id = uuid4()
    nutrient_row_id = uuid4()

    with postgres_sessions() as db:
        db.add(
            FoodItem(
                id=food_id,
                user_id=None,
                name="Food nutrient integrity control",
                brand=None,
                source_type="manual",
                source_id=None,
                recipe_publication_revision_id=None,
                is_recipe=False,
                notes=None,
            )
        )
        db.flush()
        db.add(
            FoodNutrient(
                id=nutrient_row_id,
                food_item_id=food_id,
                nutrient_id="total_fat",
                amount=Decimal("2.000000"),
                unit="g",
                basis="per_100g",
                data_status="known",
                confidence=None,
                source="manual",
                is_user_confirmed=True,
                original_amount=None,
                original_unit=None,
                original_text=None,
            )
        )
        db.commit()

    return food_id, nutrient_row_id


def test_postgres_food_nutrient_rejects_negative_and_preserves_zero(
    postgres_sessions,
) -> None:
    _food_id, nutrient_row_id = _seed_food(postgres_sessions)

    with postgres_sessions() as db:
        nutrient = db.get(FoodNutrient, nutrient_row_id)
        assert nutrient is not None
        nutrient.amount = Decimal("-1.000000")

        with pytest.raises(IntegrityError) as caught:
            db.flush()

        assert (
            caught.value.orig.diag.constraint_name
            == "ck_food_nutrients_amount_nonnegative"
        )
        db.rollback()

        nutrient = db.get(FoodNutrient, nutrient_row_id)
        assert nutrient is not None
        assert nutrient.amount == Decimal("2.000000")

        nutrient.amount = Decimal("0.000000")
        nutrient.data_status = "zero"
        db.commit()

    with postgres_sessions() as db:
        nutrient = db.get(FoodNutrient, nutrient_row_id)
        assert nutrient is not None
        assert nutrient.amount == Decimal("0.000000")
        assert nutrient.data_status == "zero"


def test_postgres_food_nutrient_allows_unknown_amountless_value(
    postgres_sessions,
) -> None:
    food_id, _nutrient_row_id = _seed_food(postgres_sessions)

    with postgres_sessions() as db:
        unknown_id = uuid4()
        db.add(
            FoodNutrient(
                id=unknown_id,
                food_item_id=food_id,
                nutrient_id="protein",
                amount=None,
                unit="g",
                basis="per_100g",
                data_status="unknown",
                confidence=None,
                source="manual",
                is_user_confirmed=False,
                original_amount=None,
                original_unit=None,
                original_text=None,
            )
        )
        db.commit()

    with postgres_sessions() as db:
        unknown = db.get(FoodNutrient, unknown_id)
        assert unknown is not None
        assert unknown.amount is None
        assert unknown.data_status == "unknown"


def test_postgres_food_nutrient_allows_same_nutrient_at_distinct_bases(
    postgres_sessions,
) -> None:
    food_id, _nutrient_row_id = _seed_food(postgres_sessions)

    with postgres_sessions() as db:
        db.add(
            FoodNutrient(
                id=uuid4(),
                food_item_id=food_id,
                nutrient_id="total_fat",
                amount=Decimal("4.000000"),
                unit="g",
                basis="per_serving",
                data_status="known",
                confidence=None,
                source="manual",
                is_user_confirmed=True,
                original_amount=None,
                original_unit=None,
                original_text=None,
            )
        )
        db.commit()

    with postgres_sessions() as db:
        rows = db.scalars(
            select(FoodNutrient).where(
                FoodNutrient.food_item_id == food_id,
                FoodNutrient.nutrient_id == "total_fat",
            )
        ).all()

        assert len(rows) == 2
        assert {row.basis for row in rows} == {
            "per_100g",
            "per_serving",
        }


def test_postgres_food_nutrient_rejects_duplicate_identity_and_rolls_back(
    postgres_sessions,
) -> None:
    food_id, _nutrient_row_id = _seed_food(postgres_sessions)

    with postgres_sessions() as db:
        db.add(
            FoodNutrient(
                id=uuid4(),
                food_item_id=food_id,
                nutrient_id="total_fat",
                amount=Decimal("3.000000"),
                unit="g",
                basis="per_100g",
                data_status="known",
                confidence=None,
                source="manual",
                is_user_confirmed=True,
                original_amount=None,
                original_unit=None,
                original_text=None,
            )
        )

        with pytest.raises(IntegrityError) as caught:
            db.flush()

        assert (
            caught.value.orig.diag.constraint_name
            == "uq_food_nutrients_food_nutrient_basis"
        )
        db.rollback()

        count = db.scalar(
            select(func.count())
            .select_from(FoodNutrient)
            .where(
                FoodNutrient.food_item_id == food_id,
                FoodNutrient.nutrient_id == "total_fat",
            )
        )
        assert count == 1
