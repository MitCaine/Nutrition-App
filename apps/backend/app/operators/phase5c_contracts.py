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
EXECUTION_REVISION = "0017_phase5c_indexes"
DEFAULT_ARCHIVE_SCHEMA = "nutrition_phase5c_archive"
SAFE_DATABASE_IDENTITY_VERSION = "phase5c_safe_database_identity_v1"
CLONE_MARKER_VERSION = "phase5c_conversion_clone_marker_v1"
OPERATOR_ATTESTATION_VERSION = "phase5c_operator_attestation_v1"
ISOLATION_EVIDENCE_VERSION = "phase5c_isolation_evidence_v1"
EXECUTION_OPERATOR_ATTESTATION_VERSION = "phase5c_operator_attestation_v2"
EXECUTION_ISOLATION_EVIDENCE_VERSION = "phase5c_isolation_evidence_v2"
CONVERTER_VERSION = "phase5c_checkpointed_converter_v1"
EXECUTION_RECEIPT_VERSION = "phase5c_execution_receipt_v1"
QUALIFICATION_RECEIPT_VERSION = "phase5c_conversion_qualification_receipt_v1"
QUALIFIER_VERSION = "phase5c_independent_qualifier_v1"
QUALIFICATION_DIAGNOSTIC_VERSION = "phase5c_qualification_diagnostic_v1"

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_REASON_CODE = re.compile(r"^[a-z][a-z0-9_]{2,127}$")


class Phase5CAdmissionError(RuntimeError):
    """Fail closed when an offline conversion prerequisite is not proven."""


class _DuplicateCanonicalKey(ValueError):
    """Internal signal used to reject duplicate JSON object keys."""


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
    return sha256_digest_bytes(canonical_json(value).encode("utf-8"))


def sha256_digest_bytes(document: bytes) -> str:
    if not isinstance(document, bytes):
        raise TypeError("SHA-256 input must be bytes")
    return hashlib.sha256(document).hexdigest()


def parse_canonical_json(
    document: bytes | str,
    *,
    max_bytes: int = 64 * 1024 * 1024,
) -> Any:
    """Parse an exact canonical JSON byte sequence and reject ambiguous JSON forms.

    Canonical artifacts are immutable bytes, not merely equivalent JSON values. The parser
    therefore rejects duplicate keys, a UTF-8 BOM, whitespace, alternate number spellings, and
    any other input whose bytes differ from the one canonical serializer in this module.
    """
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise TypeError("Canonical JSON byte limit must be a positive integer")
    if isinstance(document, str):
        try:
            raw = document.encode("utf-8")
        except UnicodeEncodeError:
            raise Phase5CAdmissionError("Canonical JSON must be valid UTF-8") from None
    elif isinstance(document, bytes):
        raw = document
    else:
        raise TypeError("Canonical JSON document must be bytes or text")
    if not raw or len(raw) > max_bytes or raw.startswith(b"\xef\xbb\xbf"):
        raise Phase5CAdmissionError("Canonical JSON byte sequence is invalid or oversized")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise Phase5CAdmissionError("Canonical JSON must be valid UTF-8") from None

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise _DuplicateCanonicalKey(key)
            result[key] = value
        return result

    def reject_nonfinite_constant(value: str) -> Any:
        raise ValueError(value)

    try:
        payload = json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite_constant,
        )
    except (json.JSONDecodeError, _DuplicateCanonicalKey, ValueError):
        raise Phase5CAdmissionError("Canonical JSON document is invalid or ambiguous") from None
    try:
        rendered = canonical_json(payload).encode("utf-8")
    except (TypeError, ValueError):
        raise Phase5CAdmissionError("Canonical JSON document contains unsupported values") from None
    if rendered != raw:
        raise Phase5CAdmissionError("JSON document is not in canonical byte form")
    return payload


def load_inventory_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise Phase5CAdmissionError("Unable to read a valid inventory JSON document") from None
    return validate_inventory_contract(payload)


