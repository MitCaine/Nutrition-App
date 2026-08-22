from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.food import FoodItem
from app.models.log import DailyLog, DailyLogNutrientSnapshot
from app.models.recipe import Recipe
from tests.test_recipe_revision_logging import _published
from tests.test_recipe_revision_publication import _publish
from tests.support.foods import create_food


def _create_log(
    client: TestClient,
    food: dict,
    *,
    logged_date: str = "2026-07-13",
    meal_type: str | None = "lunch",
    notes: str | None = "reference note",
    amount_quantity: str = "2",
    amount_unit: str = "serving",
    serving_definition_id: str | None = None,
):
    serving = food["serving_definitions"][0]
    response = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": logged_date,
            "amount_quantity": amount_quantity,
            "amount_unit": amount_unit,
            "serving_definition_id": serving_definition_id if serving_definition_id is not None else (
                serving["id"] if amount_unit == "serving" else None
            ),
            "meal_type": meal_type,
            "notes": notes,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_recent_entries_are_distinct_newest_first_and_bounded(client: TestClient) -> None:
    food = create_food(client, "Repeatable Food")
    created = [_create_log(client, food, notes=f"note-{index}") for index in range(11)]

    response = client.get("/api/v1/logs/recent-entries")

    assert response.status_code == 200, response.text
    entries = response.json()["entries"]
    assert len(entries) == 10
    assert [entry["id"] for entry in entries] == [
        item["id"]
        for item in sorted(
            created,
            key=lambda item: (item["created_at"], item["id"]),
            reverse=True,
        )[:10]
    ]
    assert entries[0]["food_name_snapshot"] == "Repeatable Food"
    assert entries[0]["amount_quantity"] == "2.000000"
    assert entries[0]["meal_type"] == "lunch"
    assert entries[0]["reuse_status"] == "exact"
    assert entries[0]["current_amount_definition_id"] == entries[0]["serving_definition_id"]
    created_by_id = {item["id"]: item for item in created}
    assert entries[0]["notes"] == created_by_id[entries[0]["id"]]["notes"]


def test_recent_entries_exclude_future_and_currently_unavailable_sources(
    client: TestClient,
    db_session: Session,
) -> None:
    available = create_food(client, "Available Food")
    deleted = create_food(client, "Deleted Food")
    _create_log(client, available, logged_date="2026-07-13")
    _create_log(client, available, logged_date="2030-01-01")
    deleted_log = _create_log(client, deleted, logged_date="2026-07-13")

    assert client.delete(f"/api/v1/foods/{deleted['id']}").status_code == 200
    response = client.get("/api/v1/logs/recent-entries")

    assert response.status_code == 200, response.text
    ids = {entry["id"] for entry in response.json()["entries"]}
    assert deleted_log["id"] not in ids
    assert all(entry["logged_date"] <= date.today().isoformat() for entry in response.json()["entries"])
    assert db_session.get(FoodItem, UUID(deleted["id"])).deleted_at is not None


def test_recent_entries_keep_old_eligible_events_and_expose_gram_reuse(
    client: TestClient,
) -> None:
    food = create_food(client, "Old and gram food")
    historical = _create_log(
        client,
        food,
        logged_date="2020-01-02",
        amount_quantity="40",
        amount_unit="g",
    )

    response = client.get("/api/v1/logs/recent-entries")

    assert response.status_code == 200, response.text
    entry = next(item for item in response.json()["entries"] if item["id"] == historical["id"])
    assert entry["logged_date"] == "2020-01-02"
    assert entry["current_source_loggable"] is True
    assert entry["current_amount_unit"] == "g"
    assert entry["current_amount_definition_id"] is not None
    assert entry["reuse_status"] == "exact"


def test_recent_entries_note_reference_obeys_legacy_copy_rules(
    client: TestClient,
    db_session: Session,
) -> None:
    food = create_food(client, "Notes food")
    compliant = _create_log(client, food, notes="line one\n🍎 line two")
    whitespace = _create_log(client, food, notes=" \n\t ")
    overlength = _create_log(client, food, notes="short")
    stored = db_session.get(DailyLog, UUID(overlength["id"]))
    assert stored is not None
    stored.notes = "x" * 1_001
    db_session.commit()

    response = client.get("/api/v1/logs/recent-entries")

    assert response.status_code == 200, response.text
    entries = {item["id"]: item for item in response.json()["entries"]}
    assert entries[compliant["id"]]["note_present"] is True
    assert entries[compliant["id"]]["note_reference"] == "line one\n🍎 line two"
    assert entries[compliant["id"]]["note_copy_allowed"] is True
    assert entries[whitespace["id"]]["note_present"] is False
    assert entries[whitespace["id"]]["note_reference"] is None
    assert entries[whitespace["id"]]["note_copy_allowed"] is False
    assert entries[overlength["id"]]["note_present"] is True
    assert entries[overlength["id"]]["note_reference"] == "x" * 1_001
    assert entries[overlength["id"]]["note_copy_allowed"] is False


