from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
from typing import Any
from uuid import UUID

from app.operators.historical_database_inventory import REPORT_SCHEMA_VERSION


SUPPORTED_SOURCE_REVISION = "0003_usda_source_identity"
SUPPORTED_SCHEMA_SIGNATURE = "legacy_recipe_pre0004_v1"
CONVERSION_RULES_VERSION = "phase5c_conversion_rules_v1"
CONVERSION_PLAN_VERSION = "phase5c_conversion_plan_v2"
CONTROL_REVISION = "0015_phase5c_conversion_control"
DEFAULT_ARCHIVE_SCHEMA = "nutrition_phase5c_archive"
SAFE_DATABASE_IDENTITY_VERSION = "phase5c_safe_database_identity_v1"
CLONE_MARKER_VERSION = "phase5c_conversion_clone_marker_v1"
OPERATOR_ATTESTATION_VERSION = "phase5c_operator_attestation_v1"
ISOLATION_EVIDENCE_VERSION = "phase5c_isolation_evidence_v1"


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
