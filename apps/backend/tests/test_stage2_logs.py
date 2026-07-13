from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.dependencies.user import ensure_dev_user
from app.models.log import DailyLog
from app.repositories.log_repository import LogRepository
from tests.test_stage2_foods import create_food, food_payload


def create_food_with_distinct_servings(client: TestClient) -> dict:
    payload = food_payload("Two Serving Food")
    payload["serving_definitions"] = [
        {
            "label": "1 container",
            "quantity": "1",
            "unit": "container",
            "gram_weight": "200",
            "is_default": True,
        },
        {
            "label": "1 small container",
            "quantity": "1",
            "unit": "container",
            "gram_weight": "100",
            "is_default": False,
        },
    ]
    for nutrient in payload["nutrients"]:
        nutrient["basis"] = "per_100g"
    response = client.post("/api/v1/foods", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_serving_logging_creates_snapshots_and_daily_summary(client: TestClient) -> None:
    food = create_food(client)
    response = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": "2026-07-08",
            "amount_quantity": "2",
            "amount_unit": "serving",
        },
    )
    assert response.status_code == 201, response.text
    log = response.json()
    assert log["food_name_snapshot"] == "Greek Yogurt"
    assert log["is_editable"] is True
    assert log["edit_block_reason"] is None
    protein = next(s for s in log["snapshots"] if s["nutrient_id"] == "protein")
    vitamin_d = next(s for s in log["snapshots"] if s["nutrient_id"] == "vitamin_d")
    added_sugars = next(s for s in log["snapshots"] if s["nutrient_id"] == "added_sugars")

    assert protein["amount"] == "40.000000"
    assert protein["source_food_item_id"] == food["id"]
    assert protein["source_food_nutrient_id"] is not None
    assert protein["serving_definition_id"] == food["serving_definitions"][0]["id"]
    assert protein["consumed_amount_quantity"] == "2.000000"
    assert protein["consumed_gram_amount"] == "340.000000"
    assert vitamin_d["amount"] is None
    assert added_sugars["amount"] == "0.000000"

    summary = client.get("/api/v1/logs/daily-summary", params={"date": "2026-07-08"})
    assert summary.status_code == 200
    totals = {total["nutrient_id"]: total for total in summary.json()["totals"]}
    assert totals["protein"]["amount_known"] == "40.000000"
    assert totals["calcium"]["amount_estimated"] == "360.000000"
    assert totals["vitamin_d"]["has_unknown_contributors"] is True
    assert totals["vitamin_d"]["unknown_contributor_count"] == 1
    assert totals["added_sugars"]["amount_known"] in {"0", "0.000000"}
    assert totals["added_sugars"]["has_unknown_contributors"] is False


def test_gram_logging_allowed_with_serving_gram_weight_and_rejected_without_conversion(
    client: TestClient,
) -> None:
    food = create_food(client)
    allowed = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": "2026-07-08",
            "amount_quantity": "85",
            "amount_unit": "g",
        },
    )
    assert allowed.status_code == 201, allowed.text
    protein = next(s for s in allowed.json()["snapshots"] if s["nutrient_id"] == "protein")
    assert protein["amount"] == "10.000000"

    unresolved_payload = food_payload("No Gram Conversion")
    unresolved_payload["serving_definitions"][0].pop("gram_weight")
    unresolved = client.post("/api/v1/foods", json=unresolved_payload).json()
    rejected = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": unresolved["id"],
            "logged_date": "2026-07-08",
            "amount_quantity": "85",
            "amount_unit": "g",
        },
    )
    assert rejected.status_code == 400


def test_resolved_food_detail_and_log_share_count_only_serving_interpretation(
    client: TestClient,
) -> None:
    payload = food_payload("Count Only")
    payload["serving_definitions"][0].pop("gram_weight")
    food = client.post("/api/v1/foods", json=payload).json()

    detail = client.get(f"/api/v1/foods/{food['id']}/resolved-nutrition")
    assert detail.status_code == 200, detail.text
    amount = detail.json()["amounts"][0]
    detail_protein = next(
        nutrient for nutrient in amount["nutrients"] if nutrient["nutrient_id"] == "protein"
    )
    assert amount["semantic_amount_mode"] == "serving"
    assert amount["amount_definition_id"] == food["serving_definitions"][0]["id"]
    assert amount["entered_quantity"] == "1"
    assert amount["resolved_grams"] is None
    assert detail_protein["amount"] == "20.000000"

    log = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": "2026-07-08",
            "amount_quantity": amount["entered_quantity"],
            "amount_unit": amount["semantic_amount_mode"],
            "serving_definition_id": amount["amount_definition_id"],
        },
    )
    assert log.status_code == 201, log.text
    snapshot = next(
        snapshot for snapshot in log.json()["snapshots"] if snapshot["nutrient_id"] == "protein"
    )
    assert snapshot["amount"] == detail_protein["amount"] == "20.000000"
    assert snapshot["unit"] == detail_protein["unit"] == "g"
    assert snapshot["data_status"] == detail_protein["data_status"] == "known"


