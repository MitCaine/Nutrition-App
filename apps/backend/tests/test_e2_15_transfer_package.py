from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.transfer.e2_15 import (
    CONTRACT,
    MAXIMUM_TRANSFER_BYTES,
    SCHEMA_CONTRACT_DIGEST,
    SECTION_NAMES,
    TransferPackageError,
    build_daily_totals_section,
    build_section,
    canonical_digest,
    canonicalize_transfer_scalar,
    canonical_transfer_json,
    parse_transfer_document,
    serialize_transfer_document,
    sort_transfer_records,
    validate_transfer_package,
    with_overall_digest,
)


ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = (
    ROOT / "packages" / "shared-contracts" / "e2-15" / "transfer-contract.json"
)
FIXTURE_PATH = (
    ROOT / "packages" / "shared-contracts" / "e2-15" / "parity-fixtures.json"
)
REPRESENTATIVE_PATH = (
    ROOT / "packages" / "shared-contracts" / "e2-15" / "representative-package.json"
)
HISTORICAL_CONTRACT_ROOT = ROOT / "packages" / "shared-contracts" / "e2-15"


def test_shared_contract_fixes_the_approved_package_boundary() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    assert contract["format"] == "nutrition-personal-transfer"
    assert contract["format_version"] == "4"
    assert contract["contract_version"] == "e2-15.v4"
    assert "recipe.duplicate" in contract["idempotency"]["copied_operations"]
    assert "recipe.duplicate" in contract["enums"]["idempotency_operation"]
    assert contract["codec_version"] == "e2-02.v1"
    assert contract["maximum_bytes"] == 64 * 1024 * 1024 == MAXIMUM_TRANSFER_BYTES
    assert tuple(section["name"] for section in contract["sections"]) == SECTION_NAMES
    assert len(SECTION_NAMES) == 18
    assert len(contract["source"]["expected_public_tables"]) == 32


def test_historical_contract_artifacts_remain_byte_exact() -> None:
    expected = {
        "transfer-contract-v1.json": "5718f6ad821a637fa1e2fbe11893e1c4ffa6fa81697d037cb6a16eadb6da090f",
        "source-schema-v1.json": "ffca3a3405a4e65e13aa992ccb7c57e92e4167a9588629ad0d242c37d5a4c223",
        "target-schema-v1.json": "1fc6cca4b0b27c61b08fc458ebaca7bc7109e7afcb2b1efc20663d16ff3c1772",
        "representative-package-v1.json": "5be395008899920704119cffcabb70cda80a357aa96b2ffb533a76d5985efb79",
        "transfer-contract-v2.json": "eaf508a7264898bc616682c949d2fcf249b0359f6df332e7eff06f908e86b52f",
        "source-schema-v2.json": "b74df441d484bb09a54ffb514123b3acc329237996ca2e990b565525b88dc4d5",
        "target-schema-v2.json": "fb8c24beefda15b3a4735a3e72443bcc6f438c7dbd94d1386ad833167d7ee697",
        "representative-package-v2.json": "f1bedf2cad4e71a540c39d7e38e8fd68542d3280018b36c1ecd7ea4c9acf8537",
        "transfer-contract-v3.json": "92062ada0d384dc9bc996252ac0f32dc1e6e416469e2fede53598cf957f91395",
        "source-schema-v3.json": "6e25248fcace9b6d5a874a8715cc5757250bafd94eeadd673c5e4da3c3d4073d",
        "target-schema-v3.json": "84fe934c42c087a96ed10a813e36234c90b901c7a01e9b47f8c16f2b2f2a501c",
        "representative-package-v3.json": "c9c6ee70d4999e9c6ec3199ffa0c2c0a66e00699f81059f5818df8528e79406e",
    }
    for name, digest in expected.items():
        assert hashlib.sha256((HISTORICAL_CONTRACT_ROOT / name).read_bytes()).hexdigest() == digest

    frozen_v3 = json.loads(
        (HISTORICAL_CONTRACT_ROOT / "transfer-contract-v3.json").read_text(encoding="utf-8")
    )
    assert frozen_v3["format_version"] == "3"
    assert "recipe.duplicate" not in frozen_v3["idempotency"]["copied_operations"]


