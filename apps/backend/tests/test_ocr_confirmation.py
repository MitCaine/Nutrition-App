from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.food import FoodItem, OcrNutritionConfirmationTrace
from app.ocr.confirmation_schemas import OcrNutritionConfirmationRequest
from app.ocr.confirmation_service import OcrConfirmationService, _fingerprint


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


def _set_confirmed_food_name(payload, value):
    payload["food"]["name"] = value
    payload["field_decisions"][0]["confirmed_value"] = value


@pytest.mark.parametrize(
    ("secret", "mutation"),
    [
        ("file:///private/label.jpg", lambda value, secret: value["field_decisions"][7].update(source_text=secret)),
        ("content://label/image/1", lambda value, secret: value["field_decisions"][7].update(suggested_value=secret)),
        ("/Users/example/label.jpg", _set_confirmed_food_name),
        ("ph://ABC-123", lambda value, secret: value["field_decisions"][7].update(resolution=secret)),
        ("assets-library://asset/1", lambda value, secret: value["field_decisions"][7].update(source_observation_ids=[secret])),
        ("/var/mobile/label.jpg", lambda value, secret: value["field_decisions"][7].update(warning_codes=[secret])),
        ("/private/parser-warning", lambda value, secret: value.update(parser_warning_codes=[secret])),
        ("CONTENT://unknown/name", lambda value, secret: value["unknown_nutrients"][0].update(original_name=secret)),
        ("FILE:///private/unknown.jpg", lambda value, secret: value["unknown_nutrients"][0].update(source_text=secret)),
        ("PH://unknown-observation", lambda value, secret: value["unknown_nutrients"][0].update(source_observation_ids=[secret])),
        ("ASSETS-LIBRARY://unknown-warning", lambda value, secret: value["unknown_nutrients"][0].update(warning_codes=[secret])),
    ],
    ids=[
        "source-text",
        "suggested-value",
        "confirmed-value",
        "resolution",
        "observation-id",
        "warning-code",
        "parser-warning-code",
        "unknown-name",
        "unknown-source-text",
        "unknown-observation-id",
        "unknown-warning-code",
    ],
)
def test_confirmation_rejects_forbidden_material_from_every_trace_string(
    client, secret, mutation
):
    payload = confirmation_payload()
    mutation(payload, secret)

    response = client.post("/api/v1/ocr/nutrition-label/confirm", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_ocr_confirmation_request"
    assert secret.lower() not in response.text.lower()


def test_confirmation_accepts_ordinary_nutrition_punctuation(client):
    payload = confirmation_payload()
    label = "1/2 cup (30 g)"
    payload["food"]["serving_definitions"][1]["label"] = label
    payload["field_decisions"][3].update(
        suggested_value=label,
        confirmed_value=label,
        source_text="Serving size: 1/2 cup (30 g); about 6% DV",
        source_observation_ids=["obs:serving/1-2_(30g)"],
        warning_codes=["label/punctuation-ok"],
        resolution="selected (1/2 cup); 6% DV",
    )
    payload["parser_warning_codes"] = ["nutrition/fraction-ok"]
    payload["unknown_nutrients"][0].update(
        original_name="Vitamin B6 (6%)",
        source_text="Protein/fiber: 1/2 g (2%); n/a",
        source_observation_ids=["obs:unknown/1-2"],
        warning_codes=["unknown/name-ok"],
    )

    response = client.post("/api/v1/ocr/nutrition-label/confirm", json=payload)

    assert response.status_code == 201, response.text


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


def test_fingerprint_is_deterministic_and_preserves_review_order():
    payload = OcrNutritionConfirmationRequest.model_validate(confirmation_payload())
    assert _fingerprint(payload) == _fingerprint(
        OcrNutritionConfirmationRequest.model_validate(payload.model_dump(mode="json"))
    )
    reordered = payload.model_copy(
        update={"field_decisions": list(reversed(payload.field_decisions))}
    )
    assert _fingerprint(reordered) != _fingerprint(payload)

    nutrient_reordered = payload.model_copy(
        update={
            "food": payload.food.model_copy(
                update={"nutrients": list(reversed(payload.food.nutrients))}
            )
        }
    )
    assert _fingerprint(nutrient_reordered) != _fingerprint(payload)

    with_unknown_pair = OcrNutritionConfirmationRequest.model_validate(
        {
            **payload.model_dump(mode="json"),
            "unknown_nutrients": [
                *payload.model_dump(mode="json")["unknown_nutrients"],
                {
                    "original_name": "Second unknown",
                    "source_text": "Second unknown 2 mg",
                    "source_observation_ids": ["obs-second"],
                    "warning_codes": ["unmapped_nutrient"],
                    "decision": "dismissed",
                },
            ],
        }
    )
    unknown_reordered = with_unknown_pair.model_copy(
        update={"unknown_nutrients": list(reversed(with_unknown_pair.unknown_nutrients))}
    )
    assert _fingerprint(unknown_reordered) != _fingerprint(with_unknown_pair)


def test_unrelated_integrity_error_propagates_even_if_matching_request_exists(
    client, db_session, monkeypatch
):
    submitted = confirmation_payload()
    body = client.post("/api/v1/ocr/nutrition-label/confirm", json=submitted).json()
    trace = db_session.get(OcrNutritionConfirmationTrace, UUID(body["trace_id"]))
    assert trace is not None
    service = OcrConfirmationService(db_session)
    existing_calls = iter([None, trace])
    monkeypatch.setattr(service, "_existing", lambda *_args: next(existing_calls))

    unrelated = IntegrityError("insert", {}, Exception("foreign key constraint failed"))
    monkeypatch.setattr(service.foods, "add", lambda _food: (_ for _ in ()).throw(unrelated))
    payload = OcrNutritionConfirmationRequest.model_validate(submitted)
    with pytest.raises(IntegrityError) as raised:
        service.confirm(trace.user_id, payload)
    assert raised.value is unrelated


def _food_update_payload(food: dict, *, name: str) -> dict:
    return {
        "name": name,
        "brand": food["brand"],
        "notes": food["notes"],
        "serving_definitions": [
            {
                "label": item["label"],
                "quantity": item["quantity"],
                "unit": item["unit"],
                "gram_weight": item["gram_weight"],
                "is_default": item["is_default"],
            }
            for item in food["serving_definitions"]
        ],
        "nutrients": [
            {
                "nutrient_id": item["nutrient_id"],
                "amount": item["amount"],
                "unit": item["unit"],
                "basis": item["basis"],
                "data_status": item["data_status"],
            }
            for item in food["nutrients"]
        ],
    }


def test_edit_duplicate_and_soft_delete_preserve_creation_trace_semantics(client, db_session):
    created = client.post(
        "/api/v1/ocr/nutrition-label/confirm", json=confirmation_payload()
    ).json()
    food = created["food"]
    trace_id = UUID(created["trace_id"])
    original_snapshot = deepcopy(
        db_session.get(OcrNutritionConfirmationTrace, trace_id).trace_snapshot
    )

    edited = client.patch(
        f"/api/v1/foods/{food['id']}",
        json=_food_update_payload(food, name="Edited Cereal"),
    )
    assert edited.status_code == 200
    db_session.expire_all()
    assert db_session.get(OcrNutritionConfirmationTrace, trace_id).trace_snapshot == original_snapshot

    duplicated = client.post(f"/api/v1/foods/{food['id']}/duplicate")
    assert duplicated.status_code == 201
    duplicate_id = UUID(duplicated.json()["id"])
    assert db_session.scalar(
        select(func.count()).select_from(OcrNutritionConfirmationTrace).where(
            OcrNutritionConfirmationTrace.food_item_id == duplicate_id
        )
    ) == 0

    deleted = client.delete(f"/api/v1/foods/{food['id']}")
    assert deleted.status_code == 200
    db_session.expire_all()
    assert db_session.get(OcrNutritionConfirmationTrace, trace_id) is not None


def test_ordinary_manual_food_has_no_ocr_trace(client, db_session):
    payload = confirmation_payload()["food"]
    response = client.post("/api/v1/foods", json=payload)
    assert response.status_code == 201
    assert db_session.scalar(
        select(func.count()).select_from(OcrNutritionConfirmationTrace)
    ) == 0


def test_trace_snapshot_is_not_food_resolver_authority(client, db_session):
    created = client.post(
        "/api/v1/ocr/nutrition-label/confirm", json=confirmation_payload()
    ).json()
    before = client.get(
        f"/api/v1/foods/{created['food']['id']}/resolved-nutrition"
    )
    assert before.status_code == 200

    trace = db_session.get(OcrNutritionConfirmationTrace, UUID(created["trace_id"]))
    changed = deepcopy(trace.trace_snapshot)
    calories = next(
        item
        for item in changed["field_decisions"]
        if item["field_key"] == "nutrient.calories"
    )
    calories["confirmed_value"] = "999999"
    trace.trace_snapshot = changed
    db_session.commit()

    after = client.get(
        f"/api/v1/foods/{created['food']['id']}/resolved-nutrition"
    )
    assert after.status_code == 200
    assert after.json() == before.json()


def test_persisted_trace_contains_no_forbidden_raw_material(client, db_session):
    body = client.post(
        "/api/v1/ocr/nutrition-label/confirm", json=confirmation_payload()
    ).json()
    snapshot = db_session.get(
        OcrNutritionConfirmationTrace, UUID(body["trace_id"])
    ).trace_snapshot
    encoded = str(snapshot).lower()
    for forbidden in ("image_uri", "image_path", "image_bytes", "full_text", "file://", "/private/"):
        assert forbidden not in encoded
