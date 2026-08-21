from __future__ import annotations

from copy import deepcopy

import json
from pathlib import Path

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.operators.immutable_provenance_qualification import (
    ImmutableProvenanceQualificationError,
)
from app.transfer.e2_15 import (
    SECTION_NAMES,
    SOURCE_SCHEMA,
    TransferPackageError,
    canonicalize_transfer_scalar,
)
from app.transfer import e2_15_exporter

from app.transfer.e2_15_exporter import (
    REQUIRED_EXPORT_SELECT_TABLES,
    TransferExportError,
    canonical_owner_id,
    local_log_response,
    normalize_reflected_default,
    normalize_reflected_foreign_key_options,
    normalize_reflected_predicate,
    qualify_optional_clone_marker,
    qualify_source_schema,
    source_select_expression,
    target_ready_idempotency,
    translate_update_receipt,
    validate_export_session_observation,
    validate_output_path,
    validate_source_schema_tables,
    write_transfer_file,
)


OWNER = "00000000-0000-4000-8000-000000000001"
LOG_ID = "00000000-0000-4000-8000-000000000101"
FOOD_ID = "00000000-0000-4000-8000-000000000102"
REQUEST_ID = "00000000-0000-4000-8000-000000000103"
INSTANT = "2026-08-10T12:34:56.123456Z"


def test_postgresql_reflection_defaults_are_normalized_without_hiding_changes() -> None:
    assert normalize_reflected_foreign_key_options({}) == {
        "deferrable": False,
        "initially": None,
        "match": "SIMPLE",
        "ondelete": "NO ACTION",
        "onupdate": "NO ACTION",
    }
    assert normalize_reflected_foreign_key_options(
        {"deferrable": True, "initially": "DEFERRED", "ondelete": "CASCADE"}
    ) == {
        "deferrable": True,
        "initially": "DEFERRED",
        "match": "SIMPLE",
        "ondelete": "CASCADE",
        "onupdate": "NO ACTION",
    }
    assert normalize_reflected_default("'general_adult'::text", "general_adult") == (
        "general_adult"
    )
    assert normalize_reflected_predicate(
        "(deleted_at IS NULL) AND (source_id IS NOT NULL)",
        "deleted_at IS NULL AND source_id IS NOT NULL",
    ) == "deleted_at IS NULL AND source_id IS NOT NULL"
    assert normalize_reflected_predicate(
        "(semantic_mode = 'g'::text)", "semantic_mode = 'g'"
    ) == "semantic_mode = 'g'"
    assert normalize_reflected_predicate(
        "deleted_at IS NOT NULL", "deleted_at IS NULL"
    ) == "deleted_at IS NOT NULL"


def _current_source_schema() -> dict:
    return deepcopy(SOURCE_SCHEMA)


class _SchemaQualificationConnection:
    def scalars(self, _statement):
        return [e2_15_exporter.CURRENT_EXPORT_SOURCE_REVISION]


def test_source_schema_requires_exact_current_validator_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _SchemaQualificationConnection()
    manifest_calls: list[object] = []
    monkeypatch.setattr(e2_15_exporter, "observe_source_schema", lambda _connection: _current_source_schema())
    monkeypatch.setattr(
        e2_15_exporter,
        "qualify_immutable_provenance_manifest",
        lambda value: manifest_calls.append(value),
    )
    monkeypatch.setattr(
        e2_15_exporter,
        "qualify_current_validator_inputs",
        lambda _value: (_ for _ in ()).throw(
            ImmutableProvenanceQualificationError("current authority mismatch")
        ),
    )

    with pytest.raises(TransferExportError) as failure:
        qualify_source_schema(connection)  # type: ignore[arg-type]

    assert failure.value.code == "source_immutability_invalid"
    assert manifest_calls == [connection]


def test_source_schema_accepts_only_required_tables_plus_the_single_optional_marker() -> None:
    required = SOURCE_SCHEMA["tables"]
    marker_name = "phase5c_conversion_clone_marker"
    marker = SOURCE_SCHEMA["optional_tables"][marker_name]

    assert validate_source_schema_tables(required) is False
    assert validate_source_schema_tables({**required, marker_name: marker}) is True

    for invalid in (
        {name: value for name, value in required.items() if name != "users"},
        {**required, "unexpected_public_table": marker},
        {
            **required,
            marker_name: {
                **marker,
                "columns": marker["columns"][:-1],
            },
        },
    ):
        with pytest.raises(TransferExportError) as failure:
            validate_source_schema_tables(invalid)
        assert failure.value.code == "source_schema_invalid"