def validate_inventory_contract(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise Phase5CAdmissionError("Historical inventory must be a JSON object")
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
    if set(payload) != required_sections | {"schema_version", "read_only"}:
        raise Phase5CAdmissionError("Historical inventory has an unsupported v1 shape")
    if payload.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise Phase5CAdmissionError("Unsupported historical inventory contract version")
    if payload.get("read_only") is not True:
        raise Phase5CAdmissionError("Historical inventory does not prove read-only inspection")
    if any(
        not isinstance(payload[section], dict)
        for section in required_sections - {"limitations"}
    ):
        raise Phase5CAdmissionError("Historical inventory sections must be JSON objects")
    limitations = payload["limitations"]
    if (
        not isinstance(limitations, list)
        or any(not isinstance(value, str) or not value for value in limitations)
        or limitations != sorted(set(limitations))
    ):
        raise Phase5CAdmissionError("Historical inventory limitations are invalid")
    classification = payload["classification"]
    if set(classification) != {"value", "reason"} or any(
        not isinstance(classification[field], str) or not classification[field]
        for field in classification
    ):
        raise Phase5CAdmissionError("Historical inventory classification is invalid")
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
        or isolation.get("operator_attestation_version") != OPERATOR_ATTESTATION_VERSION
        or isolation.get("operator_attestation_scope") not in {"planning", "bridge_and_planning"}
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


def validate_qualification_receipt_contract(payload: Any) -> dict[str, Any]:
    """Pure validator for the preserved qualification receipt v1 public shape."""
    expected = {
        "receipt_version",
        "verifier_version",
        "plan",
        "execution_attestation",
        "conversion_run_id",
        "execution_receipt",
        "clone_marker_digest",
        "archive_identity_digest",
        "inventory_digest",
        "schema_signature_digest",
        "conversion_rules_version",
        "planned_counts",
        "observed_counts",
        "reason_code_counts",
        "source_roots",
        "daily_log_state_digest",
        "ocr_state_digest",
        "outcome_ledger_digest",
        "verification_result",
        "receipt_digest",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise Phase5CAdmissionError("Qualification receipt has an unsupported shape")
    if (
        payload.get("receipt_version") != QUALIFICATION_RECEIPT_VERSION
        or payload.get("verifier_version") != QUALIFIER_VERSION
        or payload.get("verification_result") != "qualified"
    ):
        raise Phase5CAdmissionError("Qualification receipt identity or result is unsupported")
    for field in (
        "clone_marker_digest",
        "archive_identity_digest",
        "inventory_digest",
        "schema_signature_digest",
        "daily_log_state_digest",
        "ocr_state_digest",
        "outcome_ledger_digest",
        "receipt_digest",
    ):
        if not _is_digest(payload.get(field)):
            raise Phase5CAdmissionError("Qualification receipt contains an invalid digest")
    for field in ("plan", "execution_attestation", "execution_receipt"):
        evidence = payload.get(field)
        if (
            not isinstance(evidence, dict)
            or set(evidence) != {"contract_version", "digest"}
            or not isinstance(evidence["contract_version"], str)
            or not _is_digest(evidence["digest"])
        ):
            raise Phase5CAdmissionError("Qualification receipt evidence reference is invalid")
    try:
        UUID(str(payload.get("conversion_run_id")))
    except (TypeError, ValueError):
        raise Phase5CAdmissionError("Qualification receipt run ID is invalid") from None
    if set(payload.get("source_roots", {})) != {
        "archived_recipes",
        "archived_recipe_ingredients",
        "archive",
        "planning_source",
    } or any(not _is_digest(value) for value in payload["source_roots"].values()):
        raise Phase5CAdmissionError("Qualification receipt source roots are invalid")
    for field in ("planned_counts", "observed_counts"):
        counts = payload.get(field)
        if not isinstance(counts, dict) or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in counts.values()
        ):
            raise Phase5CAdmissionError("Qualification receipt counts are invalid")
    reason_counts = payload.get("reason_code_counts")
    if not isinstance(reason_counts, dict) or set(reason_counts) != {"planned", "observed"}:
        raise Phase5CAdmissionError("Qualification receipt reason counts are invalid")
    for values in reason_counts.values():
        if not isinstance(values, dict) or any(
            not isinstance(code, str)
            or not _REASON_CODE.fullmatch(code)
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
            for code, count in values.items()
        ):
            raise Phase5CAdmissionError("Qualification receipt reason counts are invalid")
    unsigned = {key: value for key, value in payload.items() if key != "receipt_digest"}
    if canonical_digest(unsigned) != payload["receipt_digest"]:
        raise Phase5CAdmissionError("Qualification receipt digest verification failed")
    return payload


def validate_execution_receipt_contract(payload: Any) -> dict[str, Any]:
    """Pure validator for the preserved execution receipt v1 public shape."""
    expected = {
        "receipt_version",
        "run_id",
        "plan_digest",
        "converter_version",
        "counts",
        "subjects",
        "verification_result",
        "report_digest",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise Phase5CAdmissionError("Execution receipt has an unsupported shape")
    if payload.get("receipt_version") != EXECUTION_RECEIPT_VERSION:
        raise Phase5CAdmissionError("Execution receipt version is unsupported")
    try:
        UUID(str(payload.get("run_id")))
    except (TypeError, ValueError):
        raise Phase5CAdmissionError("Execution receipt run ID is invalid") from None
    if not _is_digest(payload.get("plan_digest")) or not _is_digest(
        payload.get("report_digest")
    ):
        raise Phase5CAdmissionError("Execution receipt contains an invalid digest")
    if not isinstance(payload.get("converter_version"), str):
        raise Phase5CAdmissionError("Execution receipt converter version is invalid")
    counts = payload.get("counts")
    if not isinstance(counts, dict) or set(counts) != {
        "converted",
        "quarantined",
        "blocked",
        "failed",
        "pending",
    }:
        raise Phase5CAdmissionError("Execution receipt counts are invalid")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in counts.values()
    ):
        raise Phase5CAdmissionError("Execution receipt counts are invalid")
    subjects = payload.get("subjects")
    if not isinstance(subjects, list) or sum(counts.values()) != len(subjects):
        raise Phase5CAdmissionError("Execution receipt subject coverage is invalid")
    seen: set[UUID] = set()
    for subject in subjects:
        base = {"source_recipe_id", "disposition", "reason_code"}
        converted = subject.get("disposition") == "converted" if isinstance(subject, dict) else False
        expected_subject = base | (
            {"target_recipe_id", "projection_food_item_id", "revision_id", "revision_digest"}
            if converted
            else set()
        )
        if not isinstance(subject, dict) or set(subject) != expected_subject:
            raise Phase5CAdmissionError("Execution receipt subject shape is invalid")
        try:
            recipe_id = UUID(str(subject["source_recipe_id"]))
            if converted:
                UUID(str(subject["target_recipe_id"]))
                UUID(str(subject["projection_food_item_id"]))
                UUID(str(subject["revision_id"]))
        except (TypeError, ValueError):
            raise Phase5CAdmissionError("Execution receipt subject UUID is invalid") from None
        if recipe_id in seen:
            raise Phase5CAdmissionError("Execution receipt subject is duplicated")
        seen.add(recipe_id)
        if subject["disposition"] not in {
            "converted",
            "quarantined",
            "blocked",
            "failed",
            "pending",
        }:
            raise Phase5CAdmissionError("Execution receipt disposition is invalid")
        if not isinstance(subject["reason_code"], str) or not _REASON_CODE.fullmatch(
            subject["reason_code"]
        ):
            raise Phase5CAdmissionError("Execution receipt reason code is invalid")
        if converted and not _is_digest(subject["revision_digest"]):
            raise Phase5CAdmissionError("Execution receipt revision digest is invalid")
    unsigned = {key: value for key, value in payload.items() if key != "report_digest"}
    if canonical_digest(unsigned) != payload["report_digest"]:
        raise Phase5CAdmissionError("Execution receipt digest verification failed")
    return payload
