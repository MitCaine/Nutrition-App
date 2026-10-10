from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal
from importlib import import_module
import json
import os
from pathlib import Path
import time
from threading import Event, Thread, get_ident
from uuid import UUID, uuid4

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import event, func, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session as OrmSession

from app import models  # noqa: F401
from app.models.food import FoodFavorite, FoodItem, FoodNutrient, ServingDefinition
from app.models.create_idempotency import CreateOperationIdempotency
from app.models.food import OcrNutritionConfirmationTrace
from app.models.log import DailyLog, DailyLogDayCompletion, DailyLogNutrientSnapshot
from app.models.recipe import Recipe, RecipeIngredient
from app.models.recipe_publication import RecipePublicationRevision
from app.models.user import User, UserProfile
from app.models.target import NutritionTarget
from app.dependencies.database import get_db
from app.dependencies.user import get_current_user
from app.main import app
from app.publication.recipe_revision import (
    PublishedAmountContent,
    PublishedNutrientContent,
    RecipePublicationContent,
    apply_revision_to_projection,
    build_revision,
)
from app.ocr.confirmation_schemas import OcrNutritionConfirmationRequest
from app.ocr.confirmation_service import OcrConfirmationService
from app.schemas.log import (
    DailyLogCompleteRequest,
    DailyLogCreateRequest,
    DailyLogDeleteRequest,
    DailyLogResponse,
    DailyLogUpdateRequest,
)
from app.schemas.food import (
    FoodCreateRequest,
    FoodNutrientInput,
    FoodUpdateRequest,
    ServingDefinitionInput,
)
from app.schemas.recipe import RecipeCreateRequest, RecipeUpdateRequest
from app.schemas.target import TargetConfigurationUpdate
from app.api.v1.routers.logs import daily_summary as route_daily_summary
from app.services.calendar_service import CalendarDomainError, CalendarService
from app.services.log_day_completion_service import LogDayCompletionService
from app.services.log_service import (
    LogIdempotencyConflictError,
    LogMutationReplay,
    LogService,
    LogSourceAmountChangedError,
    LogSourceChangedError,
    LogSourceUnavailableError,
    StaleLogMutationError,
)
from app.repositories.log_repository import LogRepository
from app.repositories.recipe_publication_repository import RecipePublicationRepository
from app.services.food_service import FoodService
from app.services.recipe_service import (
    RECIPE_DELETE_DEPENDENCY_RESTART_LIMIT,
    RecipeDependenciesUnstableError,
    RecipeGraphCycleError,
    RecipeService,
)
from app.services.target_service import TargetService
from app.services.create_idempotency import (
    CreateIdempotencyCoordinator,
    CreateOperationIdempotencyConflictError,
    CreateOperationResultUnavailableError,
)
from tests.postgres_test_support import isolated_postgres_session_factory
from tests.time_zone_test_support import establish_test_time_zone


pytestmark = [
    pytest.mark.postgres_concurrency,
    pytest.mark.filterwarnings(
        "error:DELETE statement on table "
        "'daily_log_nutrient_snapshots'.*:sqlalchemy.exc.SAWarning"
    ),
]
POSTGRES_URL = os.getenv(
    "NUTRITION_TEST_POSTGRES_URL",
    "postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app",
)
idempotency_migration = import_module("app.migrations.versions.0009_log_creation_idempotency")
integrity_migration = import_module("app.migrations.versions.0013_food_recipe_dependency_integrity")


def _idempotent_food_payload(request_id, name="Concurrent Idempotent Create"):
    return FoodCreateRequest(
        client_request_id=request_id,
        name=name,
        serving_definitions=[
            {
                "label": "1 portion",
                "quantity": "1",
                "unit": "portion",
                "gram_weight": "100",
                "is_default": True,
            }
        ],
        nutrients=[],
    )


@pytest.fixture()
def postgres_sessions():
    with isolated_postgres_session_factory(
        database_url=POSTGRES_URL,
        schema_prefix="test_phase3n",
    ) as factory:
        yield factory


def _gh271_daily_log_target(factory, label: str) -> tuple:
    with factory() as db:
        user_id = uuid4()
        db.add(User(id=user_id, email=f"gh271-{user_id}@example.test"))
        db.flush()
        establish_test_time_zone(db, user_id, "UTC")
        food = FoodService(db).create_manual_food(
            user_id,
            FoodCreateRequest(
                name=label,
                serving_definitions=[
                    ServingDefinitionInput(
                        label="1 serving",
                        quantity=Decimal("1"),
                        unit="serving",
                        gram_weight=Decimal("100"),
                        is_default=True,
                    )
                ],
                nutrients=[
                    FoodNutrientInput(
                        nutrient_id="protein",
                        amount=Decimal("10"),
                        unit="g",
                        basis="per_serving",
                        data_status="known",
                    )
                ],
            ),
        )
        serving_id = food.serving_definitions[0].id
        return user_id, food.id, serving_id


def _create_result_snapshot(result) -> dict:
    if isinstance(result, DailyLog):
        return DailyLogResponse.model_validate(result).model_dump(mode="json")
    return result.snapshot


def _recipe_create_target(factory) -> tuple:
    """Create a published Recipe target and return its reviewed authority."""

    with factory() as db:
        user = User(id=uuid4(), email=f"phase3n-{uuid4()}@example.test")
        recipe = Recipe(
            id=uuid4(),
            user_id=user.id,
            name="Concurrent Recipe",
            serving_count_yield=Decimal("1"),
            final_cooked_weight_grams=Decimal("100"),
        )
        db.add(user)
        db.flush()
        db.add(recipe)
        db.flush()
        revision = build_revision(
            recipe_id=recipe.id,
            user_id=user.id,
            revision_number=1,
            creation_origin="normal_publication",
            provenance_confidence="complete",
            content=RecipePublicationContent(
                published_name=recipe.name,
                published_notes=None,
                amount_definitions=(
                    PublishedAmountContent(
                        display_order=0,
                        display_label="1 serving",
                        semantic_mode="serving",
                        display_quantity=Decimal("1"),
                        display_unit="serving",
                        gram_equivalent=Decimal("100"),
                        is_default=True,
                    ),
                    PublishedAmountContent(
                        display_order=1,
                        display_label="g",
                        semantic_mode="g",
                        display_quantity=None,
                        display_unit="g",
                        gram_equivalent=None,
                        is_default=False,
                    ),
                ),
                nutrients=(
                    PublishedNutrientContent(
                        nutrient_id="calories",
                        amount=Decimal("100"),
                        unit="kcal",
                        basis="per_serving",
                        data_status="known",
                    ),
                    PublishedNutrientContent(
                        nutrient_id="calories",
                        amount=Decimal("100"),
                        unit="kcal",
                        basis="per_100g",
                        data_status="known",
                    ),
                ),
            ),
        )
        db.add(revision)
        db.flush()
        projection = FoodItem(id=uuid4(), user_id=user.id, name=recipe.name)
        apply_revision_to_projection(
            projection,
            revision,
            recipe_id=recipe.id,
            user_id=user.id,
            updated_at=recipe.created_at,
        )
        projection.recipe_publication_revision_id = revision.id
        db.add(projection)
        db.flush()
        recipe.active_publication_revision_id = revision.id
        recipe.published_food_item_id = projection.id
        establish_test_time_zone(db, user.id)
        db.commit()
        serving_id = next(row.id for row in projection.serving_definitions if row.is_default)
        return (
            user.id,
            recipe.id,
            projection.id,
            revision.id,
            serving_id,
            projection.updated_at,
        )


def _revision_log(factory) -> tuple:
    user_id, _recipe_id, projection_id, _revision_id, serving_id, _updated_at = (
        _recipe_create_target(factory)
    )
    with factory() as db:
        log = LogService(db).create_log(
            user_id,
            DailyLogCreateRequest(
                food_item_id=projection_id,
                logged_date=date(2026, 7, 13),
                amount_quantity=Decimal("1"),
                amount_unit="serving",
                serving_definition_id=serving_id,
            ),
        )
        return user_id, log.id


