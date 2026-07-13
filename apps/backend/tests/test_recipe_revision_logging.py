from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dependencies.user import ensure_dev_user
from app.models.log import DailyLog, DailyLogNutrientSnapshot
from app.models.recipe import Recipe
from app.nutrition.resolution import resolve_nutrition
from app.repositories.food_repository import FoodRepository
from app.repositories.recipe_publication_repository import RecipePublicationRepository
from app.schemas.log import DailyLogCreateRequest
from app.services.log_service import LogService
from tests.test_recipe_revision_publication import _create_recipe, _history, _publish
from tests.test_stage2_foods import create_food


def _post_log(
    client: TestClient,
    food: dict,
    *,
    amount_quantity: str = "1",
    amount_unit: str = "serving",
    serving_definition_id: str | None = None,
    logged_date: str = "2026-07-13",
):
    return client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": logged_date,
            "amount_quantity": amount_quantity,
            "amount_unit": amount_unit,
            "serving_definition_id": serving_definition_id,
        },
    )


def _published(client: TestClient, **kwargs) -> tuple[UUID, dict]:
    recipe_id = _create_recipe(client, **kwargs)
    return recipe_id, _publish(client, recipe_id)["food"]


def _stored_log(db: Session, response) -> DailyLog:
    db.expire_all()
    log = db.get(DailyLog, UUID(response.json()["id"]))
    assert log is not None
    return log


def test_manual_food_logging_path_and_snapshots_are_unchanged(
    client: TestClient,
    db_session: Session,
) -> None:
    food = create_food(client, "Manual Food")
    serving = food["serving_definitions"][0]

    response = _post_log(client, food, serving_definition_id=serving["id"])

    assert response.status_code == 201, response.text
    log = _stored_log(db_session, response)
    assert log.recipe_publication_revision_id is None
    assert log.recipe_publication_amount_definition_id is None
    assert log.serving_definition_id == UUID(serving["id"])
    assert all(snapshot.source_food_nutrient_id is not None for snapshot in log.snapshots)