def test_section_digest_uses_only_count_name_and_records() -> None:
    section = build_section("users", [])

    assert section == {
        "count": 0,
        "digest": "504abae8357482f227bf6b86f154f4c48737c9d50911bc80ee12d06e05b744a1",
        "name": "users",
        "records": [],
    }
    preimage = canonical_transfer_json({"count": 0, "name": "users", "records": []})
    assert hashlib.sha256(preimage.encode("utf-8")).hexdigest() == section["digest"]


def test_parser_rejects_noncanonical_or_oversized_bytes_before_shape_validation() -> None:
    with pytest.raises(TransferPackageError, match="canonical"):
        parse_transfer_document(b'{ "format":"nutrition-personal-transfer" }')
    with pytest.raises(TransferPackageError, match="canonical"):
        parse_transfer_document(b'\xef\xbb\xbf{}')
    with pytest.raises(TransferPackageError, match="maximum"):
        parse_transfer_document(b"x" * (MAXIMUM_TRANSFER_BYTES + 1))
    encoded = serialize_transfer_document(_minimal_document())
    with pytest.raises(TransferPackageError, match="canonical"):
        parse_transfer_document(encoded[:-1])
    with pytest.raises(TransferPackageError, match="canonical"):
        parse_transfer_document(b'{"a":1,"a":1}')


def test_shared_canonical_and_digest_fixtures_match_python() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    for case in fixture["canonical_json_cases"]:
        assert canonical_transfer_json(case["value"]) == case["canonical"]
        assert hashlib.sha256(case["canonical"].encode("utf-8")).hexdigest() == case["sha256"]
    for case in fixture["section_cases"]:
        assert canonical_transfer_json(
            {
                "count": len(case["sorted_records"]),
                "name": case["section_name"],
                "records": case["sorted_records"],
            }
        ) == case["preimage"]
        section = build_section(case["section_name"], case["sorted_records"])
        assert section["digest"] == case["digest"]
    for case in fixture["scalar_cases"]:
        assert canonicalize_transfer_scalar(case["kind"], case["input"]) == case["canonical"]
    for case in fixture["record_order_cases"]:
        assert sort_transfer_records(case["unsorted_records"], case["primary_key"]) == case["sorted_records"]
    for case in fixture["overall_digest_cases"]:
        assert canonical_transfer_json(case["unsigned_document"]) == case["preimage"]
        assert canonical_digest(case["unsigned_document"]) == case["digest"]
        assert with_overall_digest(case["unsigned_document"]) == case["completed_document"]
    for case in fixture["unsafe_integer_cases"]:
        with pytest.raises(TransferPackageError):
            canonical_transfer_json(int(case["input"]))


OWNER_ID = "00000000-0000-4000-8000-000000000001"
INSTANT = "2026-08-10T12:34:56.123456Z"


def _trace_decision(
    field_key: str,
    *,
    confirmed_value: str | None,
    nutrient_id: str | None = None,
    unit: str | None = None,
    decision: str | None = None,
) -> dict:
    return {
        "field_key": field_key,
        "nutrient_id": nutrient_id,
        "suggested_value": confirmed_value,
        "confirmed_value": confirmed_value,
        "unit": unit,
        "decision": decision or ("accepted" if confirmed_value is not None else "omitted"),
        "parse_status": "parsed" if confirmed_value is not None else "missing",
        "comparison": None,
        "confidence": "1" if confirmed_value is not None else "0",
        "source_text": "",
        "source_observation_ids": [],
        "warning_codes": [],
        "resolution": None,
    }


def _valid_trace() -> dict:
    return {
        "schema_version": "ocr_nutrition_confirmation_v1",
        "field_decisions": [
            _trace_decision("food.name", confirmed_value="OCR Food"),
            _trace_decision("food.brand", confirmed_value=None),
            _trace_decision("food.notes", confirmed_value=None),
            _trace_decision("serving.display", confirmed_value="1 serving"),
            _trace_decision("serving.quantity", confirmed_value="1"),
            _trace_decision("serving.unit", confirmed_value="serving"),
            _trace_decision("serving.gram_weight", confirmed_value=None),
            _trace_decision(
                "nutrient.calories",
                confirmed_value="100",
                nutrient_id="calories",
                unit="kcal",
            ),
        ],
        "unknown_nutrients": [],
        "parser_warning_codes": [],
    }


