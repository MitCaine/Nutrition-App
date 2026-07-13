from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.dependencies.user import ensure_dev_user
from app.models.log import DailyLog
from app.models.recipe import Recipe
from app.repositories.recipe_publication_repository import RecipePublicationRepository
from app.schemas.log import DailyLogCreateRequest, DailyLogUpdateRequest
from app.services.log_service import LogService
from tests.test_recipe_revision_capture import _published_recipe as _legacy_published_recipe
from tests.test_recipe_revision_logging import _post_log, _published, _stored_log


def _default_serving(food: dict) -> dict:
    return next(value for value in food["serving_definitions"] if value["is_default"])


def _create_serving_log(client: TestClient, db: Session, **published_kwargs) -> tuple[UUID, dict, DailyLog]:
    recipe_id, food = _published(client, **published_kwargs)
    response = _post_log(client, food, serving_definition_id=_default_serving(food)["id"])
    assert response.status_code == 201, response.text
    return recipe_id, food, _stored_log(db, response)


def _snapshot_state(log: DailyLog) -> tuple:
    return tuple(
        sorted(
            (
                snapshot.id,
                snapshot.nutrient_id,
                snapshot.amount,
                snapshot.unit,
                snapshot.data_status,
                snapshot.consumed_amount_quantity,
                snapshot.consumed_amount_unit,
            )
            for snapshot in log.snapshots
        )
    )


def _protein_amount(log: DailyLog) -> Decimal | None:
    return next(row.amount for row in log.snapshots if row.nutrient_id == "protein")


def test_metadata_only_edit_preserves_revision_amount_and_snapshot_rows(
    client: TestClient,
    db_session: Session,
) -> None:
    _, _, log = _create_serving_log(client, db_session)
    revision_id = log.recipe_publication_revision_id
    amount_id = log.recipe_publication_amount_definition_id
    snapshots = _snapshot_state(log)

    response = client.patch(
        f"/api/v1/logs/{log.id}",
        json={"notes": "metadata only", "meal_type": "dinner"},
    )

    assert response.status_code == 200, response.text
    updated = _stored_log(db_session, response)
    assert updated.notes == "metadata only"
    assert updated.meal_type == "dinner"
    assert updated.recipe_publication_revision_id == revision_id
    assert updated.recipe_publication_amount_definition_id == amount_id
    assert _snapshot_state(updated) == snapshots


def test_quantity_edit_reuses_stored_revision_amount_and_regenerates_snapshots(
    client: TestClient,
    db_session: Session,
) -> None:
    _, _, log = _create_serving_log(client, db_session)
    revision_id = log.recipe_publication_revision_id
    amount_id = log.recipe_publication_amount_definition_id
    old_snapshot_ids = {row.id for row in log.snapshots}
    old_protein = _protein_amount(log)

    response = client.patch(f"/api/v1/logs/{log.id}", json={"amount_quantity": "2"})

    assert response.status_code == 200, response.text
    updated = _stored_log(db_session, response)
    assert updated.recipe_publication_revision_id == revision_id
    assert updated.recipe_publication_amount_definition_id == amount_id
    assert updated.amount_quantity == Decimal("2")
    assert {row.id for row in updated.snapshots}.isdisjoint(old_snapshot_ids)
    assert _protein_amount(updated) == old_protein * 2


