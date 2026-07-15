from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dependencies.user import ensure_dev_user
from app.models.create_idempotency import CreateOperationIdempotency
from app.models.food import FoodItem, ServingDefinition
from app.models.recipe import Recipe
from app.models.recipe_publication import RecipePublicationRevision
from app.models.user import User
from app.schemas.food import FoodCreateRequest
from app.services.create_idempotency import is_create_idempotency_conflict
from app.services.food_service import FoodService
from tests.test_stage2_foods import food_payload


def test_manual_food_replay_returns_original_and_payload_mismatch_conflicts(
    client: TestClient,
) -> None:
    request_id = str(uuid4())
    payload = {**food_payload("Retry Food"), "client_request_id": request_id}

    first = client.post("/api/v1/foods", json=payload)
    replay = client.post("/api/v1/foods", json=payload)
    changed = client.post("/api/v1/foods", json={**payload, "name": "Different"})

    assert first.status_code == replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]
    assert changed.status_code == 409
    assert changed.json()["detail"]["code"] == "create_idempotency_payload_conflict"


def test_semantically_equal_decimal_spellings_replay(client: TestClient) -> None:
    request_id = str(uuid4())
    first_payload = {**food_payload("Decimal Retry"), "client_request_id": request_id}
    equivalent_payload = {**first_payload}
    equivalent_payload["serving_definitions"] = [
        {**first_payload["serving_definitions"][0], "quantity": "1.000000"}
    ]

    first = client.post("/api/v1/foods", json=first_payload)
    replay = client.post("/api/v1/foods", json=equivalent_payload)

    assert first.status_code == replay.status_code == 201
    assert first.json()["id"] == replay.json()["id"]


def test_duplicate_and_serving_create_replay_without_duplicate_rows(
    client: TestClient,
    db_session: Session,
) -> None:
    source = client.post("/api/v1/foods", json=food_payload("Source")).json()
    duplicate_request_id = str(uuid4())
    duplicate_body = {"client_request_id": duplicate_request_id}
    first_duplicate = client.post(
        f"/api/v1/foods/{source['id']}/duplicate", json=duplicate_body
    )
    replay_duplicate = client.post(
        f"/api/v1/foods/{source['id']}/duplicate", json=duplicate_body
    )
    assert first_duplicate.status_code == replay_duplicate.status_code == 201
    assert first_duplicate.json()["id"] == replay_duplicate.json()["id"]

    serving_request_id = str(uuid4())
    serving = {
        "client_request_id": serving_request_id,
        "label": "1 retry portion",
        "quantity": "1",
        "unit": "portion",
        "gram_weight": "42",
        "is_default": False,
    }
    first_serving = client.post(
        f"/api/v1/foods/{source['id']}/serving-definitions", json=serving
    )
    replay_serving = client.post(
        f"/api/v1/foods/{source['id']}/serving-definitions", json=serving
    )
    assert first_serving.status_code == replay_serving.status_code == 201
    assert first_serving.json()["id"] == replay_serving.json()["id"]
    assert db_session.scalar(
        select(func.count(ServingDefinition.id)).where(
            ServingDefinition.food_item_id == source["id"],
            ServingDefinition.label == "1 retry portion",
        )
    ) == 1


def test_recipe_create_and_publish_replay_preserve_single_revision(
    client: TestClient,
    db_session: Session,
) -> None:
    create_request_id = str(uuid4())
    payload = {
        "client_request_id": create_request_id,
        "name": "Retry Recipe",
        "serving_count_yield": "2",
        "ingredients": [],
    }
    first = client.post("/api/v1/recipes", json=payload)
    replay = client.post("/api/v1/recipes", json=payload)
    assert first.status_code == replay.status_code == 201
    assert first.json()["id"] == replay.json()["id"]

    publish_body = {"client_request_id": str(uuid4())}
    first_publish = client.post(
        f"/api/v1/recipes/{first.json()['id']}/publish", json=publish_body
    )
    replay_publish = client.post(
        f"/api/v1/recipes/{first.json()['id']}/publish", json=publish_body
    )
    assert first_publish.status_code == replay_publish.status_code == 200
    assert first_publish.json()["food"]["id"] == replay_publish.json()["food"]["id"]
    assert db_session.scalar(
        select(func.count(RecipePublicationRevision.id)).where(
            RecipePublicationRevision.recipe_id == first.json()["id"]
        )
    ) == 1