def _minimal_document() -> dict:
    records = {name: [] for name in SECTION_NAMES}
    records["users"] = [
        {
            "id": OWNER_ID,
            "email": "owner@example.invalid",
            "display_name": "Transfer Owner",
            "created_at": INSTANT,
        }
    ]
    records["user_profiles"] = [
        {
            "user_id": OWNER_ID,
            "birth_date": None,
            "height_cm": None,
            "weight_kg": None,
            "biological_sex_for_reference_calculations": None,
            "activity_level": None,
            "energy_estimation_context": "general_adult",
            "authoritative_time_zone": "America/Los_Angeles",
            "calendar_revision": 0,
            "created_at": INSTANT,
            "updated_at": INSTANT,
        }
    ]
    return {
        "format": "nutrition-personal-transfer",
        "format_version": CONTRACT["format_version"],
        "codec_version": "e2-02.v1",
        "source": {
            "postgres_major": "16",
            "alembic_revision": CONTRACT["source"]["alembic_revision"],
            "schema_contract": CONTRACT["source"]["schema_contract"],
            "schema_contract_digest": SCHEMA_CONTRACT_DIGEST,
        },
        "target": CONTRACT["target"],
        "exported_at": INSTANT,
        "owner_id": OWNER_ID,
        "nutrient_catalog_digest": CONTRACT["nutrient_catalog_digest"],
        "idempotency_policy": {
            "version": "e2-15.idempotency.v1",
            "copied_portable_count": 0,
            "translated_log_update_count": 0,
            "reconstructed_log_create_count": 0,
            "excluded_log_delete_count": 0,
        },
        "sections": [build_section(name, records[name]) for name in SECTION_NAMES],
        "qualification": {"daily_totals": build_daily_totals_section([])},
    }


def test_complete_minimal_package_is_validated_before_database_access() -> None:
    encoded = serialize_transfer_document(_minimal_document())

    validated = validate_transfer_package(encoded)

    assert validated["owner_id"] == OWNER_ID
    assert [section["name"] for section in validated["sections"]] == list(SECTION_NAMES)
    assert canonical_transfer_json(validated).encode("utf-8") == encoded


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda value: value.update({"unexpected": True}), "invalid_package_shape"),
        (lambda value: value["sections"].reverse(), "section_order_invalid"),
        (
            lambda value: value["sections"][0].update(
                {"count": value["sections"][0]["count"] + 1}
            ),
            "section_count_invalid",
        ),
        (
            lambda value: value["sections"][0]["records"][0].update(
                {"id": "NOT-A-UUID"}
            ),
            "invalid_record_value",
        ),
    ],
)
def test_metadata_shape_order_counts_and_scalars_fail_closed(mutate, code: str) -> None:
    document = _minimal_document()
    mutate(document)
    encoded = serialize_transfer_document(document)

    with pytest.raises(TransferPackageError) as failure:
        validate_transfer_package(encoded)

    assert failure.value.code == code


def test_duplicate_or_unsorted_primary_keys_fail_before_import() -> None:
    document = _minimal_document()
    users = document["sections"][0]
    users["records"].append(dict(users["records"][0]))
    users.update(build_section("users", users["records"]))

    with pytest.raises(TransferPackageError) as failure:
        validate_transfer_package(serialize_transfer_document(document))

    assert failure.value.code == "duplicate_primary_key"