def test_semantic_amount_change_selects_definition_inside_stored_revision(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe_id, _, log = _create_serving_log(client, db_session)
    revision = RecipePublicationRepository(db_session).get_required(
        log.recipe_publication_revision_id,
        db_session.get(Recipe, recipe_id).user_id,
    )
    canonical_gram = next(
        amount for amount in revision.amount_definitions if amount.semantic_mode == "g"
    )

    response = client.patch(
        f"/api/v1/logs/{log.id}",
        json={
            "amount_quantity": "50",
            "amount_unit": "g",
            "serving_definition_id": str(canonical_gram.id),
        },
    )

    assert response.status_code == 200, response.text
    updated = _stored_log(db_session, response)
    assert updated.recipe_publication_revision_id == revision.id
    assert updated.recipe_publication_amount_definition_id == canonical_gram.id
    assert updated.serving_definition_id is None
    assert updated.amount_unit == "g"
    assert updated.gram_amount == Decimal("50")


def test_gram_quantity_edit_reuses_canonical_definition_without_creating_amounts(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe_id, food = _published(client)
    hundred_grams = next(
        value for value in food["serving_definitions"] if value["label"] == "100 g"
    )
    created = _post_log(
        client,
        food,
        amount_quantity="37",
        amount_unit="g",
        serving_definition_id=hundred_grams["id"],
    )
    log = _stored_log(db_session, created)
    amount_id = log.recipe_publication_amount_definition_id
    revision = RecipePublicationRepository(db_session).get_required(
        log.recipe_publication_revision_id,
        db_session.get(Recipe, recipe_id).user_id,
    )
    amount_ids = {amount.id for amount in revision.amount_definitions}

    response = client.patch(f"/api/v1/logs/{log.id}", json={"amount_quantity": "83.5"})

    assert response.status_code == 200, response.text
    updated = _stored_log(db_session, response)
    db_session.expire_all()
    revision = RecipePublicationRepository(db_session).get_required(
        updated.recipe_publication_revision_id,
        db_session.get(Recipe, recipe_id).user_id,
    )
    assert updated.recipe_publication_amount_definition_id == amount_id
    assert updated.gram_amount == Decimal("83.5")
    assert {amount.id for amount in revision.amount_definitions} == amount_ids


def test_count_only_revision_allows_serving_edit_and_rejects_gram_edit(
    client: TestClient,
    db_session: Session,
) -> None:
    _, _, log = _create_serving_log(client, db_session, cooked_grams=None)
    revision_id = log.recipe_publication_revision_id
    amount_id = log.recipe_publication_amount_definition_id

    serving = client.patch(f"/api/v1/logs/{log.id}", json={"amount_quantity": "2"})
    gram = client.patch(
        f"/api/v1/logs/{log.id}",
        json={"amount_quantity": "20", "amount_unit": "g", "serving_definition_id": None},
    )

    assert serving.status_code == 200, serving.text
    assert gram.status_code == 400
    assert gram.json()["detail"]["code"] == "recipe_log_conversion_unsupported"
    db_session.expire_all()
    unchanged = db_session.get(DailyLog, log.id)
    assert unchanged.recipe_publication_revision_id == revision_id
    assert unchanged.recipe_publication_amount_definition_id == amount_id
    assert unchanged.amount_quantity == Decimal("2")


def test_edit_after_republish_uses_original_revision_not_active_revision(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe_id, _, log = _create_serving_log(client, db_session)
    revision_one = log.recipe_publication_revision_id
    update = client.patch(
        f"/api/v1/recipes/{recipe_id}",
        json={"serving_count_yield": "4"},
    )
    assert update.status_code == 200, update.text
    republished = client.post(f"/api/v1/recipes/{recipe_id}/publish")
    assert republished.status_code == 200, republished.text
    db_session.expire_all()
    revision_two = db_session.get(Recipe, recipe_id).active_publication_revision_id

    response = client.patch(f"/api/v1/logs/{log.id}", json={"amount_quantity": "2"})

    assert response.status_code == 200, response.text
    updated = _stored_log(db_session, response)
    assert revision_two != revision_one
    assert updated.recipe_publication_revision_id == revision_one
    assert _protein_amount(updated) == Decimal("5")


def test_projection_serving_rename_and_republish_do_not_affect_historical_edit(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe_id, food, log = _create_serving_log(client, db_session)
    revision_id = log.recipe_publication_revision_id
    projection = db_session.get(Recipe, recipe_id).published_food_item
    default = next(value for value in projection.serving_definitions if value.is_default)
    default.label = "Renamed Slice"
    db_session.commit()
    recipe_update = client.patch(f"/api/v1/recipes/{recipe_id}", json={"notes": "republish"})
    assert recipe_update.status_code == 200, recipe_update.text
    assert client.post(f"/api/v1/recipes/{recipe_id}/publish").status_code == 200

    response = client.patch(f"/api/v1/logs/{log.id}", json={"amount_quantity": "1.5"})

    assert response.status_code == 200, response.text
    updated = _stored_log(db_session, response)
    assert updated.food_item_id == UUID(food["id"])
    assert updated.recipe_publication_revision_id == revision_id
    assert updated.amount_quantity == Decimal("1.5")


def test_deleted_projection_does_not_block_revision_aware_edit(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe_id, _, log = _create_serving_log(client, db_session)
    assert client.delete(f"/api/v1/recipes/{recipe_id}").status_code == 204

    response = client.patch(f"/api/v1/logs/{log.id}", json={"amount_quantity": "2"})

    assert response.status_code == 200, response.text
    assert response.json()["is_editable"] is True
    assert response.json()["edit_block_reason"] is None
    updated = _stored_log(db_session, response)
    assert updated.recipe_publication_revision_id == log.recipe_publication_revision_id
    assert updated.amount_quantity == Decimal("2")


def test_missing_stored_revision_returns_structured_validation(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, log = _create_serving_log(client, db_session)

    def missing(_self, _revision_id, _user_id):
        return None

    monkeypatch.setattr(RecipePublicationRepository, "get", missing)
    response = client.patch(f"/api/v1/logs/{log.id}", json={"notes": "blocked"})

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "recipe_log_revision_missing",
        "message": "This entry's publication revision is no longer available.",
    }


def test_missing_stored_amount_returns_structured_validation(
    client: TestClient,
    db_session: Session,
) -> None:
    _, _, log = _create_serving_log(client, db_session)
    log.recipe_publication_amount_definition_id = uuid4()

    response = client.patch(f"/api/v1/logs/{log.id}", json={"amount_quantity": "2"})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "recipe_log_amount_definition_missing"


def test_requested_serving_outside_stored_revision_is_rejected(
    client: TestClient,
    db_session: Session,
) -> None:
    _, _, log = _create_serving_log(client, db_session)
    revision_id = log.recipe_publication_revision_id
    amount_id = log.recipe_publication_amount_definition_id

    response = client.patch(
        f"/api/v1/logs/{log.id}",
        json={"serving_definition_id": str(uuid4())},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "recipe_log_serving_not_in_revision",
        "message": "The selected amount is not available in this entry's publication revision.",
    }
    db_session.expire_all()
    unchanged = db_session.get(DailyLog, log.id)
    assert unchanged.recipe_publication_revision_id == revision_id
    assert unchanged.recipe_publication_amount_definition_id == amount_id


@pytest.mark.parametrize(
    "seam",
    [
        "_after_edit_revision_lookup",
        "_after_edit_amount_lookup",
        "_after_edit_snapshot_regeneration",
    ],
)
def test_revision_edit_failures_roll_back_all_changes(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    seam: str,
) -> None:
    _, _, log = _create_serving_log(client, db_session)
    original = (
        log.notes,
        log.amount_quantity,
        log.recipe_publication_revision_id,
        log.recipe_publication_amount_definition_id,
        _snapshot_state(log),
    )
    user = ensure_dev_user(db_session)
    service = LogService(db_session)

    def fail(*_args) -> None:
        raise RuntimeError("injected edit failure")

    monkeypatch.setattr(service, seam, fail)
    with pytest.raises(RuntimeError, match="injected edit failure"):
        service.update_log(
            user.id,
            log.id,
            DailyLogUpdateRequest(amount_quantity=Decimal("2"), notes="must roll back"),
        )

    db_session.expire_all()
    unchanged = db_session.get(DailyLog, log.id)
    assert (
        unchanged.notes,
        unchanged.amount_quantity,
        unchanged.recipe_publication_revision_id,
        unchanged.recipe_publication_amount_definition_id,
        _snapshot_state(unchanged),
    ) == original


def test_legacy_recipe_log_remains_on_compatibility_edit_path(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe, projection = _legacy_published_recipe(client, db_session)
    serving = next(value for value in projection.serving_definitions if value.is_default)
    user = ensure_dev_user(db_session)
    service = LogService(db_session)
    legacy = service._create_food_log(
        user.id,
        projection,
        DailyLogCreateRequest(
            food_item_id=projection.id,
            logged_date=date(2026, 7, 13),
            amount_quantity=Decimal("1"),
            amount_unit="serving",
            serving_definition_id=serving.id,
        ),
    )
    service.logs.add(legacy)
    db_session.commit()

    response = client.patch(f"/api/v1/logs/{legacy.id}", json={"amount_quantity": "2"})

    assert response.status_code == 200, response.text
    updated = _stored_log(db_session, response)
    assert recipe.active_publication_revision_id is None
    assert updated.recipe_publication_revision_id is None
    assert updated.recipe_publication_amount_definition_id is None
    assert updated.amount_quantity == Decimal("2")
