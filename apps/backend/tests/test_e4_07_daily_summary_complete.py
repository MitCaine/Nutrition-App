from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.test_e4_03_complete_invalidation import (
    SOURCE_DATE,
    _create_log,
    _patch_log,
    _set_complete,
)
from tests.test_stage2_foods import create_food


def _summary(client: TestClient) -> dict:
    response = client.get(
        "/api/v1/logs/daily-summary",
        params={"date": SOURCE_DATE.isoformat()},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_daily_summary_projects_authoritative_complete_state(
    db_session: Session,
    client: TestClient,
) -> None:
    food = create_food(client, "E4-07 Complete Summary")
    created = _create_log(client, food)

    initial = _summary(client)
    assert initial["logged_date"] == SOURCE_DATE.isoformat()
    assert initial["is_complete"] is False

    _set_complete(db_session, SOURCE_DATE)

    completed = _summary(client)
    assert completed["is_complete"] is True

    changed = _patch_log(
        client,
        created,
        amount_quantity="2",
        amount_unit="serving",
        serving_definition_id=food["serving_definitions"][0]["id"],
    )
    assert changed["logged_date"] == SOURCE_DATE.isoformat()

    invalidated = _summary(client)
    assert invalidated["is_complete"] is False