def test_recipe_serving_log_persists_active_revision_amount_and_compatible_food(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe_id, food = _published(client)
    serving = next(value for value in food["serving_definitions"] if value["is_default"])

    response = _post_log(client, food, serving_definition_id=serving["id"])

    assert response.status_code == 201, response.text
    assert "recipe_publication_revision_id" not in response.json()
    log = _stored_log(db_session, response)
    recipe = db_session.get(Recipe, recipe_id)
    revision = RecipePublicationRepository(db_session).get_required(
        recipe.active_publication_revision_id,
        recipe.user_id,
    )
    selected = next(
        amount
        for amount in revision.amount_definitions
        if amount.id == log.recipe_publication_amount_definition_id
    )
    assert log.food_item_id == UUID(food["id"])
    assert log.serving_definition_id == UUID(serving["id"])
    assert log.recipe_publication_revision_id == revision.id
    assert selected.semantic_mode == "serving"
    assert selected.display_label == serving["label"]
    assert log.snapshots
    assert all(snapshot.source_food_item_id == UUID(food["id"]) for snapshot in log.snapshots)
    assert all(snapshot.source_food_nutrient_id is None for snapshot in log.snapshots)


def test_recipe_log_snapshots_match_authoritative_revision_resolution(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe_id, food_data = _published(client)
    serving_data = next(
        value for value in food_data["serving_definitions"] if value["is_default"]
    )
    food = FoodRepository(db_session).get_required(UUID(food_data["id"]), ensure_dev_user(db_session).id)
    projection_result = resolve_nutrition(
        food,
        Decimal("1"),
        "serving",
        UUID(serving_data["id"]),
    )

    response = _post_log(client, food_data, serving_definition_id=serving_data["id"])

    assert response.status_code == 201, response.text
    log = _stored_log(db_session, response)
    assert log.recipe_publication_revision_id == db_session.get(
        Recipe, recipe_id
    ).active_publication_revision_id
    expected = {
        nutrient.nutrient_id: (nutrient.amount, nutrient.unit, nutrient.data_status.value)
        for nutrient in projection_result.nutrients
    }
    actual = {
        snapshot.nutrient_id: (snapshot.amount, snapshot.unit, snapshot.data_status)
        for snapshot in log.snapshots
    }
    assert actual == expected


def test_recipe_gram_log_uses_one_canonical_definition_for_arbitrary_quantities(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe_id, food = _published(client)
    hundred_grams = next(
        value for value in food["serving_definitions"] if value["label"] == "100 g"
    )
    recipe = db_session.get(Recipe, recipe_id)
    before = _history(db_session, recipe)[0]
    before_amount_ids = {amount.id for amount in before.amount_definitions}

    first = _post_log(
        client,
        food,
        amount_quantity="37",
        amount_unit="g",
        serving_definition_id=hundred_grams["id"],
    )
    second = _post_log(
        client,
        food,
        amount_quantity="83.5",
        amount_unit="g",
        serving_definition_id=hundred_grams["id"],
        logged_date="2026-07-14",
    )

    assert first.status_code == second.status_code == 201
    first_log = _stored_log(db_session, first)
    second_log = _stored_log(db_session, second)
    db_session.expire_all()
    revision = _history(db_session, db_session.get(Recipe, recipe_id))[0]
    canonical = [amount for amount in revision.amount_definitions if amount.semantic_mode == "g"]
    assert len(canonical) == 1
    assert canonical[0].display_quantity is None
    assert first_log.recipe_publication_amount_definition_id == canonical[0].id
    assert second_log.recipe_publication_amount_definition_id == canonical[0].id
    assert first_log.gram_amount == Decimal("37")
    assert second_log.gram_amount == Decimal("83.5")
    assert {amount.id for amount in revision.amount_definitions} == before_amount_ids


def test_count_only_recipe_logs_servings_and_rejects_grams(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe_id, food = _published(client, cooked_grams=None)
    serving = food["serving_definitions"][0]

    serving_response = _post_log(client, food, serving_definition_id=serving["id"])
    gram_response = _post_log(
        client,
        food,
        amount_quantity="25",
        amount_unit="g",
        serving_definition_id=serving["id"],
    )

    assert serving_response.status_code == 201, serving_response.text
    assert gram_response.status_code == 400
    revision = _history(db_session, db_session.get(Recipe, recipe_id))[0]
    assert all(amount.semantic_mode != "g" for amount in revision.amount_definitions)


def test_logs_pin_the_active_revision_across_republish(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe_id, first_food = _published(client)
    first_serving = next(
        value for value in first_food["serving_definitions"] if value["is_default"]
    )
    first_response = _post_log(
        client,
        first_food,
        serving_definition_id=first_serving["id"],
    )
    first_log = _stored_log(db_session, first_response)
    first_revision_id = first_log.recipe_publication_revision_id
    first_snapshots = [
        (row.nutrient_id, row.amount, row.unit, row.data_status) for row in first_log.snapshots
    ]

    updated = client.patch(
        f"/api/v1/recipes/{recipe_id}",
        json={"serving_count_yield": "4"},
    )
    assert updated.status_code == 200, updated.text
    second_food = _publish(client, recipe_id)["food"]
    second_serving = next(
        value for value in second_food["serving_definitions"] if value["is_default"]
    )
    second_response = _post_log(
        client,
        second_food,
        serving_definition_id=second_serving["id"],
        logged_date="2026-07-14",
    )
    second_log = _stored_log(db_session, second_response)
    db_session.expire_all()
    first_log = db_session.get(DailyLog, first_log.id)

    assert first_log.recipe_publication_revision_id == first_revision_id
    assert second_log.recipe_publication_revision_id != first_revision_id
    assert [
        (row.nutrient_id, row.amount, row.unit, row.data_status) for row in first_log.snapshots
    ] == first_snapshots


def test_recipe_draft_changes_do_not_affect_logging_before_republish(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe_id, food = _published(client, name="Published Name")
    serving = next(value for value in food["serving_definitions"] if value["is_default"])
    revision_id = db_session.get(Recipe, recipe_id).active_publication_revision_id
    updated = client.patch(
        f"/api/v1/recipes/{recipe_id}",
        json={"name": "Unpublished Draft Name", "serving_count_yield": "8"},
    )
    assert updated.status_code == 200, updated.text

    response = _post_log(client, food, serving_definition_id=serving["id"])

    assert response.status_code == 201, response.text
    log = _stored_log(db_session, response)
    assert log.recipe_publication_revision_id == revision_id
    assert log.food_name_snapshot == "Published Name"


@pytest.mark.parametrize(
    ("break_integrity", "expected"),
    [
        ("active", "active publication"),
        ("projection", "active publication"),
        ("amount", "does not map"),
    ],
)
def test_recipe_log_rejects_missing_revision_projection_or_amount_mapping(
    client: TestClient,
    db_session: Session,
    break_integrity: str,
    expected: str,
) -> None:
    recipe_id, food_data = _published(client)
    recipe = db_session.get(Recipe, recipe_id)
    food = FoodRepository(db_session).get_required(UUID(food_data["id"]), recipe.user_id)
    serving = next(value for value in food.serving_definitions if value.is_default)
    if break_integrity == "active":
        recipe.active_publication_revision_id = None
    elif break_integrity == "projection":
        food.recipe_publication_revision_id = None
    else:
        serving.label = "No matching immutable amount"
    db_session.commit()

    response = _post_log(
        client,
        food_data,
        serving_definition_id=str(serving.id),
    )

    assert response.status_code == 400
    assert expected in response.json()["detail"]
    assert db_session.scalar(select(func.count(DailyLog.id))) == 0


@pytest.mark.parametrize(
    "seam",
    [
        "_after_recipe_revision_lookup",
        "_after_recipe_amount_definition_lookup",
        "_after_snapshot_creation",
    ],
)
def test_recipe_log_failures_roll_back_log_snapshots_and_associations(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    seam: str,
) -> None:
    _, food = _published(client)
    serving = next(value for value in food["serving_definitions"] if value["is_default"])
    user = ensure_dev_user(db_session)
    service = LogService(db_session)

    def fail(*_args) -> None:
        raise RuntimeError("injected logging failure")

    monkeypatch.setattr(service, seam, fail)
    payload = DailyLogCreateRequest(
        food_item_id=UUID(food["id"]),
        logged_date=date(2026, 7, 13),
        amount_quantity=Decimal("1"),
        amount_unit="serving",
        serving_definition_id=UUID(serving["id"]),
    )

    with pytest.raises(RuntimeError, match="injected logging failure"):
        service.create_log(user.id, payload)

    assert db_session.scalar(select(func.count(DailyLog.id))) == 0
    assert db_session.scalar(select(func.count(DailyLogNutrientSnapshot.id))) == 0
