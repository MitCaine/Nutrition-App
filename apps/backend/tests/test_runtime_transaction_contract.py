from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dependencies.user import ensure_dev_user
from app.models.food import FoodFavorite, FoodItem, FoodNutrient, ServingDefinition
from app.models.log import DailyLog
from app.models.recipe import Recipe
from app.models.target import NutritionTarget
from app.models.user import User, UserProfile
from app.schemas.log import DailyLogCreateRequest, DailyLogUpdateRequest
from app.schemas.recipe import RecipeCreateRequest, RecipeUpdateRequest
from app.schemas.target import TargetConfigurationUpdate
from app.services.food_service import FoodService
from app.services.log_service import LogService
from app.services.recipe_service import RecipeService
from app.services.target_service import TargetService
from app.services.usda_service import UsdaService
from tests.test_stage3_usda_import import FakeUsdaClient
from tests.test_stage3_usda_mapper import usda_banana_payload


def _marker_commit(db: Session) -> None:
    marker = User(id=uuid4(), email=f"session-reuse-{uuid4()}@example.test")
    db.add(marker)
    db.commit()
    assert db.get(User, marker.id) is not None


def _target_payload(*, protein: str | None) -> TargetConfigurationUpdate:
    return TargetConfigurationUpdate.model_validate(
        {
            "profile": {
                "birth_date": "1996-01-15",
                "sex_for_equation": "male",
                "height_cm": "175",
                "height_unit": "cm",
                "weight_kg": "70",
                "weight_unit": "kg",
                "activity_level": "sedentary",
                "energy_estimation_context": "general_adult",
            },
            "manual_overrides": {
                "calories": None,
                "protein": protein,
                "total_carbohydrate": None,
                "total_fat": None,
            },
        }
    )


def test_recipe_update_failure_rolls_back_flushed_mutation_and_session_is_reusable(
    db_session: Session,
) -> None:
    user = ensure_dev_user(db_session)
    original = RecipeService(db_session).create_recipe(
        user.id,
        RecipeCreateRequest(name="Original Recipe", serving_count_yield=Decimal("1")),
    )
    service = RecipeService(db_session)

    def fail_after_flush(_recipe: Recipe) -> None:
        raise RuntimeError("forced Recipe update failure")

    service._after_recipe_update_flush = fail_after_flush
    with pytest.raises(RuntimeError, match="forced Recipe update failure"):
        service.update_recipe(
            user.id,
            original.id,
            RecipeUpdateRequest(name="Partial Recipe"),
        )

    assert not db_session.in_transaction()
    _marker_commit(db_session)
    db_session.expire_all()
    assert db_session.get(Recipe, original.id).name == "Original Recipe"


def test_target_update_failure_rolls_back_profile_and_overrides_and_session_is_reusable(
    db_session: Session,
) -> None:
    user = ensure_dev_user(db_session)
    service = TargetService(db_session)

    def fail_after_flush(_user_id) -> None:
        raise RuntimeError("forced Target update failure")

    service._after_target_update_flush = fail_after_flush
    with pytest.raises(RuntimeError, match="forced Target update failure"):
        service.update(user.id, _target_payload(protein="150"), date(2026, 7, 21))

    assert not db_session.in_transaction()
    _marker_commit(db_session)
    assert db_session.get(UserProfile, user.id) is None
    assert db_session.scalar(select(func.count(NutritionTarget.id))) == 0


def test_target_reset_failure_restores_override_and_session_is_reusable(
    db_session: Session,
) -> None:
    user = ensure_dev_user(db_session)
    TargetService(db_session).update(
        user.id,
        _target_payload(protein="150"),
        date(2026, 7, 21),
    )
    service = TargetService(db_session)

    def fail_after_flush(_user_id, _nutrient_id) -> None:
        raise RuntimeError("forced Target reset failure")

    service._after_target_reset_flush = fail_after_flush
    with pytest.raises(RuntimeError, match="forced Target reset failure"):
        service.reset_override(user.id, "protein", date(2026, 7, 21))

    assert not db_session.in_transaction()
    _marker_commit(db_session)
    stored = db_session.scalar(
        select(NutritionTarget).where(
            NutritionTarget.user_id == user.id,
            NutritionTarget.nutrient_id == "protein",
        )
    )
    assert stored is not None
    assert stored.target_amount == Decimal("150.000000")