def _with_unicode_ocr_trace(document: dict, unicode_count: int) -> dict:
    food_id = "00000000-0000-4000-8000-000000000101"
    trace_id = "00000000-0000-4000-8000-000000000102"
    trace = _valid_trace()
    trace["parser_warning_codes"] = ["é" * unicode_count]
    sections = {section["name"]: section for section in document["sections"]}
    sections["food_items"].update(
        build_section(
            "food_items",
            [
                {
                    "id": food_id,
                    "user_id": OWNER_ID,
                    "name": "OCR Food",
                    "brand": None,
                    "source_type": "ocr_label",
                    "source_id": None,
                    "recipe_publication_revision_id": None,
                    "is_recipe": False,
                    "notes": None,
                    "created_at": INSTANT,
                    "updated_at": INSTANT,
                    "deleted_at": None,
                }
            ],
        )
    )
    sections["ocr_nutrition_confirmation_traces"].update(
        build_section(
            "ocr_nutrition_confirmation_traces",
            [
                {
                    "id": trace_id,
                    "user_id": OWNER_ID,
                    "food_item_id": food_id,
                    "parser_version": "nutrition_label_v1",
                    "image_source_type": "camera",
                    "schema_version": "ocr_nutrition_confirmation_v1",
                    "trace_snapshot": canonical_transfer_json(trace),
                    "client_request_id": "00000000-0000-4000-8000-000000000103",
                    "request_fingerprint": "0" * 64,
                    "confirmed_at": INSTANT,
                }
            ],
        )
    )
    return document


def test_ocr_trace_bound_preserves_e2_13_ensure_ascii_byte_semantics() -> None:
    # 7,000 non-ASCII characters remain below the established Python-json bound.
    validate_transfer_package(
        serialize_transfer_document(_with_unicode_ocr_trace(_minimal_document(), 7_000))
    )

    # 9,000 characters are only ~18 KiB in UTF-8, but exceed 48,000 bytes when
    # measured by E2-13's compact json.dumps(..., ensure_ascii=True) contract.
    document = _with_unicode_ocr_trace(_minimal_document(), 9_000)
    with pytest.raises(TransferPackageError) as failure:
        validate_transfer_package(serialize_transfer_document(document))

    assert failure.value.code == "ocr_trace_invalid"


def _trace_tamper(mutator) -> bytes:
    def mutate(_package, sections) -> None:
        row = sections["ocr_nutrition_confirmation_traces"]["records"][0]
        trace = _valid_trace()
        mutator(trace)
        row["trace_snapshot"] = canonical_transfer_json(trace)

    return _resigned_representative(mutate)


def _remove_required_trace_decision(trace: dict) -> None:
    trace["field_decisions"] = [
        row for row in trace["field_decisions"] if row["field_key"] != "food.name"
    ]


def _remove_calories_trace_decision(trace: dict) -> None:
    trace["field_decisions"] = [
        row for row in trace["field_decisions"]
        if row["field_key"] != "nutrient.calories"
    ]


def _duplicate_trace_key(trace: dict) -> None:
    trace["field_decisions"].append(deepcopy(trace["field_decisions"][0]))


def _invalid_nutrient(trace: dict) -> None:
    trace["field_decisions"][-1].update(
        field_key="nutrient.not-a-nutrient",
        nutrient_id="not-a-nutrient",
    )


def _invalid_unit(trace: dict) -> None:
    trace["field_decisions"][-1]["unit"] = "mg"


def _invalid_decision(trace: dict) -> None:
    trace["field_decisions"][0]["decision"] = "unresolved"


def _invalid_parse_status(trace: dict) -> None:
    trace["field_decisions"][0]["parse_status"] = "invalid"


def _invalid_confidence(trace: dict) -> None:
    trace["field_decisions"][0]["confidence"] = "1.01"


def _ambiguous_without_resolution(trace: dict) -> None:
    trace["field_decisions"][0].update(parse_status="ambiguous", resolution=None)


def _invalid_unknown_nutrient(trace: dict) -> None:
    trace["unknown_nutrients"] = [
        {
            "original_name": "Mystery",
            "source_text": "Mystery 1g",
            "source_observation_ids": [],
            "warning_codes": [],
            "decision": "accepted",
        }
    ]


def _excessive_trace_list(trace: dict) -> None:
    trace["field_decisions"][0]["source_observation_ids"] = ["x"] * 21


def _excessive_trace_string(trace: dict) -> None:
    trace["field_decisions"][0]["suggested_value"] = "x" * 257


