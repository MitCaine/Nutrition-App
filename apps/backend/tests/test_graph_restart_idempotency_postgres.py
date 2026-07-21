from __future__ import annotations

from decimal import Decimal
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select

from app import models  # noqa: F401
from app.models.create_idempotency import CreateOperationIdempotency
from app.models.food import ServingDefinition
from app.models.recipe import Recipe, RecipeIngredient
from app.models.recipe_publication import RecipePublicationRevision
from app.models.user import User
from app.schemas.food import FoodCreateRequest, ServingDefinitionCreateRequest
from app.schemas.recipe import RecipeCreateRequest
from app.services.food_service import FoodService
from app.services.recipe_service import RecipeService
from tests.postgres_test_support import isolated_postgres_session_factory


pytestmark = pytest.mark.postgres_concurrency
POSTGRES_URL = os.getenv(
    "NUTRITION_TEST_POSTGRES_URL",
    "postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app",
)


@pytest.fixture()
def restart_postgres_sessions():
    with isolated_postgres_session_factory(
        database_url=POSTGRES_URL,
        schema_prefix="test_graph_restart_idem",
    ) as factory:
        yield factory


def _manual_food_payload(name: str) -> FoodCreateRequest:
    return FoodCreateRequest(
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


def _add_parent(
    db,
    *,
    user_id: UUID,
    food_id: UUID,
    serving_id: UUID | None,
    name: str,
) -> UUID:
    parent = Recipe(
        id=uuid4(),
        user_id=user_id,
        name=name,
        serving_count_yield=Decimal("1"),
    )
    db.add(parent)
    db.flush()
    db.add(
        RecipeIngredient(
            id=uuid4(),
            recipe_id=parent.id,
            food_item_id=food_id,
            position=0,
            amount_quantity=Decimal("1") if serving_id is not None else Decimal("100"),
            amount_unit="serving" if serving_id is not None else "g",
            serving_definition_id=serving_id,
            resolved_gram_amount=Decimal("100"),
        )
    )
    db.commit()
    return parent.id


def _instrument_restart_and_receipt(service, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    events: list[str] = []
    original_reserve = service.create_idempotency.reserve
    original_complete = service.create_idempotency.complete
    original_commit = service.db.commit

    def after_soft_rollback(_session, previous_transaction) -> None:
        events.append(
            "graph_rollback" if previous_transaction.nested else "outer_rollback"
        )

    def reserve(*args, **kwargs):
        events.append("reserve")
        return original_reserve(*args, **kwargs)

    def complete(*args, **kwargs) -> None:
        events.append("complete")
        original_complete(*args, **kwargs)

    def commit() -> None:
        events.append("commit")
        original_commit()

    event.listen(service.db, "after_soft_rollback", after_soft_rollback)
    monkeypatch.setattr(service.create_idempotency, "reserve", reserve)
    monkeypatch.setattr(service.create_idempotency, "complete", complete)
    monkeypatch.setattr(service.db, "commit", commit)
    return events


def test_food_add_serving_restart_preserves_one_completed_receipt_and_exact_replay(
    restart_postgres_sessions,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = restart_postgres_sessions
    with factory() as db:
        user = User(id=uuid4(), email=f"serving-restart-{uuid4()}@example.test")
        db.add(user)
        db.commit()
        created = FoodService(db).create_manual_food(
            user.id, _manual_food_payload("Restarted serving Food")
        )
        user_id, food_id = user.id, created.id
        original_serving_id = created.serving_definitions[0].id
        parent_id = _add_parent(
            db,
            user_id=user_id,
            food_id=food_id,
            serving_id=original_serving_id,
            name="Late Food parent",
        )

    request_id = uuid4()
    payload = ServingDefinitionCreateRequest(
        client_request_id=request_id,
        label="Restart-safe serving",
        quantity=Decimal("1"),
        unit="portion",
        gram_weight=Decimal("42"),
        is_default=False,
    )
    with factory() as db:
        service = FoodService(db)
        original_dependencies = service._dependent_recipe_ids
        dependency_scans = 0

        def changing_dependencies(owner_id, target_food_id):
            nonlocal dependency_scans
            dependency_scans += 1
            if dependency_scans == 1:
                return set()
            return original_dependencies(owner_id, target_food_id)

        monkeypatch.setattr(service, "_dependent_recipe_ids", changing_dependencies)
        events = _instrument_restart_and_receipt(service, monkeypatch)
        first = service.add_serving_definition(user_id, food_id, payload)
        first_snapshot = first.model_dump(mode="json")

    assert dependency_scans == 4
    assert events == ["reserve", "graph_rollback", "complete", "commit"]

    with factory() as db:
        created_servings = list(
            db.scalars(
                select(ServingDefinition).where(
                    ServingDefinition.food_item_id == food_id,
                    ServingDefinition.label == payload.label,
                )
            ).all()
        )
        receipts = list(
            db.scalars(
                select(CreateOperationIdempotency).where(
                    CreateOperationIdempotency.user_id == user_id,
                    CreateOperationIdempotency.operation == "food.add_serving",
                    CreateOperationIdempotency.client_request_id == request_id,
                )
            ).all()
        )
        assert len(created_servings) == 1
        assert len(receipts) == 1
        assert receipts[0].resource_id == created_servings[0].id
        assert receipts[0].completed_at is not None
        assert receipts[0].response_snapshot == first_snapshot
        assert db.get(Recipe, parent_id) is not None

    with factory() as db:
        replay = FoodService(db).add_serving_definition(user_id, food_id, payload)
        assert replay.model_dump(mode="json") == first_snapshot
        assert db.scalar(
            select(func.count(ServingDefinition.id)).where(
                ServingDefinition.food_item_id == food_id,
                ServingDefinition.label == payload.label,
            )
        ) == 1
        assert db.scalar(
            select(func.count(CreateOperationIdempotency.id)).where(
                CreateOperationIdempotency.user_id == user_id,
                CreateOperationIdempotency.operation == "food.add_serving",
                CreateOperationIdempotency.client_request_id == request_id,
            )
        ) == 1


def test_recipe_publish_restart_preserves_one_completed_receipt_and_exact_replay(
    restart_postgres_sessions,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = restart_postgres_sessions
    with factory() as db:
        user = User(id=uuid4(), email=f"publish-restart-{uuid4()}@example.test")
        db.add(user)
        db.commit()
        child = RecipeService(db).create_recipe(
            user.id,
            RecipeCreateRequest(
                name="Restarted publication Recipe",
                serving_count_yield=Decimal("1"),
            ),
        )
        initial = RecipeService(db).publish(user.id, child.id)
        user_id, recipe_id = user.id, child.id
        projection_id = initial.food.id
        parent_id = _add_parent(
            db,
            user_id=user_id,
            food_id=projection_id,
            serving_id=None,
            name="Late Recipe parent",
        )

    request_id = uuid4()
    with factory() as db:
        revision_count_before = db.scalar(
            select(func.count(RecipePublicationRevision.id)).where(
                RecipePublicationRevision.recipe_id == recipe_id
            )
        )
        service = RecipeService(db)
        original_dependencies = service._dependent_recipe_ids
        dependency_scans = 0

        def changing_dependencies(owner_id, target_projection_id):
            nonlocal dependency_scans
            dependency_scans += 1
            if dependency_scans == 1:
                return set()
            return original_dependencies(owner_id, target_projection_id)

        monkeypatch.setattr(service, "_dependent_recipe_ids", changing_dependencies)
        events = _instrument_restart_and_receipt(service, monkeypatch)
        first = service.publish(user_id, recipe_id, request_id).response
        first_snapshot = first.model_dump(mode="json")

    assert revision_count_before == 1
    assert dependency_scans == 4
    assert events == ["reserve", "graph_rollback", "complete", "commit"]

    with factory() as db:
        revisions = list(
            db.scalars(
                select(RecipePublicationRevision)
                .where(RecipePublicationRevision.recipe_id == recipe_id)
                .order_by(RecipePublicationRevision.revision_number)
            ).all()
        )
        receipts = list(
            db.scalars(
                select(CreateOperationIdempotency).where(
                    CreateOperationIdempotency.user_id == user_id,
                    CreateOperationIdempotency.operation == "recipe.publish",
                    CreateOperationIdempotency.client_request_id == request_id,
                )
            ).all()
        )
        assert len(revisions) == revision_count_before + 1
        assert len(receipts) == 1
        assert receipts[0].resource_id == revisions[-1].id
        assert receipts[0].completed_at is not None
        assert receipts[0].response_snapshot == first_snapshot
        assert db.get(Recipe, recipe_id).active_publication_revision_id == revisions[-1].id
        assert db.get(Recipe, parent_id) is not None

    with factory() as db:
        replay = RecipeService(db).publish(user_id, recipe_id, request_id).response
        assert replay.model_dump(mode="json") == first_snapshot
        assert db.scalar(
            select(func.count(RecipePublicationRevision.id)).where(
                RecipePublicationRevision.recipe_id == recipe_id
            )
        ) == revision_count_before + 1
        assert db.scalar(
            select(func.count(CreateOperationIdempotency.id)).where(
                CreateOperationIdempotency.user_id == user_id,
                CreateOperationIdempotency.operation == "recipe.publish",
                CreateOperationIdempotency.client_request_id == request_id,
            )
        ) == 1
