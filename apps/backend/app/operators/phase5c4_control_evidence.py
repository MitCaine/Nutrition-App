"""Strict artifact preparation and cross-plane evidence collection for 5C4.3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import stat
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.operators import phase5c_contracts as canonical
from app.operators import phase5c4_contracts
from app.operators.phase5c4_prerequisites import (
    Phase5C4PrerequisiteError,
    validate_prerequisite_observation,
)


APPLICATION_QUALIFIER_LOCK = 5_542_018
APPLICATION_QUALIFIER_HEAD = "0018_phase5c_promotion_prerequisites"


class Phase5C4EvidenceError(RuntimeError):
    """Reject unsafe files, unsupported artifacts, or substituted evidence."""


LOGICAL_IDENTITY_VERSION = "phase5c4_artifact_logical_identity_v1"
ARTIFACT_LOGICAL_IDENTITY_RULES: dict[str, str] = {
    "historical_database_inventory_v1": "artifact_digest_content",
    "phase5c_safe_database_identity_v1": "identity_digest",
    "phase5c_database_incarnation_identity_v1": "observation_id",
    "phase5c_clone_origin_receipt_v1": "receipt_id",
    "phase5c_conversion_clone_marker_v1": "clone_marker_identity",
    "phase5c_bridge_metadata_evidence_v1": "evidence_id",
    "phase5c_conversion_plan_v2": "manifest_digest",
    "phase5c_operator_attestation_v1": "attestation_digest",
    "phase5c_operator_attestation_v2": "attestation_digest",
    "phase5c_run_outcomes_admission_receipt_v1": "receipt_id",
    "phase5c_execution_receipt_v1": "run_id",
    "phase5c_conversion_qualification_receipt_v1": "conversion_run_id",
    "phase5c_qualification_observation_v1": "observation_id",
    "phase5c_candidate_state_seal_v1": "target_database_incarnation_digest",
    "phase5c_source_candidate_reconciliation_v1": "reconciliation_id",
    "phase5c_performance_qualification_manifest_v1": "manifest_digest",
    "phase5c_performance_contract_ratification_v1": "payload.ratification_id",
    "phase5c_backup_evidence_v1": "evidence_id",
    "phase5c_restore_test_receipt_v1": "receipt_id",
    "phase5c_quarantine_acceptance_v1": "payload.acceptance_id",
    "phase5c_zero_block_receipt_v1": "run_id",
    "phase5c_promotion_policy_v1": "policy_digest",
    "phase5c_deployment_routing_descriptor_v1": "descriptor_id",
}


def _logical_identity_scope(
    artifact_type: str,
    payload: dict[str, Any],
    artifact_digest: str,
) -> str:
    rule = ARTIFACT_LOGICAL_IDENTITY_RULES.get(artifact_type)
    if rule is None:
        raise Phase5C4EvidenceError("Artifact logical identity rule is missing")
    if rule == "artifact_digest_content":
        return artifact_digest
    value: Any = payload
    for component in rule.split("."):
        if not isinstance(value, dict) or component not in value:
            raise Phase5C4EvidenceError("Artifact logical identity scope is missing")
        value = value[component]
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise Phase5C4EvidenceError("Artifact logical identity scope is invalid")
    return value


@dataclass(frozen=True)
class PreparedArtifact:
    artifact_type: str
    contract_version: str
    logical_id: str
    canonical_bytes: bytes
    logical_identity_bytes: bytes
    artifact_digest: str
    parsed: dict[str, Any]
    bindings: tuple[dict[str, Any], ...]


def _read_regular_file(path: Path, *, maximum_bytes: int) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise Phase5C4EvidenceError("Unable to open canonical evidence file") from None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size < 1:
            raise Phase5C4EvidenceError("Evidence path must be a nonempty regular file")
        if metadata.st_size > maximum_bytes:
            raise Phase5C4EvidenceError("Canonical evidence exceeds its contract limit")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, maximum_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum_bytes:
                raise Phase5C4EvidenceError("Canonical evidence exceeds its contract limit")
        document = b"".join(chunks)
        if len(document) != metadata.st_size:
            raise Phase5C4EvidenceError("Evidence file changed while it was read")
        return document
    finally:
        os.close(descriptor)


def _binding(name: str, value_type: str, value: Any) -> dict[str, Any]:
    return {"name": name, "type": value_type, "value": str(value)}


def _safe_bindings(payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    bindings: list[dict[str, Any]] = []
    for name, value in sorted(payload.items()):
        if value is None or len(name) > 128:
            continue
        if name.endswith("digest") and isinstance(value, str) and len(value) == 64:
            bindings.append(_binding(name, "digest", value))
            continue
        if name.endswith(("_id", "_uuid", "_nonce")) and isinstance(value, str):
            try:
                normalized = str(UUID(value))
            except ValueError:
                continue
            if value == normalized:
                bindings.append(_binding(name, "uuid", value))
            continue
        if name.endswith("_lsn") and isinstance(value, str) and "/" in value:
            bindings.append(_binding(name, "lsn", value))
            continue
        if name.endswith(("_at", "_time")) and isinstance(value, str):
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
            bindings.append(_binding(name, "time", value))
            continue
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            bindings.append(_binding(name, "integer", value))
            continue
        if (
            isinstance(value, str)
            and name.endswith(("version", "type", "role", "mode", "tier"))
            and 0 < len(value) <= 1024
        ):
            bindings.append(_binding(name, "text", value))
    structural_rules = payload.get("structural_rules")
    if isinstance(structural_rules, dict):
        bindings.append(
            _binding(
                "rules_digest",
                "digest",
                canonical.canonical_digest(structural_rules),
            )
        )
    deduplicated = {(item["name"], item["type"]): item for item in bindings}
    return tuple(deduplicated[key] for key in sorted(deduplicated))


def prepare_artifact(
    *,
    artifact_type: str,
    contract_version: str,
    logical_id: str,
    path: Path,
) -> PreparedArtifact:
    expected_version = phase5c4_contracts.ARTIFACT_TYPE_VERSIONS.get(artifact_type)
    if expected_version is None or expected_version != contract_version:
        raise Phase5C4EvidenceError("Unsupported artifact type or contract version")
    allowed_logical_ids = set(
        phase5c4_contracts.ARTIFACT_REQUIRED_LOGICAL_IDS.get(artifact_type, ())
    ) | set(phase5c4_contracts.ARTIFACT_OPTIONAL_LOGICAL_IDS.get(artifact_type, ()))
    if allowed_logical_ids and logical_id not in allowed_logical_ids:
        raise Phase5C4EvidenceError("Artifact logical identity is unsupported")
    maximum = phase5c4_contracts.ARTIFACT_MAX_BYTES.get(artifact_type, 4 * 1024 * 1024)
    document = _read_regular_file(path, maximum_bytes=maximum)
    try:
        parsed = canonical.parse_canonical_json(document, max_bytes=maximum)
    except canonical.Phase5CAdmissionError as exc:
        raise Phase5C4EvidenceError(str(exc)) from None
    if not isinstance(parsed, dict):
        raise Phase5C4EvidenceError("Canonical artifact must be a JSON object")
    version_field = phase5c4_contracts.ARTIFACT_TYPE_VERSION_FIELDS[artifact_type]
    if parsed.get(version_field) != contract_version:
        raise Phase5C4EvidenceError("Artifact document version does not match metadata")
    try:
        validated = phase5c4_contracts.ARTIFACT_TYPE_VALIDATORS[artifact_type](parsed)
    except (phase5c4_contracts.Phase5C4ContractError, canonical.Phase5CAdmissionError) as exc:
        raise Phase5C4EvidenceError(str(exc)) from None
    if validated != parsed or canonical.canonical_json(validated).encode("utf-8") != document:
        raise Phase5C4EvidenceError("Artifact validator attempted to rewrite canonical evidence")
    artifact_digest = canonical.sha256_digest_bytes(document)
    identity = {
        "artifact_type": artifact_type,
        "contract_version": contract_version,
        "identity_contract_version": LOGICAL_IDENTITY_VERSION,
        "logical_id": logical_id,
        "scope": _logical_identity_scope(artifact_type, validated, artifact_digest),
    }
    return PreparedArtifact(
        artifact_type=artifact_type,
        contract_version=contract_version,
        logical_id=logical_id,
        canonical_bytes=document,
        logical_identity_bytes=canonical.canonical_json(identity).encode("utf-8"),
        artifact_digest=artifact_digest,
        parsed=validated,
        bindings=_safe_bindings(validated),
    )


def write_private_file(path: Path, document: bytes, *, maximum_bytes: int = 64 * 1024 * 1024) -> None:
    if not document or len(document) > maximum_bytes:
        raise Phase5C4EvidenceError("Evidence export is empty or oversized")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError:
        raise Phase5C4EvidenceError("Evidence export path is unsafe or already exists") from None
    try:
        view = memoryview(document)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def collect_application_qualifier_snapshot(database_url: str) -> dict[str, Any]:
    """Re-query 5C4.2b evidence under its exact read-only lock boundary."""
    try:
        url = make_url(database_url)
    except (ArgumentError, TypeError, ValueError):
        raise Phase5C4EvidenceError("Application qualifier database URL is invalid") from None
    if url.get_backend_name() != "postgresql":
        raise Phase5C4EvidenceError("Application qualifier requires PostgreSQL")
    engine = create_engine(
        database_url,
        poolclass=NullPool,
        hide_parameters=True,
        isolation_level="REPEATABLE READ",
        connect_args={"connect_timeout": 5},
    )
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            identity = connection.execute(
                text(
                    """
                    SELECT session_user::text AS session_user,
                           current_user::text AS current_user,
                           current_setting('transaction_read_only') AS transaction_read_only,
                           current_setting('transaction_isolation') AS transaction_isolation
                    """
                )
            ).mappings().one()
            if (
                identity["session_user"] != "nutrition_qualifier"
                or identity["current_user"] != "nutrition_qualifier"
                or identity["transaction_read_only"] != "on"
                or identity["transaction_isolation"] != "repeatable read"
            ):
                raise Phase5C4EvidenceError("Application qualifier role boundary is invalid")
            connection.execute(
                text("SELECT pg_catalog.pg_advisory_xact_lock_shared(:lock_id)"),
                {"lock_id": APPLICATION_QUALIFIER_LOCK},
            )
            revision = str(connection.scalar(text("SELECT version_num FROM alembic_version")))
            if revision != APPLICATION_QUALIFIER_HEAD:
                raise Phase5C4EvidenceError("Application qualifier schema revision is unsupported")
            raw_qualifier = connection.scalar(
                text("SELECT public.phase5c_read_qualifier_evidence_v2()")
            )
            prerequisites = validate_prerequisite_observation(raw_qualifier)
            if prerequisites.session_role != "nutrition_qualifier":
                raise Phase5C4EvidenceError("Application qualifier identity was substituted")
            projection = prerequisites.qualifier_projection()
            physical = dict(
                connection.execute(
                    text(
                        """
                        SELECT (pg_catalog.pg_control_system()).system_identifier::text
                                   AS system_identifier,
                               pg_catalog.current_database()::text AS database_name,
                               (SELECT oid::text FROM pg_catalog.pg_database
                                WHERE datname = current_database()) AS database_oid,
                               pg_catalog.pg_is_in_recovery() AS in_recovery,
                               CASE WHEN pg_catalog.pg_is_in_recovery()
                                    THEN pg_catalog.pg_last_wal_replay_lsn()::text
                                    ELSE pg_catalog.pg_current_wal_lsn()::text
                               END AS current_wal_lsn,
                               pg_catalog.clock_timestamp() AS observed_at
                        """
                    )
                ).mappings().one()
            )
            if (
                not str(physical["system_identifier"]).isdigit()
                or not 0 <= int(physical["system_identifier"]) <= 2**64 - 1
                or not str(physical["database_oid"]).isdigit()
                or int(physical["database_oid"]) <= 0
                or projection["target_identity_digest"]
                != prerequisites.identity["identity_digest"]
                or projection["fence_epoch"] != prerequisites.state["epoch"]
                or projection["fence_mode"] != prerequisites.state["mode"]
                or projection["event_chain_digest"]
                != prerequisites.state["last_event_digest"]
            ):
                raise Phase5C4EvidenceError("Application qualifier evidence was substituted")
            snapshot = {
                "contract_version": "phase5c4_application_qualifier_snapshot_v1",
                "physical": physical,
                "qualifier": dict(raw_qualifier),
                "qualifier_projection": projection,
                "schema_revision": revision,
            }
            return {**snapshot, "snapshot_digest": canonical.canonical_digest(snapshot)}
    except Phase5C4EvidenceError:
        raise
    except Phase5C4PrerequisiteError as exc:
        raise Phase5C4EvidenceError(
            f"Application qualifier evidence is invalid: {exc.reason_code}"
        ) from None
    except SQLAlchemyError:
        raise Phase5C4EvidenceError("Application qualifier evidence collection failed") from None
    finally:
        engine.dispose()