def test_optional_clone_marker_uses_authoritative_semantics_and_exact_protections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = object()
    marker = {"marker_format_version": "validated-by-authority"}
    semantic_calls: list[object] = []
    monkeypatch.setattr(
        e2_15_exporter,
        "load_clone_marker",
        lambda value: semantic_calls.append(value) or marker,
    )
    monkeypatch.setattr(
        e2_15_exporter,
        "observe_clone_marker_protections",
        lambda value: e2_15_exporter.EXPECTED_CLONE_MARKER_PROTECTIONS,
    )

    assert qualify_optional_clone_marker(connection) == marker  # type: ignore[arg-type]
    assert semantic_calls == [connection]


def test_optional_clone_marker_rejects_semantic_or_protection_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = object()
    monkeypatch.setattr(
        e2_15_exporter,
        "load_clone_marker",
        lambda _value: {"marker_format_version": "validated-by-authority"},
    )
    monkeypatch.setattr(
        e2_15_exporter,
        "observe_clone_marker_protections",
        lambda _value: (),
    )

    with pytest.raises(TransferExportError) as protection_failure:
        qualify_optional_clone_marker(connection)  # type: ignore[arg-type]
    assert protection_failure.value.code == "source_immutability_invalid"

    def malformed(_value):
        raise e2_15_exporter.Phase5CAdmissionError("malformed marker")

    monkeypatch.setattr(e2_15_exporter, "load_clone_marker", malformed)
    with pytest.raises(TransferExportError) as semantic_failure:
        qualify_optional_clone_marker(connection)  # type: ignore[arg-type]
    assert semantic_failure.value.code == "source_marker_invalid"


def test_source_schema_requires_manifest_and_current_validator_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _SchemaQualificationConnection()
    manifest_calls: list[object] = []
    authority_calls: list[object] = []
    monkeypatch.setattr(e2_15_exporter, "observe_source_schema", lambda _connection: _current_source_schema())
    monkeypatch.setattr(
        e2_15_exporter,
        "qualify_immutable_provenance_manifest",
        lambda value: manifest_calls.append(value),
    )
    monkeypatch.setattr(
        e2_15_exporter,
        "qualify_current_validator_inputs",
        lambda value: authority_calls.append(value),
    )

    qualify_source_schema(connection)  # type: ignore[arg-type]

    assert manifest_calls == [connection]
    assert authority_calls == [connection]


def test_source_schema_fails_closed_when_current_validator_input_read_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _SchemaQualificationConnection()
    monkeypatch.setattr(e2_15_exporter, "observe_source_schema", lambda _connection: _current_source_schema())
    monkeypatch.setattr(e2_15_exporter, "qualify_immutable_provenance_manifest", lambda _value: None)
    monkeypatch.setattr(
        e2_15_exporter,
        "qualify_current_validator_inputs",
        lambda _value: (_ for _ in ()).throw(SQLAlchemyError("missing routine")),
    )

    with pytest.raises(TransferExportError) as failure:
        qualify_source_schema(connection)  # type: ignore[arg-type]

    assert failure.value.code == "source_immutability_invalid"


def test_source_schema_still_requires_manifest_qualification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _SchemaQualificationConnection()
    monkeypatch.setattr(e2_15_exporter, "observe_source_schema", lambda _connection: _current_source_schema())

    def fail_manifest(_connection) -> None:
        raise ImmutableProvenanceQualificationError("manifest mismatch")

    monkeypatch.setattr(
        e2_15_exporter,
        "qualify_immutable_provenance_manifest",
        fail_manifest,
    )
    authority_calls: list[object] = []
    monkeypatch.setattr(
        e2_15_exporter,
        "qualify_current_validator_inputs",
        lambda value: authority_calls.append(value),
    )

    with pytest.raises(TransferExportError) as failure:
        qualify_source_schema(connection)  # type: ignore[arg-type]

    assert failure.value.code == "source_immutability_invalid"
    assert authority_calls == []


