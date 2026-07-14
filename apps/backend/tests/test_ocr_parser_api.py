from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dependencies.user import DEV_USER_ID, ensure_dev_user
from app.models.food import FoodItem
from app.models.user import User


def valid_payload() -> dict:
    return {
        "full_text": "Nutrition Facts\nServing size 1 bar (40g)\nCalories 180\nProtein 6g",
        "observations": [
            {"id": "obs-1", "text": "Nutrition Facts", "confidence": 0.99},
            {"id": "obs-2", "text": "Serving size 1 bar (40g)", "confidence": 0.98},
            {"id": "obs-3", "text": "Calories 180", "confidence": 0.99},
            {"id": "obs-4", "text": "Protein 6g", "confidence": 0.97},
        ],
    }


def assert_structured_bad_request(response) -> None:
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_ocr_parse_request"
    assert detail["errors"]


def test_parse_endpoint_returns_deterministic_non_persisted_draft(
    client: TestClient,
    db_session: Session,
) -> None:
    ensure_dev_user(db_session)
    db_session.commit()
    before_foods = db_session.scalar(select(func.count()).select_from(FoodItem))

    first = client.post("/api/v1/ocr/nutrition-label/parse", json=valid_payload())
    second = client.post("/api/v1/ocr/nutrition-label/parse", json=valid_payload())

    assert first.status_code == 200, first.text
    assert first.json() == second.json()
    assert first.json()["parser_version"] == "nutrition_label_v1"
    assert first.json()["calories"]["value"] == "180"
    assert first.json()["nutrients"][0]["nutrient_id"] == "protein"
    assert db_session.scalar(select(func.count()).select_from(FoodItem)) == before_foods
    assert db_session.get(User, DEV_USER_ID) is not None


def test_parse_endpoint_rejects_malformed_observation(client: TestClient) -> None:
    payload = valid_payload()
    payload["observations"][0].pop("id")
    assert_structured_bad_request(
        client.post("/api/v1/ocr/nutrition-label/parse", json=payload)
    )


def test_parse_endpoint_rejects_invalid_confidence(client: TestClient) -> None:
    payload = valid_payload()
    payload["observations"][0]["confidence"] = 1.01
    assert_structured_bad_request(
        client.post("/api/v1/ocr/nutrition-label/parse", json=payload)
    )


def test_parse_endpoint_rejects_invalid_bounding_box(client: TestClient) -> None:
    payload = valid_payload()
    payload["observations"][0]["bounding_box"] = {
        "x": 0.8,
        "y": 0.1,
        "width": 0.3,
        "height": 0.2,
    }
    assert_structured_bad_request(
        client.post("/api/v1/ocr/nutrition-label/parse", json=payload)
    )


def test_parse_endpoint_rejects_duplicate_observation_ids(client: TestClient) -> None:
    payload = valid_payload()
    payload["observations"][1]["id"] = payload["observations"][0]["id"]
    assert_structured_bad_request(
        client.post("/api/v1/ocr/nutrition-label/parse", json=payload)
    )


def test_parse_endpoint_rejects_text_size_limit(client: TestClient) -> None:
    payload = valid_payload()
    payload["full_text"] = "x" * 50_001
    assert_structured_bad_request(
        client.post("/api/v1/ocr/nutrition-label/parse", json=payload)
    )


def test_parse_endpoint_rejects_observation_count_limit(client: TestClient) -> None:
    payload = valid_payload()
    payload["observations"] = [
        {"id": f"obs-{index}", "text": "x", "confidence": 0.9}
        for index in range(501)
    ]
    assert_structured_bad_request(
        client.post("/api/v1/ocr/nutrition-label/parse", json=payload)
    )


def test_parse_endpoint_rejects_non_object_body(client: TestClient) -> None:
    assert_structured_bad_request(
        client.post("/api/v1/ocr/nutrition-label/parse", json=["not", "an", "object"])
    )