def test_recent_entries_require_authoritative_calendar(unconfirmed_client: TestClient) -> None:
    response = unconfirmed_client.get("/api/v1/logs/recent-entries")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "authoritative_time_zone_required"


def test_active_recipe_recent_entry_uses_current_revision_after_republish(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe_id, food = _published(client)
    serving = next(item for item in food["serving_definitions"] if item["is_default"])
    historical = _create_log(client, food)
    first_revision = db_session.get(DailyLog, UUID(historical["id"])).recipe_publication_revision_id

    client.patch(f"/api/v1/recipes/{recipe_id}", json={"name": "Republished recipe"})
    _publish(client, recipe_id)
    response = client.get("/api/v1/logs/recent-entries")

    assert response.status_code == 200, response.text
    entry = next(item for item in response.json()["entries"] if item["id"] == historical["id"])
    assert entry["current_source_loggable"] is True
    active_revision_id = db_session.get(Recipe, UUID(str(recipe_id))).active_publication_revision_id
    assert entry["source_recipe_publication_revision_id"] == str(active_revision_id)
    assert entry["source_recipe_publication_revision_id"] != str(first_revision)
    assert entry["reuse_status"] in {"exact", "equivalent"}
    assert entry["current_amount_definition_id"] is not None
    assert serving["id"] == historical["serving_definition_id"]


def test_inactive_recipe_recent_entry_is_excluded(
    client: TestClient,
) -> None:
    recipe_id, food = _published(client)
    historical = _create_log(client, food)

    deleted = client.delete(f"/api/v1/recipes/{recipe_id}")
    assert deleted.status_code == 204, deleted.text
    response = client.get("/api/v1/logs/recent-entries")

    assert response.status_code == 200, response.text
    assert historical["id"] not in {entry["id"] for entry in response.json()["entries"]}


def test_removed_serving_never_infers_equivalence_from_grams(
    client: TestClient,
) -> None:
    food = create_food(client, "Serving mapping food")
    historical = _create_log(client, food)
    replacement = client.patch(
        f"/api/v1/foods/{food['id']}",
        json={
            "serving_definitions": [
                {
                    "label": "One slice",
                    "quantity": "1",
                    "unit": "slice",
                    "gram_weight": "170",
                    "is_default": True,
                }
            ]
        },
    )
    assert replacement.status_code == 200, replacement.text
    entry = next(
        item for item in client.get("/api/v1/logs/recent-entries").json()["entries"]
        if item["id"] == historical["id"]
    )
    assert entry["serving_definition_id"] is None
    assert entry["current_source_loggable"] is True
    assert entry["reuse_status"] == "unavailable"
    assert entry["current_amount_definition_id"] is None

    ambiguous = client.patch(
        f"/api/v1/foods/{food['id']}",
        json={
            "serving_definitions": [
                {"label": "Cup A", "quantity": "1", "unit": "cup", "gram_weight": "170", "is_default": True},
                {"label": "Cup B", "quantity": "1", "unit": "bowl", "gram_weight": "170", "is_default": False},
            ]
        },
    )
    assert ambiguous.status_code == 200, ambiguous.text
    entry = next(
        item for item in client.get("/api/v1/logs/recent-entries").json()["entries"]
        if item["id"] == historical["id"]
    )
    assert entry["reuse_status"] == "unavailable"
    assert entry["current_amount_definition_id"] is None


def test_recent_entries_read_preserves_historical_log_and_snapshots(
    client: TestClient,
    db_session: Session,
) -> None:
    food = create_food(client, "Immutable recent entry")
    historical = _create_log(client, food)
    stored = db_session.get(DailyLog, UUID(historical["id"]))
    assert stored is not None
    before = (stored.logged_date, stored.amount_quantity, stored.notes)
    snapshot_count = db_session.query(DailyLogNutrientSnapshot).filter_by(daily_log_id=stored.id).count()

    assert client.get("/api/v1/logs/recent-entries").status_code == 200

    db_session.expire_all()
    after = db_session.get(DailyLog, stored.id)
    assert after is not None
    assert (after.logged_date, after.amount_quantity, after.notes) == before
    assert db_session.query(DailyLogNutrientSnapshot).filter_by(daily_log_id=stored.id).count() == snapshot_count
