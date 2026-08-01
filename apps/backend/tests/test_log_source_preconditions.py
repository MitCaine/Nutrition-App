from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.food import FoodItem
from app.models.log import DailyLog, DailyLogNutrientSnapshot
from tests.test_recipe_revision_logging import _published
from tests.test_recipe_revision_publication import _publish
from tests.test_stage2_foods import create_food


def _payload(
    food: dict,
    *,
    request_id=None,
    source_updated_at=None,
    source_revision_id=None,
) -> dict:
    return {
        "client_request_id": str(request_id or uuid4()),
        "food_item_id": food["id"],
        "logged_date": "2026-07-14",
        "amount_quantity": "1",
        "amount_unit": "serving",
        "serving_definition_id": food["serving_definitions"][0]["id"],
        "source_food_updated_at": source_updated_at or food["updated_at"],
        "source_recipe_publication_revision_id": source_revision_id,
    }


def _counts(db_session: Session) -> tuple[int, int]:
    return (
        db_session.scalar(select(func.count()).select_from(DailyLog)) or 0,
        db_session.scalar(select(func.count()).select_from(DailyLogNutrientSnapshot)) or 0,
    )


def test_reviewed_mutable_food_generation_commits(client: TestClient, db_session: Session) -> None:
    food = create_food(client, "Reviewed Food")
    response = client.post("/api/v1/logs", json=_payload(food))
    assert response.status_code == 201, response.text
    assert _counts(db_session) == (1, len(response.json()["snapshots"]))


def test_mutable_food_generation_change_rejects_without_partial_log(
    client: TestClient,
    db_session: Session,
) -> None:
    food = create_food(client, "Changed Food")
    source = db_session.get(FoodItem, UUID(food["id"]))
    assert source is not None
    source.nutrients[0].amount = source.nutrients[0].amount + 1
    source.updated_at = datetime.now(timezone.utc)
    db_session.commit()

    response = client.post("/api/v1/logs", json=_payload(food))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_log_source"
    assert _counts(db_session) == (0, 0)


def test_removed_reviewed_serving_returns_amount_conflict(
    client: TestClient,
    db_session: Session,
) -> None:
    food = create_food(client, "Serving Changed Food")
    source = db_session.get(FoodItem, UUID(food["id"]))
    assert source is not None
    reviewed_serving = source.serving_definitions[0]
    db_session.delete(reviewed_serving)
    db_session.commit()

    response = client.post("/api/v1/logs", json=_payload(food))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_log_amount"
    assert _counts(db_session) == (0, 0)


def test_replaced_reviewed_serving_returns_amount_conflict(
    client: TestClient,
    db_session: Session,
) -> None:
    food = create_food(client, "Replaced Serving Food")
    response = client.patch(
        f"/api/v1/foods/{food['id']}",
        json={
            "serving_definitions": [{
                "label": "New serving",
                "quantity": "1",
                "unit": "portion",
                "gram_weight": "125",
                "is_default": True,
            }],
        },
    )
    assert response.status_code == 200, response.text

    conflict = client.post("/api/v1/logs", json=_payload(food))
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "stale_log_amount"
    assert _counts(db_session) == (0, 0)


def test_source_deletion_returns_unavailable_conflict(
    client: TestClient,
    db_session: Session,
) -> None:
    food = create_food(client, "Unavailable Food")
    source = db_session.get(FoodItem, UUID(food["id"]))
    assert source is not None
    source.deleted_at = datetime.now(timezone.utc)
    source.updated_at = source.deleted_at
    db_session.commit()

    response = client.post("/api/v1/logs", json=_payload(food))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "source_food_unavailable"
    assert _counts(db_session) == (0, 0)


def test_identical_replay_returns_confirmed_log_after_source_changes(
    client: TestClient,
    db_session: Session,
) -> None:
    food = create_food(client, "Replay Food")
    request_id = uuid4()
    payload = _payload(food, request_id=request_id)
    first = client.post("/api/v1/logs", json=payload)
    assert first.status_code == 201, first.text

    source = db_session.get(FoodItem, UUID(food["id"]))
    assert source is not None
    source.updated_at = datetime.now(timezone.utc)
    db_session.commit()

    replay = client.post("/api/v1/logs", json=payload)
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]
    assert _counts(db_session) == (1, len(first.json()["snapshots"]))


def test_recipe_republication_rejects_old_reviewed_revision(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe_id, food = _published(client)
    nutrition = client.get(f"/api/v1/foods/{food['id']}/resolved-nutrition").json()
    payload = _payload(
        food,
        source_revision_id=nutrition["recipe_publication_revision_id"],
    )

    updated = client.patch(f"/api/v1/recipes/{recipe_id}", json={"name": "Republished"})
    assert updated.status_code == 200, updated.text
    _publish(client, recipe_id)

    response = client.post("/api/v1/logs", json=payload)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_log_source"
    assert _counts(db_session) == (0, 0)