def test_postgres_recipe_edit_after_republication_updates_current_provenance(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    user_id, recipe_id, food_id, first_revision_id, serving_id, _ = _recipe_create_target(factory)
    with factory() as db:
        created = LogService(db).create_log(
            user_id,
            DailyLogCreateRequest(
                food_item_id=food_id,
                logged_date=date(2026, 7, 13),
                amount_quantity=Decimal("1"),
                amount_unit="serving",
                serving_definition_id=serving_id,
            ),
        )
        old_snapshot_ids = {snapshot.id for snapshot in created.snapshots}

    with factory() as db:
        recipes = RecipeService(db)
        recipes.update_recipe(
            user_id,
            recipe_id,
            RecipeUpdateRequest(serving_count_yield=Decimal("2")),
        )
        recipes.publish(user_id, recipe_id, uuid4())

    with factory() as db:
        recipe = db.get(Recipe, recipe_id)
        assert recipe is not None
        projection = db.get(FoodItem, food_id)
        assert projection is not None
        current_revision = RecipePublicationRepository(db).get_required(
            recipe.active_publication_revision_id,
            user_id,
        )
        current_amount = next(
            amount for amount in current_revision.amount_definitions if amount.is_default
        )
        LogService(db).update_log(
            user_id,
            created.id,
            DailyLogUpdateRequest(
                amount_quantity=Decimal("2"),
                amount_unit="serving",
                serving_definition_id=current_amount.id,
                source_food_updated_at=projection.updated_at,
                source_recipe_publication_revision_id=current_revision.id,
            ),
        )
        db.expire_all()
        stored = db.get(DailyLog, created.id)
        assert stored is not None
        assert stored.recipe_publication_revision_id == current_revision.id
        assert stored.recipe_publication_revision_id != first_revision_id
        assert stored.recipe_publication_amount_definition_id == current_amount.id
        assert {snapshot.id for snapshot in stored.snapshots}.isdisjoint(old_snapshot_ids)


def test_postgres_unavailable_recipe_metadata_edit_preserves_history(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    user_id, log_id = _revision_log(factory)
    with factory() as db:
        log = db.get(DailyLog, log_id)
        assert log is not None
        revision_id = log.recipe_publication_revision_id
        amount_id = log.recipe_publication_amount_definition_id
        snapshots = tuple(
            (snapshot.id, snapshot.amount, snapshot.consumed_amount_quantity)
            for snapshot in log.snapshots
        )
        assert log.food_item is not None
        log.food_item.deleted_at = log.updated_at
        db.commit()

    with factory() as db:
        updated = LogService(db).update_log(
            user_id,
            log_id,
            DailyLogUpdateRequest(notes="metadata only", logged_date=date(2026, 7, 12)),
        )
        assert updated.notes == "metadata only"
        assert updated.logged_date == date(2026, 7, 12)
        assert updated.recipe_publication_revision_id == revision_id
        assert updated.recipe_publication_amount_definition_id == amount_id
        assert tuple(
            (snapshot.id, snapshot.amount, snapshot.consumed_amount_quantity)
            for snapshot in updated.snapshots
        ) == snapshots
        with pytest.raises(LogSourceUnavailableError):
            LogService(db).update_log(
                user_id,
                log_id,
                DailyLogUpdateRequest(amount_quantity=Decimal("2")),
            )


def _manual_log(factory) -> tuple:
    with factory() as db:
        user = User(id=uuid4(), email=f"manual-phase3n-{uuid4()}@example.test")
        db.add(user)
        db.flush()
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
            name="Concurrent Manual Food",
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
        db.add(food)
        establish_test_time_zone(db, user.id)
        db.commit()
        log = LogService(db).create_log(
            user.id,
            DailyLogCreateRequest(
                food_item_id=food.id,
                logged_date=date(2026, 7, 13),
                amount_quantity=Decimal("1"),
                amount_unit="serving",
                serving_definition_id=serving.id,
            ),
        )
        return user.id, log.id


def _manual_create_target(factory) -> tuple:
    with factory() as db:
        user = User(id=uuid4(), email=f"manual-create-{uuid4()}@example.test")
        db.add(user)
        db.flush()
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
            name="Idempotent Concurrent Food",
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
        db.add(food)
        establish_test_time_zone(db, user.id)
        db.commit()
        return user.id, food.id, serving.id


def test_snapshot_replacement_routine_rejects_wrong_owner_and_is_targeted(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    first_user_id, first_log_id = _manual_log(factory)
    second_user_id, second_log_id = _manual_log(factory)

    with factory() as db:
        before_second = tuple(
            db.execute(
                select(
                    DailyLogNutrientSnapshot.id,
                    DailyLogNutrientSnapshot.amount,
                    DailyLogNutrientSnapshot.consumed_amount_quantity,
                    DailyLogNutrientSnapshot.calculation_metadata,
                ).where(DailyLogNutrientSnapshot.daily_log_id == second_log_id)
            ).all()
        )
        with pytest.raises(DBAPIError) as caught:
            LogRepository(db).delete_snapshots(first_log_id, second_user_id)
        assert getattr(caught.value.orig, "sqlstate", None) == "P0027"
        db.rollback()

        LogService(db).update_log(
            first_user_id,
            first_log_id,
            DailyLogUpdateRequest(amount_quantity=Decimal("2")),
        )

    with factory() as db:
        first_amounts = tuple(
            db.scalars(
                select(DailyLogNutrientSnapshot.amount).where(
                    DailyLogNutrientSnapshot.daily_log_id == first_log_id
                )
            ).all()
        )
        after_second = tuple(
            db.execute(
                select(
                    DailyLogNutrientSnapshot.id,
                    DailyLogNutrientSnapshot.amount,
                    DailyLogNutrientSnapshot.consumed_amount_quantity,
                    DailyLogNutrientSnapshot.calculation_metadata,
                ).where(DailyLogNutrientSnapshot.daily_log_id == second_log_id)
            ).all()
        )

    assert first_amounts == (Decimal("200"),)
    assert after_second == before_second


def _target_payload(
    *,
    protein: str | None,
    activity: str = "sedentary",
) -> TargetConfigurationUpdate:
    return TargetConfigurationUpdate.model_validate(
        {
            "profile": {
                "birth_date": "1996-01-15",
                "sex_for_equation": "male",
                "height_cm": "175",
                "height_unit": "cm",
                "weight_kg": "70",
                "weight_unit": "kg",
                "activity_level": activity,
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


def _published_recipe_pair(factory) -> tuple:
    with factory() as db:
        user = User(id=uuid4(), email=f"graph-{uuid4()}@example.test")
        db.add(user)
        db.commit()
        service = RecipeService(db)
        recipe_a = service.create_recipe(
            user.id,
            RecipeCreateRequest(name="Recipe A", serving_count_yield=Decimal("1")),
        )
        recipe_b = service.create_recipe(
            user.id,
            RecipeCreateRequest(name="Recipe B", serving_count_yield=Decimal("1")),
        )
        recipe_a, food_a = service.publish(user.id, recipe_a.id)
        recipe_b, food_b = service.publish(user.id, recipe_b.id)
        serving_a = next(row.id for row in food_a.serving_definitions if row.is_default)
        serving_b = next(row.id for row in food_b.serving_definitions if row.is_default)
        return (
            user.id,
            recipe_a.id,
            food_a.id,
            serving_a,
            recipe_b.id,
            food_b.id,
            serving_b,
        )


def _recipe_ingredient_update(food_id, serving_id) -> RecipeUpdateRequest:
    return RecipeUpdateRequest.model_validate(
        {
            "ingredients": [
                {
                    "food_item_id": str(food_id),
                    "position": 0,
                    "amount_quantity": "1",
                    "amount_unit": "serving",
                    "serving_definition_id": str(serving_id),
                }
            ]
        }
    )


def _run_recipe_update(
    factory,
    user_id,
    recipe_id,
    payload,
    result: list[object],
    *,
    after_locks=None,
) -> None:
    with factory() as db:
        service = RecipeService(db)
        if after_locks is not None:
            service._after_recipe_graph_initial_locks = after_locks
        try:
            service.update_recipe(user_id, recipe_id, payload)
            result.append("committed")
        except Exception as exc:
            result.append(exc)


def test_concurrent_reciprocal_recipe_updates_cannot_commit_a_cycle(postgres_sessions) -> None:
    factory = postgres_sessions
    user_id, recipe_a, food_a, serving_a, recipe_b, food_b, serving_b = _published_recipe_pair(
        factory
    )
    a_locked, b_locked, release = Event(), Event(), Event()
    a_result: list[object] = []
    b_result: list[object] = []

    def update(
        recipe_id,
        ingredient_food_id,
        serving_id,
        locked: Event,
        result: list[object],
    ) -> None:
        with factory() as db:
            service = RecipeService(db)

            def after_locks(_recipe):
                locked.set()
                assert release.wait(5)

            service._after_recipe_graph_initial_locks = after_locks
            try:
                service.update_recipe(
                    user_id,
                    recipe_id,
                    RecipeUpdateRequest.model_validate(
                        {
                            "ingredients": [
                                {
                                    "food_item_id": str(ingredient_food_id),
                                    "position": 0,
                                    "amount_quantity": "1",
                                    "amount_unit": "serving",
                                    "serving_definition_id": str(serving_id),
                                }
                            ]
                        }
                    ),
                )
                result.append("committed")
            except Exception as exc:
                result.append(exc)

    first = Thread(target=update, args=(recipe_a, food_b, serving_b, a_locked, a_result))
    second = Thread(target=update, args=(recipe_b, food_a, serving_a, b_locked, b_result))
    first.start()
    assert a_locked.wait(5)
    second.start()
    Event().wait(0.2)
    assert not b_locked.is_set()
    assert not b_result
    release.set()
    first.join(5)
    second.join(5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert a_result == ["committed"]
    assert len(b_result) == 1
    assert isinstance(b_result[0], RecipeGraphCycleError)
    with factory() as db:
        edges = {
            recipe.id: {ingredient.food_item_id for ingredient in recipe.ingredients}
            for recipe in db.scalars(
                select(Recipe).where(Recipe.id.in_([recipe_a, recipe_b]))
            ).unique()
        }
        assert edges[recipe_a] == {food_b}
        assert edges[recipe_b] == set()


def test_concurrent_indirect_recipe_cycle_cannot_commit(postgres_sessions) -> None:
    factory = postgres_sessions
    user_id, recipe_a, food_a, serving_a, recipe_b, food_b, serving_b = _published_recipe_pair(
        factory
    )
    with factory() as db:
        service = RecipeService(db)
        recipe_c = service.create_recipe(
            user_id,
            RecipeCreateRequest(name="Recipe C", serving_count_yield=Decimal("1")),
        )
        recipe_c, food_c = service.publish(user_id, recipe_c.id)
        serving_c = next(row.id for row in food_c.serving_definitions if row.is_default)
        recipe_c_id = recipe_c.id
        food_c_id = food_c.id
        service.update_recipe(
            user_id,
            recipe_a,
            _recipe_ingredient_update(food_b, serving_b),
        )

    first_locked, second_locked, release = Event(), Event(), Event()
    first_result: list[object] = []
    second_result: list[object] = []

    def hold_first(_recipe):
        first_locked.set()
        assert release.wait(5)

    def mark_second(_recipe):
        second_locked.set()

    first = Thread(
        target=_run_recipe_update,
        args=(
            factory,
            user_id,
            recipe_b,
            _recipe_ingredient_update(food_c_id, serving_c),
            first_result,
        ),
        kwargs={"after_locks": hold_first},
    )
    second = Thread(
        target=_run_recipe_update,
        args=(
            factory,
            user_id,
            recipe_c_id,
            _recipe_ingredient_update(food_a, serving_a),
            second_result,
        ),
        kwargs={"after_locks": mark_second},
    )
    first.start()
    assert first_locked.wait(5)
    second.start()
    Event().wait(0.2)
    assert not second_locked.is_set()
    release.set()
    first.join(5)
    second.join(5)

    assert first_result == ["committed"]
    assert len(second_result) == 1
    assert isinstance(second_result[0], RecipeGraphCycleError)


def test_valid_same_user_graph_mutations_serialize_and_both_commit(postgres_sessions) -> None:
    factory = postgres_sessions
    user_id, recipe_a, _food_a, _serving_a, recipe_b, food_b, serving_b = _published_recipe_pair(
        factory
    )
    first_locked, second_locked, release = Event(), Event(), Event()
    first_result: list[object] = []
    second_result: list[object] = []

    def hold_first(_recipe):
        first_locked.set()
        assert release.wait(5)

    def mark_second(_recipe):
        second_locked.set()

    first = Thread(
        target=_run_recipe_update,
        args=(
            factory,
            user_id,
            recipe_a,
            _recipe_ingredient_update(food_b, serving_b),
            first_result,
        ),
        kwargs={"after_locks": hold_first},
    )
    second = Thread(
        target=_run_recipe_update,
        args=(factory, user_id, recipe_b, RecipeUpdateRequest(ingredients=[]), second_result),
        kwargs={"after_locks": mark_second},
    )
    first.start()
    assert first_locked.wait(5)
    second.start()
    Event().wait(0.2)
    assert not second_locked.is_set()
    release.set()
    first.join(5)
    second.join(5)

    assert first_result == ["committed"]
    assert second_result == ["committed"]


def test_different_user_graph_mutations_do_not_block_each_other(postgres_sessions) -> None:
    factory = postgres_sessions
    first_graph = _published_recipe_pair(factory)
    second_graph = _published_recipe_pair(factory)
    user_a, recipe_a, _food_a, _serving_a, _recipe_b, food_b, serving_b = first_graph
    user_c, recipe_c, _food_c, _serving_c, _recipe_d, food_d, serving_d = second_graph
    first_locked, second_locked, release = Event(), Event(), Event()
    first_result: list[object] = []
    second_result: list[object] = []

    def hold_first(_recipe):
        first_locked.set()
        assert release.wait(5)

    def mark_second(_recipe):
        second_locked.set()

    first = Thread(
        target=_run_recipe_update,
        args=(
            factory,
            user_a,
            recipe_a,
            _recipe_ingredient_update(food_b, serving_b),
            first_result,
        ),
        kwargs={"after_locks": hold_first},
    )
    second = Thread(
        target=_run_recipe_update,
        args=(
            factory,
            user_c,
            recipe_c,
            _recipe_ingredient_update(food_d, serving_d),
            second_result,
        ),
        kwargs={"after_locks": mark_second},
    )
    first.start()
    assert first_locked.wait(5)
    second.start()
    assert second_locked.wait(5)
    second.join(5)
    assert second_result == ["committed"]
    release.set()
    first.join(5)
    assert first_result == ["committed"]


def test_waiting_graph_mutation_proceeds_after_first_transaction_rolls_back(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    user_id, recipe_a, food_a, serving_a, recipe_b, food_b, serving_b = _published_recipe_pair(
        factory
    )
    first_locked, second_locked, release = Event(), Event(), Event()
    first_result: list[object] = []
    second_result: list[object] = []

    def fail_first(_recipe):
        first_locked.set()
        assert release.wait(5)
        raise RuntimeError("forced graph mutation rollback")

    def mark_second(_recipe):
        second_locked.set()

    first = Thread(
        target=_run_recipe_update,
        args=(
            factory,
            user_id,
            recipe_a,
            _recipe_ingredient_update(food_b, serving_b),
            first_result,
        ),
        kwargs={"after_locks": fail_first},
    )
    second = Thread(
        target=_run_recipe_update,
        args=(
            factory,
            user_id,
            recipe_b,
            _recipe_ingredient_update(food_a, serving_a),
            second_result,
        ),
        kwargs={"after_locks": mark_second},
    )
    first.start()
    assert first_locked.wait(5)
    second.start()
    Event().wait(0.2)
    assert not second_locked.is_set()
    release.set()
    first.join(5)
    second.join(5)

    assert len(first_result) == 1
    assert isinstance(first_result[0], RuntimeError)
    assert second_result == ["committed"]
    with factory() as db:
        stored_a = db.get(Recipe, recipe_a)
        stored_b = db.get(Recipe, recipe_b)
        assert stored_a.ingredients == []
        assert {row.food_item_id for row in stored_b.ingredients} == {food_a}


def test_mutable_food_log_snapshot_and_food_update_are_serialized(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    user_id, food_id, serving_id = _manual_create_target(factory)
    with factory() as db:
        establish_test_time_zone(db, user_id)
        reviewed_updated_at = db.get(FoodItem, food_id).updated_at
        db.commit()
    locked, update_waiting, release = Event(), Event(), Event()
    log_result: list[object] = []
    update_result: list[object] = []
    request_id = uuid4()

    def create_log() -> None:
        with factory() as db:
            service = LogService(db)

            def after_lock(_food):
                locked.set()
                assert release.wait(5)

            service._after_mutable_food_lock = after_lock
            try:
                log_result.append(
                    service.create_log(
                        user_id,
                        DailyLogCreateRequest(
                            food_item_id=food_id,
                            client_request_id=request_id,
                            logged_date=date(2026, 7, 14),
                            amount_quantity=Decimal("1"),
                            amount_unit="serving",
                            serving_definition_id=serving_id,
                            source_food_updated_at=reviewed_updated_at,
                        ),
                    ).id
                )
            except Exception as exc:
                log_result.append(exc)

    def update_food() -> None:
        with factory() as db:
            service = FoodService(db)
            original_get_for_update = service.foods.get_for_update

            def signal_food_lock(*args, **kwargs):
                update_waiting.set()
                return original_get_for_update(*args, **kwargs)

            service.foods.get_for_update = signal_food_lock
            try:
                service.update_food(
                    user_id,
                    food_id,
                    FoodUpdateRequest.model_validate(
                        {
                            "nutrients": [
                                {
                                    "nutrient_id": "calories",
                                    "amount": "200",
                                    "unit": "kcal",
                                    "basis": "per_serving",
                                    "data_status": "known",
                                }
                            ]
                        }
                    ),
                )
                update_result.append("committed")
            except Exception as exc:
                update_result.append(exc)

    logger = Thread(target=create_log)
    logger.start()
    assert locked.wait(5)
    updater = Thread(target=update_food)
    updater.start()
    assert update_waiting.wait(5)
    assert not update_result
    release.set()
    logger.join(5)
    updater.join(5)

    assert len(log_result) == len(update_result) == 1
    assert update_result == ["committed"]
    with factory() as db:
        log = db.get(DailyLog, log_result[0])
        assert log.snapshots[0].amount == Decimal("100.000000")
        assert log.client_request_id == request_id
        food = db.get(FoodItem, food_id)
        assert food.nutrients[0].amount == Decimal("200.000000")
        replay = LogService(db).create_log(
            user_id,
            DailyLogCreateRequest(
                food_item_id=food_id,
                client_request_id=request_id,
                logged_date=date(2026, 7, 14),
                amount_quantity=Decimal("1"),
                amount_unit="serving",
                serving_definition_id=serving_id,
                source_food_updated_at=reviewed_updated_at,
            ),
        )
        assert replay.id == log.id


def test_mutable_food_update_wins_and_reviewed_log_returns_stale_source(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    user_id, food_id, serving_id = _manual_create_target(factory)
    with factory() as db:
        establish_test_time_zone(db, user_id)
        reviewed_updated_at = db.get(FoodItem, food_id).updated_at
        db.commit()

    food_locked, create_waiting, release = Event(), Event(), Event()
    update_result: list[object] = []
    create_result: list[object] = []
    request_id = uuid4()

    def update_food() -> None:
        with factory() as db:
            service = FoodService(db)

            def hold_after_lock(_food, _parents):
                food_locked.set()
                assert release.wait(5)

            service._after_food_dependency_lock = hold_after_lock
            try:
                service.update_food(
                    user_id,
                    food_id,
                    FoodUpdateRequest.model_validate(
                        {
                            "nutrients": [
                                {
                                    "nutrient_id": "calories",
                                    "amount": "250",
                                    "unit": "kcal",
                                    "basis": "per_serving",
                                    "data_status": "known",
                                }
                            ]
                        }
                    ),
                )
                update_result.append("committed")
            except Exception as exc:
                update_result.append(exc)

    def create_log() -> None:
        with factory() as db:
            service = LogService(db)
            original_get_for_update = service.foods.get_for_update

            def signal_create_lock(*args, **kwargs):
                create_waiting.set()
                return original_get_for_update(*args, **kwargs)

            service.foods.get_for_update = signal_create_lock
            try:
                service.create_log(
                    user_id,
                    DailyLogCreateRequest(
                        food_item_id=food_id,
                        client_request_id=request_id,
                        logged_date=date(2026, 7, 14),
                        amount_quantity=Decimal("1"),
                        amount_unit="serving",
                        serving_definition_id=serving_id,
                        source_food_updated_at=reviewed_updated_at,
                    ),
                )
                create_result.append("committed")
            except Exception as exc:
                create_result.append(exc)

    updater = Thread(target=update_food)
    updater.start()
    assert food_locked.wait(5)
    creator = Thread(target=create_log)
    creator.start()
    assert create_waiting.wait(5)
    assert not create_result
    release.set()
    updater.join(10)
    creator.join(10)

    assert update_result == ["committed"]
    assert len(create_result) == 1
    assert isinstance(create_result[0], LogSourceChangedError)
    with factory() as db:
        assert db.scalar(
            select(func.count()).select_from(DailyLog).where(
                DailyLog.client_request_id == request_id,
            )
        ) == 0
        assert db.scalar(
            select(func.count()).select_from(DailyLogNutrientSnapshot).where(
                DailyLogNutrientSnapshot.source_food_item_id == food_id,
            )
        ) == 0


def test_mutable_food_serving_replacement_wins_and_reviewed_log_returns_stale_amount(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    user_id, food_id, serving_id = _manual_create_target(factory)
    with factory() as db:
        establish_test_time_zone(db, user_id)
        reviewed_updated_at = db.get(FoodItem, food_id).updated_at
        db.commit()

    food_locked, create_waiting, release = Event(), Event(), Event()
    update_result: list[object] = []
    create_result: list[object] = []
    request_id = uuid4()

    def replace_serving() -> None:
        with factory() as db:
            service = FoodService(db)

            def hold_after_lock(_food, _parents):
                food_locked.set()
                assert release.wait(5)

            service._after_food_dependency_lock = hold_after_lock
            try:
                service.update_food(
                    user_id,
                    food_id,
                    FoodUpdateRequest.model_validate(
                        {
                            "serving_definitions": [
                                {
                                    "label": "2 portions",
                                    "quantity": "2",
                                    "unit": "portion",
                                    "gram_weight": "200",
                                    "is_default": True,
                                }
                            ]
                        }
                    ),
                )
                update_result.append("committed")
            except Exception as exc:
                update_result.append(exc)

    def create_log() -> None:
        with factory() as db:
            service = LogService(db)
            original_get_for_update = service.foods.get_for_update

            def signal_create_lock(*args, **kwargs):
                create_waiting.set()
                return original_get_for_update(*args, **kwargs)

            service.foods.get_for_update = signal_create_lock
            try:
                service.create_log(
                    user_id,
                    DailyLogCreateRequest(
                        food_item_id=food_id,
                        client_request_id=request_id,
                        logged_date=date(2026, 7, 14),
                        amount_quantity=Decimal("1"),
                        amount_unit="serving",
                        serving_definition_id=serving_id,
                        source_food_updated_at=reviewed_updated_at,
                    ),
                )
                create_result.append("committed")
            except Exception as exc:
                create_result.append(exc)

    updater = Thread(target=replace_serving)
    updater.start()
    assert food_locked.wait(5)
    creator = Thread(target=create_log)
    creator.start()
    assert create_waiting.wait(5)
    assert not create_result
    release.set()
    updater.join(10)
    creator.join(10)

    assert update_result == ["committed"]
    assert len(create_result) == 1
    assert isinstance(create_result[0], LogSourceAmountChangedError)
    with factory() as db:
        assert db.scalar(
            select(func.count()).select_from(DailyLog).where(
                DailyLog.client_request_id == request_id,
            )
        ) == 0
        assert db.scalar(
            select(func.count()).select_from(DailyLogNutrientSnapshot).where(
                DailyLogNutrientSnapshot.source_food_item_id == food_id,
            )
        ) == 0


def test_recipe_log_stabilizes_reviewed_revision_before_republication(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    user_id, recipe_id, food_id, revision_id, serving_id, reviewed_updated_at = (
        _recipe_create_target(factory)
    )
    create_locked, republish_waiting, release = Event(), Event(), Event()
    create_result: list[object] = []
    republish_result: list[object] = []
    create_request_id = uuid4()

    def create_log() -> None:
        with factory() as db:
            service = LogService(db)

            def hold_after_revision(_revision):
                create_locked.set()
                assert release.wait(5)

            service._after_recipe_revision_lookup = hold_after_revision
            try:
                create_result.append(
                    service.create_log(
                        user_id,
                        DailyLogCreateRequest(
                            food_item_id=food_id,
                            client_request_id=create_request_id,
                            logged_date=date(2026, 7, 14),
                            amount_quantity=Decimal("1"),
                            amount_unit="serving",
                            serving_definition_id=serving_id,
                            source_food_updated_at=reviewed_updated_at,
                            source_recipe_publication_revision_id=revision_id,
                        ),
                    ).id
                )
            except Exception as exc:
                create_result.append(exc)

    def republish() -> None:
        with factory() as db:
            service = RecipeService(db)
            original_get_for_update = service.foods.get_for_update

            def signal_publication_lock(*args, **kwargs):
                republish_waiting.set()
                return original_get_for_update(*args, **kwargs)

            service.foods.get_for_update = signal_publication_lock
            try:
                service.publish(user_id, recipe_id, uuid4())
                republish_result.append("committed")
            except Exception as exc:
                republish_result.append(exc)

    creator = Thread(target=create_log)
    creator.start()
    assert create_locked.wait(5)
    publisher = Thread(target=republish)
    publisher.start()
    assert republish_waiting.wait(5)
    assert not republish_result
    release.set()
    creator.join(10)
    publisher.join(10)

    assert len(create_result) == 1
    assert republish_result == ["committed"]
    with factory() as db:
        log = db.get(DailyLog, create_result[0])
        assert log is not None
        assert log.recipe_publication_revision_id == revision_id
        assert log.snapshots
        assert all(snapshot.source_food_item_id == food_id for snapshot in log.snapshots)
        recipe = db.get(Recipe, recipe_id)
        assert recipe is not None
        assert recipe.active_publication_revision_id != revision_id
        assert db.get(RecipePublicationRevision, revision_id) is not None
        assert db.scalar(
            select(func.count()).select_from(DailyLog).where(
                DailyLog.client_request_id == create_request_id,
            )
        ) == 1
        replay = LogService(db).create_log(
            user_id,
            DailyLogCreateRequest(
                food_item_id=food_id,
                client_request_id=create_request_id,
                logged_date=date(2026, 7, 14),
                amount_quantity=Decimal("1"),
                amount_unit="serving",
                serving_definition_id=serving_id,
                source_food_updated_at=reviewed_updated_at,
                source_recipe_publication_revision_id=revision_id,
            ),
        )
        assert replay.id == log.id


def test_recipe_republication_wins_and_reviewed_log_returns_stale_source(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    user_id, recipe_id, food_id, revision_id, serving_id, reviewed_updated_at = (
        _recipe_create_target(factory)
    )
    republish_locked, create_waiting, release = Event(), Event(), Event()
    republish_result: list[object] = []
    create_result: list[object] = []
    create_request_id = uuid4()

    def republish() -> None:
        with factory() as db:
            service = RecipeService(db)

            def hold_after_active_revision(_recipe):
                republish_locked.set()
                assert release.wait(5)

            service._after_active_revision_assignment = hold_after_active_revision
            try:
                service.publish(user_id, recipe_id, uuid4())
                republish_result.append("committed")
            except Exception as exc:
                republish_result.append(exc)

    def create_log() -> None:
        with factory() as db:
            service = LogService(db)
            original_get_for_update = service.foods.get_for_update

            def signal_create_lock(*args, **kwargs):
                create_waiting.set()
                return original_get_for_update(*args, **kwargs)

            service.foods.get_for_update = signal_create_lock
            try:
                service.create_log(
                    user_id,
                    DailyLogCreateRequest(
                        food_item_id=food_id,
                        client_request_id=create_request_id,
                        logged_date=date(2026, 7, 14),
                        amount_quantity=Decimal("1"),
                        amount_unit="serving",
                        serving_definition_id=serving_id,
                        source_food_updated_at=reviewed_updated_at,
                        source_recipe_publication_revision_id=revision_id,
                    ),
                )
                create_result.append("committed")
            except Exception as exc:
                create_result.append(exc)

    publisher = Thread(target=republish)
    publisher.start()
    assert republish_locked.wait(5)
    creator = Thread(target=create_log)
    creator.start()
    assert create_waiting.wait(5)
    assert not create_result
    release.set()
    publisher.join(10)
    creator.join(10)

    assert republish_result == ["committed"]
    assert len(create_result) == 1
    assert isinstance(create_result[0], LogSourceChangedError)
    with factory() as db:
        recipe = db.get(Recipe, recipe_id)
        assert recipe is not None
        assert recipe.active_publication_revision_id != revision_id
        assert db.scalar(
            select(func.count()).select_from(DailyLog).where(
                DailyLog.client_request_id == create_request_id,
            )
        ) == 0
        assert db.scalar(
            select(func.count()).select_from(DailyLogNutrientSnapshot).where(
                DailyLogNutrientSnapshot.source_food_item_id == food_id,
            )
        ) == 0


def test_food_delete_prevents_concurrent_recipe_dependency_addition(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    user_id, food_id, serving_id = _manual_create_target(factory)
    locked, release = Event(), Event()
    delete_result: list[object] = []
    recipe_result: list[object] = []

    def delete_food() -> None:
        with factory() as db:
            service = FoodService(db)

            def after_lock(_food, _parents):
                locked.set()
                assert release.wait(5)

            service._after_food_dependency_lock = after_lock
            try:
                service.soft_delete_food(user_id, food_id)
                delete_result.append("committed")
            except Exception as exc:
                delete_result.append(exc)

    def create_recipe() -> None:
        with factory() as db:
            try:
                RecipeService(db).create_recipe(
                    user_id,
                    RecipeCreateRequest.model_validate(
                        {
                            "name": "Concurrent parent",
                            "ingredients": [
                                {
                                    "food_item_id": str(food_id),
                                    "position": 0,
                                    "amount_quantity": "1",
                                    "amount_unit": "serving",
                                    "serving_definition_id": str(serving_id),
                                }
                            ],
                        }
                    ),
                )
                recipe_result.append("committed")
            except Exception as exc:
                recipe_result.append(exc)

    deleter = Thread(target=delete_food)
    deleter.start()
    assert locked.wait(5)
    author = Thread(target=create_recipe)
    author.start()
    Event().wait(0.2)
    assert not recipe_result
    release.set()
    deleter.join(5)
    author.join(5)

    assert delete_result == ["committed"]
    assert len(recipe_result) == 1
    assert isinstance(recipe_result[0], LookupError)
    with factory() as db:
        assert db.scalar(select(func.count(Recipe.id))) == 0


def test_concurrent_default_serving_creation_leaves_exactly_one_default(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    user_id, food_id, _serving_id = _manual_create_target(factory)
    locked, release = Event(), Event()
    first_result: list[object] = []
    second_result: list[object] = []

    def add_default(label: str, result: list[object], *, hold: bool = False) -> None:
        with factory() as db:
            service = FoodService(db)
            if hold:

                def after_lock(_food, _parents):
                    locked.set()
                    assert release.wait(5)

                service._after_food_dependency_lock = after_lock
            try:
                service.add_serving_definition(
                    user_id,
                    food_id,
                    ServingDefinitionInput(
                        label=label,
                        quantity=Decimal("1"),
                        unit="portion",
                        gram_weight=Decimal("100"),
                        is_default=True,
                    ),
                )
                result.append("committed")
            except Exception as exc:
                result.append(exc)

    first = Thread(target=add_default, args=("First", first_result), kwargs={"hold": True})
    first.start()
    assert locked.wait(5)
    second = Thread(target=add_default, args=("Second", second_result))
    second.start()
    Event().wait(0.2)
    assert not second_result
    release.set()
    first.join(5)
    second.join(5)

    assert first_result == ["committed"]
    assert second_result == ["committed"]
    with factory() as db:
        defaults = db.scalar(
            select(func.count(ServingDefinition.id)).where(
                ServingDefinition.food_item_id == food_id,
                ServingDefinition.is_default.is_(True),
            )
        )
        assert defaults == 1


def test_food_update_and_recipe_ingredient_addition_follow_food_then_recipe_order(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    user_id, food_id, serving_id = _manual_create_target(factory)
    locked, release = Event(), Event()
    update_result: list[object] = []
    recipe_result: list[object] = []

    def update_food() -> None:
        with factory() as db:
            service = FoodService(db)

            def after_lock(_food, _parents):
                locked.set()
                assert release.wait(5)

            service._after_food_dependency_lock = after_lock
            try:
                service.update_food(user_id, food_id, FoodUpdateRequest(name="Updated first"))
                update_result.append("committed")
            except Exception as exc:
                update_result.append(exc)

    def create_recipe() -> None:
        with factory() as db:
            try:
                RecipeService(db).create_recipe(
                    user_id,
                    RecipeCreateRequest.model_validate(
                        {
                            "name": "Concurrent parent",
                            "ingredients": [
                                {
                                    "food_item_id": str(food_id),
                                    "position": 0,
                                    "amount_quantity": "1",
                                    "amount_unit": "serving",
                                    "serving_definition_id": str(serving_id),
                                }
                            ],
                        }
                    ),
                )
                recipe_result.append("committed")
            except Exception as exc:
                recipe_result.append(exc)

    food_writer = Thread(target=update_food)
    food_writer.start()
    assert locked.wait(5)
    recipe_writer = Thread(target=create_recipe)
    recipe_writer.start()
    Event().wait(0.2)
    assert not recipe_result
    release.set()
    food_writer.join(5)
    recipe_writer.join(5)

    assert update_result == ["committed"]
    assert recipe_result == ["committed"]


def test_serving_replacement_and_recipe_ingredient_update_do_not_deadlock(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    user_id, food_id, serving_id = _manual_create_target(factory)
    with factory() as db:
        recipe = RecipeService(db).create_recipe(
            user_id,
            RecipeCreateRequest.model_validate(
                {
                    "name": "Existing parent",
                    "ingredients": [
                        {
                            "food_item_id": str(food_id),
                            "position": 0,
                            "amount_quantity": "1",
                            "amount_unit": "serving",
                            "serving_definition_id": str(serving_id),
                        }
                    ],
                }
            ),
        )
        recipe_id = recipe.id

    locked, release = Event(), Event()
    food_result: list[object] = []
    recipe_result: list[object] = []

    def replace_servings() -> None:
        with factory() as db:
            service = FoodService(db)

            def after_lock(_food, _parents):
                locked.set()
                assert release.wait(5)

            service._after_food_dependency_lock = after_lock
            try:
                service.update_food(
                    user_id,
                    food_id,
                    FoodUpdateRequest.model_validate(
                        {
                            "serving_definitions": [
                                {
                                    "label": "Renamed portion",
                                    "quantity": "1",
                                    "unit": "portion",
                                    "gram_weight": "100",
                                    "is_default": True,
                                }
                            ]
                        }
                    ),
                )
                food_result.append("committed")
            except Exception as exc:
                food_result.append(exc)

    def update_recipe() -> None:
        with factory() as db:
            try:
                RecipeService(db).update_recipe(
                    user_id,
                    recipe_id,
                    RecipeUpdateRequest.model_validate(
                        {
                            "ingredients": [
                                {
                                    "food_item_id": str(food_id),
                                    "position": 0,
                                    "amount_quantity": "100",
                                    "amount_unit": "g",
                                }
                            ]
                        }
                    ),
                )
                recipe_result.append("committed")
            except Exception as exc:
                recipe_result.append(exc)

    food_writer = Thread(target=replace_servings)
    food_writer.start()
    assert locked.wait(5)
    recipe_writer = Thread(target=update_recipe)
    recipe_writer.start()
    Event().wait(0.2)
    assert not recipe_result
    release.set()
    food_writer.join(5)
    recipe_writer.join(5)

    assert food_result == ["committed"]
    assert recipe_result == ["committed"]


def test_food_dependency_set_change_restarts_before_mutation(postgres_sessions) -> None:
    factory = postgres_sessions
    user_id, food_id, serving_id = _manual_create_target(factory)
    with factory() as db:
        parent = Recipe(id=uuid4(), user_id=user_id, name="Late parent")
        db.add(parent)
        db.flush()
        db.add(
            RecipeIngredient(
                id=uuid4(),
                user_id=parent.user_id,
                recipe_id=parent.id,
                food_item_id=food_id,
                position=0,
                amount_quantity=Decimal("1"),
                amount_unit="serving",
                serving_definition_id=serving_id,
                resolved_gram_amount=Decimal("100"),
            )
        )
        db.commit()
        parent_id = parent.id

    with factory() as db:
        service = FoodService(db)
        original_dependencies = service._dependent_recipe_ids
        calls = 0

        def dependencies(owner_id, target_food_id):
            nonlocal calls
            calls += 1
            return set() if calls == 1 else original_dependencies(owner_id, target_food_id)

        service._dependent_recipe_ids = dependencies
        service.update_food(user_id, food_id, FoodUpdateRequest(name="Restarted update"))

    assert calls == 4
    assert parent_id


def test_unrelated_food_mutation_does_not_wait_on_another_food_lock(postgres_sessions) -> None:
    factory = postgres_sessions
    first_user, first_food, _first_serving = _manual_create_target(factory)
    second_user, second_food, _second_serving = _manual_create_target(factory)
    locked, release = Event(), Event()
    first_result: list[object] = []
    second_result: list[object] = []

    def hold_first() -> None:
        with factory() as db:
            service = FoodService(db)

            def after_lock(_food, _parents):
                locked.set()
                assert release.wait(5)

            service._after_food_dependency_lock = after_lock
            try:
                service.update_food(first_user, first_food, FoodUpdateRequest(name="First"))
                first_result.append("committed")
            except Exception as exc:
                first_result.append(exc)

    def update_second() -> None:
        with factory() as db:
            try:
                FoodService(db).update_food(
                    second_user, second_food, FoodUpdateRequest(name="Second")
                )
                second_result.append("committed")
            except Exception as exc:
                second_result.append(exc)

    first = Thread(target=hold_first)
    first.start()
    assert locked.wait(5)
    second = Thread(target=update_second)
    second.start()
    second.join(2)
    assert second_result == ["committed"]
    release.set()
    first.join(5)
    assert first_result == ["committed"]


def test_concurrent_create_with_same_request_id_commits_one_log_and_snapshot_set(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    user_id, food_id, serving_id = _manual_create_target(factory)
    request_id = uuid4()
    first_flushed, release = Event(), Event()
    first_result, second_result = [], []

    def create(result, *, hold=False):
        with factory() as db:
            service = LogService(db)
            if hold:

                def after_flush(_log):
                    first_flushed.set()
                    assert release.wait(5)

                service._after_snapshot_creation = after_flush
            try:
                log = service.create_log(
                    user_id,
                    DailyLogCreateRequest(
                        client_request_id=request_id,
                        food_item_id=food_id,
                        logged_date=date(2026, 7, 14),
                        amount_quantity=Decimal("1"),
                        amount_unit="serving",
                        serving_definition_id=serving_id,
                    ),
                )
                result.append(log.id)
            except Exception as exc:
                result.append(exc)

    first = Thread(target=create, args=(first_result,), kwargs={"hold": True})
    first.start()
    assert first_flushed.wait(5)
    second = Thread(target=create, args=(second_result,))
    second.start()
    Event().wait(0.2)
    assert not second_result
    release.set()
    first.join(5)
    second.join(5)

    assert len(first_result) == len(second_result) == 1
    assert first_result[0] == second_result[0]
    with factory() as db:
        logs = list(
            db.scalars(
                select(DailyLog).where(
                    DailyLog.user_id == user_id,
                    DailyLog.client_request_id == request_id,
                )
            )
        )
        assert len(logs) == 1
        assert len(logs[0].snapshots) == 1


def _ocr_confirmation_request(request_id):
    def field(key, value, *, nutrient_id=None, unit=None):
        return {
            "field_key": key,
            "nutrient_id": nutrient_id,
            "suggested_value": value,
            "confirmed_value": value,
            "unit": unit,
            "decision": "accepted",
            "parse_status": "parsed",
            "comparison": None,
            "confidence": "0.95",
            "source_text": key,
            "source_observation_ids": [f"obs-{key}"],
            "warning_codes": [],
            "resolution": None,
        }

    return OcrNutritionConfirmationRequest.model_validate(
        {
            "parser_version": "nutrition_label_v2",
            "image_source_type": "photo_library",
            "client_request_id": request_id,
            "food": {
                "name": "Concurrent Cereal",
                "brand": None,
                "notes": None,
                "serving_definitions": [
                    {
                        "label": "100 g",
                        "quantity": "100",
                        "unit": "g",
                        "gram_weight": "100",
                        "is_default": False,
                    },
                    {
                        "label": "1 cup (30g)",
                        "quantity": "1",
                        "unit": "cup",
                        "gram_weight": "30",
                        "is_default": True,
                    },
                ],
                "nutrients": [
                    {
                        "nutrient_id": "calories",
                        "amount": "120",
                        "unit": "kcal",
                        "basis": "per_serving",
                        "data_status": "known",
                    }
                ],
            },
            "field_decisions": [
                field("food.name", "Concurrent Cereal"),
                {**field("food.brand", None), "decision": "omitted"},
                {**field("food.notes", None), "decision": "omitted"},
                field("serving.display", "1 cup (30g)"),
                field("serving.quantity", "1"),
                field("serving.unit", "cup"),
                field("serving.gram_weight", "30", unit="g"),
                field(
                    "nutrient.calories",
                    "120",
                    nutrient_id="calories",
                    unit="kcal",
                ),
            ],
            "unknown_nutrients": [],
            "parser_warning_codes": [],
        }
    )


def test_concurrent_same_id_confirmation_commits_one_food_and_trace(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    with factory() as db:
        user = User(id=uuid4(), email=f"ocr-concurrency-{uuid4()}@example.test")
        db.add(user)
        db.commit()
        user_id = user.id

    payload = _ocr_confirmation_request(uuid4())
    first_flushed, release = Event(), Event()
    first_result, second_result = [], []

    def confirm(result, *, hold=False):
        with factory() as db:
            service = OcrConfirmationService(db)
            if hold:

                def after_trace(_trace):
                    first_flushed.set()
                    assert release.wait(5)

                service._after_trace_creation = after_trace
            try:
                food, trace = service.confirm(user_id, payload)
                result.append((food.id, trace.id))
            except Exception as exc:
                result.append(exc)

    first = Thread(target=confirm, args=(first_result,), kwargs={"hold": True})
    first.start()
    assert first_flushed.wait(5)
    second = Thread(target=confirm, args=(second_result,))
    second.start()
    Event().wait(0.2)
    assert not second_result
    release.set()
    first.join(5)
    second.join(5)

    assert len(first_result) == len(second_result) == 1
    assert first_result[0] == second_result[0]
    with factory() as db:
        traces = list(
            db.scalars(
                select(OcrNutritionConfirmationTrace).where(
                    OcrNutritionConfirmationTrace.user_id == user_id,
                    OcrNutritionConfirmationTrace.client_request_id == payload.client_request_id,
                )
            )
        )
        assert len(traces) == 1
        assert (
            db.scalar(select(func.count()).select_from(FoodItem).where(FoodItem.user_id == user_id))
            == 1
        )


def test_concurrent_favorite_creation_recovers_only_identity_race(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    with factory() as db:
        user = User(id=uuid4(), email=f"favorite-concurrency-{uuid4()}@example.test")
        other = User(id=uuid4(), email=f"favorite-independent-{uuid4()}@example.test")
        db.add_all([user, other])
        db.flush()
        food = FoodItem(
            id=uuid4(),
            user_id=user.id,
            name="Concurrent favorite",
            source_type="manual",
            source_id=None,
            is_recipe=False,
        )
        other_food = FoodItem(
            id=uuid4(),
            user_id=other.id,
            name="Independent favorite",
            source_type="manual",
            source_id=None,
            is_recipe=False,
        )
        db.add_all([food, other_food])
        db.commit()
        user_id, food_id = user.id, food.id
        other_user_id, other_food_id = other.id, other_food.id

    first_flushed, release = Event(), Event()
    first_result: list = []
    second_result: list = []

    def favorite(result, *, hold=False):
        with factory() as db:
            service = FoodService(db)
            if hold:

                def after_creation(_favorite):
                    first_flushed.set()
                    assert release.wait(5)

                service._after_favorite_creation = after_creation
            try:
                presented = service.set_favorite(user_id, food_id, favorite=True)
                result.append((presented.id, presented.is_favorite))
            except Exception as exc:
                result.append(exc)

    first = Thread(target=favorite, args=(first_result,), kwargs={"hold": True})
    first.start()
    assert first_flushed.wait(5)
    second = Thread(target=favorite, args=(second_result,))
    second.start()
    Event().wait(0.2)
    assert not second_result
    release.set()
    first.join(5)
    second.join(5)

    assert first_result == [(food_id, True)]
    assert second_result == [(food_id, True)]
    with factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(FoodFavorite)
                .where(
                    FoodFavorite.user_id == user_id,
                    FoodFavorite.food_item_id == food_id,
                )
            )
            == 1
        )
        independent = FoodService(db).set_favorite(other_user_id, other_food_id, favorite=True)
        assert independent.is_favorite is True
        assert db.scalar(select(func.count()).select_from(FoodFavorite)) == 2


def test_postgres_target_override_uniqueness(postgres_sessions) -> None:
    factory = postgres_sessions
    with factory() as db:
        user = User(id=uuid4(), email=f"target-postgres-{uuid4()}@example.test")
        db.add(user)
        db.flush()
        values = {
            "user_id": user.id,
            "target_type": "manual_override",
            "nutrient_id": "protein",
            "target_amount": Decimal("90"),
            "unit": "g",
            "basis": "per_day",
            "source": "user",
        }
        db.add(NutritionTarget(**values))
        db.flush()
        db.add(NutritionTarget(**values))
        with pytest.raises(IntegrityError):
            db.flush()


def test_postgres_idempotency_migration_upgrade_and_downgrade(postgres_sessions) -> None:
    engine = postgres_sessions.kw["bind"]
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            idempotency_migration.downgrade()
        columns = {column["name"] for column in inspect(connection).get_columns("daily_logs")}
        assert "client_request_id" not in columns

        with Operations.context(context):
            idempotency_migration.upgrade()
        columns = {column["name"] for column in inspect(connection).get_columns("daily_logs")}
        assert {"client_request_id", "client_request_fingerprint"} <= columns

        with Operations.context(context):
            idempotency_migration.downgrade()
        columns = {column["name"] for column in inspect(connection).get_columns("daily_logs")}
        assert "client_request_id" not in columns

        # Restore the isolated fixture schema for any later test using this factory.
        with Operations.context(context):
            idempotency_migration.upgrade()


def test_postgres_food_recipe_integrity_migration_repairs_defaults_and_round_trips(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    engine = factory.kw["bind"]
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            integrity_migration.downgrade()

    with factory() as db:
        user = User(id=uuid4(), email=f"migration-{uuid4()}@example.test")
        db.add(user)
        db.flush()
        food = FoodItem(
            id=uuid4(),
            user_id=user.id,
            name="Legacy duplicate defaults",
            source_type="manual",
            is_recipe=False,
            serving_definitions=[
                ServingDefinition(
                    id=uuid4(),
                    label="First",
                    quantity=Decimal("1"),
                    unit="portion",
                    gram_weight=Decimal("10"),
                    is_default=True,
                    source="manual",
                    is_user_confirmed=True,
                ),
                ServingDefinition(
                    id=uuid4(),
                    label="Second",
                    quantity=Decimal("1"),
                    unit="portion",
                    gram_weight=Decimal("20"),
                    is_default=True,
                    source="manual",
                    is_user_confirmed=True,
                ),
            ],
        )
        db.add(food)
        db.commit()
        food_id = food.id

    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            integrity_migration.upgrade()
        indexes = {row["name"] for row in inspect(connection).get_indexes("serving_definitions")}
        assert "uq_serving_definitions_one_default_per_food" in indexes
        default_count = connection.scalar(
            select(func.count(ServingDefinition.id)).where(
                ServingDefinition.food_item_id == food_id,
                ServingDefinition.is_default.is_(True),
            )
        )
        assert default_count == 1
        with Operations.context(context):
            integrity_migration.downgrade()
            integrity_migration.upgrade()


def _run_update(
    factory, user_id, log_id, payload, *, locked=None, release=None, fail=False, result=None
):
    with factory() as db:
        service = LogService(db)
        if locked is not None:

            def after_lock(_revision):
                locked.set()
                assert release.wait(5)

            service._after_edit_revision_lookup = after_lock
        if fail:

            def fail_after_replacement(_log):
                raise RuntimeError("forced rollback after replacement")

            service._after_edit_snapshot_regeneration = fail_after_replacement
        try:
            service.update_log(user_id, log_id, DailyLogUpdateRequest(**payload))
            if result is not None:
                result.append("committed")
        except Exception as exc:  # assertions inspect the expected failure in the caller.
            if result is not None:
                result.append(exc)


def _assert_coherent(
    factory,
    user_id,
    log_id,
    quantity: Decimal,
    notes: str | None = None,
    daily_total: Decimal | None = None,
    snapshot_amount: Decimal | None = None,
):
    with factory() as db:
        log = db.get(DailyLog, log_id)
        assert log.amount_quantity == quantity
        assert log.notes == notes
        assert len(log.snapshots) == 1
        snapshot = log.snapshots[0]
        assert snapshot.consumed_amount_quantity == quantity
        expected_snapshot = (
            snapshot_amount if snapshot_amount is not None else quantity * Decimal("100")
        )
        assert snapshot.amount == expected_snapshot
        summary = LogService(db).daily_summary(user_id, log.logged_date)
        calories = next(row for row in summary if row.nutrient_id == "calories")
        assert calories.amount_known == (
            daily_total if daily_total is not None else snapshot.amount
        )


def test_second_quantity_patch_waits_then_uses_latest_committed_state(postgres_sessions) -> None:
    factory = postgres_sessions
    user_id, log_id = _revision_log(factory)
    locked, release = Event(), Event()
    first_result, second_result = [], []
    first = Thread(
        target=_run_update,
        args=(factory, user_id, log_id, {"amount_quantity": Decimal("2")}),
        kwargs={"locked": locked, "release": release, "result": first_result},
    )
    first.start()
    assert locked.wait(5)
    second = Thread(
        target=_run_update,
        args=(factory, user_id, log_id, {"amount_quantity": Decimal("3")}),
        kwargs={"result": second_result},
    )
    second.start()
    Event().wait(0.2)
    assert not second_result
    release.set()
    first.join(5)
    second.join(5)
    assert first_result == second_result == ["committed"]
    _assert_coherent(factory, user_id, log_id, Decimal("3"))


def test_metadata_patch_waits_for_nutrition_and_preserves_latest_amount(postgres_sessions) -> None:
    factory = postgres_sessions
    user_id, log_id = _revision_log(factory)
    locked, release = Event(), Event()
    first = Thread(
        target=_run_update,
        args=(factory, user_id, log_id, {"amount_quantity": Decimal("2")}),
        kwargs={"locked": locked, "release": release},
    )
    first.start()
    assert locked.wait(5)
    second = Thread(
        target=_run_update,
        args=(factory, user_id, log_id, {"notes": "latest metadata"}),
    )
    second.start()
    release.set()
    first.join(5)
    second.join(5)
    _assert_coherent(factory, user_id, log_id, Decimal("2"), "latest metadata")


def test_waiter_proceeds_after_first_replacement_rolls_back(postgres_sessions) -> None:
    factory = postgres_sessions
    user_id, log_id = _revision_log(factory)
    locked, release = Event(), Event()
    first_result, second_result = [], []
    first = Thread(
        target=_run_update,
        args=(factory, user_id, log_id, {"amount_quantity": Decimal("2")}),
        kwargs={
            "locked": locked,
            "release": release,
            "fail": True,
            "result": first_result,
        },
    )
    first.start()
    assert locked.wait(5)
    second = Thread(
        target=_run_update,
        args=(factory, user_id, log_id, {"amount_quantity": Decimal("4")}),
        kwargs={"result": second_result},
    )
    second.start()
    release.set()
    first.join(5)
    second.join(5)
    assert isinstance(first_result[0], RuntimeError)
    assert second_result == ["committed"]
    _assert_coherent(factory, user_id, log_id, Decimal("4"))


def test_different_log_row_does_not_wait(postgres_sessions) -> None:
    factory = postgres_sessions
    user_id, first_log_id = _revision_log(factory)
    with factory() as db:
        first_log = db.get(DailyLog, first_log_id)
        second_log = LogService(db).create_log(
            user_id,
            DailyLogCreateRequest(
                food_item_id=first_log.food_item_id,
                logged_date=first_log.logged_date,
                amount_quantity=Decimal("1"),
                amount_unit="serving",
                serving_definition_id=first_log.serving_definition_id,
            ),
        )
        second_log_id = second_log.id
    locked, release, second_result = Event(), Event(), []
    first = Thread(
        target=_run_update,
        args=(factory, user_id, first_log_id, {"amount_quantity": Decimal("2")}),
        kwargs={"locked": locked, "release": release},
    )
    first.start()
    assert locked.wait(5)
    second = Thread(
        target=_run_update,
        args=(factory, user_id, second_log_id, {"amount_quantity": Decimal("5")}),
        kwargs={"result": second_result},
    )
    second.start()
    second.join(2)
    assert second_result == ["committed"]
    release.set()
    first.join(5)
    _assert_coherent(
        factory,
        user_id,
        second_log_id,
        Decimal("5"),
        daily_total=Decimal("700"),
    )


def test_concurrent_valid_amount_definition_change_is_coherent(postgres_sessions) -> None:
    factory = postgres_sessions
    user_id, log_id = _revision_log(factory)
    with factory() as db:
        log = db.get(DailyLog, log_id)
        revision = db.get(RecipePublicationRevision, log.recipe_publication_revision_id)
        gram_amount_id = next(
            row.id for row in revision.amount_definitions if row.semantic_mode == "g"
        )
    locked, release = Event(), Event()
    first = Thread(
        target=_run_update,
        args=(factory, user_id, log_id, {"amount_quantity": Decimal("2")}),
        kwargs={"locked": locked, "release": release},
    )
    first.start()
    assert locked.wait(5)
    second = Thread(
        target=_run_update,
        args=(
            factory,
            user_id,
            log_id,
            {
                "amount_quantity": Decimal("50"),
                "amount_unit": "g",
                "serving_definition_id": gram_amount_id,
            },
        ),
    )
    second.start()
    release.set()
    first.join(5)
    second.join(5)
    _assert_coherent(
        factory,
        user_id,
        log_id,
        Decimal("50"),
        snapshot_amount=Decimal("50"),
    )
    with factory() as db:
        log = db.get(DailyLog, log_id)
        assert log.amount_unit == "g"
        assert log.recipe_publication_amount_definition_id == gram_amount_id


def test_manual_food_updates_are_serialized(postgres_sessions) -> None:
    factory = postgres_sessions
    user_id, log_id = _manual_log(factory)
    locked, release = Event(), Event()
    first_result, second_result = [], []

    class LockHoldingManualService(LogService):
        pass

    def first_update():
        with factory() as db:
            service = LockHoldingManualService(db)
            original = service._update_compatibility_log

            def hold(user, log, payload):
                locked.set()
                assert release.wait(5)
                original(user, log, payload)

            service._update_compatibility_log = hold
            try:
                service.update_log(
                    user_id,
                    log_id,
                    DailyLogUpdateRequest(amount_quantity=Decimal("2")),
                )
                first_result.append("committed")
            except Exception as exc:
                first_result.append(exc)

    first = Thread(target=first_update)
    first.start()
    assert locked.wait(5)
    second = Thread(
        target=_run_update,
        args=(factory, user_id, log_id, {"amount_quantity": Decimal("3")}),
        kwargs={"result": second_result},
    )
    second.start()
    Event().wait(0.2)
    assert not second_result
    release.set()
    first.join(5)
    second.join(5)
    assert first_result == second_result == ["committed"]
    _assert_coherent(factory, user_id, log_id, Decimal("3"))


def test_deleted_projection_revision_log_metadata_updates_remain_available(postgres_sessions) -> None:
    factory = postgres_sessions
    user_id, log_id = _revision_log(factory)
    with factory() as db:
        log = db.get(DailyLog, log_id)
        assert log is not None
        log.food_item.deleted_at = log.updated_at
        db.commit()
    with factory() as db:
        updated = LogService(db).update_log(
            user_id,
            log_id,
            DailyLogUpdateRequest(notes="metadata only", logged_date=date(2026, 7, 12)),
        )
        assert updated.notes == "metadata only"
        with pytest.raises(LogSourceUnavailableError):
            LogService(db).update_log(
                user_id,
                log_id,
                DailyLogUpdateRequest(amount_quantity=Decimal("2")),
            )


def test_concurrent_identical_food_creates_replay_one_committed_resource(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    with factory() as db:
        user = User(id=uuid4(), email=f"create-retry-{uuid4()}@example.test")
        db.add(user)
        db.commit()
        user_id = user.id
    request_id = uuid4()
    start = Event()
    results: list = []
    errors: list[BaseException] = []

    def run() -> None:
        with factory() as db:
            try:
                start.wait(5)
                results.append(
                    FoodService(db)
                    .create_manual_food(user_id, _idempotent_food_payload(request_id))
                    .id
                )
            except BaseException as exc:  # pragma: no cover - reported by assertion.
                errors.append(exc)

    threads = [Thread(target=run), Thread(target=run)]
    for thread in threads:
        thread.start()
    start.set()
    for thread in threads:
        thread.join(10)

    assert not errors
    assert len(results) == 2
    assert len(set(results)) == 1
    with factory() as db:
        assert db.scalar(select(func.count(FoodItem.id)).where(FoodItem.user_id == user_id)) == 1
        assert (
            db.scalar(
                select(func.count(CreateOperationIdempotency.id)).where(
                    CreateOperationIdempotency.user_id == user_id
                )
            )
            == 1
        )


def test_retry_waiting_on_failed_create_proceeds_after_receipt_rollback(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    with factory() as db:
        user = User(id=uuid4(), email=f"rollback-retry-{uuid4()}@example.test")
        db.add(user)
        db.commit()
        user_id = user.id
    request_id = uuid4()
    reserved = Event()
    release_failure = Event()
    first_errors: list[BaseException] = []
    retry_results: list = []

    def fail_first() -> None:
        with factory() as db:
            service = FoodService(db)

            def fail_after_reservation(_food):
                reserved.set()
                release_failure.wait(5)
                raise RuntimeError("injected rollback")

            service.foods.add = fail_after_reservation
            try:
                service.create_manual_food(user_id, _idempotent_food_payload(request_id))
            except BaseException as exc:
                first_errors.append(exc)

    def retry() -> None:
        with factory() as db:
            retry_results.append(
                FoodService(db).create_manual_food(user_id, _idempotent_food_payload(request_id)).id
            )

    first = Thread(target=fail_first)
    first.start()
    assert reserved.wait(5)
    second = Thread(target=retry)
    second.start()
    Event().wait(0.2)
    assert not retry_results
    release_failure.set()
    first.join(10)
    second.join(10)

    assert len(first_errors) == 1
    assert isinstance(first_errors[0], RuntimeError)
    assert len(retry_results) == 1
    with factory() as db:
        assert db.scalar(select(func.count(FoodItem.id)).where(FoodItem.user_id == user_id)) == 1
        assert (
            db.scalar(
                select(func.count(CreateOperationIdempotency.id)).where(
                    CreateOperationIdempotency.user_id == user_id
                )
            )
            == 1
        )


def test_concurrent_identical_recipe_publication_creates_one_revision(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    with factory() as db:
        user = User(id=uuid4(), email=f"publish-retry-{uuid4()}@example.test")
        db.add(user)
        db.commit()
        recipe = RecipeService(db).create_recipe(
            user.id,
            RecipeCreateRequest(name="Idempotent Publish", serving_count_yield=Decimal("1")),
        )
        user_id, recipe_id = user.id, recipe.id
    request_id = uuid4()
    start = Event()
    results: list = []
    errors: list[BaseException] = []

    def run() -> None:
        with factory() as db:
            try:
                start.wait(5)
                _, food = RecipeService(db).publish(user_id, recipe_id, request_id)
                results.append(food.id)
            except BaseException as exc:  # pragma: no cover - reported by assertion.
                errors.append(exc)

    threads = [Thread(target=run), Thread(target=run)]
    for thread in threads:
        thread.start()
    start.set()
    for thread in threads:
        thread.join(10)

    assert not errors
    assert len(results) == 2
    assert len(set(results)) == 1
    with factory() as db:
        assert (
            db.scalar(
                select(func.count(RecipePublicationRevision.id)).where(
                    RecipePublicationRevision.recipe_id == recipe_id
                )
            )
            == 1
        )


def test_committed_retry_replays_and_same_request_is_cross_user_isolated(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    with factory() as db:
        first_user = User(id=uuid4(), email=f"replay-owner-a-{uuid4()}@example.test")
        second_user = User(id=uuid4(), email=f"replay-owner-b-{uuid4()}@example.test")
        db.add_all([first_user, second_user])
        db.commit()
        first_user_id, second_user_id = first_user.id, second_user.id
    request_id = uuid4()

    with factory() as db:
        original = FoodService(db).create_manual_food(
            first_user_id, _idempotent_food_payload(request_id)
        )
        original_id = original.id
    # This models a timeout where the first commit succeeded but its response
    # was lost, followed by a later retry using the same request identity.
    with factory() as db:
        replay = FoodService(db).create_manual_food(
            first_user_id, _idempotent_food_payload(request_id)
        )
        assert replay.id == original_id
    with factory() as db:
        other_owner = FoodService(db).create_manual_food(
            second_user_id, _idempotent_food_payload(request_id)
        )
        assert other_owner.id != original_id
    with factory() as db:
        recipe = RecipeService(db).create_recipe(
            first_user_id,
            RecipeCreateRequest(
                client_request_id=request_id,
                name="Cross-operation request reuse",
                serving_count_yield=Decimal("1"),
            ),
        )
        assert recipe.user_id == first_user_id

    with factory() as db:
        assert db.scalar(select(func.count(FoodItem.id))) == 2
        assert db.scalar(select(func.count(CreateOperationIdempotency.id))) == 3


def test_different_payload_waiting_on_uncommitted_request_conflicts_after_commit(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    with factory() as db:
        user = User(id=uuid4(), email=f"payload-conflict-{uuid4()}@example.test")
        db.add(user)
        db.commit()
        user_id = user.id
    request_id = uuid4()
    first_domain_started, second_reservation_started, release = Event(), Event(), Event()
    first_results: list = []
    second_errors: list[BaseException] = []

    def first_create() -> None:
        with factory() as db:
            service = FoodService(db)
            original_add = service.foods.add

            def hold_after_reservation(food):
                first_domain_started.set()
                release.wait(5)
                return original_add(food)

            service.foods.add = hold_after_reservation
            first_results.append(
                service.create_manual_food(
                    user_id, _idempotent_food_payload(request_id, "First payload")
                ).id
            )

    def conflicting_create() -> None:
        with factory() as db:
            service = FoodService(db)
            original_reserve = service.create_idempotency.reserve

            def signal_then_reserve(*args, **kwargs):
                second_reservation_started.set()
                return original_reserve(*args, **kwargs)

            service.create_idempotency.reserve = signal_then_reserve
            try:
                service.create_manual_food(
                    user_id, _idempotent_food_payload(request_id, "Different payload")
                )
            except BaseException as exc:
                second_errors.append(exc)

    first = Thread(target=first_create)
    first.start()
    assert first_domain_started.wait(5)
    second = Thread(target=conflicting_create)
    second.start()
    assert second_reservation_started.wait(5)
    release.set()
    first.join(10)
    second.join(10)

    assert len(first_results) == 1
    assert len(second_errors) == 1
    assert isinstance(second_errors[0], CreateOperationIdempotencyConflictError)
    with factory() as db:
        assert db.scalar(select(func.count(FoodItem.id))) == 1
        assert db.scalar(select(func.count(CreateOperationIdempotency.id))) == 1


def test_publication_replay_after_later_publication_uses_original_revision_snapshot(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    with factory() as db:
        user = User(id=uuid4(), email=f"publication-snapshot-{uuid4()}@example.test")
        db.add(user)
        db.commit()
        recipe = RecipeService(db).create_recipe(
            user.id,
            RecipeCreateRequest(name="First PG Publication", serving_count_yield=Decimal("1")),
        )
        user_id, recipe_id = user.id, recipe.id
    first_request, second_request = uuid4(), uuid4()
    with factory() as db:
        first = RecipeService(db).publish(user_id, recipe_id, first_request).response
    with factory() as db:
        RecipeService(db).update_recipe(
            user_id,
            recipe_id,
            RecipeUpdateRequest(name="Second PG Publication"),
        )
        second = RecipeService(db).publish(user_id, recipe_id, second_request).response
        assert second.recipe.name == "Second PG Publication"
    with factory() as db:
        replay = RecipeService(db).publish(user_id, recipe_id, first_request).response
        assert replay.model_dump(mode="json") == first.model_dump(mode="json")
        receipt = db.scalar(
            select(CreateOperationIdempotency).where(
                CreateOperationIdempotency.user_id == user_id,
                CreateOperationIdempotency.operation == "recipe.publish",
                CreateOperationIdempotency.client_request_id == first_request,
            )
        )
        assert receipt is not None
        revision = db.get(RecipePublicationRevision, receipt.resource_id)
        assert revision is not None
        assert revision.revision_number == 1


def test_archived_result_replay_is_unavailable_and_never_replaced(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    with factory() as db:
        user = User(id=uuid4(), email=f"archive-replay-{uuid4()}@example.test")
        db.add(user)
        db.commit()
        user_id = user.id
        request_id = uuid4()
        original = FoodService(db).create_manual_food(user_id, _idempotent_food_payload(request_id))
        original_id = original.id
    with factory() as db:
        FoodService(db).soft_delete_food(user_id, original_id)
    with factory() as db:
        with pytest.raises(CreateOperationResultUnavailableError):
            FoodService(db).create_manual_food(user_id, _idempotent_food_payload(request_id))
        assert db.scalar(select(func.count(FoodItem.id))) == 1


def test_unrelated_integrity_and_post_completion_failures_leave_no_orphans(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    with factory() as db:
        user = User(id=uuid4(), email=f"orphan-owner-{uuid4()}@example.test")
        db.add(user)
        db.commit()
        user_id, duplicate_email = user.id, user.email

    unrelated_request = uuid4()
    with factory() as db:
        service = FoodService(db)

        def unrelated_failure(_food):
            db.add(User(id=uuid4(), email=duplicate_email))
            db.flush()
            raise AssertionError("unreachable")

        service.foods.add = unrelated_failure
        with pytest.raises(IntegrityError):
            service.create_manual_food(user_id, _idempotent_food_payload(unrelated_request))
        assert not service.create_idempotency.find(
            user_id,
            "food.create_manual",
            unrelated_request,
            "not-used-after-rollback",
        )

    completion_request = uuid4()
    with factory() as db:
        service = FoodService(db)

        def fail_after_completion(receipt, snapshot):
            CreateIdempotencyCoordinator.complete(receipt, snapshot)
            raise RuntimeError("injected after receipt completion")

        service.create_idempotency.complete = fail_after_completion
        with pytest.raises(RuntimeError, match="after receipt completion"):
            service.create_manual_food(user_id, _idempotent_food_payload(completion_request))

    with factory() as db:
        assert db.scalar(select(func.count(FoodItem.id))) == 0
        assert db.scalar(select(func.count(CreateOperationIdempotency.id))) == 0


def test_publication_failure_after_projection_link_rolls_back_receipt_and_domain_graph(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    with factory() as db:
        user = User(id=uuid4(), email=f"publication-orphan-{uuid4()}@example.test")
        db.add(user)
        db.commit()
        recipe = RecipeService(db).create_recipe(
            user.id,
            RecipeCreateRequest(name="Rollback Publication", serving_count_yield=Decimal("1")),
        )
        user_id, recipe_id = user.id, recipe.id

    request_id = uuid4()
    with factory() as db:
        service = RecipeService(db)

        def fail_after_projection_link(_projection):
            raise RuntimeError("injected after projection link")

        service._after_projection_link = fail_after_projection_link
        with pytest.raises(RuntimeError, match="after projection link"):
            service.publish(user_id, recipe_id, request_id)

    with factory() as db:
        recipe = db.get(Recipe, recipe_id)
        assert recipe is not None
        assert recipe.active_publication_revision_id is None
        assert recipe.published_food_item_id is None
        assert db.scalar(select(func.count(RecipePublicationRevision.id))) == 0
        assert db.scalar(select(func.count(FoodItem.id))) == 0
        assert db.scalar(select(func.count(CreateOperationIdempotency.id))) == 0


def test_mutable_log_edit_waits_for_food_commit_and_uses_one_new_generation(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    user_id, log_id = _manual_log(factory)
    with factory() as db:
        log = db.get(DailyLog, log_id)
        food_id = log.food_item_id
    new_serving_id = uuid4()
    food_locked, release = Event(), Event()
    update_result: list[object] = []
    edit_result: list[object] = []

    def update_food() -> None:
        with factory() as db:
            service = FoodService(db)

            def after_lock(_food, _parents) -> None:
                food_locked.set()
                assert release.wait(5)

            def replacement_servings(_inputs) -> list[ServingDefinition]:
                return [
                    ServingDefinition(
                        id=new_serving_id,
                        label="new coherent portion",
                        quantity=Decimal("1"),
                        unit="portion",
                        gram_weight=Decimal("150"),
                        is_default=True,
                        source="manual",
                        is_user_confirmed=True,
                    )
                ]

            service._after_food_dependency_lock = after_lock
            service._new_servings = replacement_servings
            try:
                service.update_food(
                    user_id,
                    food_id,
                    FoodUpdateRequest.model_validate(
                        {
                            "serving_definitions": [
                                {
                                    "label": "new coherent portion",
                                    "quantity": "1",
                                    "unit": "portion",
                                    "gram_weight": "150",
                                    "is_default": True,
                                }
                            ],
                            "nutrients": [
                                {
                                    "nutrient_id": "calories",
                                    "amount": "500",
                                    "unit": "kcal",
                                    "basis": "per_serving",
                                    "data_status": "known",
                                }
                            ],
                        }
                    ),
                )
                update_result.append("committed")
            except BaseException as exc:
                update_result.append(exc)

    def edit_log() -> None:
        with factory() as db:
            try:
                updated = LogService(db).update_log(
                    user_id,
                    log_id,
                    DailyLogUpdateRequest(
                        amount_quantity=Decimal("2"),
                        amount_unit="serving",
                        serving_definition_id=new_serving_id,
                    ),
                )
                edit_result.append(updated.id)
            except BaseException as exc:
                edit_result.append(exc)

    updater = Thread(target=update_food)
    updater.start()
    assert food_locked.wait(5)
    editor = Thread(target=edit_log)
    editor.start()
    Event().wait(0.2)
    assert not edit_result
    release.set()
    updater.join(5)
    editor.join(5)

    assert update_result == ["committed"]
    assert edit_result == [log_id]
    with factory() as db:
        log = db.get(DailyLog, log_id)
        assert log.serving_definition_id == new_serving_id
        assert log.gram_amount == Decimal("300.000000")
        assert len(log.snapshots) == 1
        assert log.snapshots[0].amount == Decimal("1000.000000")


def test_mutable_log_edit_waiter_uses_old_generation_after_food_update_rollback(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    user_id, log_id = _manual_log(factory)
    with factory() as db:
        log = db.get(DailyLog, log_id)
        food_id = log.food_item_id
        old_serving_id = log.serving_definition_id
    mutation_ready, release = Event(), Event()
    holder_result: list[object] = []
    waiter_result: list[object] = []

    def failing_food_update() -> None:
        with factory() as db:
            service = FoodService(db)

            def fail_after_mutation(_parents, _now) -> None:
                mutation_ready.set()
                assert release.wait(5)
                raise RuntimeError("forced Food rollback")

            service._mark_published_parents_stale = fail_after_mutation
            try:
                service.update_food(
                    user_id,
                    food_id,
                    FoodUpdateRequest.model_validate(
                        {
                            "nutrients": [
                                {
                                    "nutrient_id": "calories",
                                    "amount": "900",
                                    "unit": "kcal",
                                    "basis": "per_serving",
                                    "data_status": "known",
                                }
                            ]
                        }
                    ),
                )
                holder_result.append("unexpected commit")
            except BaseException as exc:
                holder_result.append(exc)

    def edit_log() -> None:
        with factory() as db:
            try:
                LogService(db).update_log(
                    user_id,
                    log_id,
                    DailyLogUpdateRequest(
                        amount_quantity=Decimal("2"),
                        serving_definition_id=old_serving_id,
                    ),
                )
                waiter_result.append("committed")
            except BaseException as exc:
                waiter_result.append(exc)

    holder = Thread(target=failing_food_update)
    holder.start()
    assert mutation_ready.wait(5)
    waiter = Thread(target=edit_log)
    waiter.start()
    Event().wait(0.2)
    assert not waiter_result
    release.set()
    holder.join(5)
    waiter.join(5)

    assert len(holder_result) == 1
    assert isinstance(holder_result[0], RuntimeError)
    assert waiter_result == ["committed"]
    with factory() as db:
        food = db.get(FoodItem, food_id)
        log = db.get(DailyLog, log_id)
        assert food.nutrients[0].amount == Decimal("100.000000")
        assert log.snapshots[0].amount == Decimal("200.000000")


def test_mutable_log_edit_does_not_wait_for_unrelated_food(postgres_sessions) -> None:
    factory = postgres_sessions
    user_id, log_id = _manual_log(factory)
    with factory() as db:
        unrelated = FoodItem(
            id=uuid4(),
            user_id=user_id,
            name="Unrelated locked Food",
            source_type="manual",
            is_recipe=False,
        )
        db.add(unrelated)
        db.commit()
        unrelated_id = unrelated.id
    locked, release = Event(), Event()
    edit_result: list[object] = []

    def hold_unrelated() -> None:
        with factory() as db:
            food = db.get(FoodItem, unrelated_id, with_for_update=True)
            assert food is not None
            locked.set()
            assert release.wait(5)
            db.rollback()

    def edit_log() -> None:
        with factory() as db:
            try:
                LogService(db).update_log(
                    user_id,
                    log_id,
                    DailyLogUpdateRequest(amount_quantity=Decimal("3")),
                )
                edit_result.append("committed")
            except BaseException as exc:
                edit_result.append(exc)

    holder = Thread(target=hold_unrelated)
    holder.start()
    assert locked.wait(5)
    editor = Thread(target=edit_log)
    editor.start()
    editor.join(2)
    assert edit_result == ["committed"]
    release.set()
    holder.join(5)


def test_revision_backed_edit_is_independent_of_mutable_food_lock(postgres_sessions) -> None:
    factory = postgres_sessions
    user_id, log_id = _revision_log(factory)
    with factory() as db:
        mutable = FoodItem(
            id=uuid4(),
            user_id=user_id,
            name="Unrelated mutable Food",
            source_type="manual",
            is_recipe=False,
        )
        db.add(mutable)
        db.commit()
        mutable_id = mutable.id
    locked, release = Event(), Event()
    edit_result: list[object] = []

    def hold_mutable() -> None:
        with factory() as db:
            food = db.get(FoodItem, mutable_id, with_for_update=True)
            assert food is not None
            locked.set()
            assert release.wait(5)
            db.rollback()

    holder = Thread(target=hold_mutable)
    holder.start()
    assert locked.wait(5)
    editor = Thread(
        target=_run_update,
        args=(factory, user_id, log_id, {"amount_quantity": Decimal("2")}),
        kwargs={"result": edit_result},
    )
    editor.start()
    editor.join(2)
    assert edit_result == ["committed"]
    release.set()
    holder.join(5)
    _assert_coherent(factory, user_id, log_id, Decimal("2"))


def test_legacy_projection_log_edit_and_republication_follow_daily_log_then_food_order(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    user_id, ingredient_food_id, ingredient_serving_id = _manual_create_target(factory)
    with factory() as db:
        recipe = RecipeService(db).create_recipe(
            user_id,
            RecipeCreateRequest.model_validate(
                {
                    "name": "Legacy compatibility Recipe",
                    "serving_count_yield": "1",
                    "final_cooked_weight_grams": "100",
                    "ingredients": [
                        {
                            "food_item_id": str(ingredient_food_id),
                            "position": 0,
                            "amount_quantity": "1",
                            "amount_unit": "serving",
                            "serving_definition_id": str(ingredient_serving_id),
                        }
                    ],
                }
            ),
        )
        projection = RecipeService(db).publish(user_id, recipe.id).food
        projection = db.get(FoodItem, projection.id)
        serving_id = next(row.id for row in projection.serving_definitions if row.is_default)
        service = LogService(db)
        legacy = service._create_food_log(
            user_id,
            projection,
            DailyLogCreateRequest(
                food_item_id=projection.id,
                logged_date=date(2026, 7, 21),
                amount_quantity=Decimal("1"),
                amount_unit="serving",
                serving_definition_id=serving_id,
            ),
        )
        legacy = service.logs.add(legacy)
        db.commit()
        recipe_id, log_id = recipe.id, legacy.id
    log_locked, release = Event(), Event()
    edit_result: list[object] = []
    publish_result: list[object] = []

    def edit_legacy_log() -> None:
        with factory() as db:
            service = LogService(db)
            original = service._update_compatibility_log

            def hold_after_log_lock(owner_id, log, payload) -> None:
                log_locked.set()
                assert release.wait(5)
                original(owner_id, log, payload)

            service._update_compatibility_log = hold_after_log_lock
            try:
                service.update_log(
                    user_id,
                    log_id,
                    DailyLogUpdateRequest(amount_quantity=Decimal("2")),
                )
                edit_result.append("committed")
            except BaseException as exc:
                edit_result.append(exc)

    def republish() -> None:
        with factory() as db:
            try:
                RecipeService(db).publish(user_id, recipe_id)
                publish_result.append("committed")
            except BaseException as exc:
                publish_result.append(exc)

    editor = Thread(target=edit_legacy_log)
    editor.start()
    assert log_locked.wait(5)
    publisher = Thread(target=republish)
    publisher.start()
    Event().wait(0.2)
    assert not publish_result
    release.set()
    editor.join(5)
    publisher.join(5)

    assert edit_result == publish_result == ["committed"]
    with factory() as db:
        log = db.get(DailyLog, log_id)
        assert log.recipe_publication_revision_id is None
        assert log.amount_quantity == Decimal("2.000000")
        assert log.snapshots[0].amount == Decimal("200.000000")


def test_same_user_target_updates_serialize_without_uniqueness_failures(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    with factory() as db:
        user = User(id=uuid4(), email=f"targets-{uuid4()}@example.test")
        db.add(user)
        db.commit()
        user_id = user.id
    locked, release = Event(), Event()
    first_result: list[object] = []
    second_result: list[object] = []

    def update(payload, result, *, hold: bool = False) -> None:
        with factory() as db:
            service = TargetService(db)
            if hold:

                def after_lock(_user_id) -> None:
                    locked.set()
                    assert release.wait(5)

                service._after_target_owner_lock = after_lock
            try:
                service.update(user_id, payload, date(2026, 7, 21))
                result.append("committed")
            except BaseException as exc:
                result.append(exc)

    first = Thread(
        target=update,
        args=(_target_payload(protein="100"), first_result),
        kwargs={"hold": True},
    )
    first.start()
    assert locked.wait(5)
    second = Thread(
        target=update,
        args=(_target_payload(protein="200", activity="active"), second_result),
    )
    second.start()
    Event().wait(0.2)
    assert not second_result
    release.set()
    first.join(5)
    second.join(5)

    assert first_result == second_result == ["committed"]
    with factory() as db:
        profile = db.get(UserProfile, user_id)
        target = db.scalar(
            select(NutritionTarget).where(
                NutritionTarget.user_id == user_id,
                NutritionTarget.nutrient_id == "protein",
            )
        )
        assert profile.activity_level == "active"
        assert target.target_amount == Decimal("200.000000")


def test_target_update_then_reset_is_one_deterministic_serial_order(postgres_sessions) -> None:
    factory = postgres_sessions
    with factory() as db:
        user = User(id=uuid4(), email=f"target-reset-{uuid4()}@example.test")
        db.add(user)
        db.commit()
        user_id = user.id
        TargetService(db).update(
            user_id,
            _target_payload(protein="100"),
            date(2026, 7, 21),
        )
    locked, release = Event(), Event()
    update_result: list[object] = []
    reset_result: list[object] = []

    def update() -> None:
        with factory() as db:
            service = TargetService(db)

            def after_lock(_user_id) -> None:
                locked.set()
                assert release.wait(5)

            service._after_target_owner_lock = after_lock
            try:
                service.update(
                    user_id,
                    _target_payload(protein="250", activity="very_active"),
                    date(2026, 7, 21),
                )
                update_result.append("committed")
            except BaseException as exc:
                update_result.append(exc)

    def reset() -> None:
        with factory() as db:
            try:
                TargetService(db).reset_override(
                    user_id,
                    "protein",
                    date(2026, 7, 21),
                )
                reset_result.append("committed")
            except BaseException as exc:
                reset_result.append(exc)

    updater = Thread(target=update)
    updater.start()
    assert locked.wait(5)
    resetter = Thread(target=reset)
    resetter.start()
    Event().wait(0.2)
    assert not reset_result
    release.set()
    updater.join(5)
    resetter.join(5)

    assert update_result == reset_result == ["committed"]
    with factory() as db:
        assert db.get(UserProfile, user_id).activity_level == "very_active"
        assert (
            db.scalar(
                select(func.count(NutritionTarget.id)).where(
                    NutritionTarget.user_id == user_id,
                    NutritionTarget.nutrient_id == "protein",
                )
            )
            == 0
        )


def test_target_waiter_continues_after_lock_holder_rolls_back(postgres_sessions) -> None:
    factory = postgres_sessions
    with factory() as db:
        user = User(id=uuid4(), email=f"target-rollback-{uuid4()}@example.test")
        db.add(user)
        db.commit()
        user_id = user.id
    flushed, release = Event(), Event()
    holder_result: list[object] = []
    waiter_result: list[object] = []

    def failing_update() -> None:
        with factory() as db:
            service = TargetService(db)

            def fail_after_flush(_user_id) -> None:
                flushed.set()
                assert release.wait(5)
                raise RuntimeError("forced Target rollback")

            service._after_target_update_flush = fail_after_flush
            try:
                service.update(
                    user_id,
                    _target_payload(protein="100"),
                    date(2026, 7, 21),
                )
                holder_result.append("unexpected commit")
            except BaseException as exc:
                holder_result.append(exc)

    def waiting_update() -> None:
        with factory() as db:
            try:
                TargetService(db).update(
                    user_id,
                    _target_payload(protein="300", activity="active"),
                    date(2026, 7, 21),
                )
                waiter_result.append("committed")
            except BaseException as exc:
                waiter_result.append(exc)

    holder = Thread(target=failing_update)
    holder.start()
    assert flushed.wait(5)
    waiter = Thread(target=waiting_update)
    waiter.start()
    Event().wait(0.2)
    assert not waiter_result
    release.set()
    holder.join(5)
    waiter.join(5)

    assert len(holder_result) == 1
    assert isinstance(holder_result[0], RuntimeError)
    assert waiter_result == ["committed"]
    with factory() as db:
        assert db.get(UserProfile, user_id).activity_level == "active"
        target = db.scalar(
            select(NutritionTarget).where(
                NutritionTarget.user_id == user_id,
                NutritionTarget.nutrient_id == "protein",
            )
        )
        assert target.target_amount == Decimal("300.000000")


def test_target_writes_for_different_users_do_not_block(postgres_sessions) -> None:
    factory = postgres_sessions
    with factory() as db:
        first_user = User(id=uuid4(), email=f"target-first-{uuid4()}@example.test")
        second_user = User(id=uuid4(), email=f"target-second-{uuid4()}@example.test")
        db.add_all([first_user, second_user])
        db.commit()
        first_user_id, second_user_id = first_user.id, second_user.id
    locked, release = Event(), Event()
    second_result: list[object] = []

    def hold_first_user() -> None:
        with factory() as db:
            service = TargetService(db)

            def after_lock(_user_id) -> None:
                locked.set()
                assert release.wait(5)

            service._after_target_owner_lock = after_lock
            service.update(
                first_user_id,
                _target_payload(protein="100"),
                date(2026, 7, 21),
            )

    def update_second_user() -> None:
        with factory() as db:
            try:
                TargetService(db).update(
                    second_user_id,
                    _target_payload(protein="200"),
                    date(2026, 7, 21),
                )
                second_result.append("committed")
            except BaseException as exc:
                second_result.append(exc)

    holder = Thread(target=hold_first_user)
    holder.start()
    assert locked.wait(5)
    independent = Thread(target=update_second_user)
    independent.start()
    independent.join(2)
    assert second_result == ["committed"]
    release.set()
    holder.join(5)


def test_recipe_delete_exhaustion_releases_postgres_locks_and_later_retry_succeeds(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    with factory() as db:
        user = User(id=uuid4(), email=f"delete-exhaustion-{uuid4()}@example.test")
        db.add(user)
        db.commit()
        child = RecipeService(db).create_recipe(
            user.id,
            RecipeCreateRequest(
                name="Delete child",
                serving_count_yield=Decimal("1"),
                final_cooked_weight_grams=Decimal("100"),
            ),
        )
        projection = RecipeService(db).publish(user.id, child.id).food
        parent = RecipeService(db).create_recipe(
            user.id,
            RecipeCreateRequest.model_validate(
                {
                    "name": "Delete parent",
                    "ingredients": [
                        {
                            "food_item_id": str(projection.id),
                            "position": 0,
                            "amount_quantity": "10",
                            "amount_unit": "g",
                        }
                    ],
                }
            ),
        )
        user_id = user.id
        child_id, projection_id, parent_id = child.id, projection.id, parent.id

    with factory() as db:
        service = RecipeService(db)
        original_dependencies = service._dependent_recipe_ids
        phantom_id = uuid4()
        scans = 0

        def never_stable(owner_id, food_id):
            nonlocal scans
            scans += 1
            actual = original_dependencies(owner_id, food_id)
            return actual if scans % 2 else actual | {phantom_id}

        service._dependent_recipe_ids = never_stable
        with pytest.raises(RecipeDependenciesUnstableError):
            service.soft_delete_recipe(
                user_id,
                child_id,
                remove_from_recipes=True,
            )
        assert scans == RECIPE_DELETE_DEPENDENCY_RESTART_LIMIT * 2

    with factory() as db:
        assert (
            db.scalar(
                select(FoodItem).where(FoodItem.id == projection_id).with_for_update(nowait=True)
            )
            is not None
        )
        assert (
            len(
                db.scalars(
                    select(Recipe)
                    .where(Recipe.id.in_({child_id, parent_id}))
                    .order_by(Recipe.id)
                    .with_for_update(nowait=True)
                ).all()
            )
            == 2
        )
        db.rollback()

    with factory() as db:
        RecipeService(db).soft_delete_recipe(
            user_id,
            child_id,
            remove_from_recipes=True,
        )
    with factory() as db:
        assert db.get(Recipe, child_id).deleted_at is not None
        assert db.get(FoodItem, projection_id).deleted_at is not None
        assert db.get(Recipe, parent_id).ingredients == []


def _log_updated_at(factory, log_id):
    with factory() as db:
        return db.get(DailyLog, log_id).updated_at


def _run_delete(
    factory,
    user_id,
    log_id,
    payload,
    *,
    locked=None,
    release=None,
    waiting=None,
    result=None,
):
    with factory() as db:
        service = LogService(db)
        if waiting is not None:
            original_get_for_update = service.logs.get_for_update

            def signal_get_for_update(*args, **kwargs):
                waiting.set()
                return original_get_for_update(*args, **kwargs)

            service.logs.get_for_update = signal_get_for_update
        if locked is not None:
            original_delete = service.logs.delete

            def hold_delete(log, owner_id):
                locked.set()
                assert release is not None and release.wait(5)
                return original_delete(log, owner_id)

            service.logs.delete = hold_delete
        try:
            replay = service.delete_log(
                user_id,
                log_id,
                DailyLogDeleteRequest(**payload),
            )
            if result is not None:
                result.append("replayed" if isinstance(replay, LogMutationReplay) else "committed")
        except Exception as exc:  # assertions inspect the expected failure in the caller.
            if result is not None:
                result.append(exc)


def test_concurrent_deletes_serialize_preconditions_and_report_stale_winner(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    user_id, log_id = _manual_log(factory)
    expected = _log_updated_at(factory, log_id)
    first_locked, second_waiting, release = Event(), Event(), Event()
    first_result, second_result = [], []
    first_payload = {
        "client_request_id": uuid4(),
        "expected_updated_at": expected,
    }
    second_payload = {
        "client_request_id": uuid4(),
        "expected_updated_at": expected,
    }
    first = Thread(
        target=_run_delete,
        args=(factory, user_id, log_id, first_payload),
        kwargs={"locked": first_locked, "release": release, "result": first_result},
    )
    first.start()
    assert first_locked.wait(5)
    second = Thread(
        target=_run_delete,
        args=(factory, user_id, log_id, second_payload),
        kwargs={"waiting": second_waiting, "result": second_result},
    )
    second.start()
    assert second_waiting.wait(5)
    release.set()
    first.join(10)
    second.join(10)

    assert first_result == ["committed"]
    assert len(second_result) == 1
    assert isinstance(second_result[0], StaleLogMutationError)
    with factory() as db:
        assert db.get(DailyLog, log_id) is None
        assert db.scalar(
            select(func.count()).select_from(DailyLogNutrientSnapshot).where(
                DailyLogNutrientSnapshot.daily_log_id == log_id
            )
        ) == 0
        assert db.scalar(
            select(func.count()).select_from(CreateOperationIdempotency).where(
                CreateOperationIdempotency.user_id == user_id,
                CreateOperationIdempotency.operation == "log.delete",
            )
        ) == 1


def test_concurrent_identical_deletes_replay_after_row_lock_wait(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    user_id, log_id = _manual_log(factory)
    expected = _log_updated_at(factory, log_id)
    request_id = uuid4()
    payload = {"client_request_id": request_id, "expected_updated_at": expected}
    first_locked, second_waiting, release = Event(), Event(), Event()
    first_result, second_result = [], []
    first = Thread(
        target=_run_delete,
        args=(factory, user_id, log_id, payload),
        kwargs={"locked": first_locked, "release": release, "result": first_result},
    )
    first.start()
    assert first_locked.wait(5)
    second = Thread(
        target=_run_delete,
        args=(factory, user_id, log_id, payload),
        kwargs={"waiting": second_waiting, "result": second_result},
    )
    second.start()
    assert second_waiting.wait(5)
    release.set()
    first.join(10)
    second.join(10)

    assert first_result == ["committed"]
    assert second_result == ["replayed"]
    with factory() as db:
        receipt = db.scalar(
            select(CreateOperationIdempotency).where(
                CreateOperationIdempotency.user_id == user_id,
                CreateOperationIdempotency.operation == "log.delete",
                CreateOperationIdempotency.client_request_id == request_id,
            )
        )
        assert receipt is not None
        assert receipt.response_snapshot == {"deleted": True, "log_id": str(log_id)}
        assert receipt.completed_at is not None
        assert db.get(DailyLog, log_id) is None


def test_concurrent_update_and_delete_use_one_generation_precondition(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    user_id, log_id = _manual_log(factory)
    expected = _log_updated_at(factory, log_id)
    update_locked, delete_waiting, release = Event(), Event(), Event()
    update_result, delete_result = [], []

    def run_update_winner() -> None:
        with factory() as db:
            service = LogService(db)

            def hold_after_food_lock(_food):
                update_locked.set()
                assert release.wait(5)

            service._after_edit_mutable_food_lock = hold_after_food_lock
            try:
                service.update_log(
                    user_id,
                    log_id,
                    DailyLogUpdateRequest(
                        client_request_id=uuid4(),
                        expected_updated_at=expected,
                        notes="update wins",
                    ),
                )
                update_result.append("committed")
            except Exception as exc:  # pragma: no cover - reported by assertion.
                update_result.append(exc)

    def run_delete_loser() -> None:
        _run_delete(
            factory,
            user_id,
            log_id,
            {"client_request_id": uuid4(), "expected_updated_at": expected},
            waiting=delete_waiting,
            result=delete_result,
        )

    first = Thread(target=run_update_winner)
    first.start()
    assert update_locked.wait(5)
    second = Thread(target=run_delete_loser)
    second.start()
    assert delete_waiting.wait(5)
    release.set()
    first.join(10)
    second.join(10)

    assert update_result == ["committed"]
    assert len(delete_result) == 1
    assert isinstance(delete_result[0], StaleLogMutationError)
    with factory() as db:
        log = db.get(DailyLog, log_id)
        assert log is not None
        assert log.notes == "update wins"
        assert len(log.snapshots) == 1

def test_postgres_create_retry_controls_after_calendar_change(
    postgres_sessions,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = postgres_sessions
    logged_date = date(2026, 7, 14)
    now_date = date(2026, 7, 14)
    monkeypatch.setattr(
        CalendarService,
        "today_in_zone",
        staticmethod(
            lambda time_zone, _now=None: now_date
            if time_zone == "UTC"
            else date(2026, 7, 13)
        ),
    )
    user_id, food_id, serving_id = _gh271_daily_log_target(
        factory,
        "GH-271 Calendar Replay",
    )
    request_id = uuid4()

    def payload(client_request_id=request_id, quantity: str = "1") -> DailyLogCreateRequest:
        return DailyLogCreateRequest(
            client_request_id=client_request_id,
            calendar_revision=0,
            food_item_id=food_id,
            logged_date=logged_date,
            amount_quantity=Decimal(quantity),
            amount_unit="serving",
            serving_definition_id=serving_id,
        )

    with factory() as db:
        original = LogService(db).create_log(user_id, payload())
        original_result = _create_result_snapshot(original)
        LogDayCompletionService(db).mark_complete(
            user_id,
            DailyLogCompleteRequest(
                client_request_id=uuid4(),
                calendar_revision=0,
                logged_date=logged_date,
            ),
        )
        calendar = CalendarService(db)
        preview = calendar.preview_change(user_id, "Pacific/Pago_Pago")
        changed = calendar.confirm_change(
            user_id,
            "Pacific/Pago_Pago",
            preview.calendar_revision,
            preview.preview_token,
        )
        assert changed.calendar_revision == 1

    with factory() as db:
        replay = LogService(db).create_log(user_id, payload())
        replay_result = _create_result_snapshot(replay)
        assert replay_result == original_result
        assert db.get(DailyLogDayCompletion, (user_id, logged_date)) is not None

        with pytest.raises(LogIdempotencyConflictError):
            LogService(db).create_log(user_id, payload(quantity="2"))
        with pytest.raises(CalendarDomainError) as stale_fresh:
            LogService(db).create_log(user_id, payload(client_request_id=uuid4()))
        assert stale_fresh.value.code == "calendar_context_changed"
        assert db.scalar(
            select(func.count()).select_from(DailyLog).where(DailyLog.user_id == user_id)
        ) == 1
        assert db.scalar(
            select(func.count())
            .select_from(DailyLogNutrientSnapshot)
            .join(DailyLog, DailyLog.id == DailyLogNutrientSnapshot.daily_log_id)
            .where(DailyLog.user_id == user_id)
        ) == len(original_result["snapshots"])
        assert db.get(DailyLogDayCompletion, (user_id, logged_date)) is not None


def test_postgres_daily_summary_reads_complete_and_snapshots_from_one_statement(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    logged_date = date(2026, 7, 13)
    with factory() as db:
        assert int(db.scalar(text("SHOW server_version_num"))) // 10000 == 16
        user_id, food_id, serving_id = _gh271_daily_log_target(
            factory,
            "GH-271 Coherent Summary",
        )
        created = LogService(db).create_log(
            user_id,
            DailyLogCreateRequest(
                client_request_id=uuid4(),
                calendar_revision=0,
                food_item_id=food_id,
                logged_date=logged_date,
                amount_quantity=Decimal("1"),
                amount_unit="serving",
                serving_definition_id=serving_id,
            ),
        )
        log_id = created.id
        LogDayCompletionService(db).mark_complete(
            user_id,
            DailyLogCompleteRequest(
                client_request_id=uuid4(),
                calendar_revision=0,
                logged_date=logged_date,
            ),
        )
        engine = db.get_bind()

    query_arrived = Event()
    release_query = Event()
    summary_thread_id: list[int] = []
    summary_statements: list[str] = []
    summary_results = []
    summary_errors: list[BaseException] = []

    def pause_summary_read(connection, cursor, statement, parameters, context, executemany):
        if (
            summary_thread_id
            and get_ident() == summary_thread_id[0]
            and "daily_log_day_completions" in statement.lower()
        ):
            summary_statements.append(statement)
            if len(summary_statements) == 1:
                query_arrived.set()
                if not release_query.wait(timeout=10):
                    raise AssertionError("summary statement barrier was not released")

    def read_summary() -> None:
        summary_thread_id.append(get_ident())
        try:
            with factory() as summary_db:
                user = summary_db.get(User, user_id)
                assert user is not None
                summary_results.append(
                    route_daily_summary(logged_date, summary_db, user)
                )
        except BaseException as exc:
            summary_errors.append(exc)

    worker = Thread(target=read_summary)
    event.listen(engine, "after_cursor_execute", pause_summary_read)
    try:
        worker.start()
        assert query_arrived.wait(timeout=10), "summary did not reach its statement barrier"

        with factory() as writer:
            log = writer.get(DailyLog, log_id)
            assert log is not None
            LogService(writer).update_log(
                user_id,
                log_id,
                DailyLogUpdateRequest(
                    client_request_id=uuid4(),
                    calendar_revision=0,
                    expected_updated_at=log.updated_at,
                    amount_quantity=Decimal("2"),
                ),
            )
    finally:
        release_query.set()
        if worker.ident is not None:
            worker.join(timeout=10)
        event.remove(engine, "after_cursor_execute", pause_summary_read)

    assert not worker.is_alive(), "summary worker did not settle after release"
    assert not summary_errors, summary_errors
    assert len(summary_results) == 1
    assert len(summary_statements) == 1
    assert "daily_log_nutrient_snapshots" in summary_statements[0].lower()

    observed = summary_results[0]
    observed_totals = {item.nutrient_id: item.amount_known for item in observed.totals}
    before_pair = (True, Decimal("10"))
    after_pair = (False, Decimal("20"))
    assert (observed.is_complete, observed_totals.get("protein")) in {
        before_pair,
        after_pair,
    }


def test_postgres_create_retry_waits_for_accepted_calendar_boundary_then_rechecks(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    user_id, food_id, serving_id = _gh271_daily_log_target(
        factory,
        "GH-271 Create Replay",
    )
    request_id = uuid4()
    logged_date = date(2026, 7, 13)

    def payload() -> DailyLogCreateRequest:
        return DailyLogCreateRequest(
            client_request_id=request_id,
            calendar_revision=0,
            food_item_id=food_id,
            logged_date=logged_date,
            amount_quantity=Decimal("1"),
            amount_unit="serving",
            serving_definition_id=serving_id,
        )

    original_snapshot_ready = Event()
    release_original = Event()
    retry_started = Event()
    retry_result = []
    original_result = []
    worker_errors: list[BaseException] = []
    retry_food_loaded = Event()
    retry_pid: list[int] = []

    def original_create() -> None:
        try:
            with factory() as db:
                service = LogService(db)

                def pause_before_commit(_created) -> None:
                    original_snapshot_ready.set()
                    if not release_original.wait(timeout=10):
                        raise AssertionError("original create barrier was not released")

                service._after_snapshot_creation = pause_before_commit
                created = service.create_log(user_id, payload())
                original_result.append(_create_result_snapshot(created))
        except BaseException as exc:
            worker_errors.append(exc)

    def retry_create() -> None:
        try:
            with factory() as db:
                retry_pid.append(int(db.scalar(text("SELECT pg_backend_pid()"))))
                retry_started.set()
                service = LogService(db)
                service._after_mutable_food_lock = lambda _food: retry_food_loaded.set()
                created = service.create_log(user_id, payload())
                retry_result.append(_create_result_snapshot(created))
        except BaseException as exc:
            worker_errors.append(exc)

    first_worker = Thread(target=original_create)
    retry_worker = Thread(target=retry_create)
    first_worker.start()
    assert original_snapshot_ready.wait(timeout=10), "original create did not reach its commit barrier"
    retry_worker.start()
    try:
        assert retry_started.wait(timeout=10), "retry worker did not start"

        deadline = time.monotonic() + 10
        waiting_on_owner_lock = False
        while time.monotonic() < deadline:
            with factory() as observer:
                waiting_on_owner_lock = bool(
                    observer.scalar(
                        text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                        {"pid": retry_pid[0]},
                    )
                )
            if waiting_on_owner_lock:
                break
            time.sleep(0.01)
        assert waiting_on_owner_lock, "retry did not wait behind the original owner/calendar lock"
    finally:
        release_original.set()
        first_worker.join(timeout=10)
        retry_worker.join(timeout=10)

    assert not first_worker.is_alive()
    assert not retry_worker.is_alive()
    assert not worker_errors, worker_errors
    assert len(original_result) == len(retry_result) == 1
    assert retry_result[0] == original_result[0]
    assert not retry_food_loaded.is_set()

    with factory() as db:
        assert db.scalar(
            select(func.count()).select_from(DailyLog).where(
                DailyLog.user_id == user_id,
                DailyLog.client_request_id == request_id,
            )
        ) == 1
        assert db.scalar(
            select(func.count())
            .select_from(DailyLogNutrientSnapshot)
            .where(
                DailyLogNutrientSnapshot.daily_log_id
                == UUID(original_result[0]["id"])
            )
        ) == len(original_result[0]["snapshots"])


def test_postgres_create_receipt_wait_replays_commit_and_rejects_changed_payload(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    user_id, food_id, serving_id = _gh271_daily_log_target(
        factory,
        "GH-277 Receipt Commit Wait",
    )
    request_id = uuid4()
    logged_date = date(2026, 7, 13)

    def payload(quantity: str = "1") -> DailyLogCreateRequest:
        return DailyLogCreateRequest(
            client_request_id=request_id,
            food_item_id=food_id,
            logged_date=logged_date,
            amount_quantity=Decimal(quantity),
            amount_unit="serving",
            serving_definition_id=serving_id,
        )

    reservation_ready = Event()
    release_winner = Event()
    retry_started = {"same": Event(), "changed": Event()}
    pids: dict[str, int] = {}
    outcomes: dict[str, list[object]] = {"winner": [], "same": [], "changed": []}

    def run_winner() -> None:
        try:
            with factory() as db:
                service = LogService(db)
                reserve = service.mutation_receipts.reserve

                def hold_reservation(
                    reserve_user_id,
                    operation,
                    client_request_id,
                    fingerprint,
                    resource_id,
                ):
                    receipt = reserve(
                        reserve_user_id,
                        operation,
                        client_request_id,
                        fingerprint,
                        resource_id,
                    )
                    if operation == "log.create":
                        reservation_ready.set()
                        if not release_winner.wait(timeout=10):
                            raise AssertionError("create reservation barrier was not released")
                    return receipt

                service.mutation_receipts.reserve = hold_reservation
                outcomes["winner"].append(_create_result_snapshot(service.create_log(user_id, payload())))
        except BaseException as exc:
            outcomes["winner"].append(exc)

    def run_duplicate(kind: str, quantity: str) -> None:
        try:
            with factory() as db:
                pids[kind] = int(db.scalar(text("SELECT pg_backend_pid()")))
                service = LogService(db)
                reserve = service.mutation_receipts.reserve

                def observe_reservation(
                    reserve_user_id,
                    operation,
                    client_request_id,
                    fingerprint,
                    resource_id,
                ):
                    if operation == "log.create":
                        retry_started[kind].set()
                    return reserve(
                        reserve_user_id,
                        operation,
                        client_request_id,
                        fingerprint,
                        resource_id,
                    )

                service.mutation_receipts.reserve = observe_reservation
                result = service.create_log(user_id, payload(quantity))
                outcomes[kind].append(_create_result_snapshot(result))
        except BaseException as exc:
            outcomes[kind].append(exc)

    winner = Thread(target=run_winner)
    same_retry = Thread(target=run_duplicate, args=("same", "1"))
    changed_retry = Thread(target=run_duplicate, args=("changed", "2"))
    winner.start()
    try:
        assert reservation_ready.wait(timeout=10), "winner did not flush its create receipt"
        same_retry.start()
        changed_retry.start()
        assert retry_started["same"].wait(timeout=10), "matching retry did not reach reservation"
        assert retry_started["changed"].wait(timeout=10), "changed retry did not reach reservation"

        blocked: dict[str, bool] = {"same": False, "changed": False}
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not all(blocked.values()):
            for kind in blocked:
                if blocked[kind]:
                    continue
                with factory() as observer:
                    blocked[kind] = bool(
                        observer.scalar(
                            text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                            {"pid": pids[kind]},
                        )
                    )
            if not all(blocked.values()):
                time.sleep(0.01)
        assert blocked == {"same": True, "changed": True}, (
            "duplicate sessions did not wait on the uncommitted unique create reservation"
        )
    finally:
        release_winner.set()
        winner.join(timeout=10)
        if same_retry.ident is not None:
            same_retry.join(timeout=10)
        if changed_retry.ident is not None:
            changed_retry.join(timeout=10)

    assert not winner.is_alive()
    assert not same_retry.is_alive()
    assert not changed_retry.is_alive()
    assert len(outcomes["winner"]) == 1
    assert len(outcomes["same"]) == 1
    assert len(outcomes["changed"]) == 1
    assert isinstance(outcomes["winner"][0], dict)
    assert outcomes["same"][0] == outcomes["winner"][0]
    assert isinstance(outcomes["changed"][0], LogIdempotencyConflictError)

    with factory() as db:
        receipt = db.scalar(
            select(CreateOperationIdempotency).where(
                CreateOperationIdempotency.user_id == user_id,
                CreateOperationIdempotency.operation == "log.create",
                CreateOperationIdempotency.client_request_id == request_id,
            )
        )
        assert receipt is not None
        assert receipt.resource_id == UUID(outcomes["winner"][0]["id"])
        assert receipt.response_snapshot == outcomes["winner"][0]
        assert receipt.completed_at is not None
        assert db.scalar(
            select(func.count()).select_from(DailyLog).where(DailyLog.user_id == user_id)
        ) == 1
        assert db.scalar(
            select(func.count())
            .select_from(DailyLogNutrientSnapshot)
            .join(DailyLog, DailyLog.id == DailyLogNutrientSnapshot.daily_log_id)
            .where(DailyLog.user_id == user_id)
        ) == len(outcomes["winner"][0]["snapshots"])


def test_postgres_rolled_back_create_reservation_releases_one_valid_retry(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    user_id, food_id, serving_id = _gh271_daily_log_target(
        factory,
        "GH-277 Receipt Rollback Wait",
    )
    request_id = uuid4()
    payload = DailyLogCreateRequest(
        client_request_id=request_id,
        food_item_id=food_id,
        logged_date=date(2026, 7, 13),
        amount_quantity=Decimal("1"),
        amount_unit="serving",
        serving_definition_id=serving_id,
    )
    reservation_ready = Event()
    release_winner = Event()
    retry_started = Event()
    retry_pid: list[int] = []
    winner_outcome: list[BaseException] = []
    retry_outcome: list[object] = []

    def rollback_winner() -> None:
        try:
            with factory() as db:
                service = LogService(db)
                reserve = service.mutation_receipts.reserve

                def hold_reservation(
                    reserve_user_id,
                    operation,
                    client_request_id,
                    fingerprint,
                    resource_id,
                ):
                    receipt = reserve(
                        reserve_user_id,
                        operation,
                        client_request_id,
                        fingerprint,
                        resource_id,
                    )
                    if operation == "log.create":
                        reservation_ready.set()
                        if not release_winner.wait(timeout=10):
                            raise AssertionError("rollback reservation barrier was not released")
                    return receipt

                service.mutation_receipts.reserve = hold_reservation
                service._after_snapshot_creation = lambda _log: (_ for _ in ()).throw(
                    RuntimeError("injected winner rollback")
                )
                service.create_log(user_id, payload)
        except BaseException as exc:
            winner_outcome.append(exc)

    def retry_create() -> None:
        try:
            with factory() as db:
                retry_pid.append(int(db.scalar(text("SELECT pg_backend_pid()"))))
                service = LogService(db)
                reserve = service.mutation_receipts.reserve

                def observe_reservation(
                    reserve_user_id,
                    operation,
                    client_request_id,
                    fingerprint,
                    resource_id,
                ):
                    if operation == "log.create":
                        retry_started.set()
                    return reserve(
                        reserve_user_id,
                        operation,
                        client_request_id,
                        fingerprint,
                        resource_id,
                    )

                service.mutation_receipts.reserve = observe_reservation
                retry_outcome.append(_create_result_snapshot(service.create_log(user_id, payload)))
        except BaseException as exc:
            retry_outcome.append(exc)

    first = Thread(target=rollback_winner)
    second = Thread(target=retry_create)
    first.start()
    try:
        assert reservation_ready.wait(timeout=10), "first writer did not flush its receipt"
        second.start()
        assert retry_started.wait(timeout=10), "retry did not reach reservation"
        deadline = time.monotonic() + 10
        waiting = False
        while time.monotonic() < deadline:
            with factory() as observer:
                waiting = bool(
                    observer.scalar(
                        text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                        {"pid": retry_pid[0]},
                    )
                )
            if waiting:
                break
            time.sleep(0.01)
        assert waiting, "retry did not wait on the uncommitted create reservation"
    finally:
        release_winner.set()
        first.join(timeout=10)
        if second.ident is not None:
            second.join(timeout=10)

    assert not first.is_alive()
    assert not second.is_alive()
    assert len(winner_outcome) == 1
    assert isinstance(winner_outcome[0], RuntimeError)
    assert str(winner_outcome[0]) == "injected winner rollback"
    assert len(retry_outcome) == 1
    assert isinstance(retry_outcome[0], dict)

    with factory() as db:
        receipt = db.scalar(
            select(CreateOperationIdempotency).where(
                CreateOperationIdempotency.user_id == user_id,
                CreateOperationIdempotency.operation == "log.create",
                CreateOperationIdempotency.client_request_id == request_id,
            )
        )
        assert receipt is not None
        assert receipt.response_snapshot == retry_outcome[0]
        assert receipt.resource_id == UUID(retry_outcome[0]["id"])
        assert db.scalar(
            select(func.count()).select_from(DailyLog).where(DailyLog.user_id == user_id)
        ) == 1
        assert db.scalar(
            select(func.count())
            .select_from(DailyLogNutrientSnapshot)
            .join(DailyLog, DailyLog.id == DailyLogNutrientSnapshot.daily_log_id)
            .where(DailyLog.user_id == user_id)
        ) == len(retry_outcome[0]["snapshots"])


def test_postgres_create_receipt_log_and_complete_failures_roll_back_atomically(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    user_id, food_id, serving_id = _gh271_daily_log_target(
        factory,
        "GH-277 Receipt Atomicity",
    )
    logged_date = date(2026, 7, 13)
    with factory() as db:
        anchor = LogService(db).create_log(
            user_id,
            DailyLogCreateRequest(
                food_item_id=food_id,
                logged_date=logged_date,
                amount_quantity=Decimal("1"),
                amount_unit="serving",
                serving_definition_id=serving_id,
            ),
        )
        anchor_id = anchor.id
        anchor_snapshot_count = len(anchor.snapshots)
        LogDayCompletionService(db).mark_complete(
            user_id,
            DailyLogCompleteRequest(
                client_request_id=uuid4(),
                calendar_revision=0,
                logged_date=logged_date,
            ),
        )

    class FailAfterCompleteInvalidation(LogService):
        def _after_complete_invalidation(self, _logged_dates: set[date]) -> None:
            raise RuntimeError("injected failure after Complete invalidation")

    failure_modes = ("after_snapshots", "after_receipt_completion", "after_complete_invalidation")
    for failure_mode in failure_modes:
        request_id = uuid4()
        payload = DailyLogCreateRequest(
            client_request_id=request_id,
            calendar_revision=0,
            food_item_id=food_id,
            logged_date=logged_date,
            amount_quantity=Decimal("1"),
            amount_unit="serving",
            serving_definition_id=serving_id,
        )
        with factory() as db:
            if failure_mode == "after_complete_invalidation":
                service = FailAfterCompleteInvalidation(db)
            else:
                service = LogService(db)
            if failure_mode == "after_snapshots":
                service._after_snapshot_creation = lambda _log: (_ for _ in ()).throw(
                    RuntimeError("injected failure after snapshots")
                )
            elif failure_mode == "after_receipt_completion":
                complete = service.mutation_receipts.complete

                def fail_after_receipt_completion(receipt, response_snapshot):
                    complete(receipt, response_snapshot)
                    raise RuntimeError("injected failure after receipt completion")

                service.mutation_receipts.complete = fail_after_receipt_completion

            expected_message = {
                "after_snapshots": "injected failure after snapshots",
                "after_receipt_completion": "injected failure after receipt completion",
                "after_complete_invalidation": "injected failure after Complete invalidation",
            }[failure_mode]
            with pytest.raises(RuntimeError, match=expected_message):
                service.create_log(user_id, payload)

        with factory() as db:
            assert db.get(DailyLog, anchor_id) is not None
            assert db.get(DailyLogDayCompletion, (user_id, logged_date)) is not None
            assert db.scalar(
                select(CreateOperationIdempotency).where(
                    CreateOperationIdempotency.user_id == user_id,
                    CreateOperationIdempotency.operation == "log.create",
                    CreateOperationIdempotency.client_request_id == request_id,
                )
            ) is None
            assert db.scalar(
                select(func.count())
                .select_from(DailyLog)
                .where(DailyLog.user_id == user_id, DailyLog.logged_date == logged_date)
            ) == 1
            assert db.scalar(
                select(func.count())
                .select_from(DailyLogNutrientSnapshot)
                .where(DailyLogNutrientSnapshot.daily_log_id == anchor_id)
            ) == anchor_snapshot_count


@pytest.mark.parametrize("post_commit_mutation", ["food_deleted", "log_edited", "log_deleted"])
def test_postgres_first_create_response_uses_committed_snapshot_after_mutation(
    postgres_sessions,
    monkeypatch,
    post_commit_mutation: str,
) -> None:
    """The first API response must use the committed receipt after source/Log changes."""
    factory = postgres_sessions
    user_id, food_id, serving_id = _gh271_daily_log_target(
        factory,
        f"GH-277 first response {post_commit_mutation}",
    )
    request_id = uuid4()
    payload = {
        "client_request_id": str(request_id),
        "food_item_id": str(food_id),
        "logged_date": "2026-10-09",
        "amount_quantity": "1.25",
        "amount_unit": "serving",
        "serving_definition_id": str(serving_id),
        "meal_type": "lunch",
        "notes": "accepted response",
    }
    pause_after_commit_key = "gh277_pause_after_real_create_commit"
    real_commit_finished = Event()
    release_projection = Event()
    original_commit = OrmSession.commit

    def commit_then_pause_after_real_commit(session: OrmSession) -> None:
        original_commit(session)
        if session.info.pop(pause_after_commit_key, False):
            real_commit_finished.set()
            if not release_projection.wait(timeout=30):
                raise RuntimeError("timed out waiting to release first-response projection")

    monkeypatch.setattr(OrmSession, "commit", commit_then_pause_after_real_commit)
    previous_overrides = app.dependency_overrides.copy()
    initial_request_session_marked = False

    def override_get_db():
        nonlocal initial_request_session_marked
        db = factory()
        try:
            if not initial_request_session_marked:
                db.info[pause_after_commit_key] = True
                initial_request_session_marked = True
            yield db
        finally:
            db.close()

    def override_current_user() -> User:
        return User(id=user_id, email=f"gh277-{user_id}@example.test")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    first_responses = []
    first_request_errors = []

    def post_first_create() -> None:
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                first_responses.append(client.post("/api/v1/logs", json=payload))
        except Exception as exc:  # surfaced separately from response assertions below
            first_request_errors.append(exc)

    first_request = Thread(target=post_first_create, name="gh277-first-create-response")
    try:
        first_request.start()
        try:
            assert real_commit_finished.wait(timeout=20), (
                "first create did not reach the post-real-commit barrier"
            )
            with factory() as db:
                receipt = db.scalar(
                    select(CreateOperationIdempotency).where(
                        CreateOperationIdempotency.user_id == user_id,
                        CreateOperationIdempotency.operation == "log.create",
                        CreateOperationIdempotency.client_request_id == request_id,
                    )
                )
                assert receipt is not None
                assert receipt.completed_at is not None
                accepted_snapshot = deepcopy(receipt.response_snapshot)
                resource_id = receipt.resource_id
                assert accepted_snapshot["id"] == str(resource_id)
                assert db.get(DailyLog, resource_id) is not None

            with factory() as db:
                if post_commit_mutation == "food_deleted":
                    FoodService(db).soft_delete_food(user_id, food_id)
                elif post_commit_mutation == "log_edited":
                    LogService(db).update_log(
                        user_id,
                        resource_id,
                        DailyLogUpdateRequest(notes="independent post-commit edit"),
                    )
                else:
                    LogService(db).delete_log(user_id, resource_id)

            with factory() as db:
                if post_commit_mutation == "food_deleted":
                    food = db.get(FoodItem, food_id)
                    assert food is not None and food.deleted_at is not None
                elif post_commit_mutation == "log_edited":
                    edited = db.get(DailyLog, resource_id)
                    assert edited is not None
                    assert edited.notes == "independent post-commit edit"
                else:
                    assert db.get(DailyLog, resource_id) is None
                logs_after_mutation = db.scalar(
                    select(func.count()).select_from(DailyLog).where(DailyLog.id == resource_id)
                )
                snapshots_after_mutation = db.scalar(
                    select(func.count())
                    .select_from(DailyLogNutrientSnapshot)
                    .where(DailyLogNutrientSnapshot.daily_log_id == resource_id)
                )
        finally:
            release_projection.set()
            first_request.join(timeout=20)

        assert not first_request.is_alive(), "first create response thread did not finish"
        assert not first_request_errors, f"first API request raised: {first_request_errors!r}"
        assert len(first_responses) == 1, "first API request did not produce exactly one response"
        first_response = first_responses[0]
        try:
            first_body = first_response.json()
        except ValueError:
            first_body = None

        with TestClient(app, raise_server_exceptions=False) as client:
            replay_response = client.post("/api/v1/logs", json=payload)
        try:
            replay_body = replay_response.json()
        except ValueError:
            replay_body = None

        with factory() as db:
            retained_receipt = db.scalar(
                select(CreateOperationIdempotency).where(
                    CreateOperationIdempotency.user_id == user_id,
                    CreateOperationIdempotency.operation == "log.create",
                    CreateOperationIdempotency.client_request_id == request_id,
                )
            )
            assert retained_receipt is not None
            final_snapshot = deepcopy(retained_receipt.response_snapshot)
            final_resource_id = retained_receipt.resource_id
            receipt_count = db.scalar(
                select(func.count())
                .select_from(CreateOperationIdempotency)
                .where(
                    CreateOperationIdempotency.user_id == user_id,
                    CreateOperationIdempotency.operation == "log.create",
                    CreateOperationIdempotency.client_request_id == request_id,
                )
            )
            logs_after_replay = db.scalar(
                select(func.count()).select_from(DailyLog).where(DailyLog.id == resource_id)
            )
            snapshots_after_replay = db.scalar(
                select(func.count())
                .select_from(DailyLogNutrientSnapshot)
                .where(DailyLogNutrientSnapshot.daily_log_id == resource_id)
            )

        checks = {
            "first_status_is_201": first_response.status_code == 201,
            "first_body_matches_accepted_receipt": first_body == accepted_snapshot,
            "replay_status_is_201": replay_response.status_code == 201,
            "replay_body_matches_accepted_receipt": replay_body == accepted_snapshot,
            "first_body_matches_replay": first_body == replay_body,
            "receipt_snapshot_is_unchanged": final_snapshot == accepted_snapshot,
            "resource_uuid_is_unchanged": final_resource_id == resource_id,
            "exactly_one_create_receipt_remains": receipt_count == 1,
            "replay_did_not_change_log_count": logs_after_replay == logs_after_mutation,
            "replay_did_not_change_snapshot_count": (
                snapshots_after_replay == snapshots_after_mutation
            ),
        }
        assert all(checks.values()), (
            f"post-commit mutation {post_commit_mutation!r} violated the retained first response; "
            f"checks={checks!r}, first_status={first_response.status_code}, "
            f"first_body={first_body!r}, replay_status={replay_response.status_code}, "
            f"replay_body={replay_body!r}"
        )
    finally:
        release_projection.set()
        if first_request.is_alive():
            first_request.join(timeout=20)
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


def _read_gh278_status_http(
    *,
    request_id: UUID,
    operation: str,
    response_holder: list,
    error_holder: list,
    returned: Event,
) -> Thread:
    def request_status() -> None:
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response_holder.append(
                    client.get(
                        f"/api/v1/logs/mutations/{request_id}",
                        params={"operation": operation},
                    )
                )
        except BaseException as exc:  # the caller re-raises after its bounded wait
            error_holder.append(exc)
        finally:
            returned.set()

    thread = Thread(target=request_status, name=f"gh278-status-{operation}", daemon=True)
    thread.start()
    return thread


def _record_gh278_status_trace(trace: dict) -> None:
    output_path = os.environ.get("GH278_STATUS_TRACE_PATH")
    if output_path is None:
        return
    path = Path(output_path)
    assert path.is_absolute(), "GH278_STATUS_TRACE_PATH must be an absolute external path"
    assert path.parent.is_dir(), "GH278 status trace parent directory must already exist"
    with path.open("a", encoding="utf-8") as evidence:
        evidence.write(json.dumps(trace, sort_keys=True, separators=(",", ":")))
        evidence.write("\n")


def _exercise_gh278_held_log_status(
    *,
    factory,
    user_id: UUID,
    request_id: UUID,
    operation: str,
    mutation,
    source_date: date,
    destination_date: date | None,
    request_payload: dict,
    initial_notes: str | None = None,
    rollback: bool = False,
) -> None:
    """Read the real status route from another PostgreSQL session around commit/rollback."""

    ready_to_commit = Event()
    release_commit = Event()
    writer_backend_pid: list[int] = []
    writer_resource_id: list[UUID] = []
    writer_results: list = []
    writer_errors: list[BaseException] = []
    reader_backend_pids: list[int] = []
    reader_threads: list[Thread] = []
    response_sequence: list = []
    returned_before_release: list[bool] = []
    previous_overrides = app.dependency_overrides.copy()

    def override_get_db():
        db = factory()
        try:
            reader_backend_pids.append(int(db.scalar(text("SELECT pg_backend_pid()"))))
            yield db
        finally:
            db.close()

    def override_current_user() -> User:
        return User(id=user_id, email=f"gh278-status-{user_id}@example.test")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    def run_mutation() -> None:
        try:
            with factory() as db:
                real_commit = db.commit

                def flush_then_hold_commit() -> None:
                    db.flush()
                    receipt = db.scalar(
                        select(CreateOperationIdempotency).where(
                            CreateOperationIdempotency.user_id == user_id,
                            CreateOperationIdempotency.operation == f"log.{operation}",
                            CreateOperationIdempotency.client_request_id == request_id,
                        )
                    )
                    assert receipt is not None
                    assert receipt.response_snapshot is not None
                    assert receipt.completed_at is not None
                    writer_resource_id.append(receipt.resource_id)
                    if operation in {"create", "update"}:
                        log = db.get(DailyLog, receipt.resource_id)
                        assert log is not None
                        if operation == "update":
                            assert log.notes == "GH-278 held update"
                    elif operation == "delete":
                        assert db.get(DailyLog, receipt.resource_id) is None
                    writer_backend_pid.append(int(db.scalar(text("SELECT pg_backend_pid()"))))
                    ready_to_commit.set()
                    if not release_commit.wait(timeout=15):
                        raise TimeoutError("timed out waiting for GH-278 commit release")
                    if rollback:
                        db.rollback()
                        raise RuntimeError("GH-278 injected rollback after flushed mutation")
                    real_commit()

                db.commit = flush_then_hold_commit
                writer_results.append(mutation(db))
        except BaseException as exc:  # surfaced by the assertions below
            writer_errors.append(exc)

    writer = Thread(target=run_mutation, name=f"gh278-writer-{operation}", daemon=True)
    writer_started = False

    def read_status(*, expect_before_release: bool = True) -> object:
        response_holder: list = []
        error_holder: list[BaseException] = []
        returned = Event()
        reader = _read_gh278_status_http(
            request_id=request_id,
            operation=operation,
            response_holder=response_holder,
            error_holder=error_holder,
            returned=returned,
        )
        reader_threads.append(reader)
        assert returned.wait(timeout=5), (
            f"{operation} status HTTP request did not return within the held-writer bound"
        )
        reader.join(timeout=1)
        assert not reader.is_alive(), f"{operation} status HTTP thread did not join"
        assert not error_holder, f"{operation} status HTTP request raised: {error_holder!r}"
        assert len(response_holder) == 1
        assert release_commit.is_set() is (not expect_before_release), (
            "status return ordering did not match the writer barrier"
        )
        returned_before_release.append(not release_commit.is_set())
        return response_holder[0]

    try:
        with TestClient(app, raise_server_exceptions=False):
            writer.start()
            writer_started = True
            if not ready_to_commit.wait(timeout=15):
                raise AssertionError(
                    f"{operation} writer did not flush receipt/domain work before the barrier; "
                    f"writer_errors={writer_errors!r}"
                )
            assert len(writer_backend_pid) == 1

            for _ in range(2):
                response = read_status()
                assert response.status_code == 200, response.text
                assert response.json()["operation"] == operation
                assert response.json()["client_request_id"] == str(request_id)
                assert response.json()["status"] == "unresolved", response.text
                response_sequence.append(
                    {"status_code": response.status_code, "body": response.text}
                )

            release_commit.set()
            writer.join(timeout=15)
            assert not writer.is_alive(), f"{operation} writer did not join after release"

            if rollback:
                assert len(writer_errors) == 1
                assert isinstance(writer_errors[0], RuntimeError)
                assert "GH-278 injected rollback" in str(writer_errors[0])
                with factory() as db:
                    assert db.scalar(
                        select(func.count()).select_from(CreateOperationIdempotency).where(
                            CreateOperationIdempotency.user_id == user_id,
                            CreateOperationIdempotency.operation == f"log.{operation}",
                            CreateOperationIdempotency.client_request_id == request_id,
                        )
                    ) == 0
                    if operation == "create":
                        assert db.get(DailyLog, writer_resource_id[0]) is None
                    elif operation == "update":
                        rolled_back_log = db.get(DailyLog, writer_resource_id[0])
                        assert rolled_back_log is not None
                        assert rolled_back_log.notes == initial_notes
                    else:
                        assert db.get(DailyLog, writer_resource_id[0]) is not None
                final_response = read_status(expect_before_release=False)
                assert final_response.status_code == 200, final_response.text
                assert final_response.json()["status"] == "unresolved", final_response.text
                response_sequence.append(
                    {"status_code": final_response.status_code, "body": final_response.text}
                )
            else:
                assert not writer_errors, f"{operation} mutation failed: {writer_errors!r}"
                assert len(writer_results) == 1
                final_response = read_status(expect_before_release=False)
                assert final_response.status_code == 200, final_response.text
                assert final_response.json()["operation"] == operation
                assert final_response.json()["client_request_id"] == str(request_id)
                assert final_response.json()["status"] == "confirmed_success", final_response.text
                response_sequence.append(
                    {"status_code": final_response.status_code, "body": final_response.text}
                )

            assert returned_before_release[:2] == [True, True]
            assert len(reader_backend_pids) >= 2
            assert all(pid != writer_backend_pid[0] for pid in reader_backend_pids[:2])
            assert response_sequence[0]["status_code"] == 200
            if not rollback:
                assert [item["status_code"] for item in response_sequence] == [200, 200, 200]

            _record_gh278_status_trace(
                {
                    "schema_version": 1,
                    "operation": operation,
                    "client_request_id": str(request_id),
                    "owner_id": str(user_id),
                    "settlement": "rolled_back" if rollback else "committed",
                    "source_date": source_date.isoformat(),
                    "destination_date": (
                        destination_date.isoformat() if destination_date is not None else None
                    ),
                    "request_payload": request_payload,
                    "writer_backend_pid": writer_backend_pid[0],
                    "reader_backend_pids": reader_backend_pids,
                    "returned_before_release": returned_before_release,
                    "status_responses": response_sequence,
                }
            )
    finally:
        release_commit.set()
        if writer_started:
            writer.join(timeout=15)
        for reader in reader_threads:
            reader.join(timeout=10)
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
        assert not writer.is_alive(), f"{operation} writer remained alive after unconditional release"
        assert all(not reader.is_alive() for reader in reader_threads), (
            f"{operation} status reader remained alive after writer release"
        )


@pytest.mark.parametrize("operation", ["create", "update", "delete"])
def test_postgres_status_stays_unresolved_during_real_log_mutation_then_confirms(
    postgres_sessions,
    operation: str,
) -> None:
    factory = postgres_sessions
    request_id = uuid4()
    if operation == "create":
        user_id, food_id, serving_id = _gh271_daily_log_target(
            factory,
            "GH-278 held create",
        )
        source_date = date(2026, 7, 14)
        payload = DailyLogCreateRequest(
            client_request_id=request_id,
            food_item_id=food_id,
            logged_date=source_date,
            amount_quantity=Decimal("1"),
            amount_unit="serving",
            serving_definition_id=serving_id,
        )
        def mutation(db: OrmSession):
            return LogService(db).create_log(user_id, payload)

        log_id = None
        destination_date = None
        initial_notes = None
    else:
        user_id, log_id = _manual_log(factory)
        source_date = date(2026, 7, 13)
        initial_notes = None
        if operation == "update":
            destination_date = date(2026, 7, 14)
            expected_updated_at = _log_updated_at(factory, log_id)
            payload = DailyLogUpdateRequest(
                client_request_id=request_id,
                expected_updated_at=expected_updated_at,
                logged_date=destination_date,
                notes="GH-278 held update",
            )
            def mutation(db: OrmSession):
                return LogService(db).update_log(user_id, log_id, payload)

        else:
            destination_date = None
            expected_updated_at = _log_updated_at(factory, log_id)
            payload = DailyLogDeleteRequest(
                client_request_id=request_id,
                expected_updated_at=expected_updated_at,
            )
            def mutation(db: OrmSession):
                return LogService(db).delete_log(user_id, log_id, payload)


    _exercise_gh278_held_log_status(
        factory=factory,
        user_id=user_id,
        request_id=request_id,
        operation=operation,
        mutation=mutation,
        source_date=source_date,
        destination_date=destination_date,
        request_payload=(
            payload.model_dump(mode="json", exclude_unset=True)
            | ({"log_id": str(log_id)} if log_id is not None else {})
        ),
        initial_notes=initial_notes,
    )


@pytest.mark.parametrize("operation", ["create", "update", "delete"])
def test_postgres_status_stays_unresolved_during_and_after_real_log_rollback(
    postgres_sessions,
    operation: str,
) -> None:
    factory = postgres_sessions
    request_id = uuid4()
    if operation == "create":
        user_id, food_id, serving_id = _gh271_daily_log_target(
            factory,
            "GH-278 rollback create",
        )
        source_date = date(2026, 7, 14)
        payload = DailyLogCreateRequest(
            client_request_id=request_id,
            food_item_id=food_id,
            logged_date=source_date,
            amount_quantity=Decimal("1"),
            amount_unit="serving",
            serving_definition_id=serving_id,
        )
        def mutation(db: OrmSession):
            return LogService(db).create_log(user_id, payload)

        log_id = None
        destination_date = None
        initial_notes = None
    else:
        user_id, log_id = _manual_log(factory)
        source_date = date(2026, 7, 13)
        initial_notes = None
        expected_updated_at = _log_updated_at(factory, log_id)
        if operation == "update":
            destination_date = date(2026, 7, 14)
            payload = DailyLogUpdateRequest(
                client_request_id=request_id,
                expected_updated_at=expected_updated_at,
                logged_date=destination_date,
                notes="GH-278 held update",
            )
            def mutation(db: OrmSession):
                return LogService(db).update_log(user_id, log_id, payload)

        else:
            destination_date = None
            payload = DailyLogDeleteRequest(
                client_request_id=request_id,
                expected_updated_at=expected_updated_at,
            )
            def mutation(db: OrmSession):
                return LogService(db).delete_log(user_id, log_id, payload)


    _exercise_gh278_held_log_status(
        factory=factory,
        user_id=user_id,
        request_id=request_id,
        operation=operation,
        mutation=mutation,
        source_date=source_date,
        destination_date=destination_date,
        request_payload=(
            payload.model_dump(mode="json", exclude_unset=True)
            | ({"log_id": str(log_id)} if log_id is not None else {})
        ),
        initial_notes=initial_notes,
        rollback=True,
    )
