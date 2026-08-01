from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.dependencies.user import ensure_dev_user
from app.models.food import FoodItem
from app.models.log import DailyLog
from app.schemas.log import DailyLogUpdateRequest
from app.services.log_service import LogService
from tests.test_recipe_revision_logging import _post_log, _published, _stored_log
from tests.test_stage2_foods import create_food


def _calendar(client: TestClient) -> dict:
    response = client.get("/api/v1/settings/calendar")
    assert response.status_code == 200, response.text
    return response.json()


def _manual_log(client: TestClient, food: dict, *, notes: str = "before") -> dict:
    response = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": "2026-07-13",
            "amount_quantity": "1",
            "amount_unit": "serving",
            "serving_definition_id": food["serving_definitions"][0]["id"],
            "notes": notes,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _snapshot_state(log: DailyLog) -> tuple:
    return tuple(
        sorted(
            (
                snapshot.id,
                snapshot.nutrient_id,
                snapshot.amount,
                snapshot.unit,
                snapshot.consumed_amount_quantity,
                snapshot.consumed_amount_unit,
            )
            for snapshot in log.snapshots
        )
    )


def _edit_payload(
    calendar: dict,
    log: dict,
    *,
    source_updated_at: str | None = None,
    **fields,
) -> dict:
    payload = {
        "client_request_id": str(uuid4()),
        "expected_updated_at": log["updated_at"],
        "calendar_revision": calendar["calendar_revision"],
        **fields,
    }
    if source_updated_at is not None:
        payload["source_food_updated_at"] = source_updated_at
    return payload


def test_metadata_edit_preserves_snapshots_and_creation_time(
    client: TestClient,
    db_session: Session,
) -> None:
    food = create_food(client, "Editable Food")
    created = _manual_log(client, food)
    stored = db_session.get(DailyLog, UUID(created["id"]))
    assert stored is not None
    snapshot_ids = {snapshot.id for snapshot in stored.snapshots}
    snapshot_values = [(snapshot.nutrient_id, snapshot.amount) for snapshot in stored.snapshots]
    creation_time = stored.created_at
    calendar = _calendar(client)
    source = db_session.get(FoodItem, UUID(food["id"]))
    assert source is not None

    response = client.patch(
        f"/api/v1/logs/{created['id']}",
        json=_edit_payload(
            calendar,
            created,
            source_updated_at=source.updated_at.isoformat(),
            meal_type="dinner",
            notes="after",
        ),
    )

    assert response.status_code == 200, response.text
    db_session.expire_all()
    updated = db_session.get(DailyLog, UUID(created["id"]))
    assert updated is not None
    assert updated.meal_type == "dinner"
    assert updated.notes == "after"
    assert updated.created_at == creation_time
    assert {snapshot.id for snapshot in updated.snapshots} == snapshot_ids
    assert [(snapshot.nutrient_id, snapshot.amount) for snapshot in updated.snapshots] == snapshot_values


def test_valid_date_move_preserves_snapshots_and_uses_destination_date(
    client: TestClient,
    db_session: Session,
) -> None:
    food = create_food(client, "Move Food")
    created = _manual_log(client, food)
    stored = db_session.get(DailyLog, UUID(created["id"]))
    assert stored is not None
    snapshot_ids = {snapshot.id for snapshot in stored.snapshots}
    calendar = _calendar(client)
    source = db_session.get(FoodItem, UUID(food["id"]))
    assert source is not None

    response = client.patch(
        f"/api/v1/logs/{created['id']}",
        json=_edit_payload(
            calendar,
            created,
            source_updated_at=source.updated_at.isoformat(),
            logged_date="2026-07-12",
        ),
    )

    assert response.status_code == 200, response.text
    assert response.json()["logged_date"] == "2026-07-12"
    db_session.expire_all()
    updated = db_session.get(DailyLog, UUID(created["id"]))
    assert updated is not None
    assert updated.logged_date.isoformat() == "2026-07-12"
    assert {snapshot.id for snapshot in updated.snapshots} == snapshot_ids