def _omitted_with_confirmed_value(trace: dict) -> None:
    trace["field_decisions"][1]["confirmed_value"] = "Brand"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda trace: trace.update(field_decisions=[]),
        _remove_required_trace_decision,
        _remove_calories_trace_decision,
        _duplicate_trace_key,
        _invalid_nutrient,
        _invalid_unit,
        _invalid_decision,
        _invalid_parse_status,
        _invalid_confidence,
        _ambiguous_without_resolution,
        _invalid_unknown_nutrient,
        _excessive_trace_list,
        _excessive_trace_string,
        _omitted_with_confirmed_value,
    ],
)
def test_intrinsically_invalid_e2_13_ocr_traces_fail_closed(mutator) -> None:
    with pytest.raises(TransferPackageError) as failure:
        validate_transfer_package(_trace_tamper(mutator))

    assert failure.value.code == "ocr_trace_invalid"


def test_minimal_intrinsically_valid_e2_13_trace_is_transferable() -> None:
    validate_transfer_package(_trace_tamper(lambda _trace: None))


def test_explicitly_omitted_calories_trace_is_transferable() -> None:
    def omit_calories(trace: dict) -> None:
        calories = next(
            row for row in trace["field_decisions"]
            if row["field_key"] == "nutrient.calories"
        )
        calories.update(decision="omitted", confirmed_value=None)

    validate_transfer_package(_trace_tamper(omit_calories))


def test_representative_cross_runtime_package_covers_the_approved_owner_graph() -> None:
    fixture = json.loads(REPRESENTATIVE_PATH.read_text(encoding="utf-8"))
    package = validate_transfer_package(canonical_transfer_json(fixture).encode("utf-8"))
    sections = {section["name"]: section["records"] for section in package["sections"]}

    assert len(sections["food_items"]) == 4
    assert any(row["deleted_at"] is not None for row in sections["food_items"])
    assert len(sections["recipe_publication_revisions"]) == 3
    assert len(sections["recipes"]) == 3
    assert len(sections["daily_log_nutrient_snapshots"]) == 2
    assert len(sections["ocr_nutrition_confirmation_traces"]) == 1
    assert len(sections["nutrition_targets"]) == 1
    assert {row["operation"] for row in sections["create_operation_idempotency"]} == {
        "food.create_manual",
        "log.create",
        "log.update",
        "recipe.duplicate",
    }


@pytest.mark.parametrize(
    ("label", "mutate_row", "code"),
    [
        (
            "cross-owner",
            lambda row: row.update(
                user_id="00000000-0000-4000-8000-000000000002"
            ),
            "owner_graph_invalid",
        ),
        (
            "orphan-date",
            lambda row: row.update(logged_date="2026-08-11"),
            "owner_graph_invalid",
        ),
        (
            "malformed-date",
            lambda row: row.update(logged_date="2026-02-30"),
            "invalid_record_value",
        ),
        (
            "malformed-completion-time",
            lambda row: row.update(
                completed_at="2026-08-10T12:34:56"
            ),
            "invalid_record_value",
        ),
    ],
)
def test_v3_complete_evidence_fails_closed(
    label: str,
    mutate_row,
    code: str,
) -> None:
    def mutate(_package, sections) -> None:
        row = sections[
            "daily_log_day_completions"
        ]["records"][0]
        mutate_row(row)

    with pytest.raises(
        TransferPackageError
    ) as failure:
        validate_transfer_package(
            _resigned_representative(mutate)
        )

    assert failure.value.code == code, label


def _resigned_representative(mutator) -> bytes:
    fixture = deepcopy(json.loads(REPRESENTATIVE_PATH.read_text(encoding="utf-8")))
    sections = {section["name"]: section for section in fixture["sections"]}
    mutator(fixture, sections)
    fixture["sections"] = [
        build_section(name, sections[name]["records"])
        for name in SECTION_NAMES
    ]
    fixture.pop("overall_digest", None)
    fixture["overall_digest"] = canonical_digest(fixture)
    return serialize_transfer_document(fixture)




@pytest.mark.parametrize(
    "mutator",
    [
        lambda serving: serving.update(reference_gram_weight=None),
        lambda serving: serving.update(reference_quantity="0.000000"),
        lambda serving: serving.update(reference_gram_weight="0.000000"),
        lambda serving: serving.update(reference_unit=""),
    ],
)
def test_v2_transfer_rejects_incomplete_or_nonpositive_serving_reference_measurements(mutator) -> None:
    def mutate(_package, sections) -> None:
        serving = next(
            row for row in sections["serving_definitions"]["records"]
            if row["reference_quantity"] is not None
        )
        mutator(serving)

    with pytest.raises(TransferPackageError) as failure:
        validate_transfer_package(_resigned_representative(mutate))

    assert failure.value.code == "owner_graph_invalid"


