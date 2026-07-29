"""Disposable infrastructure qualification contracts for Phase 5C4.8.

This module is deliberately outside the runtime/control authority surface.  It
validates one opt-in local provider exercise, computes measurements from
authoritative timestamps, and emits canonical evidence.  It does not authorize
activation, cutback, recovery, routing, or database mutation in production.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import shutil
from typing import Any, Literal
from uuid import UUID

from app.operators.phase5c_contracts import canonical_json


QUALIFICATION_VERSION = "phase5c4_infrastructure_qualification_v1"
EVIDENCE_SCHEMA_VERSION = "phase5c4_infrastructure_evidence_schema_v1"
PROVIDER_CONTRACT_VERSION = "phase5c4_disposable_routing_provider_v1"
TIMING_CONTRACT_VERSION = "phase5c4_authoritative_recovery_timing_v1"
DISPOSABLE_CONFIRMATION = "phase5c4_infrastructure_destroy_disposable"
PROJECT_PREFIX = "nutrition-p5c4q-"
LOCAL_PROVIDER_KIND = "disposable_postgresql_routing_provider"
SUMMARY_FILE = "qualification-summary.json"

_PROJECT = re.compile(r"^nutrition-p5c4q-[0-9a-f]{12}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_GIT_OID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
_SAFE_TEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,511}$")
_SECRET_KEY = re.compile(
    r"(password|secret|private.?key|database.?url|access.?key|bearer|token)",
    re.IGNORECASE,
)
_CREDENTIAL_URL = re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^@\s/]+@", re.IGNORECASE)

ScenarioStatus = Literal["passed", "failed", "hold", "skipped"]


class InfrastructureQualificationError(RuntimeError):
    """Stable fail-closed qualification error."""


def canonical_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise InfrastructureQualificationError("timestamp must be timezone-aware")
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or _TIMESTAMP.fullmatch(value) is None:
        raise InfrastructureQualificationError("timestamp is not canonical UTC")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        raise InfrastructureQualificationError("timestamp is invalid") from None


def _uuid(value: str, label: str) -> str:
    try:
        parsed = UUID(value)
    except (TypeError, ValueError, AttributeError):
        raise InfrastructureQualificationError(f"{label} is not a canonical UUID") from None
    if str(parsed) != value:
        raise InfrastructureQualificationError(f"{label} is not a canonical UUID")
    return value


def _digest(value: str, label: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise InfrastructureQualificationError(f"{label} is not lowercase sha256")
    return value


def _safe_text(value: str, label: str) -> str:
    if not isinstance(value, str) or _SAFE_TEXT.fullmatch(value) is None:
        raise InfrastructureQualificationError(f"{label} is invalid")
    return value


def _port(value: str, label: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise InfrastructureQualificationError(f"{label} is invalid") from None
    if not 1024 <= parsed <= 65535:
        raise InfrastructureQualificationError(f"{label} is outside the disposable range")
    return parsed


def require_loopback_endpoint(value: str) -> tuple[str, int]:
    host, separator, port_text = value.rpartition(":")
    if not separator or not host:
        raise InfrastructureQualificationError("endpoint is invalid")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if host != "localhost":
            raise InfrastructureQualificationError("endpoint must be loopback") from None
    else:
        if not address.is_loopback:
            raise InfrastructureQualificationError("endpoint must be loopback")
    return host, _port(port_text, "endpoint port")


@dataclass(frozen=True)
class InfrastructureQualificationConfig:
    repository_root: Path
    compose_file: Path
    evidence_root: Path
    project: str
    minio_port: int
    source_port: int
    restored_port: int
    provider_port: int
    control_port: int
    retain_evidence: bool

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str],
        *,
        repository_root: Path,
    ) -> "InfrastructureQualificationConfig":
        if (
            environment.get("NUTRITION_PHASE5C4_QUALIFICATION_CONFIRM")
            != DISPOSABLE_CONFIRMATION
        ):
            raise InfrastructureQualificationError(
                "explicit destructive qualification confirmation is required"
            )
        resolved_root = repository_root.resolve(strict=True)
        compose_file = (
            resolved_root / "docker-compose.phase5c4-qualification.yml"
        ).resolve(strict=True)
        if compose_file.parent != resolved_root or compose_file.is_symlink():
            raise InfrastructureQualificationError("qualification compose file is unsafe")
        project = environment.get("NUTRITION_PHASE5C4_QUALIFICATION_PROJECT", "")
        if _PROJECT.fullmatch(project) is None:
            raise InfrastructureQualificationError(
                "qualification project must use the isolated generated namespace"
            )
        evidence_root = (
            resolved_root / ".project-runtime" / "phase5c4-qualification" / project
        ).resolve()
        runtime_root = (resolved_root / ".project-runtime").resolve()
        if runtime_root not in evidence_root.parents:
            raise InfrastructureQualificationError("evidence path escaped runtime root")
        retain = environment.get(
            "NUTRITION_PHASE5C4_QUALIFICATION_RETAIN_EVIDENCE", "0"
        )
        if retain not in {"0", "1"}:
            raise InfrastructureQualificationError("retain-evidence must be 0 or 1")
        return cls(
            repository_root=resolved_root,
            compose_file=compose_file,
            evidence_root=evidence_root,
            project=project,
            minio_port=_port(
                environment.get("NUTRITION_PHASE5C4_QUALIFICATION_MINIO_PORT", "59100"),
                "MinIO port",
            ),
            source_port=_port(
                environment.get("NUTRITION_PHASE5C4_QUALIFICATION_SOURCE_PORT", "59101"),
                "source port",
            ),
            restored_port=_port(
                environment.get("NUTRITION_PHASE5C4_QUALIFICATION_RESTORED_PORT", "59102"),
                "restored port",
            ),
            provider_port=_port(
                environment.get("NUTRITION_PHASE5C4_QUALIFICATION_PROVIDER_PORT", "59103"),
                "provider port",
            ),
            control_port=_port(
                environment.get("NUTRITION_PHASE5C4_QUALIFICATION_CONTROL_PORT", "59104"),
                "control port",
            ),
            retain_evidence=retain == "1",
        )

    def validate_unique_ports(self) -> None:
        ports = {
            self.minio_port,
            self.source_port,
            self.restored_port,
            self.provider_port,
            self.control_port,
        }
        if len(ports) != 5:
            raise InfrastructureQualificationError(
                "qualification service ports must be distinct"
            )


@dataclass(frozen=True)
class ProviderActionRequest:
    operation_id: str
    action: Literal["route_source", "route_target", "restore_source", "fence_target"]
    request_digest: str
    expected_route_state: Literal["source", "target", "unknown"]
    expected_source_writable: bool
    expected_target_fenced: bool

    def validate(self) -> None:
        _uuid(self.operation_id, "provider operation ID")
        _digest(self.request_digest, "provider request digest")
        if self.action not in {
            "route_source",
            "route_target",
            "restore_source",
            "fence_target",
        }:
            raise InfrastructureQualificationError("provider action is unsupported")
        if self.expected_route_state not in {"source", "target", "unknown"}:
            raise InfrastructureQualificationError("expected route state is invalid")
        if not isinstance(self.expected_source_writable, bool) or not isinstance(
            self.expected_target_fenced, bool
        ):
            raise InfrastructureQualificationError("provider booleans are invalid")


@dataclass(frozen=True)
class ProviderCommandResult:
    returncode: int
    output_digest: str
    output_bytes: int
    interrupted: bool = False
    conflict: bool = False

    def validate(self) -> None:
        if isinstance(self.returncode, bool) or not isinstance(self.returncode, int):
            raise InfrastructureQualificationError("provider return code is invalid")
        _digest(self.output_digest, "provider output digest")
        if (
            isinstance(self.output_bytes, bool)
            or not isinstance(self.output_bytes, int)
            or not 0 <= self.output_bytes <= 1024 * 1024
        ):
            raise InfrastructureQualificationError("provider output size is invalid")
        if not isinstance(self.interrupted, bool):
            raise InfrastructureQualificationError("provider interruption is invalid")
        if not isinstance(self.conflict, bool):
            raise InfrastructureQualificationError("provider conflict is invalid")


@dataclass(frozen=True)
class ProviderObservation:
    last_operation_id: str
    last_request_digest: str
    last_result: Literal["applied", "partial", "unknown", "conflicting"]
    provider_revision: int
    route_state: Literal["source", "target", "unknown"]
    source_writable: bool
    target_fenced: bool
    observed_at: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ProviderObservation":
        if set(value) != {
            "last_operation_id",
            "last_request_digest",
            "last_result",
            "provider_revision",
            "route_state",
            "source_writable",
            "target_fenced",
            "updated_at",
        }:
            raise InfrastructureQualificationError("provider observation keys are invalid")
        result = cls(
            last_operation_id=value["last_operation_id"],
            last_request_digest=value["last_request_digest"],
            last_result=value["last_result"],
            provider_revision=value["provider_revision"],
            route_state=value["route_state"],
            source_writable=value["source_writable"],
            target_fenced=value["target_fenced"],
            observed_at=value["updated_at"],
        )
        result.validate()
        return result

    def validate(self) -> None:
        _uuid(self.last_operation_id, "observed provider operation ID")
        _digest(self.last_request_digest, "observed provider request digest")
        if self.last_result not in {
            "applied",
            "partial",
            "unknown",
            "conflicting",
        }:
            raise InfrastructureQualificationError("observed provider result is invalid")
        if (
            isinstance(self.provider_revision, bool)
            or not isinstance(self.provider_revision, int)
            or self.provider_revision < 1
        ):
            raise InfrastructureQualificationError("provider revision is invalid")
        if self.route_state not in {"source", "target", "unknown"}:
            raise InfrastructureQualificationError("observed route is invalid")
        if not isinstance(self.source_writable, bool) or not isinstance(
            self.target_fenced, bool
        ):
            raise InfrastructureQualificationError("provider observation is invalid")
        parse_timestamp(self.observed_at)

    def matches(self, request: ProviderActionRequest) -> bool:
        return (
            self.last_operation_id == request.operation_id
            and self.last_request_digest == request.request_digest
            and self.last_result == "applied"
            and self.route_state == request.expected_route_state
            and self.source_writable is request.expected_source_writable
            and self.target_fenced is request.expected_target_fenced
        )


@dataclass(frozen=True)
class ProviderQualificationResult:
    status: ScenarioStatus
    reason: str
    command: ProviderCommandResult
    observation: ProviderObservation
    reconciled_after_interruption: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": {
                "conflict": self.command.conflict,
                "interrupted": self.command.interrupted,
                "output_bytes": self.command.output_bytes,
                "output_digest": self.command.output_digest,
                "returncode": self.command.returncode,
            },
            "observation": {
                "last_operation_id": self.observation.last_operation_id,
                "last_request_digest": self.observation.last_request_digest,
                "last_result": self.observation.last_result,
                "observed_at": self.observation.observed_at,
                "provider_revision": self.observation.provider_revision,
                "route_state": self.observation.route_state,
                "source_writable": self.observation.source_writable,
                "target_fenced": self.observation.target_fenced,
            },
            "reason": self.reason,
            "reconciled_after_interruption": self.reconciled_after_interruption,
            "status": self.status,
        }


ProviderCommand = Callable[[ProviderActionRequest], ProviderCommandResult]
ProviderReadback = Callable[[], ProviderObservation]


class AuthoritativeProviderAdapter:
    """Accept provider success only from independent authoritative readback."""

    def __init__(
        self,
        *,
        command: ProviderCommand,
        readback: ProviderReadback,
    ) -> None:
        self.command = command
        self.readback = readback

    def execute(self, request: ProviderActionRequest) -> ProviderQualificationResult:
        request.validate()
        command = self.command(request)
        command.validate()
        observation = self.readback()
        observation.validate()
        if command.conflict:
            return ProviderQualificationResult(
                status="failed",
                reason="provider_operation_conflict",
                command=command,
                observation=observation,
                reconciled_after_interruption=False,
            )
        if observation.matches(request):
            return ProviderQualificationResult(
                status="passed",
                reason=(
                    "authoritative_readback_reconciled"
                    if command.returncode != 0 or command.interrupted
                    else "authoritative_readback_confirmed"
                ),
                command=command,
                observation=observation,
                reconciled_after_interruption=(
                    command.returncode != 0 or command.interrupted
                ),
            )
        if command.returncode != 0 or command.interrupted:
            return ProviderQualificationResult(
                status="hold",
                reason="provider_result_unknown",
                command=command,
                observation=observation,
                reconciled_after_interruption=False,
            )
        return ProviderQualificationResult(
            status="failed",
            reason="provider_readback_conflict",
            command=command,
            observation=observation,
            reconciled_after_interruption=False,
        )


@dataclass(frozen=True)
class RecoveryTiming:
    failure_detected_at: str
    recovery_authorized_at: str
    restore_started_at: str
    postgres_ready_at: str
    provider_ready_at: str
    qualification_completed_at: str
    first_runtime_write_permitted_at: str | None
    latest_durable_transaction_at: str
    latest_restored_transaction_at: str
    latest_durable_lsn: str
    restored_lsn: str
    lost_transaction_count: int

    def measurements(self) -> dict[str, Any]:
        points = {
            name: parse_timestamp(getattr(self, name))
            for name in (
                "failure_detected_at",
                "recovery_authorized_at",
                "restore_started_at",
                "postgres_ready_at",
                "provider_ready_at",
                "qualification_completed_at",
                "latest_durable_transaction_at",
                "latest_restored_transaction_at",
            )
        }
        if self.first_runtime_write_permitted_at is not None:
            parse_timestamp(self.first_runtime_write_permitted_at)
        ordered = (
            "failure_detected_at",
            "recovery_authorized_at",
            "restore_started_at",
            "postgres_ready_at",
            "provider_ready_at",
            "qualification_completed_at",
        )
        if any(points[right] < points[left] for left, right in zip(ordered, ordered[1:])):
            raise InfrastructureQualificationError("RTO timestamps are out of order")
        if points["latest_restored_transaction_at"] > points["latest_durable_transaction_at"]:
            raise InfrastructureQualificationError(
                "restored transaction is newer than durable boundary"
            )
        if (
            isinstance(self.lost_transaction_count, bool)
            or not isinstance(self.lost_transaction_count, int)
            or self.lost_transaction_count < 0
        ):
            raise InfrastructureQualificationError("lost transaction count is invalid")
        for value, label in (
            (self.latest_durable_lsn, "latest durable LSN"),
            (self.restored_lsn, "restored LSN"),
        ):
            if not isinstance(value, str) or re.fullmatch(r"[0-9A-F]+/[0-9A-F]+", value) is None:
                raise InfrastructureQualificationError(f"{label} is invalid")
        def seconds(end: str, start: str) -> int:
            return int((points[end] - points[start]).total_seconds())
        rpo_seconds = math.ceil(
            max(
                0.0,
                (
                    points["latest_durable_transaction_at"]
                    - points["latest_restored_transaction_at"]
                ).total_seconds(),
            )
        )
        return {
            "contract_version": TIMING_CONTRACT_VERSION,
            "failure_detection_to_authorization_seconds": seconds(
                "recovery_authorized_at", "failure_detected_at"
            ),
            "latest_durable_lsn": self.latest_durable_lsn,
            "latest_durable_transaction_at": self.latest_durable_transaction_at,
            "latest_restored_transaction_at": self.latest_restored_transaction_at,
            "lost_transaction_count": self.lost_transaction_count,
            "provider_reconciliation_seconds": seconds(
                "provider_ready_at", "postgres_ready_at"
            ),
            "qualification_seconds": seconds(
                "qualification_completed_at", "provider_ready_at"
            ),
            "restore_seconds": seconds("postgres_ready_at", "restore_started_at"),
            "restored_lsn": self.restored_lsn,
            "rpo_seconds": rpo_seconds,
            "rto_seconds": seconds(
                "qualification_completed_at", "failure_detected_at"
            ),
            "timestamps": {
                "failure_detected_at": self.failure_detected_at,
                "first_runtime_write_permitted_at": self.first_runtime_write_permitted_at,
                "postgres_ready_at": self.postgres_ready_at,
                "provider_ready_at": self.provider_ready_at,
                "qualification_completed_at": self.qualification_completed_at,
                "recovery_authorized_at": self.recovery_authorized_at,
                "restore_started_at": self.restore_started_at,
            },
        }


@dataclass(frozen=True)
class ScenarioEvidence:
    name: str
    status: ScenarioStatus
    started_at: str
    completed_at: str
    evidence_digest: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        _safe_text(self.name, "scenario name")
        if self.status not in {"passed", "failed", "hold", "skipped"}:
            raise InfrastructureQualificationError("scenario status is invalid")
        started = parse_timestamp(self.started_at)
        completed = parse_timestamp(self.completed_at)
        if completed < started:
            raise InfrastructureQualificationError("scenario timestamps are reversed")
        _digest(self.evidence_digest, "scenario evidence digest")
        _safe_text(self.reason, "scenario reason")
        return {
            "completed_at": self.completed_at,
            "evidence_digest": self.evidence_digest,
            "name": self.name,
            "reason": self.reason,
            "started_at": self.started_at,
            "status": self.status,
        }


def ensure_secret_free(value: Any, *, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise InfrastructureQualificationError("evidence keys must be strings")
            if _SECRET_KEY.search(key):
                raise InfrastructureQualificationError(f"secret-bearing evidence key: {path}.{key}")
            ensure_secret_free(item, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            ensure_secret_free(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and _CREDENTIAL_URL.search(value):
        raise InfrastructureQualificationError(f"credential URL in evidence: {path}")


def validate_evidence_bundle(document: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "cleanup",
        "contract_version",
        "control",
        "environment",
        "evidence_schema_version",
        "limitations",
        "provider",
        "recovery",
        "result",
        "run",
        "scenarios",
    }
    if set(document) != expected:
        raise InfrastructureQualificationError("qualification evidence keys are invalid")
    root = dict(document)
    if root["contract_version"] != QUALIFICATION_VERSION:
        raise InfrastructureQualificationError("qualification version is unsupported")
    if root["evidence_schema_version"] != EVIDENCE_SCHEMA_VERSION:
        raise InfrastructureQualificationError("evidence schema is unsupported")
    run = root["run"]
    if not isinstance(run, dict) or set(run) != {
        "completed_at",
        "dirty_tree",
        "git_commit",
        "run_id",
        "started_at",
    }:
        raise InfrastructureQualificationError("run evidence is invalid")
    _uuid(run["run_id"], "run ID")
    if not isinstance(run["git_commit"], str) or _GIT_OID.fullmatch(run["git_commit"]) is None:
        raise InfrastructureQualificationError("Git commit is invalid")
    if not isinstance(run["dirty_tree"], bool):
        raise InfrastructureQualificationError("dirty-tree state is invalid")
    if parse_timestamp(run["completed_at"]) < parse_timestamp(run["started_at"]):
        raise InfrastructureQualificationError("run timestamps are reversed")
    scenarios = root["scenarios"]
    if not isinstance(scenarios, list) or not scenarios:
        raise InfrastructureQualificationError("scenario evidence is empty")
    names: list[str] = []
    for item in scenarios:
        if not isinstance(item, dict):
            raise InfrastructureQualificationError("scenario evidence is invalid")
        validated = ScenarioEvidence(**item).to_dict()
        names.append(validated["name"])
    if names != sorted(set(names)):
        raise InfrastructureQualificationError(
            "scenarios must be unique and deterministically sorted"
        )
    cleanup = root["cleanup"]
    if (
        not isinstance(cleanup, dict)
        or set(cleanup) != {"completed", "residual_resources"}
        or not isinstance(cleanup["completed"], bool)
        or not isinstance(cleanup["residual_resources"], list)
    ):
        raise InfrastructureQualificationError("cleanup evidence is invalid")
    if root["result"] not in {"qualified", "failed", "hold"}:
        raise InfrastructureQualificationError("qualification result is invalid")
    provider = root["provider"]
    if (
        not isinstance(provider, dict)
        or set(provider) != {"contract_version", "operations"}
        or provider["contract_version"] != PROVIDER_CONTRACT_VERSION
        or not isinstance(provider["operations"], list)
    ):
        raise InfrastructureQualificationError("provider evidence is invalid")
    if not isinstance(root["limitations"], list) or not all(
        isinstance(item, str) and item for item in root["limitations"]
    ):
        raise InfrastructureQualificationError("limitations are invalid")
    ensure_secret_free(root)
    canonical_json(root)
    return root


def evidence_bytes(document: Mapping[str, Any]) -> bytes:
    validated = validate_evidence_bundle(document)
    return canonical_json(validated).encode("ascii")


def evidence_digest(document: Mapping[str, Any]) -> str:
    return sha256(evidence_bytes(document)).hexdigest()


def prerequisite_observation() -> dict[str, Any]:
    commands = {
        "docker": shutil.which("docker"),
        "git": shutil.which("git"),
        "openssl": shutil.which("openssl"),
        "pytest": importlib.util.find_spec("pytest"),
    }
    missing = sorted(name for name, path in commands.items() if path is None)
    return {
        "available": not missing,
        "commands": {name: path is not None for name, path in sorted(commands.items())},
        "missing": missing,
    }


CleanupAction = tuple[str, Callable[[], None]]


def run_cleanup(actions: Sequence[CleanupAction]) -> dict[str, Any]:
    failures: list[str] = []
    for label, action in reversed(tuple(actions)):
        try:
            action()
        except Exception:
            failures.append(label)
    result = {
        "completed": not failures,
        "residual_resources": sorted(failures),
    }
    if failures:
        raise InfrastructureQualificationError(
            "qualification cleanup failed: " + ",".join(sorted(failures))
        )
    return result


def write_evidence_bundle(path: Path, document: Mapping[str, Any]) -> str:
    payload = evidence_bytes(document)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return sha256(payload).hexdigest()


def parse_evidence_bundle(payload: bytes) -> dict[str, Any]:
    if not isinstance(payload, bytes) or not payload:
        raise InfrastructureQualificationError("evidence payload is empty")
    try:
        text = payload.decode("ascii")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_reject_number,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InfrastructureQualificationError("evidence JSON is invalid") from exc
    if not isinstance(value, dict):
        raise InfrastructureQualificationError("evidence root is invalid")
    validated = validate_evidence_bundle(value)
    if canonical_json(validated).encode("ascii") != payload:
        raise InfrastructureQualificationError("evidence JSON is not canonical")
    return validated


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InfrastructureQualificationError("duplicate evidence key")
        result[key] = value
    return result


def _reject_number(value: str) -> Any:
    raise InfrastructureQualificationError("floating-point evidence is forbidden")


__all__ = [
    "AuthoritativeProviderAdapter",
    "DISPOSABLE_CONFIRMATION",
    "EVIDENCE_SCHEMA_VERSION",
    "InfrastructureQualificationConfig",
    "InfrastructureQualificationError",
    "LOCAL_PROVIDER_KIND",
    "PROJECT_PREFIX",
    "PROVIDER_CONTRACT_VERSION",
    "ProviderActionRequest",
    "ProviderCommandResult",
    "ProviderObservation",
    "ProviderQualificationResult",
    "QUALIFICATION_VERSION",
    "RecoveryTiming",
    "SUMMARY_FILE",
    "ScenarioEvidence",
    "TIMING_CONTRACT_VERSION",
    "canonical_timestamp",
    "ensure_secret_free",
    "evidence_bytes",
    "evidence_digest",
    "parse_evidence_bundle",
    "prerequisite_observation",
    "require_loopback_endpoint",
    "run_cleanup",
    "validate_evidence_bundle",
    "write_evidence_bundle",
]
