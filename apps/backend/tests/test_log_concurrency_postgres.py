from __future__ import annotations

from datetime import date
from decimal import Decimal
from importlib import import_module
import os
from threading import Event, Thread
from uuid import uuid4

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import MetaData, create_engine, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401
from app.catalog.nutrients import nutrient_seed_rows
from app.core.database import Base
from app.models.food import FoodFavorite, FoodItem, FoodNutrient, ServingDefinition
from app.models.create_idempotency import CreateOperationIdempotency
from app.models.food import OcrNutritionConfirmationTrace
from app.models.log import DailyLog
from app.models.nutrient import Nutrient
from app.models.recipe import Recipe, RecipeIngredient
from app.models.recipe_publication import RecipePublicationRevision
from app.models.user import User
from app.models.target import NutritionTarget
from app.publication.recipe_revision import (
    PublishedAmountContent,
    PublishedNutrientContent,
    RecipePublicationContent,
    apply_revision_to_projection,
    build_revision,
)
from app.ocr.confirmation_schemas import OcrNutritionConfirmationRequest
from app.ocr.confirmation_service import OcrConfirmationService
from app.schemas.log import DailyLogCreateRequest, DailyLogUpdateRequest
from app.schemas.food import FoodCreateRequest, FoodUpdateRequest, ServingDefinitionInput
from app.schemas.recipe import RecipeCreateRequest, RecipeUpdateRequest
from app.services.log_service import LogService
from app.services.food_service import FoodService
from app.services.recipe_service import RecipeGraphCycleError, RecipeService
from app.services.create_idempotency import (
    CreateIdempotencyCoordinator,
    CreateOperationIdempotencyConflictError,
    CreateOperationResultUnavailableError,
)