def _food_response(food: dict, source_kind: str, *, servings: list[dict] | None = None) -> dict:
    return {
        "id": food["id"],
        "name": food["name"],
        "brand": food["brand"],
        "notes": food["notes"],
        "source_type": food["source_type"],
        "source_id": food["source_id"],
        "is_recipe": food["is_recipe"],
        "source_kind": source_kind,
        "source_label": source_kind.replace("_", " ").title(),
        "is_favorite": False,
        "can_favorite": True,
        "created_at": food["created_at"],
        "updated_at": food["updated_at"],
        "serving_definitions": servings or [],
        "nutrients": [],
    }


def _recipe_response(recipe: dict, *, name: str | None = None, published_food_id=None) -> dict:
    return {
        "id": recipe["id"],
        "user_id": recipe["user_id"],
        "published_food_item_id": published_food_id,
        "name": name or recipe["name"],
        "notes": recipe["notes"],
        "serving_count_yield": recipe["serving_count_yield"],
        "final_cooked_weight_grams": recipe["final_cooked_weight_grams"],
        "final_cooked_weight_display_quantity": recipe[
            "final_cooked_weight_display_quantity"
        ],
        "final_cooked_weight_display_unit": recipe["final_cooked_weight_display_unit"],
        "needs_republish": False,
        "created_at": recipe["created_at"],
        "updated_at": recipe["updated_at"],
        "ingredients": [],
    }


def _portable_receipt_mutation(operation: str, tamper=None):
    def mutate(_package, sections) -> None:
        foods = {row["id"]: row for row in sections["food_items"]["records"]}
        recipes = {row["id"]: row for row in sections["recipes"]["records"]}
        receipt = next(
            row
            for row in sections["create_operation_idempotency"]["records"]
            if row["operation"] == "food.create_manual"
        )
        receipt["operation"] = operation
        if operation == "food.create_manual":
            receipt["resource_id"] = "00000000-0000-4000-8000-000000000011"
            snapshot = _food_response(foods[receipt["resource_id"]], "manual")
        elif operation == "food.duplicate":
            receipt["resource_id"] = "00000000-0000-4000-8000-000000000011"
            foods[receipt["resource_id"]]["source_id"] = (
                "00000000-0000-4000-8000-000000000010"
            )
            snapshot = _food_response(foods[receipt["resource_id"]], "duplicate")
        elif operation == "food.add_serving":
            receipt["resource_id"] = "00000000-0000-4000-8000-000000000029"
            snapshot = _food_response(
                foods["00000000-0000-4000-8000-000000000010"],
                "usda",
                servings=[
                    {
                        "id": receipt["resource_id"],
                        "label": "Historical cup",
                        "quantity": "1.000000",
                        "unit": "cup",
                        "gram_weight": "125.000000",
                        "reference_quantity": None,
                        "reference_unit": None,
                        "reference_gram_weight": None,
                        "is_default": False,
                        "source": "manual",
                        "is_user_confirmed": True,
                    }
                ],
            )
        elif operation in {"recipe.create", "recipe.duplicate"}:
            receipt["resource_id"] = (
                "00000000-0000-4000-8000-000000000050"
                if operation == "recipe.create"
                else "00000000-0000-4000-8000-000000000052"
            )
            snapshot = _recipe_response(recipes[receipt["resource_id"]])
        else:
            assert operation == "recipe.publish"
            receipt["resource_id"] = "00000000-0000-4000-8000-000000000060"
            recipe = _recipe_response(
                recipes["00000000-0000-4000-8000-000000000050"],
                name="Base v1",
                published_food_id="00000000-0000-4000-8000-000000000012",
            )
            food = dict(foods["00000000-0000-4000-8000-000000000012"])
            food["name"] = "Base v1"
            snapshot = {"recipe": recipe, "food": _food_response(food, "recipe")}
        if tamper is not None:
            tamper(receipt, snapshot)
        receipt["response_snapshot"] = canonical_transfer_json(snapshot)

    return mutate


