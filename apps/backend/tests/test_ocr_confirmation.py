from copy import deepcopy
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.catalog.nutrients import NUTRIENT_CATALOG
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.attributes import set_committed_value

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
        "parser_version": "nutrition_label_v2",
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


def _payload_with_trace_bytes(target_bytes, unicode_unit=""):
    payload = confirmation_payload()
    payload["parser_warning_codes"] = [""]
    snapshot = OcrNutritionConfirmationRequest.model_validate(payload).trace_snapshot()
    base_bytes = len(json.dumps(snapshot, separators=(",", ":")).encode())
    unit_bytes = len(json.dumps(unicode_unit, separators=(",", ":")).encode()) - 2
    available = target_bytes - base_bytes
    unicode_count = 0 if not unicode_unit else available // unit_bytes
    payload["parser_warning_codes"] = [
        unicode_unit * unicode_count + "x" * (available - unicode_count * unit_bytes)
    ]
    snapshot["parser_warning_codes"] = payload["parser_warning_codes"]
    assert len(json.dumps(snapshot, separators=(",", ":")).encode()) == target_bytes
    return payload


@pytest.mark.parametrize(
    ("target_bytes", "unicode_unit", "accepted"),
    [
        (47_999, "", True),
        (48_001, "", False),
        (48_000, "é", True),
        (48_001, "é", False),
        (48_000, "😀", True),
        (48_001, "😀", False),
    ],
)
def test_confirmation_trace_limit_uses_ascii_escaped_json_bytes(
    target_bytes, unicode_unit, accepted
):
    payload = _payload_with_trace_bytes(target_bytes, unicode_unit)

    if accepted:
        OcrNutritionConfirmationRequest.model_validate(payload)
    else:
        with pytest.raises(ValueError, match="confirmation trace exceeds size limit"):
            OcrNutritionConfirmationRequest.model_validate(payload)


def test_confirmation_accepts_full_extended_catalog_trace_and_semantic_units() -> None:
    payload = confirmation_payload()

    existing_ids = {
        item["nutrient_id"]
        for item in payload["field_decisions"]
        if item["nutrient_id"] is not None
    }

    for nutrient in NUTRIENT_CATALOG:
        if nutrient.id in existing_ids:
            continue

        payload["field_decisions"].append(
            {
                **decision(
                    f"nutrient.{nutrient.id}",
                    None,
                    nutrient_id=nutrient.id,
                    unit=nutrient.default_unit,
                    status="missing",
                ),
                "decision": "omitted",
                "suggested_value": None,
            }
        )

    assert 40 < len(payload["field_decisions"]) <= 64

    validated = OcrNutritionConfirmationRequest.model_validate(payload)

    vitamin_a = next(
        item
        for item in validated.field_decisions
        if item.nutrient_id == "vitamin_a"
    )
    vitamin_e = next(
        item
        for item in validated.field_decisions
        if item.nutrient_id == "vitamin_e"
    )
    niacin = next(
        item
        for item in validated.field_decisions
        if item.nutrient_id == "niacin"
    )
    folate = next(
        item
        for item in validated.field_decisions
        if item.nutrient_id == "folate"
    )

    assert vitamin_a.unit == "mcg RAE"
    assert vitamin_e.unit == "mg alpha-tocopherol"
    assert niacin.unit == "mg NE"
    assert folate.unit == "mcg DFE"


