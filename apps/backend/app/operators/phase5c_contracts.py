from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any
from uuid import UUID

from app.operators.historical_database_inventory import REPORT_SCHEMA_VERSION


SUPPORTED_SOURCE_REVISION = "0003_usda_source_identity"
SUPPORTED_SCHEMA_SIGNATURE = "legacy_recipe_pre0004_v1"
CONVERSION_RULES_VERSION = "phase5c_conversion_rules_v1"
CONVERSION_PLAN_VERSION = "phase5c_conversion_plan_v2"
CONTROL_REVISION = "0015_phase5c_conversion_control"
EXECUTION_REVISION = "0016_phase5c_execution"
DEFAULT_ARCHIVE_SCHEMA = "nutrition_phase5c_archive"
SAFE_DATABASE_IDENTITY_VERSION = "phase5c_safe_database_identity_v1"
CLONE_MARKER_VERSION = "phase5c_conversion_clone_marker_v1"
OPERATOR_ATTESTATION_VERSION = "phase5c_operator_attestation_v1"
ISOLATION_EVIDENCE_VERSION = "phase5c_isolation_evidence_v1"
EXECUTION_OPERATOR_ATTESTATION_VERSION = "phase5c_operator_attestation_v2"
EXECUTION_ISOLATION_EVIDENCE_VERSION = "phase5c_isolation_evidence_v2"
CONVERTER_VERSION = "phase5c_checkpointed_converter_v1"
EXECUTION_RECEIPT_VERSION = "phase5c_execution_receipt_v1"

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_REASON_CODE = re.compile(r"^[a-z][a-z0-9_]{2,127}$")


class Phase5CAdmissionError(RuntimeError):
    """Fail closed when an offline conversion prerequisite is not proven."""