@pytest.mark.parametrize(
    ("operation", "tamper"),
    [
        ("food.create_manual", lambda _receipt, snapshot: snapshot.update(extra=True)),
        (
            "food.duplicate",
            lambda _receipt, snapshot: snapshot.update(
                source_id="00000000-0000-4000-8000-000000000099"
            ),
        ),
        (
            "food.add_serving",
            lambda receipt, _snapshot: receipt.update(
                resource_id="00000000-0000-4000-8000-000000000028"
            ),
        ),
        (
            "recipe.create",
            lambda _receipt, snapshot: snapshot.update(
                user_id="00000000-0000-4000-8000-000000000002"
            ),
        ),
        (
            "recipe.duplicate",
            lambda receipt, _snapshot: receipt.update(
                resource_id="00000000-0000-4000-8000-000000000050"
            ),
        ),
        (
            "recipe.publish",
            lambda receipt, _snapshot: receipt.update(
                resource_id="00000000-0000-4000-8000-000000000062"
            ),
        ),
    ],
)
def test_portable_receipts_validate_exact_shapes_and_reject_operation_tampering(
    operation: str,
    tamper,
) -> None:
    valid = _resigned_representative(_portable_receipt_mutation(operation))
    validate_transfer_package(valid)

    with pytest.raises(TransferPackageError) as failure:
        validate_transfer_package(
            _resigned_representative(_portable_receipt_mutation(operation, tamper))
        )

    assert failure.value.code == "idempotency_policy_invalid"


def test_recipe_duplicate_receipt_requires_only_the_independent_result_recipe() -> None:
    document = _minimal_document()
    sections = {section["name"]: section for section in document["sections"]}
    recipe = {
        "id": "00000000-0000-4000-8000-000000000052",
        "user_id": OWNER_ID,
        "published_food_item_id": None,
        "active_publication_revision_id": None,
        "name": "Independent Copy",
        "notes": None,
        "serving_count_yield": "1.000000",
        "final_cooked_weight_grams": None,
        "final_cooked_weight_display_quantity": None,
        "final_cooked_weight_display_unit": None,
        "needs_republish": False,
        "created_at": INSTANT,
        "updated_at": INSTANT,
        "deleted_at": None,
    }
    response = _recipe_response(recipe)
    receipt = {
        "id": "00000000-0000-4000-8000-000000000142",
        "user_id": OWNER_ID,
        "operation": "recipe.duplicate",
        "client_request_id": "00000000-0000-4000-8000-000000000154",
        "request_fingerprint": "5" * 64,
        "resource_id": recipe["id"],
        "response_snapshot": canonical_transfer_json(response),
        "completed_at": INSTANT,
        "created_at": INSTANT,
    }
    sections["recipes"] = build_section("recipes", [recipe])
    sections["create_operation_idempotency"] = build_section(
        "create_operation_idempotency", [receipt]
    )
    document["sections"] = [sections[name] for name in SECTION_NAMES]
    document["idempotency_policy"]["copied_portable_count"] = 1

    validated = validate_transfer_package(serialize_transfer_document(document))
    records = {
        section["name"]: section["records"] for section in validated["sections"]
    }
    assert records["recipes"] == [recipe]
    assert records["create_operation_idempotency"][0]["operation"] == "recipe.duplicate"


def test_pre_0027_food_receipt_without_reference_keys_remains_portable() -> None:
    def remove_reference_keys(_receipt, snapshot) -> None:
        serving = snapshot["serving_definitions"][0]
        serving.pop("reference_quantity")
        serving.pop("reference_unit")
        serving.pop("reference_gram_weight")

    validate_transfer_package(
        _resigned_representative(
            _portable_receipt_mutation("food.add_serving", remove_reference_keys)
        )
    )


