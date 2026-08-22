from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.log import DailyLog
from tests.support.recipes import published_recipe


def post_log(
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


def stored_log(db: Session, response) -> DailyLog:
    db.expire_all()
    log = db.get(DailyLog, UUID(response.json()["id"]))
    assert log is not None
    return log


def _default_serving(food: dict) -> dict:
    return next(
        value
        for value in food["serving_definitions"]
        if value["is_default"]
    )


def create_serving_log(
    client: TestClient,
    db: Session,
    **published_kwargs,
) -> tuple[UUID, dict, DailyLog]:
    recipe_id, food = published_recipe(
        client,
        **published_kwargs,
    )
    response = post_log(
        client,
        food,
        serving_definition_id=_default_serving(food)["id"],
    )
    assert response.status_code == 201, response.text
    return recipe_id, food, stored_log(db, response)
