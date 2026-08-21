from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from os import getenv
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.models.create_idempotency import CreateOperationIdempotency
from app.models.food import FoodItem
from app.models.recipe import Recipe
from app.models.user import User
from app.schemas.food import FoodCreateRequest
from app.schemas.recipe import RecipeCreateRequest, RecipeIngredientInput
from app.services.food_service import FoodService
from app.services.recipe_service import RecipeService
from tests.postgres_test_support import isolated_postgres_session_factory


pytestmark = pytest.mark.postgres_concurrency

POSTGRES_URL = getenv(
    "NUTRITION_TEST_POSTGRES_URL",
    "postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app",
)


@pytest.fixture()
def postgres_sessions():
    with isolated_postgres_session_factory(
        database_url=POSTGRES_URL,
        schema_prefix="test_recipe_duplicate",
    ) as factory:
        yield factory


def _seed_source(postgres_sessions, name: str = "Concurrent Chili") -> tuple[UUID, UUID]:
    with postgres_sessions() as db:
        user = User(id=uuid4(), email=f"recipe-duplicate-{uuid4()}@example.test")
        db.add(user)
        db.commit()
        source = RecipeService(db).create_recipe(
            user.id,
            RecipeCreateRequest(name=name),
        )
        return user.id, source.id


def test_concurrent_duplicate_requests_allocate_distinct_deterministic_names(
    postgres_sessions,
) -> None:
    user_id, source_id = _seed_source(postgres_sessions)
    worker_count = 6
    start = Barrier(worker_count + 1)

    def duplicate_once():
        with postgres_sessions() as db:
            start.wait(timeout=10)
            return RecipeService(db).duplicate_recipe(
                user_id,
                source_id,
                uuid4(),
            )

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = [pool.submit(duplicate_once) for _ in range(worker_count)]
        start.wait(timeout=10)
        results = [future.result(timeout=20) for future in futures]

    assert {result.name for result in results} == {
        "Concurrent Chili Copy",
        "Concurrent Chili Copy 2",
        "Concurrent Chili Copy 3",
        "Concurrent Chili Copy 4",
        "Concurrent Chili Copy 5",
        "Concurrent Chili Copy 6",
    }
    assert len({result.id for result in results}) == worker_count


def test_concurrent_same_request_replays_one_duplicate_without_deadlock(
    postgres_sessions,
) -> None:
    user_id, source_id = _seed_source(postgres_sessions, "Replay Chili")
    request_id = uuid4()
    start = Barrier(3)

    def duplicate_once():
        with postgres_sessions() as db:
            start.wait(timeout=10)
            return RecipeService(db).duplicate_recipe(
                user_id,
                source_id,
                request_id,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(duplicate_once) for _ in range(2)]
        start.wait(timeout=10)
        results = [future.result(timeout=20) for future in futures]

    assert results[0].model_dump(mode="json") == results[1].model_dump(mode="json")
    with postgres_sessions() as db:
        assert db.scalar(
            select(func.count())
            .select_from(Recipe)
            .where(Recipe.user_id == user_id, Recipe.name == "Replay Chili Copy")
        ) == 1
        assert db.scalar(
            select(func.count())
            .select_from(CreateOperationIdempotency)
            .where(
                CreateOperationIdempotency.user_id == user_id,
                CreateOperationIdempotency.operation == "recipe.duplicate",
                CreateOperationIdempotency.client_request_id == request_id,
            )
        ) == 1


def test_duplicate_failure_rolls_back_recipe_ingredients_and_receipt(
    postgres_sessions,
) -> None:
    with postgres_sessions() as db:
        user = User(id=uuid4(), email=f"recipe-rollback-{uuid4()}@example.test")
        db.add(user)
        db.commit()
        food = FoodService(db).create_manual_food(
            user.id,
            FoodCreateRequest(
                name="Rollback Beans",
                serving_definitions=[
                    {
                        "label": "serving",
                        "quantity": "1",
                        "unit": "serving",
                        "gram_weight": "100",
                        "is_default": True,
                    }
                ],
                nutrients=[],
            ),
        )
        source = RecipeService(db).create_recipe(
            user.id,
            RecipeCreateRequest(
                name="Rollback Chili",
                ingredients=[
                    RecipeIngredientInput(
                        food_item_id=food.id,
                        position=0,
                        amount_quantity="1",
                        amount_unit="serving",
                        serving_definition_id=food.serving_definitions[0].id,
                    )
                ],
            ),
        )
        user_id = user.id
        source_id = source.id
        food_id = food.id

    with postgres_sessions() as db:
        stored_food = db.get(FoodItem, food_id)
        assert stored_food is not None
        from datetime import datetime, timezone

        stored_food.deleted_at = datetime.now(timezone.utc)
        db.commit()

    request_id = uuid4()
    with postgres_sessions() as db:
        with pytest.raises(LookupError, match="Food not found"):
            RecipeService(db).duplicate_recipe(user_id, source_id, request_id)

    with postgres_sessions() as db:
        assert db.scalar(
            select(func.count())
            .select_from(Recipe)
            .where(Recipe.user_id == user_id)
        ) == 1
        assert db.scalar(
            select(func.count())
            .select_from(CreateOperationIdempotency)
            .where(
                CreateOperationIdempotency.user_id == user_id,
                CreateOperationIdempotency.operation == "recipe.duplicate",
            )
        ) == 0