def test_v2_food_receipt_rejects_partial_reference_measurement() -> None:
    def partial_reference(_receipt, snapshot) -> None:
        serving = snapshot["serving_definitions"][0]
        serving["reference_quantity"] = "1.000000"
        serving["reference_unit"] = "cup"
        serving["reference_gram_weight"] = None

    with pytest.raises(TransferPackageError) as failure:
        validate_transfer_package(
            _resigned_representative(
                _portable_receipt_mutation("food.add_serving", partial_reference)
            )
        )
    assert failure.value.code == "idempotency_policy_invalid"


def test_historical_serving_and_publication_receipts_remain_portable() -> None:
    serving_package = validate_transfer_package(
        _resigned_representative(_portable_receipt_mutation("food.add_serving"))
    )
    publication_package = validate_transfer_package(
        _resigned_representative(_portable_receipt_mutation("recipe.publish"))
    )
    serving_sections = {
        section["name"]: section["records"] for section in serving_package["sections"]
    }
    publication_sections = {
        section["name"]: section["records"] for section in publication_package["sections"]
    }
    assert all(
        row["id"] != "00000000-0000-4000-8000-000000000029"
        for row in serving_sections["serving_definitions"]
    )
    recipe = next(
        row
        for row in publication_sections["recipes"]
        if row["id"] == "00000000-0000-4000-8000-000000000050"
    )
    assert recipe["active_publication_revision_id"] == (
        "00000000-0000-4000-8000-000000000061"
    )


def _update_receipt_mutation(mutator) -> bytes:
    def mutate(_package, sections) -> None:
        receipt = next(
            row
            for row in sections["create_operation_idempotency"]["records"]
            if row["operation"] == "log.update"
        )
        snapshot = json.loads(receipt["response_snapshot"])
        mutator(receipt, snapshot)
        receipt["response_snapshot"] = canonical_transfer_json(snapshot)

    return _resigned_representative(mutate)


def test_log_update_receipt_is_valid_with_current_or_later_deleted_log() -> None:
    validate_transfer_package(_update_receipt_mutation(lambda _receipt, _snapshot: None))

    historical_id = "00000000-0000-4000-8000-000000000199"

    def make_historical(receipt, snapshot) -> None:
        receipt["resource_id"] = historical_id
        snapshot["result"]["id"] = historical_id

    validate_transfer_package(_update_receipt_mutation(make_historical))


@pytest.mark.parametrize(
    "mutator",
    [
        lambda _receipt, snapshot: snapshot["result"].pop("amount_unit"),
        lambda receipt, _snapshot: receipt.update(
            resource_id="00000000-0000-4000-8000-000000000199"
        ),
        lambda _receipt, snapshot: snapshot.update(source_logged_date="2026-99-99"),
        lambda _receipt, snapshot: snapshot.update(destination_logged_date="not-a-date"),
    ],
)
def test_log_update_receipt_rejects_malformed_result_identity_and_dates(mutator) -> None:
    with pytest.raises(TransferPackageError) as failure:
        validate_transfer_package(_update_receipt_mutation(mutator))

    assert failure.value.code == "idempotency_policy_invalid"


def test_re_signed_cross_owner_privacy_and_receipt_tampering_still_fail_closed() -> None:
    def cross_owner(_package, sections) -> None:
        sections["food_items"]["records"][0]["user_id"] = (
            "00000000-0000-4000-8000-000000000002"
        )

    with pytest.raises(TransferPackageError) as owner_failure:
        validate_transfer_package(_resigned_representative(cross_owner))
    assert owner_failure.value.code == "owner_graph_invalid"

    def private_reference(_package, sections) -> None:
        row = sections["ocr_nutrition_confirmation_traces"]["records"][0]
        trace = json.loads(row["trace_snapshot"])
        trace["parser_warning_codes"] = ["file:///private/raw-label.png"]
        row["trace_snapshot"] = canonical_transfer_json(trace)

    with pytest.raises(TransferPackageError) as privacy_failure:
        validate_transfer_package(_resigned_representative(private_reference))
    assert privacy_failure.value.code == "privacy_violation"

    def wrong_receipt_count(package, _sections) -> None:
        package["idempotency_policy"]["copied_portable_count"] += 1

    with pytest.raises(TransferPackageError) as receipt_failure:
        validate_transfer_package(_resigned_representative(wrong_receipt_count))
    assert receipt_failure.value.code == "idempotency_policy_invalid"
