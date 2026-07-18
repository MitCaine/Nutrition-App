"""Strict artifact preparation and cross-plane evidence collection for 5C4.3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import stat
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.operators import phase5c_contracts as canonical
from app.operators import phase5c4_contracts
from app.operators.phase5c4_admission import (
    Phase5C4AdmissionError,
    build_reconciliation_projection,
    candidate_protected_relation_names,
)
from app.operators.phase5c4_prerequisites import (
    Phase5C4PrerequisiteError,
    admit_qualification_prerequisites,
    validate_prerequisite_observation,
)
from app.operators.phase5c4_roles import (
    OPTIONAL_PUBLIC_RELATIONS,
    PUBLIC_RELATIONS,
    Phase5C4RoleError,
    qualify_source_role_policy,
)
from app.operators.phase5c_performance_contracts import (
    Phase5CPerformanceContractError,
    SOURCE_DIMENSION_VERSION,
    build_source_dimensions,
    validate_source_dimensions,
)
from app.operators.phase5c4_minio import (
    EVIDENCE_BUCKET,
    Phase5C4MinioAdapter,
    evidence_object_key,
)


APPLICATION_QUALIFIER_LOCK = 5_542_018
APPLICATION_QUALIFIER_HEAD = "0018_phase5c_promotion_prerequisites"
APPLICATION_SOURCE_HEAD = "0017_phase5c_indexes"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_CANONICAL_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


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
    SOURCE_DIMENSION_VERSION: "observation_id",
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


@dataclass(frozen=True)
class SourceDimensionArtifactReference:
    """Safe executor handoff for one collector-authored source observation."""

    artifact_id: str
    artifact_digest: str
    observation_digest: str
    object_version: str


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


def prepare_source_dimension_artifact(
    observation: dict[str, Any],
) -> PreparedArtifact:
    """Prepare exact Stage 5C4.4 source-dimension bytes for generic registration."""

    try:
        validated = validate_source_dimensions(observation)
    except Phase5CPerformanceContractError as exc:
        raise Phase5C4EvidenceError(str(exc)) from None
    document = canonical.canonical_json(validated).encode("utf-8")
    artifact_digest = canonical.sha256_digest_bytes(document)
    identity = {
        "artifact_type": SOURCE_DIMENSION_VERSION,
        "contract_version": SOURCE_DIMENSION_VERSION,
        "identity_contract_version": LOGICAL_IDENTITY_VERSION,
        "logical_id": "source",
        "scope": validated["observation_id"],
    }
    return PreparedArtifact(
        artifact_type=SOURCE_DIMENSION_VERSION,
        contract_version=SOURCE_DIMENSION_VERSION,
        logical_id="source",
        canonical_bytes=document,
        logical_identity_bytes=canonical.canonical_json(identity).encode("utf-8"),
        artifact_digest=artifact_digest,
        parsed=validated,
        bindings=_safe_bindings(validated),
    )


def collect_and_register_source_dimension_artifact(
    source_database_url: str,
    *,
    control_database_url: str,
    source_database_instance_id: str,
    observation_id: str,
    environment: str,
    source_database_incarnation_digest: str,
    observation_mode: str,
    freeze_epoch_id: str | None = None,
    minio_adapter: Phase5C4MinioAdapter | None = None,
) -> SourceDimensionArtifactReference:
    """Collect, WORM-anchor, and register one source observation under collector authority."""

    from app.operators.phase5c4_control import (
        Phase5C4ControlDatabase,
        Phase5C4ControlError,
    )
    from app.operators.phase5c4_minio import Phase5C4MinioError

    observation = collect_source_dimension_snapshot(
        source_database_url,
        observation_id=observation_id,
        environment=environment,
        source_database_incarnation_digest=source_database_incarnation_digest,
        observation_mode=observation_mode,
        freeze_epoch_id=freeze_epoch_id,
    )
    prepared = prepare_source_dimension_artifact(observation)
    adapter = minio_adapter or Phase5C4MinioAdapter()
    key = evidence_object_key(prepared.artifact_type, prepared.artifact_digest)
    try:
        receipt = adapter.deliver(
            bucket=EVIDENCE_BUCKET,
            key=key,
            payload=prepared.canonical_bytes,
        )
        collector = Phase5C4ControlDatabase(control_database_url)
        registered = collector.register_artifact(
            artifact_type=prepared.artifact_type,
            contract_version=prepared.contract_version,
            canonical_bytes=prepared.canonical_bytes,
            logical_identity_bytes=prepared.logical_identity_bytes,
            database_instance_id=source_database_instance_id,
            bindings=list(prepared.bindings),
        )
        if registered["result"] not in {"accepted", "idempotent_replay"}:
            raise Phase5C4EvidenceError("Source observation registration was rejected")
        artifact_id = str(registered["artifact_id"])
        binding = collector.record_artifact_object_binding(
            artifact_id=artifact_id,
            bucket=receipt.bucket,
            object_key=receipt.object_key,
            object_version=receipt.object_version,
            etag=receipt.etag,
            byte_count=receipt.byte_count,
            payload_digest=receipt.payload_digest,
            lock_mode=receipt.lock_mode,
            retain_until=receipt.retain_until,
        )
        if binding["result"] not in {"accepted", "idempotent_replay"}:
            raise Phase5C4EvidenceError("Source observation object binding was rejected")
    except (Phase5C4ControlError, Phase5C4MinioError) as exc:
        raise Phase5C4EvidenceError("Source observation registration failed") from exc
    return SourceDimensionArtifactReference(
        artifact_id=artifact_id,
        artifact_digest=prepared.artifact_digest,
        observation_digest=observation["observation_digest"],
        object_version=receipt.object_version,
    )


def write_private_file(
    path: Path, document: bytes, *, maximum_bytes: int = 64 * 1024 * 1024
) -> None:
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
            identity = (
                connection.execute(
                    text(
                        """
                    SELECT session_user::text AS session_user,
                           current_user::text AS current_user,
                           current_setting('transaction_read_only') AS transaction_read_only,
                           current_setting('transaction_isolation') AS transaction_isolation
                    """
                    )
                )
                .mappings()
                .one()
            )
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
            admit_qualification_prerequisites(prerequisites)
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
                )
                .mappings()
                .one()
            )
            if (
                not str(physical["system_identifier"]).isdigit()
                or not 0 <= int(physical["system_identifier"]) <= 2**64 - 1
                or not str(physical["database_oid"]).isdigit()
                or int(physical["database_oid"]) <= 0
                or projection["target_identity_digest"] != prerequisites.identity["identity_digest"]
                or projection["fence_epoch"] != prerequisites.state["epoch"]
                or projection["fence_mode"] != prerequisites.state["mode"]
                or projection["event_chain_digest"] != prerequisites.state["last_event_digest"]
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


def _canonical_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _require_canonical_uuid(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not _CANONICAL_UUID.fullmatch(value):
        raise Phase5C4EvidenceError(f"{label} is invalid")
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except ValueError:
        raise Phase5C4EvidenceError(f"{label} is invalid") from None
    return value


def _require_digest(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise Phase5C4EvidenceError(f"{label} is invalid")
    return value


def _require_qualifier_transaction(connection: Connection) -> None:
    identity = connection.execute(
        text(
            "SELECT session_user::text, current_user::text, "
            "current_setting('transaction_read_only'), "
            "current_setting('transaction_isolation')"
        )
    ).one()
    if tuple(identity) != (
        "nutrition_qualifier",
        "nutrition_qualifier",
        "on",
        "repeatable read",
    ):
        raise Phase5C4EvidenceError("Application qualifier role boundary is invalid")


def _snapshot_anchor(connection: Connection) -> dict[str, Any]:
    row = (
        connection.execute(
            text(
                """
            SELECT pg_catalog.pg_current_snapshot()::text AS snapshot_id,
                   (pg_catalog.pg_control_checkpoint()).timeline_id::bigint AS timeline,
                   CASE WHEN pg_catalog.pg_is_in_recovery()
                        THEN pg_catalog.pg_last_wal_replay_lsn()::text
                        ELSE pg_catalog.pg_current_wal_lsn()::text
                   END AS lsn,
                   pg_catalog.clock_timestamp() AS observed_at
            """
            )
        )
        .mappings()
        .one()
    )
    return {
        "isolation_level": "repeatable_read",
        "read_only": True,
        "snapshot_id_digest": canonical.canonical_digest(
            {"postgresql_snapshot": str(row["snapshot_id"])}
        ),
        "timeline": int(row["timeline"]),
        "lsn": str(row["lsn"]),
        "observed_at": _canonical_timestamp(row["observed_at"]),
    }


def collect_source_dimension_snapshot(
    database_url: str,
    *,
    observation_id: str,
    environment: str,
    source_database_incarnation_digest: str,
    observation_mode: str,
    freeze_epoch_id: str | None = None,
) -> dict[str, Any]:
    """Collect the production-facing tier vector from an exact 0017 source.

    Preflight uses the normal role policy; final verification uses the already-established
    maintenance/freeze policy.  The target-only 0018 lock and identity objects are intentionally
    absent from this path.
    """

    if observation_mode == "preflight_normal":
        expected_state: Literal["normal", "maintenance"] = "normal"
    elif observation_mode == "final_frozen":
        expected_state = "maintenance"
    else:
        raise Phase5C4EvidenceError("Source observation mode is unsupported")
    _require_canonical_uuid(observation_id, label="Source observation ID")
    _require_digest(
        source_database_incarnation_digest,
        label="Source database incarnation digest",
    )
    if (observation_mode == "final_frozen") != (freeze_epoch_id is not None):
        raise Phase5C4EvidenceError("Source freeze-epoch binding is invalid")
    if freeze_epoch_id is not None:
        _require_canonical_uuid(freeze_epoch_id, label="Source freeze epoch ID")
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
            _require_qualifier_transaction(connection)
            revision = str(connection.scalar(text("SELECT version_num FROM alembic_version")))
            if revision != APPLICATION_SOURCE_HEAD:
                raise Phase5C4EvidenceError("Source schema revision is unsupported")
            eligibility = qualify_source_role_policy(connection, expected_state=expected_state)
            if eligibility["qualified"] is not True or eligibility["reason_codes"]:
                raise Phase5C4EvidenceError("Source role policy is not qualified")
            archive_schemas = tuple(
                str(value)
                for value in connection.scalars(
                    text(
                        "SELECT DISTINCT archive_schema FROM public.phase5c_conversion_metadata "
                        "ORDER BY archive_schema"
                    )
                )
            )
            if len(archive_schemas) > 1 or (
                observation_mode == "final_frozen" and len(archive_schemas) != 1
            ):
                raise Phase5C4EvidenceError("Source archive binding is invalid")
            archive_schema = archive_schemas[0] if archive_schemas else None
            clone_marker_present = bool(
                connection.scalar(
                    text(
                        "SELECT pg_catalog.to_regclass("
                        "'public.phase5c_conversion_clone_marker') IS NOT NULL"
                    )
                )
            )
            public_relations = set(PUBLIC_RELATIONS)
            if clone_marker_present:
                public_relations.update(OPTIONAL_PUBLIC_RELATIONS)
            expected_relations = {f"public.{name}" for name in public_relations}
            schemas = ["public"]
            if archive_schema is not None:
                expected_relations.update(
                    candidate_protected_relation_names(
                        archive_schema, clone_marker_present=clone_marker_present
                    )
                )
                schemas.append(archive_schema)
            protected, schema_authority_digest, reconciliation_projection = (
                _collect_protected_state(
                    connection,
                    expected_relations=tuple(sorted(expected_relations)),
                    schemas=schemas,
                )
            )
            metadata_rows = [
                dict(row)
                for row in connection.execute(
                    text(
                        """
                        SELECT archive_identity, archive_schema, clone_marker_digest,
                               clone_database_identity_digest,
                               conversion_clone_identity_digest,
                               source_production_identity_digest,
                               inventory_digest, manifest_digest AS plan_digest,
                               archive_checksum, planning_source_checksum
                        FROM public.phase5c_conversion_metadata
                        ORDER BY archive_identity
                        """
                    )
                ).mappings()
            ]
            run_rows = [
                dict(row)
                for row in connection.execute(
                    text(
                        """
                        SELECT id::text AS run_id, archive_identity, plan_digest,
                               clone_marker_digest, inventory_digest, archive_checksum,
                               planning_source_checksum, execution_state, verification_state,
                               daily_log_state_digest, ocr_state_digest
                        FROM public.phase5c_conversion_runs
                        ORDER BY id
                        """
                    )
                ).mappings()
            ]
            if len(metadata_rows) > 1 or len(run_rows) > 1:
                raise Phase5C4EvidenceError("Source conversion binding is ambiguous")
            if observation_mode == "final_frozen" and (
                len(metadata_rows) != 1 or len(run_rows) != 1
            ):
                raise Phase5C4EvidenceError("Frozen source conversion binding is incomplete")
            metadata = metadata_rows[0] if metadata_rows else None
            run = run_rows[0] if run_rows else None
            if run is not None and (
                metadata is None
                or run["archive_identity"] != metadata["archive_identity"]
                or run["plan_digest"] != metadata["plan_digest"]
                or run["clone_marker_digest"] != metadata["clone_marker_digest"]
                or run["inventory_digest"] != metadata["inventory_digest"]
                or run["archive_checksum"] != metadata["archive_checksum"]
                or run["planning_source_checksum"] != metadata["planning_source_checksum"]
                or run["execution_state"] != "completed"
                or run["verification_state"] != "verified"
            ):
                raise Phase5C4EvidenceError("Source conversion binding is invalid")
            source_bindings = {
                "archive_identity_digest": (
                    str(metadata["archive_identity"]) if metadata is not None else None
                ),
                "archive_schema": archive_schema,
                "archive_root_digest": (
                    str(metadata["archive_checksum"]) if metadata is not None else None
                ),
                "clone_database_identity_digest": (
                    str(metadata["clone_database_identity_digest"])
                    if metadata is not None
                    else None
                ),
                "clone_marker_digest": (
                    str(metadata["clone_marker_digest"]) if metadata is not None else None
                ),
                "conversion_clone_identity_digest": (
                    str(metadata["conversion_clone_identity_digest"])
                    if metadata is not None
                    else None
                ),
                "database_identity_digest": eligibility["database_identity_digest"],
                "inventory_digest": (
                    str(metadata["inventory_digest"]) if metadata is not None else None
                ),
                "plan_digest": str(run["plan_digest"]) if run is not None else None,
                "planning_source_root_digest": (
                    str(metadata["planning_source_checksum"]) if metadata is not None else None
                ),
                "run_id": str(run["run_id"]) if run is not None else None,
                "source_production_identity_digest": (
                    str(metadata["source_production_identity_digest"])
                    if metadata is not None
                    else None
                ),
            }
            dimensions = (
                connection.execute(
                    text(
                        """
                    WITH RECURSIVE ingredient_counts AS (
                        SELECT recipe.id, pg_catalog.count(ingredient.id)::bigint AS item_count
                        FROM public.recipes recipe
                        LEFT JOIN public.recipe_ingredients ingredient
                          ON ingredient.recipe_id = recipe.id
                        GROUP BY recipe.id
                    ), recipe_edges AS (
                        SELECT ingredient.recipe_id AS parent_id,
                               CASE WHEN food.source_id ~*
                                    '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
                                    THEN food.source_id::uuid END AS child_id
                        FROM public.recipe_ingredients ingredient
                        JOIN public.food_items food ON food.id = ingredient.food_item_id
                        WHERE food.is_recipe AND food.source_type = 'recipe'
                          AND food.source_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
                    ), graph_walk(root_id, node_id, depth, path) AS (
                        SELECT recipe.id, recipe.id, 0, ARRAY[recipe.id]
                        FROM public.recipes recipe
                        UNION ALL
                        SELECT walk.root_id, edge.child_id, walk.depth + 1,
                               walk.path || edge.child_id
                        FROM graph_walk walk
                        JOIN recipe_edges edge ON edge.parent_id = walk.node_id
                        WHERE walk.depth < 64 AND NOT edge.child_id = ANY(walk.path)
                    )
                    SELECT
                        (SELECT pg_catalog.count(*) FROM public.recipes)::bigint AS recipes,
                        (SELECT pg_catalog.count(*) FROM public.food_items)::bigint AS foods,
                        (SELECT pg_catalog.count(*) FROM public.daily_logs)::bigint AS daily_logs,
                        (SELECT pg_catalog.count(*) FROM public.ocr_scans)::bigint AS ocr_records,
                        (SELECT pg_catalog.count(*)
                         FROM public.food_items food
                         WHERE food.is_recipe AND food.source_type = 'recipe'
                           AND (food.source_id IS NULL OR food.source_id !~*
                                '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')
                        )::bigint AS invalid_recipe_references,
                        COALESCE((
                            SELECT pg_catalog.max(item_count) FROM (
                                SELECT pg_catalog.count(*)::bigint AS item_count
                                FROM public.serving_definitions GROUP BY food_item_id
                            ) servings
                        ), 0)::bigint AS max_servings_per_food,
                        COALESCE((
                            SELECT pg_catalog.max(item_count) FROM (
                                SELECT pg_catalog.count(*)::bigint AS item_count
                                FROM public.food_nutrients GROUP BY food_item_id
                            ) nutrients
                        ), 0)::bigint AS max_nutrients_per_food,
                        COALESCE((SELECT pg_catalog.percentile_disc(0.50) WITHIN GROUP
                            (ORDER BY item_count) FROM ingredient_counts), 0)::bigint
                            AS ingredient_p50,
                        COALESCE((SELECT pg_catalog.percentile_disc(0.95) WITHIN GROUP
                            (ORDER BY item_count) FROM ingredient_counts), 0)::bigint
                            AS ingredient_p95,
                        COALESCE((SELECT pg_catalog.max(depth) FROM graph_walk), 0)::bigint
                            AS graph_depth,
                        COALESCE((SELECT pg_catalog.max(child_count) FROM (
                            SELECT parent_id, pg_catalog.count(DISTINCT child_id)::bigint child_count
                            FROM recipe_edges GROUP BY parent_id
                        ) breadth), 0)::bigint AS graph_breadth
                    """
                    )
                )
                .mappings()
                .one()
            )
            if int(dimensions["invalid_recipe_references"]) != 0:
                raise Phase5C4EvidenceError("Source Recipe graph identity is invalid")
            snapshot = _snapshot_anchor(connection)
            result = build_source_dimensions(
                observation_id=observation_id,
                environment=environment,
                source_database_incarnation_digest=source_database_incarnation_digest,
                source_role_qualification_digest=eligibility["qualification_digest"],
                observation_mode=observation_mode,
                freeze_epoch_id=freeze_epoch_id,
                snapshot_id_digest=snapshot["snapshot_id_digest"],
                timeline=snapshot["timeline"],
                lsn=snapshot["lsn"],
                observed_at=snapshot["observed_at"],
                recipes=int(dimensions["recipes"]),
                foods=int(dimensions["foods"]),
                daily_logs=int(dimensions["daily_logs"]),
                ocr_records=int(dimensions["ocr_records"]),
                max_servings_per_food=int(dimensions["max_servings_per_food"]),
                max_nutrients_per_food=int(dimensions["max_nutrients_per_food"]),
                ingredient_p50=int(dimensions["ingredient_p50"]),
                ingredient_p95=int(dimensions["ingredient_p95"]),
                graph_depth=int(dimensions["graph_depth"]),
                graph_breadth=int(dimensions["graph_breadth"]),
                source_bindings=source_bindings,
                protected_state=protected,
                reconciliation_projection=reconciliation_projection,
                schema_authority_digest=schema_authority_digest,
            )
            return result
    except Phase5C4EvidenceError:
        raise
    except (Phase5C4RoleError, Phase5CPerformanceContractError):
        raise Phase5C4EvidenceError("Source dimension evidence is invalid") from None
    except SQLAlchemyError:
        raise Phase5C4EvidenceError("Source dimension collection failed") from None
    finally:
        engine.dispose()


def _qualified(connection: Connection, qualified_name: str) -> str:
    schema, relation = qualified_name.split(".", 1)
    quote = connection.dialect.identifier_preparer.quote
    return f"{quote(schema)}.{quote(relation)}"


def _relation_root(connection: Connection, qualified_name: str) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in connection.execute(
            text(f"SELECT * FROM {_qualified(connection, qualified_name)}")
        ).mappings()
    ]
    normalized = sorted(rows, key=canonical.canonical_json)
    return {
        "qualified_name": qualified_name,
        "row_count": len(normalized),
        "logical_root": canonical.canonical_digest(normalized),
    }


def _catalog_rows(
    connection: Connection, sql: str, parameters: dict[str, Any]
) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(text(sql), parameters).mappings()]


def _collect_protected_state(
    connection: Connection,
    *,
    expected_relations: tuple[str, ...],
    schemas: list[str],
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """Collect the single Stage 5C4.4 normalized protected-root definition."""

    actual_relations = tuple(
        f"{row['schema_name']}.{row['relation_name']}"
        for row in connection.execute(
            text(
                """
                SELECT namespace.nspname AS schema_name,
                       relation.relname AS relation_name
                FROM pg_catalog.pg_class relation
                JOIN pg_catalog.pg_namespace namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = ANY(:schemas)
                  AND relation.relkind IN ('r','p')
                  AND NOT (
                    namespace.nspname = 'public' AND relation.relname IN (
                        'phase5c_promotion_target_identity',
                        'phase5c_write_fence_events',
                        'phase5c_write_fence_state'
                    )
                  )
                ORDER BY namespace.nspname, relation.relname
                """
            ),
            {"schemas": schemas},
        ).mappings()
    )
    if actual_relations != expected_relations:
        raise Phase5C4EvidenceError("Protected relation inventory drifted")
    sequences = _catalog_rows(
        connection,
        """
        SELECT namespace.nspname AS schema_name, relation.relname AS sequence_name,
               owner.rolname AS owner
        FROM pg_catalog.pg_class relation
        JOIN pg_catalog.pg_namespace namespace ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_roles owner ON owner.oid = relation.relowner
        WHERE namespace.nspname = ANY(:schemas) AND relation.relkind = 'S'
        ORDER BY namespace.nspname, relation.relname
        """,
        {"schemas": schemas},
    )
    if sequences:
        raise Phase5C4EvidenceError("Protected sequence inventory drifted")
    relations = [_relation_root(connection, name) for name in expected_relations]
    schema_rows = _catalog_rows(
        connection,
        """
        SELECT namespace.nspname AS schema_name, relation.relname AS relation_name,
               relation.relkind::text AS relation_kind, owner.rolname AS owner,
               COALESCE(relation.relacl::text, '') AS relation_acl,
               attribute.attnum, attribute.attname AS column_name,
               pg_catalog.format_type(attribute.atttypid, attribute.atttypmod) AS data_type,
               attribute.attnotnull, attribute.attidentity::text AS identity_kind,
               attribute.attgenerated::text AS generated_kind,
               COALESCE(pg_catalog.pg_get_expr(default_value.adbin,
                   default_value.adrelid), '') AS default_expression,
               COALESCE(collation_row.collname, '') AS collation_name,
               COALESCE(attribute.attacl::text, '') AS column_acl
        FROM pg_catalog.pg_class relation
        JOIN pg_catalog.pg_namespace namespace ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_roles owner ON owner.oid = relation.relowner
        JOIN pg_catalog.pg_attribute attribute ON attribute.attrelid = relation.oid
        LEFT JOIN pg_catalog.pg_attrdef default_value
          ON default_value.adrelid = relation.oid
         AND default_value.adnum = attribute.attnum
        LEFT JOIN pg_catalog.pg_collation collation_row
          ON collation_row.oid = attribute.attcollation
        WHERE namespace.nspname = ANY(:schemas)
          AND relation.relkind IN ('r','p','S','v','m')
          AND attribute.attnum > 0 AND NOT attribute.attisdropped
        ORDER BY namespace.nspname, relation.relname, attribute.attnum
        """,
        {"schemas": schemas},
    )
    routine_rows = _catalog_rows(
        connection,
        """
        SELECT namespace.nspname AS schema_name,
               routine.oid::pg_catalog.regprocedure::text AS signature,
               owner.rolname AS owner, routine.prosecdef,
               routine.provolatile::text AS volatility,
               COALESCE(routine.proconfig, ARRAY[]::text[]) AS configuration,
               COALESCE(routine.proacl::text, '') AS routine_acl,
               pg_catalog.pg_get_functiondef(routine.oid) AS definition
        FROM pg_catalog.pg_proc routine
        JOIN pg_catalog.pg_namespace namespace ON namespace.oid = routine.pronamespace
        JOIN pg_catalog.pg_roles owner ON owner.oid = routine.proowner
        WHERE namespace.nspname = ANY(:schemas)
        ORDER BY namespace.nspname, signature
        """,
        {"schemas": schemas},
    )
    trigger_rows = _catalog_rows(
        connection,
        """
        SELECT namespace.nspname AS schema_name, relation.relname AS relation_name,
               trigger.tgname AS trigger_name, trigger.tgenabled::text,
               trigger.tgtype::integer,
               trigger.tgfoid::pg_catalog.regprocedure::text AS function_signature,
               pg_catalog.pg_get_triggerdef(trigger.oid, true) AS definition
        FROM pg_catalog.pg_trigger trigger
        JOIN pg_catalog.pg_class relation ON relation.oid = trigger.tgrelid
        JOIN pg_catalog.pg_namespace namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = ANY(:schemas) AND NOT trigger.tgisinternal
        ORDER BY namespace.nspname, relation.relname, trigger.tgname
        """,
        {"schemas": schemas},
    )
    constraint_rows = _catalog_rows(
        connection,
        """
        SELECT namespace.nspname AS schema_name, relation.relname AS relation_name,
               constraint_row.conname AS constraint_name,
               constraint_row.contype::text AS constraint_type,
               constraint_row.convalidated,
               pg_catalog.pg_get_constraintdef(constraint_row.oid, true) AS definition
        FROM pg_catalog.pg_constraint constraint_row
        JOIN pg_catalog.pg_class relation ON relation.oid = constraint_row.conrelid
        JOIN pg_catalog.pg_namespace namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = ANY(:schemas)
        ORDER BY namespace.nspname, relation.relname, constraint_row.conname
        """,
        {"schemas": schemas},
    )
    index_rows = _catalog_rows(
        connection,
        """
        SELECT namespace.nspname AS schema_name, table_relation.relname AS relation_name,
               index_relation.relname AS index_name, index_definition.indisvalid,
               index_definition.indisready, index_definition.indislive,
               pg_catalog.pg_get_indexdef(index_definition.indexrelid) AS definition
        FROM pg_catalog.pg_index index_definition
        JOIN pg_catalog.pg_class index_relation
          ON index_relation.oid = index_definition.indexrelid
        JOIN pg_catalog.pg_class table_relation
          ON table_relation.oid = index_definition.indrelid
        JOIN pg_catalog.pg_namespace namespace
          ON namespace.oid = table_relation.relnamespace
        WHERE namespace.nspname = ANY(:schemas)
        ORDER BY namespace.nspname, table_relation.relname, index_relation.relname
        """,
        {"schemas": schemas},
    )
    extension_rows = _catalog_rows(
        connection,
        """
        SELECT extension.extname AS extension_name,
               extension.extversion AS extension_version,
               namespace.nspname AS schema_name, owner.rolname AS owner
        FROM pg_catalog.pg_extension extension
        JOIN pg_catalog.pg_namespace namespace ON namespace.oid = extension.extnamespace
        JOIN pg_catalog.pg_roles owner ON owner.oid = extension.extowner
        ORDER BY extension.extname
        """,
        {},
    )
    collation_rows = _catalog_rows(
        connection,
        """
        SELECT DISTINCT collation_namespace.nspname AS collation_schema,
               collation_row.collname AS collation_name,
               collation_row.collprovider::text AS provider,
               collation_row.collisdeterministic,
               COALESCE(collation_row.collcollate, '') AS collate,
               COALESCE(collation_row.collctype, '') AS ctype,
               COALESCE(pg_catalog.pg_collation_actual_version(collation_row.oid), '')
                    AS actual_version
        FROM pg_catalog.pg_attribute attribute
        JOIN pg_catalog.pg_class relation ON relation.oid = attribute.attrelid
        JOIN pg_catalog.pg_namespace namespace ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_collation collation_row
          ON collation_row.oid = attribute.attcollation
        JOIN pg_catalog.pg_namespace collation_namespace
          ON collation_namespace.oid = collation_row.collnamespace
        WHERE namespace.nspname = ANY(:schemas)
          AND attribute.attnum > 0 AND NOT attribute.attisdropped
        ORDER BY collation_namespace.nspname, collation_row.collname
        """,
        {"schemas": schemas},
    )
    schema_fingerprint_digest = canonical.canonical_digest(
        {
            "columns_and_relations": schema_rows,
            "routines": routine_rows,
            "triggers": trigger_rows,
        }
    )
    constraint_index_fingerprint_digest = canonical.canonical_digest(
        {"constraints": constraint_rows, "indexes": index_rows}
    )
    extension_collation_digest = canonical.canonical_digest(
        {"collations": collation_rows, "extensions": extension_rows}
    )
    row_counts = [
        {"qualified_name": item["qualified_name"], "row_count": item["row_count"]}
        for item in relations
    ]
    protected_unsigned = {
        "root_version": phase5c4_contracts.PROTECTED_ROOT_VERSION,
        "relations": relations,
        "sequences": [],
        "schema_fingerprint_digest": schema_fingerprint_digest,
        "constraint_index_fingerprint_digest": constraint_index_fingerprint_digest,
        "extension_collation_digest": extension_collation_digest,
        "row_count_digest": canonical.canonical_digest(row_counts),
    }
    protected = {
        **protected_unsigned,
        "protected_root_digest": canonical.canonical_digest(protected_unsigned),
    }
    schema_authority_digest = canonical.canonical_digest(
        {
            "constraint_index_fingerprint_digest": constraint_index_fingerprint_digest,
            "extension_collation_digest": extension_collation_digest,
            "schema_fingerprint_digest": schema_fingerprint_digest,
        }
    )
    return (
        protected,
        schema_authority_digest,
        build_reconciliation_projection(protected, schema_authority_digest=schema_authority_digest),
    )


def collect_candidate_protected_snapshot(
    database_url: str,
    *,
    run_id: str,
    plan_digest: str,
    qualification_receipt_digest: str,
) -> dict[str, Any]:
    """Collect one canonical candidate protected-root observation under the 0018 lock."""

    canonical_run_id = _require_canonical_uuid(run_id, label="Candidate conversion run ID")
    _require_digest(plan_digest, label="Candidate conversion plan digest")
    _require_digest(
        qualification_receipt_digest,
        label="Candidate qualification receipt digest",
    )
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
            _require_qualifier_transaction(connection)
            connection.execute(
                text("SELECT pg_catalog.pg_advisory_xact_lock_shared(:lock_id)"),
                {"lock_id": APPLICATION_QUALIFIER_LOCK},
            )
            revision = str(connection.scalar(text("SELECT version_num FROM alembic_version")))
            if revision != APPLICATION_QUALIFIER_HEAD:
                raise Phase5C4EvidenceError("Application qualifier schema revision is unsupported")
            raw = connection.scalar(text("SELECT public.phase5c_read_qualifier_evidence_v2()"))
            prerequisites = validate_prerequisite_observation(raw)
            admit_qualification_prerequisites(prerequisites)
            archive_schemas = tuple(
                str(value)
                for value in connection.scalars(
                    text(
                        "SELECT DISTINCT archive_schema FROM public.phase5c_conversion_metadata "
                        "ORDER BY archive_schema"
                    )
                )
            )
            if len(archive_schemas) != 1:
                raise Phase5C4EvidenceError("Candidate archive schema binding is invalid")
            archive_schema = archive_schemas[0]
            expected_relations = candidate_protected_relation_names(archive_schema)
            schemas = ["public", archive_schema]
            protected, schema_authority_digest, _ = _collect_protected_state(
                connection,
                expected_relations=expected_relations,
                schemas=schemas,
            )
            snapshot = _snapshot_anchor(connection)
            run = (
                connection.execute(
                    text(
                        """
                    SELECT id::text AS run_id, plan_digest, execution_state,
                           verification_state
                    FROM public.phase5c_conversion_runs
                    WHERE id = CAST(:run_id AS uuid)
                    """
                    ),
                    {"run_id": canonical_run_id},
                )
                .mappings()
                .one_or_none()
            )
            if (
                run is None
                or str(run["plan_digest"]) != plan_digest
                or run["execution_state"] != "completed"
                or run["verification_state"] != "verified"
            ):
                raise Phase5C4EvidenceError("Candidate conversion run binding is invalid")
            block_subjects = [
                str(value)
                for value in connection.scalars(
                    text(
                        """
                        SELECT source_recipe_id
                        FROM public.phase5c_conversion_outcomes
                        WHERE run_id = CAST(:run_id AS uuid)
                          AND (planned_disposition = 'block'
                               OR execution_disposition = 'blocked')
                        ORDER BY source_recipe_id
                        """
                    ),
                    {"run_id": canonical_run_id},
                )
            ]
            zero_block_query_unsigned = {
                "query_contract_version": phase5c4_contracts.ZERO_BLOCK_QUERY_VERSION,
                "read_only": True,
                "plan_digest": plan_digest,
                "run_id": canonical_run_id,
                "qualification_receipt_digest": qualification_receipt_digest,
                "snapshot_digest": snapshot["snapshot_id_digest"],
                "block_count": len(block_subjects),
                "block_subject_set_digest": canonical.canonical_digest(block_subjects),
            }
            zero_block_query = {
                **zero_block_query_unsigned,
                "query_digest": canonical.canonical_digest(zero_block_query_unsigned),
            }
            projection = prerequisites.qualifier_projection()
            observation = {
                "contract_version": "phase5c4_candidate_protected_snapshot_v1",
                "archive_schema": archive_schema,
                "protected_state": protected,
                "qualifier_projection": projection,
                "zero_block_query": zero_block_query,
                "snapshot": snapshot,
                "schema_authority_digest": schema_authority_digest,
            }
            return {
                **observation,
                "observation_digest": canonical.canonical_digest(observation),
            }
    except Phase5C4EvidenceError:
        raise
    except Phase5C4PrerequisiteError as exc:
        raise Phase5C4EvidenceError(
            f"Application qualifier evidence is invalid: {exc.reason_code}"
        ) from None
    except (Phase5C4AdmissionError, Phase5C4RoleError, Phase5CPerformanceContractError):
        raise Phase5C4EvidenceError("Candidate protected-root evidence is invalid") from None
    except (SQLAlchemyError, TypeError, ValueError):
        raise Phase5C4EvidenceError("Candidate protected-root collection failed") from None
    finally:
        engine.dispose()