def test_log_patch_omitting_serving_definition_preserves_non_default_selection(
    client: TestClient,
) -> None:
    food = create_food_with_distinct_servings(client)
    non_default = next(
        serving for serving in food["serving_definitions"] if not serving["is_default"]
    )
    log = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": "2026-07-08",
            "amount_quantity": "1",
            "amount_unit": "serving",
            "serving_definition_id": non_default["id"],
        },
    ).json()

    updated = client.patch(f"/api/v1/logs/{log['id']}", json={"notes": "still the small one"})

    assert updated.status_code == 200, updated.text
    result = updated.json()
    protein = next(
        snapshot for snapshot in result["snapshots"] if snapshot["nutrient_id"] == "protein"
    )
    assert result["notes"] == "still the small one"
    assert result["serving_definition_id"] == non_default["id"]
    assert result["gram_amount"] == "100.000000"
    assert protein["serving_definition_id"] == non_default["id"]
    assert protein["consumed_gram_amount"] == "100.000000"
    assert protein["amount"] == "20.000000"


def test_log_patch_explicit_serving_definition_recalculates_snapshots(
    client: TestClient,
) -> None:
    food = create_food_with_distinct_servings(client)
    default = next(serving for serving in food["serving_definitions"] if serving["is_default"])
    non_default = next(
        serving for serving in food["serving_definitions"] if not serving["is_default"]
    )
    log = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": "2026-07-08",
            "amount_quantity": "1",
            "amount_unit": "serving",
            "serving_definition_id": non_default["id"],
        },
    ).json()

    updated = client.patch(
        f"/api/v1/logs/{log['id']}",
        json={"serving_definition_id": default["id"]},
    )

    assert updated.status_code == 200, updated.text
    result = updated.json()
    protein = next(
        snapshot for snapshot in result["snapshots"] if snapshot["nutrient_id"] == "protein"
    )
    assert result["serving_definition_id"] == default["id"]
    assert result["gram_amount"] == "200.000000"
    assert protein["serving_definition_id"] == default["id"]
    assert protein["consumed_gram_amount"] == "200.000000"
    assert protein["amount"] == "40.000000"


def test_log_patch_explicit_null_is_not_treated_as_omitted(client: TestClient) -> None:
    food = create_food_with_distinct_servings(client)
    default = next(serving for serving in food["serving_definitions"] if serving["is_default"])
    non_default = next(
        serving for serving in food["serving_definitions"] if not serving["is_default"]
    )
    log = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": "2026-07-08",
            "amount_quantity": "1",
            "amount_unit": "serving",
            "serving_definition_id": non_default["id"],
        },
    ).json()

    updated = client.patch(
        f"/api/v1/logs/{log['id']}",
        json={"serving_definition_id": None},
    )

    assert updated.status_code == 200, updated.text
    result = updated.json()
    protein = next(
        snapshot for snapshot in result["snapshots"] if snapshot["nutrient_id"] == "protein"
    )
    # Existing resolver semantics interpret an explicit null as selecting the
    # food's default serving; omission is what preserves the logged serving.
    assert result["serving_definition_id"] == default["id"]
    assert result["gram_amount"] == "200.000000"
    assert protein["serving_definition_id"] == default["id"]
    assert protein["amount"] == "40.000000"


def test_food_edits_do_not_change_historical_totals_and_log_update_rebuilds_snapshots(
    client: TestClient,
) -> None:
    food = create_food(client)
    log = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": "2026-07-08",
            "amount_quantity": "1",
            "amount_unit": "serving",
        },
    ).json()

    edited = food_payload("Greek Yogurt")
    edited["nutrients"][1]["amount"] = "30"
    assert client.patch(f"/api/v1/foods/{food['id']}", json=edited).status_code == 200
    logs_after_rename = client.get("/api/v1/logs", params={"date": "2026-07-08"}).json()["logs"]
    assert next(item for item in logs_after_rename if item["id"] == log["id"])["food_name_snapshot"] == "Greek Yogurt"

    summary = client.get("/api/v1/logs/daily-summary", params={"date": "2026-07-08"}).json()
    protein = next(total for total in summary["totals"] if total["nutrient_id"] == "protein")
    assert protein["amount_known"] == "20.000000"

    updated_log = client.patch(
        f"/api/v1/logs/{log['id']}",
        json={"amount_quantity": "2", "amount_unit": "serving"},
    )
    assert updated_log.status_code == 200, updated_log.text
    protein_snapshot = next(
        snapshot for snapshot in updated_log.json()["snapshots"] if snapshot["nutrient_id"] == "protein"
    )
    assert protein_snapshot["amount"] == "60.000000"

    summary_after_update = client.get(
        "/api/v1/logs/daily-summary", params={"date": "2026-07-08"}
    ).json()
    protein_after_update = next(
        total for total in summary_after_update["totals"] if total["nutrient_id"] == "protein"
    )
    assert protein_after_update["amount_known"] == "60.000000"