def test_log_delete_failure_restores_log_and_session_is_reusable(db_session: Session) -> None:
    user = ensure_dev_user(db_session)
    serving = ServingDefinition(
        id=uuid4(),
        label="1 portion",
        quantity=Decimal("1"),
        unit="portion",
        gram_weight=Decimal("100"),
        is_default=True,
        source="manual",
        is_user_confirmed=True,
    )
    food = FoodItem(
        id=uuid4(),
        user_id=user.id,
        name="Delete rollback Food",
        source_type="manual",
        is_recipe=False,
        serving_definitions=[serving],
    )
    db_session.add(food)
    db_session.commit()
    log = LogService(db_session).create_log(
        user.id,
        DailyLogCreateRequest(
            food_item_id=food.id,
            logged_date=date(2026, 7, 21),
            amount_quantity=Decimal("1"),
            amount_unit="serving",
            serving_definition_id=serving.id,
        ),
    )
    service = LogService(db_session)

    def fail_after_flush(_log: DailyLog) -> None:
        raise RuntimeError("forced DailyLog delete failure")

    service._after_log_delete_flush = fail_after_flush
    with pytest.raises(RuntimeError, match="forced DailyLog delete failure"):
        service.delete_log(user.id, log.id)

    assert not db_session.in_transaction()
    _marker_commit(db_session)
    assert db_session.get(DailyLog, log.id) is not None


def test_mutable_log_edit_failure_preserves_historical_snapshot_and_session_is_reusable(
    db_session: Session,
) -> None:
    user = ensure_dev_user(db_session)
    serving = ServingDefinition(
        id=uuid4(),
        label="1 portion",
        quantity=Decimal("1"),
        unit="portion",
        gram_weight=Decimal("100"),
        is_default=True,
        source="manual",
        is_user_confirmed=True,
    )
    food = FoodItem(
        id=uuid4(),
        user_id=user.id,
        name="Log edit rollback Food",
        source_type="manual",
        is_recipe=False,
        serving_definitions=[serving],
        nutrients=[
            FoodNutrient(
                id=uuid4(),
                nutrient_id="calories",
                amount=Decimal("100"),
                unit="kcal",
                basis="per_serving",
                data_status="known",
                source="manual",
                is_user_confirmed=True,
            )
        ],
    )
    db_session.add(food)
    db_session.commit()
    log = LogService(db_session).create_log(
        user.id,
        DailyLogCreateRequest(
            food_item_id=food.id,
            logged_date=date(2026, 7, 21),
            amount_quantity=Decimal("1"),
            amount_unit="serving",
            serving_definition_id=serving.id,
        ),
    )
    service = LogService(db_session)

    def fail_after_flush(_log: DailyLog) -> None:
        raise RuntimeError("forced mutable log edit failure")

    service._after_edit_snapshot_regeneration = fail_after_flush
    with pytest.raises(RuntimeError, match="forced mutable log edit failure"):
        service.update_log(
            user.id,
            log.id,
            DailyLogUpdateRequest(amount_quantity=Decimal("3")),
        )

    assert not db_session.in_transaction()
    _marker_commit(db_session)
    db_session.expire_all()
    stored = db_session.get(DailyLog, log.id)
    assert stored.amount_quantity == Decimal("1.000000")
    assert len(stored.snapshots) == 1
    assert stored.snapshots[0].amount == Decimal("100.000000")


def test_favorite_failure_rolls_back_insert_and_session_is_reusable(db_session: Session) -> None:
    user = ensure_dev_user(db_session)
    food = FoodItem(
        id=uuid4(),
        user_id=user.id,
        name="Favorite rollback Food",
        source_type="manual",
        is_recipe=False,
    )
    db_session.add(food)
    db_session.commit()
    service = FoodService(db_session)

    def fail_after_flush(_favorite: FoodFavorite) -> None:
        raise RuntimeError("forced favorite failure")

    service._after_favorite_creation = fail_after_flush
    with pytest.raises(RuntimeError, match="forced favorite failure"):
        service.set_favorite(user.id, food.id, favorite=True)

    assert not db_session.in_transaction()
    _marker_commit(db_session)
    assert db_session.get(FoodFavorite, (user.id, food.id)) is None


def test_usda_unrelated_integrity_failure_rolls_back_import_and_session_is_reusable(
    db_session: Session,
) -> None:
    user = ensure_dev_user(db_session)
    duplicate_email = user.email
    service = UsdaService(db_session, FakeUsdaClient(usda_banana_payload()))

    def fail_with_unrelated_integrity(_food: FoodItem) -> None:
        db_session.add(User(id=uuid4(), email=duplicate_email))
        db_session.flush()
        raise AssertionError("unreachable")

    service._after_import_creation = fail_with_unrelated_integrity
    with pytest.raises(IntegrityError):
        service.import_food(user.id, 1105314)

    assert not db_session.in_transaction()
    _marker_commit(db_session)
    assert (
        db_session.scalar(
            select(func.count(FoodItem.id)).where(
                FoodItem.user_id == user.id,
                FoodItem.source_type == "usda",
                FoodItem.source_id == "1105314",
            )
        )
        == 0
    )