def test_export_request_requires_canonical_owner_and_new_fixed_extension(tmp_path: Path) -> None:
    assert canonical_owner_id(OWNER) == OWNER
    with pytest.raises(TransferExportError):
        canonical_owner_id("A0B1C2D3-E4F5-4678-9012-ABCDEF123456")
    output = tmp_path / "owner.nutrition-transfer.json"
    assert validate_output_path(output) == output
    output.touch()
    with pytest.raises(TransferExportError):
        validate_output_path(output)


def test_export_session_is_exact_read_only_serializable_deferrable_qualifier() -> None:
    valid = {
        "current_user": "nutrition_qualifier",
        "session_user": "nutrition_qualifier",
        "default_read_only": "on",
        "transaction_read_only": "on",
        "transaction_isolation": "serializable",
        "transaction_deferrable": "on",
        "postgres_major": "16",
        "role_superuser": False,
        "role_create_db": False,
        "role_create_role": False,
        "role_replication": False,
        "role_bypass_rls": False,
        "database_create": False,
        "database_temp": False,
        "schema_create": False,
        "missing_select_count": 0,
        "write_privilege_count": 0,
        "sequence_write_privilege_count": 0,
    }
    validate_export_session_observation(valid)
    for key in valid:
        altered = dict(valid)
        altered[key] = not valid[key] if isinstance(valid[key], bool) else "wrong"
        with pytest.raises(TransferExportError) as failure:
            validate_export_session_observation(altered)
        assert failure.value.code == "source_authority_invalid"


def test_export_select_authority_is_limited_to_actual_e2_15_read_dependencies() -> None:
    assert set(REQUIRED_EXPORT_SELECT_TABLES) == {
        "alembic_version",
        "nutrients",
        *SECTION_NAMES,
        "phase5c_conversion_clone_marker",
    }
    assert set(REQUIRED_EXPORT_SELECT_TABLES).isdisjoint({
        "phase5c_activation_runtime_commands",
        "phase5c_activation_schema_evidence",
        "phase5c_promotion_target_identity",
        "phase5c_write_fence_events",
        "phase5c_write_fence_state",
    })


def test_update_receipt_translation_validates_remote_and_projects_exact_local_shape() -> None:
    row = {
        "response_snapshot": {
            "id": LOG_ID,
            "food_item_id": FOOD_ID,
            "food_name_snapshot": "Historical Food",
            "is_editable": True,
            "source_food_available": True,
            "edit_block_reason": None,
            "logged_date": "2026-08-10",
            "meal_type": "lunch",
            "amount_quantity": "1.000000",
            "amount_unit": "serving",
            "serving_definition_id": None,
            "gram_amount": None,
            "package_fraction": None,
            "notes": None,
            "created_at": INSTANT,
            "updated_at": INSTANT,
            "snapshots": [],
            "_source_logged_date": "2026-08-09",
            "_destination_logged_date": "2026-08-10",
        }
    }
    translated = translate_update_receipt(row)
    assert translated["response_snapshot"] == {
        "kind": "log.update",
        "source_logged_date": "2026-08-09",
        "destination_logged_date": "2026-08-10",
        "result": {
            "id": LOG_ID,
            "food_item_id": FOOD_ID,
            "food_name_snapshot": "Historical Food",
            "is_editable": True,
            "source_food_available": True,
            "edit_block_reason": None,
            "logged_date": "2026-08-10",
            "meal_type": "lunch",
            "amount_quantity": "1.000000",
            "amount_unit": "serving",
            "serving_definition_id": None,
            "gram_amount": None,
            "notes": None,
            "created_at": INSTANT,
            "updated_at": INSTANT,
        },
    }


def test_update_receipt_translation_rejects_non_exact_remote_shape() -> None:
    snapshot = {
        "id": LOG_ID,
        "food_item_id": FOOD_ID,
        "food_name_snapshot": "Historical Food",
        "is_editable": True,
        "source_food_available": True,
        "edit_block_reason": None,
        "logged_date": "2026-08-10",
        "meal_type": None,
        "amount_quantity": "1.000000",
        "amount_unit": "serving",
        "serving_definition_id": None,
        "gram_amount": None,
        "package_fraction": None,
        "notes": None,
        "created_at": INSTANT,
        "updated_at": INSTANT,
        "snapshots": [],
        "_source_logged_date": "2026-08-09",
        "_destination_logged_date": "2026-08-10",
        "unexpected": True,
    }

    with pytest.raises(TransferExportError) as failure:
        translate_update_receipt({"response_snapshot": snapshot})

    assert failure.value.code == "source_idempotency_invalid"