pytestmark = pytest.mark.postgres_concurrency
POSTGRES_URL = os.getenv(
    "NUTRITION_TEST_POSTGRES_URL",
    "postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app",
)
idempotency_migration = import_module(
    "app.migrations.versions.0009_log_creation_idempotency"
)
integrity_migration = import_module(
    "app.migrations.versions.0013_food_recipe_dependency_integrity"
)


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
    admin = create_engine(POSTGRES_URL, pool_pre_ping=True)
    try:
        with admin.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - depends on developer environment.
        pytest.skip(f"PostgreSQL concurrency database unavailable: {exc}")
    schema = f"test_phase3n_{uuid4().hex}"
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        POSTGRES_URL,
        connect_args={"options": f"-csearch_path={schema}"},
        pool_pre_ping=True,
    )
    isolated_metadata = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(isolated_metadata)
    isolated_metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    try:
        with factory() as db:
            db.add_all([Nutrient(**row) for row in nutrient_seed_rows()])
            db.commit()
        yield factory
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _revision_log(factory) -> tuple:
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
        db.commit()
        serving_id = next(row.id for row in projection.serving_definitions if row.is_default)
        log = LogService(db).create_log(
            user.id,
            DailyLogCreateRequest(
                food_item_id=projection.id,
                logged_date=date(2026, 7, 13),
                amount_quantity=Decimal("1"),
                amount_unit="serving",
                serving_definition_id=serving_id,
            ),
        )
        return user.id, log.id


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
        db.commit()
        return user.id, food.id, serving.id


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
    user_id, recipe_a, food_a, serving_a, recipe_b, food_b, serving_b = (
        _published_recipe_pair(factory)
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
    user_id, recipe_a, food_a, serving_a, recipe_b, food_b, serving_b = (
        _published_recipe_pair(factory)
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
    user_id, recipe_a, _food_a, _serving_a, recipe_b, food_b, serving_b = (
        _published_recipe_pair(factory)
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
    user_id, recipe_a, food_a, serving_a, recipe_b, food_b, serving_b = (
        _published_recipe_pair(factory)
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
    locked, release = Event(), Event()
    log_result: list[object] = []
    update_result: list[object] = []

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
                            logged_date=date(2026, 7, 14),
                            amount_quantity=Decimal("1"),
                            amount_unit="serving",
                            serving_definition_id=serving_id,
                        ),
                    ).id
                )
            except Exception as exc:
                log_result.append(exc)

    def update_food() -> None:
        with factory() as db:
            try:
                FoodService(db).update_food(
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
    Event().wait(0.2)
    assert not update_result
    release.set()
    logger.join(5)
    updater.join(5)

    assert len(log_result) == len(update_result) == 1
    assert update_result == ["committed"]
    with factory() as db:
        log = db.get(DailyLog, log_result[0])
        assert log.snapshots[0].amount == Decimal("100.000000")
        food = db.get(FoodItem, food_id)
        assert food.nutrients[0].amount == Decimal("200.000000")


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
                FoodService(db).update_food(second_user, second_food, FoodUpdateRequest(name="Second"))
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
            "parser_version": "nutrition_label_v1",
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
                    OcrNutritionConfirmationTrace.client_request_id
                    == payload.client_request_id,
                )
            )
        )
        assert len(traces) == 1
        assert db.scalar(
            select(func.count()).select_from(FoodItem).where(FoodItem.user_id == user_id)
        ) == 1


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
            id=uuid4(), user_id=user.id, name="Concurrent favorite", source_type="manual",
            source_id=None, is_recipe=False,
        )
        other_food = FoodItem(
            id=uuid4(), user_id=other.id, name="Independent favorite", source_type="manual",
            source_id=None, is_recipe=False,
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
        assert db.scalar(
            select(func.count()).select_from(FoodFavorite).where(
                FoodFavorite.user_id == user_id,
                FoodFavorite.food_item_id == food_id,
            )
        ) == 1
        independent = FoodService(db).set_favorite(
            other_user_id, other_food_id, favorite=True
        )
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


def _run_update(factory, user_id, log_id, payload, *, locked=None, release=None, fail=False, result=None):
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
        assert calories.amount_known == (daily_total if daily_total is not None else snapshot.amount)


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


def test_deleted_projection_revision_log_updates_are_serialized(postgres_sessions) -> None:
    factory = postgres_sessions
    user_id, log_id = _revision_log(factory)
    with factory() as db:
        log = db.get(DailyLog, log_id)
        log.food_item.deleted_at = log.updated_at
        db.commit()
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
        args=(factory, user_id, log_id, {"amount_quantity": Decimal("6")}),
    )
    second.start()
    release.set()
    first.join(5)
    second.join(5)
    _assert_coherent(factory, user_id, log_id, Decimal("6"))


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
                    FoodService(db).create_manual_food(
                        user_id, _idempotent_food_payload(request_id)
                    ).id
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
        assert db.scalar(
            select(func.count(FoodItem.id)).where(FoodItem.user_id == user_id)
        ) == 1
        assert db.scalar(
            select(func.count(CreateOperationIdempotency.id)).where(
                CreateOperationIdempotency.user_id == user_id
            )
        ) == 1


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
                FoodService(db).create_manual_food(
                    user_id, _idempotent_food_payload(request_id)
                ).id
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
        assert db.scalar(
            select(func.count(FoodItem.id)).where(FoodItem.user_id == user_id)
        ) == 1
        assert db.scalar(
            select(func.count(CreateOperationIdempotency.id)).where(
                CreateOperationIdempotency.user_id == user_id
            )
        ) == 1


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
        assert db.scalar(
            select(func.count(RecipePublicationRevision.id)).where(
                RecipePublicationRevision.recipe_id == recipe_id
            )
        ) == 1


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
        original = FoodService(db).create_manual_food(
            user_id, _idempotent_food_payload(request_id)
        )
        original_id = original.id
    with factory() as db:
        FoodService(db).soft_delete_food(user_id, original_id)
    with factory() as db:
        with pytest.raises(CreateOperationResultUnavailableError):
            FoodService(db).create_manual_food(
                user_id, _idempotent_food_payload(request_id)
            )
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
            service.create_manual_food(
                user_id, _idempotent_food_payload(unrelated_request)
            )
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
            service.create_manual_food(
                user_id, _idempotent_food_payload(completion_request)
            )

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
