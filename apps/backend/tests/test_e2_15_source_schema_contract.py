from __future__ import annotations

import json
from pathlib import Path

from app.transfer.e2_15 import CONTRACT, SCHEMA_CONTRACT_DIGEST, canonical_digest


ROOT = Path(__file__).resolve().parents[3]
DESCRIPTOR_PATH = (
    ROOT / "packages" / "shared-contracts" / "e2-15" / "source-schema.json"
)


def test_pg_0033_source_descriptor_is_complete_frozen_and_digest_bound() -> None:
    frozen = json.loads(DESCRIPTOR_PATH.read_text(encoding="utf-8"))

    assert frozen["descriptor_version"] == "e2-15.pg-0033.schema.v3"
    assert frozen["alembic_revision"] == "0033_complete_runtime_authority"
    assert len(frozen["tables"]) == 32
    assert set(frozen["tables"]) == set(CONTRACT["source"]["expected_public_tables"])
    assert CONTRACT["source"]["optional_public_tables"] == [
        "phase5c_conversion_clone_marker"
    ]
    assert set(frozen["optional_tables"]) == {
        "phase5c_conversion_clone_marker"
    }
    assert frozen["optional_tables"]["phase5c_conversion_clone_marker"] == {
        "checks": [],
        "columns": [
            {"default": None, "name": name, "nullable": False, "type": "text"}
            for name in (
                "marker_format_version",
                "isolation_evidence_contract_version",
                "clone_marker_identity",
                "clone_marker_digest",
                "conversion_clone_identity_digest",
                "clone_database_identity_digest",
                "source_production_identity_digest",
                "inventory_digest",
                "schema_signature",
                "schema_signature_digest",
                "conversion_rules_version",
                "operator_attestation_version",
                "operator_attestation_identity",
                "operator_attestation_scope",
                "operator_attestation_digest",
            )
        ],
        "foreign_keys": [],
        "indexes": [],
        "primary_key": ["clone_marker_identity"],
        "unique_constraints": [],
    }
    assert all(
        set(table) == {
            "checks",
            "columns",
            "foreign_keys",
            "indexes",
            "primary_key",
            "unique_constraints",
        }
        for table in frozen["tables"].values()
    )
    assert frozen["tables"]["daily_logs"]["columns"][0] == {
        "default": "gen_random_uuid()",
        "name": "id",
        "nullable": False,
        "type": "uuid",
    }
    assert frozen["tables"]["alembic_version"]["columns"] == [
        {
            "default": None,
            "name": "version_num",
            "nullable": False,
            "type": "character varying(64)",
        }
    ]
    assert [
        column["name"] for column in frozen["tables"]["daily_logs"]["columns"]
    ] == [
        "id",
        "user_id",
        "food_item_id",
        "logged_date",
        "meal_type",
        "amount_quantity",
        "amount_unit",
        "serving_definition_id",
        "gram_amount",
        "package_fraction",
        "notes",
        "created_at",
        "updated_at",
        "food_name_snapshot",
        "recipe_publication_revision_id",
        "recipe_publication_amount_definition_id",
        "client_request_id",
        "client_request_fingerprint",
    ]
    assert frozen["tables"]["daily_logs"]["primary_key"] == ["id"]
    assert [
        column["name"]
        for column in frozen["tables"][
            "serving_definitions"
        ]["columns"]
    ] == [
        "id",
        "food_item_id",
        "label",
        "quantity",
        "unit",
        "gram_weight",
        "is_default",
        "source",
        "confidence",
        "is_user_confirmed",
        "reference_quantity",
        "reference_unit",
        "reference_gram_weight",
    ]
    assert frozen["tables"]["daily_log_day_completions"] == {
        "checks": [],
        "columns": [
            {
                "default": None,
                "name": "user_id",
                "nullable": False,
                "type": "uuid",
            },
            {
                "default": None,
                "name": "logged_date",
                "nullable": False,
                "type": "date",
            },
            {
                "default": "now()",
                "name": "completed_at",
                "nullable": False,
                "type": "timestamp with time zone",
            },
        ],
        "foreign_keys": [
            {
                "columns": ["user_id"],
                "deferrable": False,
                "initially": None,
                "match": "SIMPLE",
                "name": "fk_daily_log_day_completions_user",
                "ondelete": "CASCADE",
                "onupdate": "NO ACTION",
                "target_columns": ["id"],
                "target_table": "users",
            }
        ],
        "indexes": [],
        "primary_key": ["user_id", "logged_date"],
        "unique_constraints": [],
    }
    assert all(
        foreign_key["match"] == "SIMPLE"
        and foreign_key["ondelete"] is not None
        and foreign_key["onupdate"] == "NO ACTION"
        for table in frozen["tables"].values()
        for foreign_key in table["foreign_keys"]
    )
    assert frozen["immutable_triggers"]
    assert frozen["immutable_routines"]
    assert all("definition_sha256" in routine for routine in frozen["immutable_routines"])
    assert canonical_digest(frozen) == CONTRACT["source"]["schema_descriptor_digest"]
    assert SCHEMA_CONTRACT_DIGEST == CONTRACT["source"]["schema_descriptor_digest"]