def test_failed_create_rolls_back_receipt_and_retry_can_succeed(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = ensure_dev_user(db_session)
    request_id = uuid4()
    payload = FoodCreateRequest(
        **{**food_payload("Rollback Retry"), "client_request_id": request_id}
    )
    service = FoodService(db_session)
    original_add = service.foods.add

    def fail_after_reservation(_food: FoodItem) -> FoodItem:
        raise RuntimeError("injected failure")

    monkeypatch.setattr(service.foods, "add", fail_after_reservation)
    with pytest.raises(RuntimeError, match="injected failure"):
        service.create_manual_food(user.id, payload)
    assert db_session.scalar(select(func.count(CreateOperationIdempotency.id))) == 0

    monkeypatch.setattr(service.foods, "add", original_add)
    created = service.create_manual_food(user.id, payload)
    assert created.name == "Rollback Retry"
    assert db_session.scalar(select(func.count(CreateOperationIdempotency.id))) == 1


def test_same_request_id_is_isolated_by_owner(db_session: Session) -> None:
    first_user = ensure_dev_user(db_session)
    second_user = User(id=uuid4(), email="idempotency-other@example.test")
    db_session.add(second_user)
    db_session.commit()
    request_id = uuid4()
    payload = FoodCreateRequest(
        **{**food_payload("Owner Scoped"), "client_request_id": request_id}
    )

    first = FoodService(db_session).create_manual_food(first_user.id, payload)
    second = FoodService(db_session).create_manual_food(second_user.id, payload)

    assert first.id != second.id
    assert db_session.scalar(select(func.count(FoodItem.id))) == 2


def test_unrelated_integrity_error_is_not_classified_as_idempotency() -> None:
    error = IntegrityError(
        "insert",
        {},
        Exception("UNIQUE constraint failed: users.email"),
    )
    assert is_create_idempotency_conflict(error) is False


def test_operation_namespace_allows_same_request_id_for_distinct_creates(
    client: TestClient,
    db_session: Session,
) -> None:
    request_id = str(uuid4())
    food = client.post(
        "/api/v1/foods",
        json={**food_payload("Namespace Food"), "client_request_id": request_id},
    )
    recipe = client.post(
        "/api/v1/recipes",
        json={
            "name": "Namespace Recipe",
            "serving_count_yield": "1",
            "ingredients": [],
            "client_request_id": request_id,
        },
    )
    assert food.status_code == recipe.status_code == 201
    assert db_session.scalar(select(func.count(Recipe.id))) == 1
    assert db_session.scalar(select(func.count(CreateOperationIdempotency.id))) == 2
    receipts = list(db_session.scalars(select(CreateOperationIdempotency)).all())
    assert all(receipt.response_snapshot is not None for receipt in receipts)
    assert all(receipt.completed_at is not None for receipt in receipts)


def test_food_replay_is_original_snapshot_then_becomes_unavailable_after_archive(
    client: TestClient,
) -> None:
    request_id = str(uuid4())
    create_payload = {
        **food_payload("Original Food Response"),
        "client_request_id": request_id,
    }
    first = client.post("/api/v1/foods", json=create_payload)
    assert first.status_code == 201
    food_id = first.json()["id"]

    updated = food_payload("Updated After Create")
    assert client.patch(f"/api/v1/foods/{food_id}", json=updated).status_code == 200
    replay = client.post("/api/v1/foods", json=create_payload)
    assert replay.status_code == 201
    assert replay.json() == first.json()

    assert client.delete(f"/api/v1/foods/{food_id}").status_code == 200
    unavailable = client.post("/api/v1/foods", json=create_payload)
    assert unavailable.status_code == 409
    assert unavailable.json()["detail"]["code"] == "create_idempotency_result_unavailable"


def test_recipe_create_replay_is_original_snapshot_then_unavailable_after_archive(
    client: TestClient,
) -> None:
    request_id = str(uuid4())
    payload = {
        "client_request_id": request_id,
        "name": "Original Recipe Response",
        "serving_count_yield": "2",
        "ingredients": [],
    }
    first = client.post("/api/v1/recipes", json=payload)
    recipe_id = first.json()["id"]
    assert client.patch(
        f"/api/v1/recipes/{recipe_id}", json={"name": "Changed Recipe"}
    ).status_code == 200
    replay = client.post("/api/v1/recipes", json=payload)
    assert replay.status_code == 201
    assert replay.json() == first.json()

    assert client.delete(f"/api/v1/recipes/{recipe_id}").status_code == 204
    unavailable = client.post("/api/v1/recipes", json=payload)
    assert unavailable.status_code == 409
    assert unavailable.json()["detail"]["code"] == "create_idempotency_result_unavailable"


def test_serving_replay_is_unavailable_if_exact_created_serving_was_replaced(
    client: TestClient,
) -> None:
    food = client.post("/api/v1/foods", json=food_payload("Serving Parent")).json()
    request_id = str(uuid4())
    serving_payload = {
        "client_request_id": request_id,
        "label": "Created Portion",
        "quantity": "1",
        "unit": "portion",
        "gram_weight": "40",
        "is_default": False,
    }
    created = client.post(
        f"/api/v1/foods/{food['id']}/serving-definitions", json=serving_payload
    )
    assert created.status_code == 201
    assert client.patch(
        f"/api/v1/foods/{food['id']}", json={"name": "Renamed Serving Parent"}
    ).status_code == 200
    replay = client.post(
        f"/api/v1/foods/{food['id']}/serving-definitions", json=serving_payload
    )
    assert replay.json() == created.json()
    replacement = food_payload("Serving Parent")
    assert client.patch(f"/api/v1/foods/{food['id']}", json=replacement).status_code == 200

    unavailable = client.post(
        f"/api/v1/foods/{food['id']}/serving-definitions", json=serving_payload
    )
    assert unavailable.status_code == 409
    assert unavailable.json()["detail"]["code"] == "create_idempotency_result_unavailable"


def test_duplicate_replay_is_original_snapshot_then_unavailable_after_archive(
    client: TestClient,
) -> None:
    source = client.post("/api/v1/foods", json=food_payload("Duplicate Source")).json()
    body = {"client_request_id": str(uuid4())}
    first = client.post(f"/api/v1/foods/{source['id']}/duplicate", json=body)
    duplicate_id = first.json()["id"]
    assert client.patch(
        f"/api/v1/foods/{duplicate_id}", json={"name": "Changed Duplicate"}
    ).status_code == 200
    replay = client.post(f"/api/v1/foods/{source['id']}/duplicate", json=body)
    assert replay.json() == first.json()

    assert client.delete(f"/api/v1/foods/{duplicate_id}").status_code == 200
    unavailable = client.post(f"/api/v1/foods/{source['id']}/duplicate", json=body)
    assert unavailable.status_code == 409
    assert unavailable.json()["detail"]["code"] == "create_idempotency_result_unavailable"


def test_publication_replay_after_later_publication_returns_exact_original_result(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe = client.post(
        "/api/v1/recipes",
        json={"name": "First Publication", "serving_count_yield": "1", "ingredients": []},
    ).json()
    first_request = str(uuid4())
    first = client.post(
        f"/api/v1/recipes/{recipe['id']}/publish",
        json={"client_request_id": first_request},
    )
    assert first.status_code == 200

    assert client.patch(
        f"/api/v1/recipes/{recipe['id']}", json={"name": "Second Publication"}
    ).status_code == 200
    second = client.post(
        f"/api/v1/recipes/{recipe['id']}/publish",
        json={"client_request_id": str(uuid4())},
    )
    assert second.status_code == 200
    assert second.json()["recipe"]["name"] == "Second Publication"

    replay = client.post(
        f"/api/v1/recipes/{recipe['id']}/publish",
        json={"client_request_id": first_request},
    )
    assert replay.status_code == 200
    assert replay.json() == first.json()
    receipt = db_session.scalar(
        select(CreateOperationIdempotency).where(
            CreateOperationIdempotency.operation == "recipe.publish",
            CreateOperationIdempotency.client_request_id == first_request,
        )
    )
    assert receipt is not None
    first_revision = db_session.get(RecipePublicationRevision, receipt.resource_id)
    assert first_revision is not None
    assert first_revision.revision_number == 1

    assert client.delete(f"/api/v1/recipes/{recipe['id']}").status_code == 204
    unavailable = client.post(
        f"/api/v1/recipes/{recipe['id']}/publish",
        json={"client_request_id": first_request},
    )
    assert unavailable.status_code == 409
    assert unavailable.json()["detail"]["code"] == "create_idempotency_result_unavailable"


@pytest.mark.parametrize(
    "path,payload",
    [
        ("/api/v1/foods", food_payload("Malformed Request ID")),
        (
            "/api/v1/recipes",
            {"name": "Malformed Request ID", "serving_count_yield": "1", "ingredients": []},
        ),
    ],
)
def test_create_request_ids_require_valid_uuids(
    client: TestClient, path: str, payload: dict
) -> None:
    response = client.post(path, json={**payload, "client_request_id": "x" * 10_000})
    assert response.status_code == 422