def test_json_source_projection_preserves_sql_null_versus_json_literal_null() -> None:
    assert source_select_expression("metadata", "nullable_json_document") == (
        'CAST(source."metadata" AS text) AS "metadata"'
    )
    assert source_select_expression("name", "text") == 'source."name"'
    assert canonicalize_transfer_scalar("nullable_json_document", None) is None
    assert canonicalize_transfer_scalar("nullable_json_document", "null") == "null"
    assert canonicalize_transfer_scalar(
        "json_document", '{ "z": 1, "a": null }'
    ) == '{"a":null,"z":1}'
    with pytest.raises(TransferPackageError):
        canonicalize_transfer_scalar("json_document", None)


def _log() -> dict:
    return {
        "id": LOG_ID,
        "user_id": OWNER,
        "food_item_id": FOOD_ID,
        "food_name_snapshot": "Deleted Food",
        "client_request_id": REQUEST_ID,
        "client_request_fingerprint": "1" * 64,
        "logged_date": "2026-08-10",
        "meal_type": "lunch",
        "amount_quantity": "1.000000",
        "amount_unit": "serving",
        "serving_definition_id": None,
        "recipe_publication_revision_id": None,
        "recipe_publication_amount_definition_id": None,
        "gram_amount": None,
        "package_fraction": None,
        "notes": None,
        "created_at": INSTANT,
        "updated_at": INSTANT,
    }


def _food() -> dict:
    return {
        "id": FOOD_ID,
        "user_id": OWNER,
        "name": "Deleted Food",
        "brand": None,
        "source_type": "manual",
        "source_id": None,
        "recipe_publication_revision_id": None,
        "is_recipe": False,
        "notes": None,
        "created_at": INSTANT,
        "updated_at": INSTANT,
        "deleted_at": INSTANT,
    }


def test_log_create_receipt_is_deterministic_and_uses_local_response_shape() -> None:
    log = _log()
    food = _food()
    response = local_log_response(log, food, {}, {})
    assert response["source_food_available"] is False
    assert response["is_editable"] is False
    assert response["edit_block_reason"] == "source_food_deleted"
    assert "package_fraction" not in response

    first, counts = target_ready_idempotency([], [log], [food], [], [], owner_id=OWNER)
    second, _ = target_ready_idempotency([], [log], [food], [], [], owner_id=OWNER)
    assert first == second
    assert first[0]["operation"] == "log.create"
    assert first[0]["response_snapshot"] == (
        '{"amount_quantity":"1.000000","amount_unit":"serving",'
        '"created_at":"2026-08-10T12:34:56.123456Z",'
        '"edit_block_reason":"source_food_deleted",'
        '"food_item_id":"00000000-0000-4000-8000-000000000102",'
        '"food_name_snapshot":"Deleted Food",'
        '"gram_amount":null,"id":"00000000-0000-4000-8000-000000000101",'
        '"is_editable":false,"logged_date":"2026-08-10","meal_type":"lunch",'
        '"notes":null,"serving_definition_id":null,"source_food_available":false,'
        '"updated_at":"2026-08-10T12:34:56.123456Z"}'
    )
    assert counts == {
        "copied_portable_count": 0,
        "translated_log_update_count": 0,
        "reconstructed_log_create_count": 1,
        "excluded_log_delete_count": 0,
    }


def test_incomplete_unknown_and_source_log_create_receipts_are_rejected() -> None:
    base = {
        "id": "00000000-0000-4000-8000-000000000201",
        "user_id": OWNER,
        "operation": "food.create_manual",
        "client_request_id": "00000000-0000-4000-8000-000000000202",
        "request_fingerprint": "2" * 64,
        "resource_id": FOOD_ID,
        "response_snapshot": None,
        "completed_at": None,
        "created_at": INSTANT,
    }
    for operation in (
        "food.create_manual",
        "food.duplicate",
        "food.add_serving",
        "recipe.create",
        "recipe.duplicate",
        "recipe.publish",
        "unknown",
        "log.create",
    ):
        row = {**base, "operation": operation}
        if operation != "food.create_manual":
            row.update(response_snapshot={"id": FOOD_ID}, completed_at=INSTANT)
        with pytest.raises(TransferExportError) as failure:
            target_ready_idempotency([row], [], [], [], [], owner_id=OWNER)
        assert failure.value.code == "source_idempotency_invalid"