def test_confirmation_creates_manual_food_and_bounded_trace_atomically(client, db_session):
    payload = confirmation_payload()
    response = client.post("/api/v1/ocr/nutrition-label/confirm", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["food"]["source_type"] == "manual"
    assert body["food"]["source_id"] is None
    assert body["food"]["source_kind"] == "ocr_confirmed"
    assert body["food"]["source_label"] == "Scanned label"
    assert body["food"]["is_favorite"] is False
    assert body["food"]["can_favorite"] is True
    sodium = next(item for item in body["food"]["nutrients"] if item["nutrient_id"] == "sodium")
    assert sodium["amount"] == "0.000000"
    trace = db_session.get(OcrNutritionConfirmationTrace, UUID(body["trace_id"]))
    assert trace is not None
    assert trace.food_item_id == UUID(body["food"]["id"])
    assert trace.trace_snapshot["schema_version"] == "ocr_nutrition_confirmation_v1"
    assert trace.trace_snapshot["unknown_nutrients"][0]["original_name"] == "Molybdenum"
    assert "image" not in trace.trace_snapshot


def test_confirmation_allows_explicit_calories_omission_when_food_has_no_calories_row(
    client, db_session
):
    payload = confirmation_payload()
    payload["food"]["nutrients"] = [
        item for item in payload["food"]["nutrients"]
        if item["nutrient_id"] != "calories"
    ]
    calories = next(
        item for item in payload["field_decisions"]
        if item["nutrient_id"] == "calories"
    )
    calories.update(
        suggested_value=None,
        confirmed_value=None,
        decision="omitted",
        parse_status="missing",
        confidence="0",
        source_text="",
        source_observation_ids=[],
        resolution="explicitly omitted after review",
    )

    response = client.post("/api/v1/ocr/nutrition-label/confirm", json=payload)

    assert response.status_code == 201, response.text
    assert all(
        item["nutrient_id"] != "calories"
        for item in response.json()["food"]["nutrients"]
    )
    trace = db_session.get(
        OcrNutritionConfirmationTrace, UUID(response.json()["trace_id"])
    )
    assert next(
        item for item in trace.trace_snapshot["field_decisions"]
        if item["nutrient_id"] == "calories"
    )["decision"] == "omitted"


def test_confirmation_accepts_physical_missing_unit_potassium_omission_with_canonical_unit(
    client, db_session
):
    payload = confirmation_payload()
    payload["field_decisions"].append(
        {
            "field_key": "nutrient.potassium",
            "nutrient_id": "potassium",
            "suggested_value": "35",
            "confirmed_value": None,
            "unit": "mg",
            "decision": "omitted",
            "parse_status": "ambiguous",
            "comparison": None,
            "confidence": "0.35",
            "source_text": "potassium",
            "source_observation_ids": ["physical-potassium"],
            "warning_codes": ["nutrient_unit_unknown"],
            "resolution": "explicitly omitted after review",
        }
    )

    response = client.post("/api/v1/ocr/nutrition-label/confirm", json=payload)

    assert response.status_code == 201, response.text
    assert all(
        item["nutrient_id"] != "potassium"
        for item in response.json()["food"]["nutrients"]
    )
    trace = db_session.get(
        OcrNutritionConfirmationTrace, UUID(response.json()["trace_id"])
    )
    potassium = next(
        item for item in trace.trace_snapshot["field_decisions"]
        if item["nutrient_id"] == "potassium"
    )
    assert potassium == {
        "field_key": "nutrient.potassium",
        "nutrient_id": "potassium",
        "suggested_value": "35",
        "confirmed_value": None,
        "unit": "mg",
        "decision": "omitted",
        "parse_status": "ambiguous",
        "comparison": None,
        "confidence": "0.35",
        "source_text": "potassium",
        "source_observation_ids": ["physical-potassium"],
        "warning_codes": ["nutrient_unit_unknown"],
        "resolution": "explicitly omitted after review",
    }


def test_confirmation_persists_unambiguous_manually_added_nutrient(client, db_session):
    payload = confirmation_payload()
    payload["food"]["nutrients"].append(
        {
            "nutrient_id": "iron",
            "amount": "4",
            "unit": "mg",
            "basis": "per_serving",
            "data_status": "known",
        }
    )
    payload["field_decisions"].append(
        {
            "field_key": "nutrient.iron",
            "nutrient_id": "iron",
            "suggested_value": None,
            "confirmed_value": "4",
            "unit": "mg",
            "decision": "edited",
            "parse_status": "missing",
            "comparison": None,
            "confidence": "0",
            "source_text": "",
            "source_observation_ids": [],
            "warning_codes": [],
            "resolution": "manually added because OCR did not provide it",
        }
    )

    response = client.post("/api/v1/ocr/nutrition-label/confirm", json=payload)

    assert response.status_code == 201, response.text
    assert next(
        item for item in response.json()["food"]["nutrients"]
        if item["nutrient_id"] == "iron"
    )["amount"] == "4.000000"
    trace = db_session.get(
        OcrNutritionConfirmationTrace, UUID(response.json()["trace_id"])
    )
    assert next(
        item for item in trace.trace_snapshot["field_decisions"]
        if item["nutrient_id"] == "iron"
    )["resolution"] == "manually added because OCR did not provide it"




def test_confirmation_fingerprint_preserves_pre_0027_null_reference_compatibility():
    payload = confirmation_payload()
    current = OcrNutritionConfirmationRequest.model_validate(payload)
    compatible_fingerprint = _fingerprint(current)

    legacy_payload = current.model_dump(mode="json", exclude={"client_request_id"})
    for serving in legacy_payload["food"]["serving_definitions"]:
        serving.pop("reference_quantity", None)
        serving.pop("reference_unit", None)
        serving.pop("reference_gram_weight", None)
    from hashlib import sha256
    legacy_fingerprint = sha256(
        json.dumps(legacy_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert compatible_fingerprint == legacy_fingerprint

    with_reference = deepcopy(payload)
    default = next(
        serving for serving in with_reference["food"]["serving_definitions"]
        if serving["is_default"]
    )
    default.update(
        reference_quantity="1",
        reference_unit="cup",
        reference_gram_weight="30",
    )
    referenced = OcrNutritionConfirmationRequest.model_validate(with_reference)
    assert _fingerprint(referenced) != legacy_fingerprint

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


def test_trace_snapshot_is_immutable_and_not_food_resolver_authority(client, db_session):
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
    with pytest.raises(IntegrityError, match="phase0020_immutable_row_mutation"):
        db_session.flush()
    db_session.rollback()

    # Preserve the original defensive boundary test without persisting a row
    # shape that 0020 intentionally rejects.  A loaded legacy/corrupt object is
    # still not a resolver input.
    trace = db_session.get(OcrNutritionConfirmationTrace, UUID(created["trace_id"]))
    set_committed_value(trace, "trace_snapshot", changed)

    with db_session.no_autoflush:
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