def normalize_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("Non-finite numbers are not valid canonical JSON")
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(key): normalize_json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [normalize_json_value(item) for item in value]
    raise TypeError(f"Unsupported canonical JSON value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        normalize_json_value(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_inventory_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise Phase5CAdmissionError("Unable to read a valid inventory JSON document") from None
    return validate_inventory_contract(payload)


def validate_inventory_contract(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise Phase5CAdmissionError("Historical inventory must be a JSON object")
    if payload.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise Phase5CAdmissionError("Unsupported historical inventory contract version")
    if payload.get("read_only") is not True:
        raise Phase5CAdmissionError("Historical inventory does not prove read-only inspection")
    required_sections = {
        "classification",
        "migration",
        "legacy_recipes",
        "current_recipes",
        "revisions",
        "daily_logs",
        "ocr",
        "idempotency",
        "retention",
        "consistency",
        "limitations",
    }
    if not required_sections <= payload.keys():
        raise Phase5CAdmissionError("Historical inventory is missing required v1 sections")
    return payload


def load_conversion_plan_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise Phase5CAdmissionError("Unable to read a valid conversion plan") from None
    return validate_conversion_plan_contract(payload)


def validate_conversion_plan_contract(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise Phase5CAdmissionError("Historical conversion plan must be a JSON object")
    expected_top = {
        "manifest_version",
        "inventory_contract_version",
        "supported_schema_signature",
        "inventory_digest",
        "conversion_rules_version",
        "source_identity",
        "isolation_evidence",
        "ordering",
        "source_checksums",
        "summary",
        "decisions",
        "manifest_digest",
    }
    if set(payload) != expected_top:
        raise Phase5CAdmissionError("Conversion plan has an unsupported v2 shape")
    if payload.get("manifest_version") != CONVERSION_PLAN_VERSION:
        raise Phase5CAdmissionError("Unsupported conversion plan version")
    if payload.get("inventory_contract_version") != REPORT_SCHEMA_VERSION:
        raise Phase5CAdmissionError("Unsupported inventory version in conversion plan")
    if payload.get("conversion_rules_version") != CONVERSION_RULES_VERSION:
        raise Phase5CAdmissionError("Unsupported conversion rules in conversion plan")
    signature = payload.get("supported_schema_signature")
    if (
        not isinstance(signature, dict)
        or set(signature) != {"name", "digest"}
        or signature.get("name") != SUPPORTED_SCHEMA_SIGNATURE
        or not _is_digest(signature.get("digest"))
    ):
        raise Phase5CAdmissionError("Unsupported schema signature in conversion plan")
    source_identity = payload.get("source_identity")
    if not isinstance(source_identity, dict) or set(source_identity) != {
        "driver_family",
        "host",
        "port",
        "database",
        "source_schema",
        "archive_schema",
        "conversion_clone_identity_digest",
        "archive_identity",
    }:
        raise Phase5CAdmissionError("Conversion plan source identity is invalid")
    isolation = payload.get("isolation_evidence")
    if not isinstance(isolation, dict) or set(isolation) != {
        "contract_version",
        "marker_format_version",
        "clone_marker_identity",
        "clone_marker_digest",
        "conversion_clone_identity_digest",
        "clone_database_identity_digest",
        "source_production_identity_digest",
        "operator_attestation_version",
        "operator_attestation_identity",
        "operator_attestation_scope",
        "operator_attestation_digest",
    }:
        raise Phase5CAdmissionError("Conversion plan isolation evidence is invalid")
    if (
        isolation.get("contract_version") != ISOLATION_EVIDENCE_VERSION
        or isolation.get("marker_format_version") != CLONE_MARKER_VERSION
        or isolation.get("operator_attestation_version")
        != OPERATOR_ATTESTATION_VERSION
        or isolation.get("operator_attestation_scope")
        not in {"planning", "bridge_and_planning"}
        or source_identity.get("conversion_clone_identity_digest")
        != isolation.get("conversion_clone_identity_digest")
    ):
        raise Phase5CAdmissionError("Conversion plan isolation contract is unsupported")
    ordering = payload.get("ordering")
    if ordering != {
        "recipes": "source_recipe_id_ascending",
        "ingredients": "sort_order_then_source_ingredient_id",
    }:
        raise Phase5CAdmissionError("Conversion plan ordering contract is invalid")
    source_checksums = payload.get("source_checksums")
    if not isinstance(source_checksums, dict) or set(source_checksums) != {
        "archived_recipes",
        "archived_recipe_ingredients",
        "archive",
        "planning_source",
    }:
        raise Phase5CAdmissionError("Conversion plan source checksums are invalid")
    digest_values = [
        payload.get("inventory_digest"),
        payload.get("manifest_digest"),
        signature.get("digest"),
        source_identity.get("conversion_clone_identity_digest"),
        source_identity.get("archive_identity"),
        isolation.get("clone_marker_digest"),
        isolation.get("conversion_clone_identity_digest"),
        isolation.get("clone_database_identity_digest"),
        isolation.get("source_production_identity_digest"),
        isolation.get("operator_attestation_digest"),
        *source_checksums.values(),
    ]
    if any(not _is_digest(value) for value in digest_values):
        raise Phase5CAdmissionError("Conversion plan contains an invalid digest")
    decisions = payload.get("decisions")
    if not isinstance(decisions, list):
        raise Phase5CAdmissionError("Conversion plan decisions must be a list")
    seen: set[UUID] = set()
    counts = {"convert": 0, "quarantine": 0, "block": 0}
    previous: UUID | None = None
    for decision in decisions:
        if not isinstance(decision, dict) or set(decision) != {
            "source_recipe_id",
            "source_checksum",
            "intended_disposition",
            "reason_code",
        }:
            raise Phase5CAdmissionError("Conversion plan decision shape is invalid")
        try:
            recipe_id = UUID(str(decision["source_recipe_id"]))
        except (TypeError, ValueError):
            raise Phase5CAdmissionError("Conversion plan contains an invalid Recipe UUID") from None
        if recipe_id in seen or (previous is not None and str(recipe_id) <= str(previous)):
            raise Phase5CAdmissionError("Conversion plan Recipe ordering is invalid")
        seen.add(recipe_id)
        previous = recipe_id
        disposition = decision.get("intended_disposition")
        if disposition not in counts:
            raise Phase5CAdmissionError("Conversion plan disposition is invalid")
        counts[disposition] += 1
        if not _is_digest(decision.get("source_checksum")):
            raise Phase5CAdmissionError("Conversion plan source checksum is invalid")
        reason = decision.get("reason_code")
        if not isinstance(reason, str) or not _REASON_CODE.fullmatch(reason):
            raise Phase5CAdmissionError("Conversion plan reason code is invalid")
    summary = payload.get("summary")
    expected_summary = {"total": len(decisions), **counts}
    if summary != expected_summary:
        raise Phase5CAdmissionError("Conversion plan summary does not match decisions")
    unsigned = {key: value for key, value in payload.items() if key != "manifest_digest"}
    if canonical_digest(unsigned) != payload["manifest_digest"]:
        raise Phase5CAdmissionError("Conversion plan digest verification failed")
    return payload


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(_DIGEST.fullmatch(value))