def test_food_delete_does_not_remove_historical_log_name_or_snapshots(client: TestClient) -> None:
    food = create_food(client, "Distinct Food")
    log_response = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": "2026-07-08",
            "amount_quantity": "1",
            "amount_unit": "serving",
        },
    )
    assert log_response.status_code == 201, log_response.text
    log = log_response.json()
    before_summary = client.get("/api/v1/logs/daily-summary", params={"date": "2026-07-08"}).json()

    delete = client.delete(f"/api/v1/foods/{food['id']}")
    assert delete.status_code == 200, delete.text

    logs = client.get("/api/v1/logs", params={"date": "2026-07-08"}).json()["logs"]
    historical = next(item for item in logs if item["id"] == log["id"])
    assert historical["food_name_snapshot"] == "Distinct Food"
    assert historical["is_editable"] is False
    assert historical["edit_block_reason"] == "source_food_deleted"
    assert historical["snapshots"] == log["snapshots"]
    assert client.get("/api/v1/logs/daily-summary", params={"date": "2026-07-08"}).json() == before_summary

    failed_update = client.patch(
        f"/api/v1/logs/{log['id']}",
        json={"amount_quantity": "2", "amount_unit": "serving"},
    )
    assert failed_update.status_code == 409
    assert failed_update.json() == {
        "detail": {
            "code": "source_food_deleted",
            "message": "This historical entry cannot be edited because its source food was deleted.",
        }
    }

    unchanged = client.get("/api/v1/logs", params={"date": "2026-07-08"}).json()["logs"][0]
    assert unchanged["amount_quantity"] == log["amount_quantity"]
    assert unchanged["food_name_snapshot"] == log["food_name_snapshot"]
    assert unchanged["snapshots"] == log["snapshots"]
    assert client.delete(f"/api/v1/logs/{log['id']}").status_code == 204


def test_older_log_without_food_name_snapshot_still_serializes(client: TestClient, db_session: Session) -> None:
    food = create_food(client, "Legacy Food")
    log = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": "2026-07-08",
            "amount_quantity": "1",
            "amount_unit": "serving",
        },
    ).json()
    db_log = db_session.get(DailyLog, log["id"])
    assert db_log is not None
    db_log.food_name_snapshot = None
    db_session.commit()

    historical = client.get("/api/v1/logs", params={"date": "2026-07-08"}).json()["logs"][0]
    assert historical["food_name_snapshot"] is None


def test_log_list_batches_source_food_editability_lookup(client: TestClient, db_session: Session) -> None:
    for name in ("First Food", "Second Food"):
        food = create_food(client, name)
        response = client.post(
            "/api/v1/logs",
            json={
                "food_item_id": food["id"],
                "logged_date": "2026-07-08",
                "amount_quantity": "1",
                "amount_unit": "serving",
            },
        )
        assert response.status_code == 201

    db_session.expire_all()
    user_id = ensure_dev_user(db_session).id
    select_count = 0

    def count_selects(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:
        nonlocal select_count
        if statement.lstrip().upper().startswith("SELECT"):
            select_count += 1

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", count_selects)
    try:
        logs = LogRepository(db_session).list_for_date(
            user_id,
            date(2026, 7, 8),
        )
        editability = [log.is_editable for log in logs]
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)

    assert editability == [True, True]
    assert select_count == 3


def test_editing_logged_food_preserves_snapshots_with_nullable_deleted_provenance(
    client: TestClient,
) -> None:
    food = create_food(client)
    log = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": "2026-07-08",
            "amount_quantity": "1",
            "amount_unit": "serving",
        },
    ).json()

    edited = food_payload("Greek Yogurt")
    edited["serving_definitions"] = [
        {
            "label": "1 container",
            "quantity": "1",
            "unit": "container",
            "gram_weight": "200",
            "is_default": True,
        }
    ]
    edited["nutrients"][1]["amount"] = "35"
    update = client.patch(f"/api/v1/foods/{food['id']}", json=edited)
    assert update.status_code == 200, update.text

    logs = client.get("/api/v1/logs", params={"date": "2026-07-08"}).json()["logs"]
    historical_log = next(item for item in logs if item["id"] == log["id"])
    assert historical_log["serving_definition_id"] is None
    assert len(historical_log["snapshots"]) == len(log["snapshots"])
    assert all(snapshot["source_food_item_id"] == food["id"] for snapshot in historical_log["snapshots"])
    assert any(snapshot["source_food_nutrient_id"] is None for snapshot in historical_log["snapshots"])
    assert any(snapshot["serving_definition_id"] is None for snapshot in historical_log["snapshots"])

    summary = client.get("/api/v1/logs/daily-summary", params={"date": "2026-07-08"}).json()
    protein = next(total for total in summary["totals"] if total["nutrient_id"] == "protein")
    assert protein["amount_known"] == "20.000000"


def test_log_delete_removes_snapshots_from_daily_summary(client: TestClient) -> None:
    food = create_food(client)
    log = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": "2026-07-08",
            "amount_quantity": "1",
            "amount_unit": "serving",
        },
    ).json()
    assert client.delete(f"/api/v1/logs/{log['id']}").status_code == 204
    summary = client.get("/api/v1/logs/daily-summary", params={"date": "2026-07-08"})
    assert summary.status_code == 200
    assert summary.json()["totals"] == []