def _delete_receipt(**changes) -> dict:
    row = {
        "id": "00000000-0000-4000-8000-000000000201",
        "user_id": OWNER,
        "operation": "log.delete",
        "client_request_id": "00000000-0000-4000-8000-000000000202",
        "request_fingerprint": "2" * 64,
        "resource_id": LOG_ID,
        "response_snapshot": {"deleted": True, "log_id": LOG_ID},
        "completed_at": INSTANT,
        "created_at": INSTANT,
    }
    row.update(changes)
    return row


def test_valid_log_delete_receipt_is_validated_then_excluded() -> None:
    receipts, counts = target_ready_idempotency(
        [_delete_receipt()], [], [], [], [], owner_id=OWNER
    )

    assert receipts == []
    assert counts["excluded_log_delete_count"] == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"response_snapshot": {"deleted": False, "log_id": LOG_ID}},
        {
            "response_snapshot": {
                "deleted": True,
                "log_id": "00000000-0000-4000-8000-000000000299",
            }
        },
        {"response_snapshot": {"deleted": True, "log_id": LOG_ID, "extra": True}},
        {"request_fingerprint": "not-a-fingerprint"},
        {"id": "not-a-uuid"},
        {"completed_at": "not-an-instant"},
        {"user_id": "00000000-0000-4000-8000-000000000002"},
    ],
)
def test_malformed_log_delete_receipt_rejects_export(changes: dict) -> None:
    with pytest.raises(TransferExportError) as failure:
        target_ready_idempotency(
            [_delete_receipt(**changes)], [], [], [], [], owner_id=OWNER
        )

    assert failure.value.code == "source_idempotency_invalid"


def test_exporter_accepts_only_a_complete_portable_receipt_snapshot() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[3]
        / "packages/shared-contracts/e2-15/representative-package.json"
    )
    package = json.loads(fixture_path.read_text(encoding="utf-8"))
    sections = {section["name"]: section["records"] for section in package["sections"]}
    receipt = next(
        row
        for row in sections["create_operation_idempotency"]
        if row["operation"] == "food.create_manual"
    )
    source_receipt = {**receipt, "response_snapshot": json.loads(receipt["response_snapshot"])}

    copied, counts = target_ready_idempotency(
        [source_receipt],
        [],
        sections["food_items"],
        sections["recipes"],
        sections["recipe_publication_revisions"],
        sections["serving_definitions"],
        owner_id=OWNER,
    )

    assert copied[0]["response_snapshot"] == receipt["response_snapshot"]
    assert counts["copied_portable_count"] == 1


def test_exporter_accepts_completed_recipe_duplicate_without_source_recipe() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[3]
        / "packages/shared-contracts/e2-15/representative-package.json"
    )
    package = json.loads(fixture_path.read_text(encoding="utf-8"))
    sections = {section["name"]: section["records"] for section in package["sections"]}
    receipt = next(
        row
        for row in sections["create_operation_idempotency"]
        if row["operation"] == "recipe.duplicate"
    )
    result_recipe = next(
        row for row in sections["recipes"] if row["id"] == receipt["resource_id"]
    )
    copied, counts = target_ready_idempotency(
        [{**receipt, "response_snapshot": json.loads(receipt["response_snapshot"])}],
        [],
        [],
        [result_recipe],
        [],
        [],
        owner_id=OWNER,
    )
    assert copied[0]["operation"] == "recipe.duplicate"
    assert copied[0]["resource_id"] == result_recipe["id"]
    assert counts["copied_portable_count"] == 1


def test_file_publish_is_0600_canonical_and_never_overwrites(tmp_path: Path) -> None:
    document = {
        "format": "nutrition-personal-transfer",
        "sections": [],
    }
    output = tmp_path / "owner.nutrition-transfer.json"
    result = write_transfer_file(document, output)
    assert result.output_path == output
    assert output.stat().st_mode & 0o777 == 0o600
    assert output.read_bytes().endswith(b"}")
    assert not output.read_bytes().endswith(b"\n")
    with pytest.raises(TransferExportError):
        write_transfer_file(document, output)
    assert not list(tmp_path.glob("*.tmp"))