def test_future_date_move_is_rejected_by_authoritative_calendar(
    client: TestClient,
    db_session: Session,
) -> None:
    food = create_food(client, "Future Move Food")
    created = _manual_log(client, food)
    calendar = _calendar(client)
    source = db_session.get(FoodItem, UUID(food["id"]))
    assert source is not None

    response = client.patch(
        f"/api/v1/logs/{created['id']}",
        json=_edit_payload(
            calendar,
            created,
            source_updated_at=source.updated_at.isoformat(),
            logged_date="2030-01-01",
        ),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "future_dated_mutation_blocked"


def test_stale_mutable_food_authority_rejects_nutrition_edit(
    client: TestClient,
    db_session: Session,
) -> None:
    food = create_food(client, "Stale Edit Food")
    created = _manual_log(client, food)
    source = db_session.get(FoodItem, UUID(food["id"]))
    assert source is not None
    reviewed_source_updated_at = source.updated_at
    source.updated_at = datetime.now(timezone.utc)
    db_session.commit()
    calendar = _calendar(client)

    response = client.patch(
        f"/api/v1/logs/{created['id']}",
        json=_edit_payload(
            calendar,
            created,
            source_updated_at=reviewed_source_updated_at.isoformat(),
            amount_quantity="2",
            amount_unit="serving",
            serving_definition_id=food["serving_definitions"][0]["id"],
        ),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_log_source"


def test_deleted_food_allows_metadata_move_but_rejects_nutrition_recalculation(
    client: TestClient,
    db_session: Session,
) -> None:
    food = create_food(client, "Deleted Source Edit")
    created = _manual_log(client, food)
    stored = db_session.get(DailyLog, UUID(created["id"]))
    assert stored is not None
    snapshot_ids = {snapshot.id for snapshot in stored.snapshots}
    source = db_session.get(FoodItem, UUID(food["id"]))
    assert source is not None
    source.deleted_at = datetime.now(timezone.utc)
    db_session.commit()

    metadata_response = client.patch(
        f"/api/v1/logs/{created['id']}",
        json=_edit_payload(
            _calendar(client),
            created,
            logged_date="2026-07-12",
            notes="corrected after source removal",
        ),
    )

    assert metadata_response.status_code == 200, metadata_response.text
    db_session.expire_all()
    updated = db_session.get(DailyLog, UUID(created["id"]))
    assert updated is not None
    assert updated.logged_date.isoformat() == "2026-07-12"
    assert updated.notes == "corrected after source removal"
    assert {snapshot.id for snapshot in updated.snapshots} == snapshot_ids

    nutrition_response = client.patch(
        f"/api/v1/logs/{created['id']}",
        json=_edit_payload(
            _calendar(client),
            metadata_response.json(),
            amount_quantity="2",
            amount_unit="serving",
            serving_definition_id=food["serving_definitions"][0]["id"],
        ),
    )

    assert nutrition_response.status_code == 409
    assert nutrition_response.json()["detail"]["code"] == "source_food_deleted"


def test_recipe_edit_with_current_revision_generates_new_authoritative_snapshot(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe_id, food = _published(client)
    created_response = _post_log(
        client,
        food,
        serving_definition_id=next(item for item in food["serving_definitions"] if item["is_default"])["id"],
    )
    assert created_response.status_code == 201, created_response.text
    log = _stored_log(db_session, created_response)
    old_revision = log.recipe_publication_revision_id
    old_snapshot_ids = {snapshot.id for snapshot in log.snapshots}
    assert client.patch(f"/api/v1/recipes/{recipe_id}", json={"serving_count_yield": "4"}).status_code == 200
    assert client.post(f"/api/v1/recipes/{recipe_id}/publish").status_code == 200
    current_food = client.get(f"/api/v1/foods/{food['id']}").json()
    current_nutrition = client.get(f"/api/v1/foods/{food['id']}/resolved-nutrition").json()
    current_revision = UUID(current_nutrition["recipe_publication_revision_id"])
    current_amount = next(amount for amount in current_nutrition["amounts"] if amount["is_default"])
    calendar = _calendar(client)

    response = client.patch(
        f"/api/v1/logs/{log.id}",
        json=_edit_payload(
            calendar,
            created_response.json(),
            source_updated_at=current_food["updated_at"],
            source_recipe_publication_revision_id=str(current_revision),
            amount_quantity="2",
            amount_unit=current_amount["semantic_amount_mode"],
            serving_definition_id=current_amount["amount_definition_id"],
        ),
    )

    assert response.status_code == 200, response.text
    db_session.expire_all()
    updated = db_session.get(DailyLog, log.id)
    assert updated is not None
    assert updated.recipe_publication_revision_id == current_revision
    assert updated.recipe_publication_amount_definition_id == UUID(
        current_amount["amount_definition_id"]
    )
    assert updated.recipe_publication_revision_id != old_revision
    assert {snapshot.id for snapshot in updated.snapshots}.isdisjoint(old_snapshot_ids)


def test_recipe_current_authority_replacement_rolls_back_atomically(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    recipe_id, food = _published(client)
    created_response = _post_log(
        client,
        food,
        serving_definition_id=next(
            item for item in food["serving_definitions"] if item["is_default"]
        )["id"],
    )
    log = _stored_log(db_session, created_response)
    assert client.patch(
        f"/api/v1/recipes/{recipe_id}",
        json={"serving_count_yield": "4"},
    ).status_code == 200
    assert client.post(f"/api/v1/recipes/{recipe_id}/publish").status_code == 200
    current_food = client.get(f"/api/v1/foods/{food['id']}").json()
    current_nutrition = client.get(f"/api/v1/foods/{food['id']}/resolved-nutrition").json()
    current_amount = next(amount for amount in current_nutrition["amounts"] if amount["is_default"])
    old_state = (
        log.id,
        log.created_at,
        log.recipe_publication_revision_id,
        log.recipe_publication_amount_definition_id,
        _snapshot_state(log),
    )
    service = LogService(db_session)

    def fail(_log) -> None:
        raise RuntimeError("injected current-authority replacement failure")

    monkeypatch.setattr(service, "_after_edit_snapshot_regeneration", fail)
    with pytest.raises(RuntimeError, match="injected current-authority replacement failure"):
        service.update_log(
            ensure_dev_user(db_session).id,
            log.id,
            DailyLogUpdateRequest(
                amount_quantity="2",
                amount_unit=current_amount["semantic_amount_mode"],
                serving_definition_id=current_amount["amount_definition_id"],
                source_food_updated_at=current_food["updated_at"],
                source_recipe_publication_revision_id=current_nutrition[
                    "recipe_publication_revision_id"
                ],
            ),
        )

    db_session.expire_all()
    unchanged = db_session.get(DailyLog, log.id)
    assert unchanged is not None
    assert (
        unchanged.id,
        unchanged.created_at,
        unchanged.recipe_publication_revision_id,
        unchanged.recipe_publication_amount_definition_id,
        _snapshot_state(unchanged),
    ) == old_state
