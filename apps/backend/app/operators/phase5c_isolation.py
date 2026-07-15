from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterator

from sqlalchemy import Connection, Engine, inspect, text

from app.core.database_identity import database_identity
from app.operators.phase5c_contracts import (
    CLONE_MARKER_VERSION,
    CONVERSION_RULES_VERSION,
    ISOLATION_EVIDENCE_VERSION,
    OPERATOR_ATTESTATION_VERSION,
    Phase5CAdmissionError,
    SAFE_DATABASE_IDENTITY_VERSION,
    canonical_digest,
    canonical_json,
)


CLONE_MARKER_TABLE = "phase5c_conversion_clone_marker"
_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{2,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ATTESTATION_SCOPES = {"bridge", "planning", "bridge_and_planning"}


def validate_operator_label(value: str, label: str) -> str:
    if not _LABEL.fullmatch(value) or "@" in value:
        raise Phase5CAdmissionError(
            f"{label} must be a bounded non-secret operator identifier"
        )
    return value


def conversion_clone_identity_digest(conversion_clone_id: str) -> str:
    validate_operator_label(conversion_clone_id, "conversion clone identity")
    return hashlib.sha256(conversion_clone_id.encode("utf-8")).hexdigest()


def safe_database_identity(connection: Connection) -> dict[str, Any]:
    identity = database_identity(connection.engine.url)
    payload = {
        "identity_contract_version": SAFE_DATABASE_IDENTITY_VERSION,
        "driver_family": identity.driver_family,
        "host": identity.host,
        "port": identity.port,
        "database": identity.database,
        "schema": str(connection.scalar(text("SELECT current_schema()"))),
    }
    return {**payload, "identity_digest": canonical_digest(payload)}


def load_safe_database_identity(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise Phase5CAdmissionError("Unable to read a safe database identity document") from None
    if not isinstance(payload, dict):
        raise Phase5CAdmissionError("Safe database identity must be a JSON object")
    expected_keys = {
        "identity_contract_version",
        "driver_family",
        "host",
        "port",
        "database",
        "schema",
        "identity_digest",
    }
    if set(payload) != expected_keys:
        raise Phase5CAdmissionError("Safe database identity has an unsupported shape")
    if payload.get("identity_contract_version") != SAFE_DATABASE_IDENTITY_VERSION:
        raise Phase5CAdmissionError("Unsupported safe database identity contract version")
    digest = payload.get("identity_digest")
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise Phase5CAdmissionError("Safe database identity digest is invalid")
    unsigned = {key: value for key, value in payload.items() if key != "identity_digest"}
    if canonical_digest(unsigned) != digest:
        raise Phase5CAdmissionError("Safe database identity digest verification failed")
    return payload


def build_operator_attestation(
    connection: Connection,
    *,
    operator_attestation_identity: str,
    scope: str,
    clone_marker_identity: str,
    conversion_clone_id: str,
    source_production_identity_digest: str,
    inventory_digest: str,
    schema_signature: str,
    schema_signature_digest: str,
    conversion_rules_version: str = CONVERSION_RULES_VERSION,
) -> dict[str, Any]:
    validate_operator_label(operator_attestation_identity, "operator attestation identity")
    validate_operator_label(clone_marker_identity, "clone marker identity")
    if scope not in _ATTESTATION_SCOPES:
        raise Phase5CAdmissionError("Unsupported operator attestation scope")
    if not _DIGEST.fullmatch(source_production_identity_digest):
        raise Phase5CAdmissionError("Source-production identity digest is invalid")
    if not _DIGEST.fullmatch(inventory_digest):
        raise Phase5CAdmissionError("Inventory digest is invalid")
    if not _DIGEST.fullmatch(schema_signature_digest):
        raise Phase5CAdmissionError("Schema-signature digest is invalid")
    clone_identity = safe_database_identity(connection)
    clone_database_digest = clone_identity["identity_digest"]
    if clone_database_digest == source_production_identity_digest:
        raise Phase5CAdmissionError(
            "phase5c_clone_matches_source_production_identity"
        )
    unsigned = {
        "attestation_version": OPERATOR_ATTESTATION_VERSION,
        "isolation_evidence_contract_version": ISOLATION_EVIDENCE_VERSION,
        "operator_attestation_identity": operator_attestation_identity,
        "scope": scope,
        "clone_marker_identity": clone_marker_identity,
        "conversion_clone_identity_digest": conversion_clone_identity_digest(
            conversion_clone_id
        ),
        "clone_database_identity_digest": clone_database_digest,
        "source_production_identity_digest": source_production_identity_digest,
        "inventory_digest": inventory_digest,
        "schema_signature": {
            "name": schema_signature,
            "digest": schema_signature_digest,
        },
        "conversion_rules_version": conversion_rules_version,
    }
    return {**unsigned, "attestation_digest": canonical_digest(unsigned)}


def load_operator_attestation(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise Phase5CAdmissionError("Unable to read an operator attestation document") from None
    return validate_operator_attestation(payload)


def validate_operator_attestation(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise Phase5CAdmissionError("Operator attestation must be a JSON object")
    expected_keys = {
        "attestation_version",
        "isolation_evidence_contract_version",
        "operator_attestation_identity",
        "scope",
        "clone_marker_identity",
        "conversion_clone_identity_digest",
        "clone_database_identity_digest",
        "source_production_identity_digest",
        "inventory_digest",
        "schema_signature",
        "conversion_rules_version",
        "attestation_digest",
    }
    if set(payload) != expected_keys:
        raise Phase5CAdmissionError("Operator attestation has an unsupported shape")
    if payload.get("attestation_version") != OPERATOR_ATTESTATION_VERSION:
        raise Phase5CAdmissionError("Unsupported operator attestation version")
    if payload.get("isolation_evidence_contract_version") != ISOLATION_EVIDENCE_VERSION:
        raise Phase5CAdmissionError("Unsupported isolation-evidence contract version")
    validate_operator_label(
        str(payload.get("operator_attestation_identity")),
        "operator attestation identity",
    )
    validate_operator_label(
        str(payload.get("clone_marker_identity")), "clone marker identity"
    )
    if payload.get("scope") not in _ATTESTATION_SCOPES:
        raise Phase5CAdmissionError("Unsupported operator attestation scope")
    digest_fields = (
        "conversion_clone_identity_digest",
        "clone_database_identity_digest",
        "source_production_identity_digest",
        "inventory_digest",
        "attestation_digest",
    )
    if any(
        not isinstance(payload.get(field), str)
        or not _DIGEST.fullmatch(payload[field])
        for field in digest_fields
    ):
        raise Phase5CAdmissionError("Operator attestation contains an invalid digest")
    signature = payload.get("schema_signature")
    if (
        not isinstance(signature, dict)
        or set(signature) != {"name", "digest"}
        or not isinstance(signature.get("digest"), str)
        or not _DIGEST.fullmatch(signature["digest"])
    ):
        raise Phase5CAdmissionError("Operator attestation schema signature is invalid")
    unsigned = {key: value for key, value in payload.items() if key != "attestation_digest"}
    if canonical_digest(unsigned) != payload["attestation_digest"]:
        raise Phase5CAdmissionError("Operator attestation digest verification failed")
    return payload


def _attestation_allows(attestation: dict[str, Any], operation: str) -> bool:
    return attestation["scope"] in {operation, "bridge_and_planning"}


def _marker_unsigned(attestation: dict[str, Any]) -> dict[str, Any]:
    return {
        "marker_format_version": CLONE_MARKER_VERSION,
        "isolation_evidence_contract_version": attestation[
            "isolation_evidence_contract_version"
        ],
        "clone_marker_identity": attestation["clone_marker_identity"],
        "conversion_clone_identity_digest": attestation[
            "conversion_clone_identity_digest"
        ],
        "clone_database_identity_digest": attestation[
            "clone_database_identity_digest"
        ],
        "source_production_identity_digest": attestation[
            "source_production_identity_digest"
        ],
        "inventory_digest": attestation["inventory_digest"],
        "schema_signature": attestation["schema_signature"]["name"],
        "schema_signature_digest": attestation["schema_signature"]["digest"],
        "conversion_rules_version": attestation["conversion_rules_version"],
        "operator_attestation_version": attestation["attestation_version"],
        "operator_attestation_identity": attestation[
            "operator_attestation_identity"
        ],
        "operator_attestation_scope": attestation["scope"],
        "operator_attestation_digest": attestation["attestation_digest"],
    }


def _marker_payload(attestation: dict[str, Any]) -> dict[str, Any]:
    unsigned = _marker_unsigned(attestation)
    return {**unsigned, "clone_marker_digest": canonical_digest(unsigned)}


def _create_marker_table(connection: Connection) -> None:
    connection.execute(
        text(
            f"""
            CREATE TABLE {CLONE_MARKER_TABLE} (
                marker_format_version text NOT NULL,
                isolation_evidence_contract_version text NOT NULL,
                clone_marker_identity text PRIMARY KEY,
                clone_marker_digest text NOT NULL,
                conversion_clone_identity_digest text NOT NULL,
                clone_database_identity_digest text NOT NULL,
                source_production_identity_digest text NOT NULL,
                inventory_digest text NOT NULL,
                schema_signature text NOT NULL,
                schema_signature_digest text NOT NULL,
                conversion_rules_version text NOT NULL,
                operator_attestation_version text NOT NULL,
                operator_attestation_identity text NOT NULL,
                operator_attestation_scope text NOT NULL,
                operator_attestation_digest text NOT NULL
            )
            """
        )
    )


def load_clone_marker(connection: Connection) -> dict[str, Any]:
    if CLONE_MARKER_TABLE not in inspect(connection).get_table_names():
        raise Phase5CAdmissionError("phase5c_clone_marker_missing")
    rows = connection.execute(text(f"SELECT * FROM {CLONE_MARKER_TABLE}")).mappings().all()
    if len(rows) != 1:
        raise Phase5CAdmissionError("phase5c_clone_marker_cardinality_invalid")
    marker = dict(rows[0])
    unsigned = {key: value for key, value in marker.items() if key != "clone_marker_digest"}
    if marker.get("marker_format_version") != CLONE_MARKER_VERSION:
        raise Phase5CAdmissionError("Unsupported conversion-clone marker version")
    if marker.get("isolation_evidence_contract_version") != ISOLATION_EVIDENCE_VERSION:
        raise Phase5CAdmissionError("Unsupported isolation-evidence contract version")
    if canonical_digest(unsigned) != marker.get("clone_marker_digest"):
        raise Phase5CAdmissionError("Conversion-clone marker digest verification failed")
    return marker


def establish_clone_marker(
    engine: Engine,
    *,
    attestation_payload: dict[str, Any],
    clone_marker_identity: str,
    conversion_clone_id: str,
) -> dict[str, Any]:
    if engine.dialect.name != "postgresql":
        raise Phase5CAdmissionError("Conversion-clone markers support PostgreSQL only")
    with engine.begin() as connection:
        return establish_clone_marker_on_connection(
            connection,
            attestation_payload=attestation_payload,
            clone_marker_identity=clone_marker_identity,
            conversion_clone_id=conversion_clone_id,
        )


def establish_clone_marker_on_connection(
    connection: Connection,
    *,
    attestation_payload: dict[str, Any],
    clone_marker_identity: str,
    conversion_clone_id: str,
) -> dict[str, Any]:
    attestation = validate_operator_attestation(attestation_payload)
    validate_operator_label(clone_marker_identity, "clone marker identity")
    expected_clone_digest = conversion_clone_identity_digest(conversion_clone_id)
    if attestation["clone_marker_identity"] != clone_marker_identity:
        raise Phase5CAdmissionError("Clone marker identity does not match attestation")
    if attestation["conversion_clone_identity_digest"] != expected_clone_digest:
        raise Phase5CAdmissionError("Conversion clone identity does not match attestation")
    if connection.dialect.name != "postgresql":
        raise Phase5CAdmissionError("Conversion-clone markers support PostgreSQL only")
    expected = _marker_payload(attestation)
    current_digest = safe_database_identity(connection)["identity_digest"]
    if current_digest != attestation["clone_database_identity_digest"]:
        raise Phase5CAdmissionError("Clone database identity does not match attestation")
    if current_digest == attestation["source_production_identity_digest"]:
        raise Phase5CAdmissionError("phase5c_clone_matches_source_production_identity")
    if CLONE_MARKER_TABLE not in inspect(connection).get_table_names():
        _create_marker_table(connection)
        columns = tuple(expected)
        connection.execute(
            text(
                f"INSERT INTO {CLONE_MARKER_TABLE} ({', '.join(columns)}) VALUES "
                f"({', '.join(':' + column for column in columns)})"
            ),
            expected,
        )
    stored = load_clone_marker(connection)
    if stored != expected:
        raise Phase5CAdmissionError("Existing conversion-clone marker does not match")
    return expected


def verify_clone_isolation_evidence(
    connection: Connection,
    *,
    attestation_payload: dict[str, Any],
    clone_marker_identity: str,
    conversion_clone_id: str,
    inventory_digest: str,
    schema_signature: str,
    schema_signature_digest: str,
    operation: str,
) -> dict[str, Any]:
    attestation = validate_operator_attestation(attestation_payload)
    if operation not in {"bridge", "planning"}:
        raise Phase5CAdmissionError("Unsupported Phase 5C isolation operation")
    if not _attestation_allows(attestation, operation):
        raise Phase5CAdmissionError("Operator attestation scope does not permit this operation")
    expected = {
        "clone_marker_identity": clone_marker_identity,
        "conversion_clone_identity_digest": conversion_clone_identity_digest(
            conversion_clone_id
        ),
        "inventory_digest": inventory_digest,
        "schema_signature": {
            "name": schema_signature,
            "digest": schema_signature_digest,
        },
        "conversion_rules_version": CONVERSION_RULES_VERSION,
    }
    if any(attestation.get(key) != value for key, value in expected.items()):
        raise Phase5CAdmissionError("Operator attestation does not match command evidence")
    current_digest = safe_database_identity(connection)["identity_digest"]
    if current_digest != attestation["clone_database_identity_digest"]:
        raise Phase5CAdmissionError("Clone database identity does not match marker evidence")
    if current_digest == attestation["source_production_identity_digest"]:
        raise Phase5CAdmissionError("phase5c_clone_matches_source_production_identity")
    marker = load_clone_marker(connection)
    if marker != _marker_payload(attestation):
        raise Phase5CAdmissionError("Conversion-clone marker and attestation differ")
    return marker


def _maintenance_lock_key(clone_marker_digest: str) -> int:
    raw = hashlib.sha256(
        f"nutrition-phase5c-maintenance:{clone_marker_digest}".encode("utf-8")
    ).digest()[:8]
    return int.from_bytes(raw, "big", signed=True)


@contextmanager
def phase5c_maintenance_session(
    connection: Connection,
    clone_marker_digest: str,
) -> Iterator[None]:
    key = _maintenance_lock_key(clone_marker_digest)
    connection.execute(text("SELECT pg_advisory_lock_shared(:key)"), {"key": key})
    connection.commit()
    try:
        yield
    finally:
        connection.execute(text("SELECT pg_advisory_unlock_shared(:key)"), {"key": key})
        connection.commit()


def _signed_advisory_key(class_id: int, object_id: int) -> int:
    unsigned = (class_id << 32) | object_id
    return unsigned - (1 << 64) if unsigned >= (1 << 63) else unsigned


def assert_database_session_isolation(
    connection: Connection,
    clone_marker_digest: str,
) -> None:
    maintenance_key = _maintenance_lock_key(clone_marker_digest)
    lock_rows = connection.execute(
        text(
            "SELECT pid, classid::bigint AS classid, objid::bigint AS objid, "
            "objsubid, mode FROM pg_locks "
            "WHERE locktype = 'advisory' AND granted = true AND pid IS NOT NULL"
        )
    ).mappings().all()
    permitted_pids = {
        int(row["pid"])
        for row in lock_rows
        if row["objsubid"] == 1
        and row["mode"] == "ShareLock"
        and _signed_advisory_key(int(row["classid"]), int(row["objid"]))
        == maintenance_key
    }
    session_pids = {
        int(pid)
        for pid in connection.scalars(
            text(
                "SELECT pid FROM pg_stat_activity "
                "WHERE datname = current_database() "
                "AND backend_type = 'client backend' "
                "AND pid <> pg_backend_pid()"
            )
        ).all()
    }
    unpermitted_count = len(session_pids - permitted_pids)
    if unpermitted_count:
        raise Phase5CAdmissionError(
            f"phase5c_nonmaintenance_sessions_connected count={unpermitted_count}"
        )


def safe_identity_json(engine: Engine) -> str:
    if engine.dialect.name != "postgresql":
        raise Phase5CAdmissionError("Safe Phase 5C database identity supports PostgreSQL only")
    with engine.connect() as connection:
        return canonical_json(safe_database_identity(connection))
