from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.models.food import FoodItem, OcrNutritionConfirmationTrace
from app.ocr.confirmation_service import OcrConfirmationService


def decision(key, confirmed, *, nutrient_id=None, unit=None, suggested=None, status="parsed", comparison=None, resolution=None):
    return {
        "field_key": key,
        "nutrient_id": nutrient_id,
        "suggested_value": suggested if suggested is not None else confirmed,
        "confirmed_value": confirmed,
        "unit": unit,
        "decision": "accepted" if suggested in (None, confirmed) else "edited",
        "parse_status": status,
        "comparison": comparison,
        "confidence": "0.95",
        "source_text": f"source for {key}",
        "source_observation_ids": [f"obs-{key}"],
        "warning_codes": [],
        "resolution": resolution,
    }


def confirmation_payload():
    fields = [
        decision("food.name", "Test Cereal", suggested=None, status="missing"),
        {**decision("food.brand", None, status="missing"), "decision": "omitted", "suggested_value": None},
        {**decision("food.notes", None, status="missing"), "decision": "omitted", "suggested_value": None},
        decision("serving.display", "1 cup (30g)"),
        decision("serving.quantity", "1"),
        decision("serving.unit", "cup"),
        decision("serving.gram_weight", "30", unit="g"),
        decision("nutrient.calories", "120", nutrient_id="calories", unit="kcal"),
        decision("nutrient.sodium", "0", nutrient_id="sodium", unit="mg"),
        {**decision("nutrient.total_fat", None, nutrient_id="total_fat", unit="g", status="missing"), "decision": "omitted", "suggested_value": None},
    ]
    return {
        "parser_version": "nutrition_label_v1",
        "image_source_type": "photo_library",
        "client_request_id": str(uuid4()),
        "food": {
            "name": "Test Cereal", "brand": None, "notes": None,
            "serving_definitions": [
                {"label": "100 g", "quantity": "100", "unit": "g", "gram_weight": "100", "is_default": False},
                {"label": "1 cup (30g)", "quantity": "1", "unit": "cup", "gram_weight": "30", "is_default": True},
            ],
            "nutrients": [
                {"nutrient_id": "calories", "amount": "120", "unit": "kcal", "basis": "per_serving", "data_status": "known"},
                {"nutrient_id": "sodium", "amount": "0", "unit": "mg", "basis": "per_serving", "data_status": "zero"},
            ],
        },
        "field_decisions": fields,
        "unknown_nutrients": [{
            "original_name": "Molybdenum", "source_text": "Molybdenum 4 mcg",
            "source_observation_ids": ["obs-unknown"], "warning_codes": ["unmapped_nutrient"], "decision": "dismissed",
        }],
        "parser_warning_codes": ["unmapped_nutrient"],
    }


def test_confirmation_creates_manual_food_and_bounded_trace_atomically(client, db_session):
    payload = confirmation_payload()
    response = client.post("/api/v1/ocr/nutrition-label/confirm", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["food"]["source_type"] == "manual"
    assert body["food"]["source_id"] is None
    sodium = next(item for item in body["food"]["nutrients"] if item["nutrient_id"] == "sodium")
    assert sodium["amount"] == "0.000000"
    trace = db_session.get(OcrNutritionConfirmationTrace, UUID(body["trace_id"]))
    assert trace is not None
    assert trace.food_item_id == UUID(body["food"]["id"])
    assert trace.trace_snapshot["schema_version"] == "ocr_nutrition_confirmation_v1"
    assert trace.trace_snapshot["unknown_nutrients"][0]["original_name"] == "Molybdenum"
    assert "image" not in trace.trace_snapshot


def test_confirmation_idempotent_replay_and_payload_conflict(client, db_session):
    payload = confirmation_payload()
    first = client.post("/api/v1/ocr/nutrition-label/confirm", json=payload)
    replay = client.post("/api/v1/ocr/nutrition-label/confirm", json=payload)
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert db_session.scalar(select(func.count()).select_from(OcrNutritionConfirmationTrace)) == 1
    changed = deepcopy(payload)
    changed["food"]["name"] = "Different"
    changed["field_decisions"][0]["confirmed_value"] = "Different"
    conflict = client.post("/api/v1/ocr/nutrition-label/confirm", json=changed)
    assert conflict.status_code == 409


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(parser_version="future_parser"),
    lambda value: value["field_decisions"][7].update(comparison="less_than"),
    lambda value: value["field_decisions"][7].update(parse_status="ambiguous", resolution=None),
    lambda value: value["field_decisions"][7].update(source_text="file:///private/label.jpg"),
    lambda value: value["field_decisions"][7].update(unit="g"),
])
def test_confirmation_rejects_unsupported_or_unresolved_trace(client, mutation):
    payload = confirmation_payload()
    mutation(payload)
    assert client.post("/api/v1/ocr/nutrition-label/confirm", json=payload).status_code == 400


def test_confirmation_rolls_back_food_when_trace_stage_fails(client, db_session, monkeypatch):
    def fail(_self, _trace):
        raise RuntimeError("trace failure")
    monkeypatch.setattr(OcrConfirmationService, "_after_trace_creation", fail)
    with pytest.raises(RuntimeError, match="trace failure"):
        client.post("/api/v1/ocr/nutrition-label/confirm", json=confirmation_payload())
    assert db_session.scalar(select(func.count()).select_from(OcrNutritionConfirmationTrace)) == 0
    assert db_session.scalar(select(func.count()).select_from(FoodItem)) == 0


def test_trace_lookup_is_user_scoped(client, db_session):
    body = client.post("/api/v1/ocr/nutrition-label/confirm", json=confirmation_payload()).json()
    with pytest.raises(LookupError):
        OcrConfirmationService(db_session).get_trace(uuid4(), UUID(body["trace_id"]))
