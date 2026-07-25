"""Phase 5C4.5 recovery execution, validation, and immutable evidence.

Restore execution is intentionally separate from validation and admission:

1. an approved provider performs one idempotent restore operation;
2. the restored database is observed in one read-only, repeatable-read snapshot;
3. a canonical receipt is admitted in one serializable control transaction.

The module does not create backups, select retention policy, activate a target,
or change any application data.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import threading
import time
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, DBAPIError, SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.core.database_identity import database_connect_args
from app.operators.immutable_provenance_contracts import (
    CURRENT_RUNTIME_SCHEMA_REVISION,
    MIGRATION_ADVISORY_LOCK_KEY,
)
from app.operators.immutable_provenance_qualification import (
    ImmutableProvenanceQualificationError,
    qualify_immutable_provenance_connection,
)
from app.operators.phase5c_contracts import canonical_digest, canonical_json
from app.operators.phase5c4_control_evidence import (
    Phase5C4EvidenceError,
    write_private_file,
)
from app.operators.phase5c4_roles import qualify_source_role_policy


RECOVERY_VALIDATION_VERSION = "phase5c4_recovery_validation_v1"
RECOVERY_PROVIDER_VERSION = "phase5c4_docker_compose_pgbackrest_v1"
RECOVERY_METHOD = "docker_compose_pgbackrest"
RECOVERY_CONTROL_REVISION = "ops_0007_recovery_validation"
EXPECTED_POSTGRES_MAJOR = 16

RECOVERY_CHECKS = (
    "backup_metadata",
    "database_identity",
    "environment",
    "fence",
    "immutable_provenance",
    "integrity_qualification",
    "postgres_revision",
    "provider_completion",
    "recovery_metadata",
    "recovery_target",
    "role_policy",
    "runtime_privileges",
    "schema_revision",
    "target_identity",
)

RECOVERY_FAILURE_CODES = frozenset(
    {
        "backup_metadata_mismatch",
        "database_identity_mismatch",
        "environment_mismatch",
        "fence_mismatch",
        "immutable_provenance_mismatch",
        "integrity_qualification_failed",
        "postgres_revision_mismatch",
        "provider_completion_failed",
        "provider_request_conflict",
        "recovery_interrupted",
        "recovery_metadata_mismatch",
        "recovery_target_mismatch",
        "role_policy_mismatch",
        "runtime_privilege_mismatch",
        "schema_revision_mismatch",
        "target_identity_mismatch",
        "validation_database_unavailable",
    }
)

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
_OPERATOR = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:@/-]{0,255}$")
_LSN = re.compile(r"^[0-9A-F]+/[0-9A-F]+$")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
_JOURNAL_MAXIMUM_BYTES = 1024 * 1024
_COMPOSE_MAXIMUM_BYTES = 16 * 1024 * 1024
_COMMAND_STREAM_MAXIMUM_BYTES = 32 * 1024 * 1024
_COMMAND_TIMEOUT_SECONDS = 1800
_OUTPUT_CHUNK_BYTES = 64 * 1024
_PGBACKREST_REPOSITORY_NUMBER = 1
_RECOVERY_TYPE = "lsn"
_TARGET_ACTION = "promote"


class RecoveryValidationError(RuntimeError):
    """Stable fail-closed recovery boundary."""

    def __init__(self, reason_code: str):
        if reason_code not in RECOVERY_FAILURE_CODES:
            reason_code = "recovery_metadata_mismatch"
        super().__init__(reason_code)
        self.reason_code = reason_code


def _uuid(value: str, label: str) -> str:
    try:
        parsed = UUID(value)
    except (TypeError, ValueError, AttributeError):
        raise RecoveryValidationError("recovery_metadata_mismatch") from None
    if str(parsed) != value:
        raise RecoveryValidationError("recovery_metadata_mismatch")
    return value


def _digest(value: str, label: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise RecoveryValidationError("recovery_metadata_mismatch")
    return value


def _name(value: str, label: str) -> str:
    if not isinstance(value, str) or _NAME.fullmatch(value) is None:
        raise RecoveryValidationError("recovery_metadata_mismatch")
    return value


def _lsn(value: str, label: str) -> str:
    if not isinstance(value, str) or _LSN.fullmatch(value) is None:
        raise RecoveryValidationError("recovery_metadata_mismatch")
    return value


def _lsn_value(value: str) -> int:
    high, low = value.split("/", 1)
    return (int(high, 16) << 32) + int(low, 16)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or _TIMESTAMP.fullmatch(value) is None:
        raise RecoveryValidationError("recovery_metadata_mismatch")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        raise RecoveryValidationError("recovery_metadata_mismatch") from None


@dataclass(frozen=True)
class RecoveryExpectation:
    """Operator-approved identities and evidence to validate after restore."""

    recovery_id: str
    request_id: str
    environment_id: str
    environment_key: str
    attempt_id: str
    target_database_instance_id: str
    operator_identity: str
    backup_artifact_id: str
    backup_artifact_digest: str
    provider_backup_id: str
    restore_artifact_id: str
    restore_artifact_digest: str
    expected_database_name: str
    expected_database_oid: int
    expected_system_identifier: str
    expected_database_identity_digest: str
    expected_physical_identity_digest: str
    expected_target_identity_digest: str
    expected_recovery_lsn: str
    expected_timeline: int
    expected_server_version_num: int
    expected_schema_revision: str
    expected_qualification_digest: str
    expected_immutable_provenance_digest: str
    expected_role_manifest_digest: str
    expected_runtime_privilege_digest: str
    expected_fence_digest: str
    expected_fence_mode: str

    def validate(self) -> None:
        for label in (
            "recovery_id",
            "request_id",
            "environment_id",
            "attempt_id",
            "target_database_instance_id",
            "backup_artifact_id",
            "restore_artifact_id",
        ):
            _uuid(str(getattr(self, label)), label)
        for label in (
            "backup_artifact_digest",
            "restore_artifact_digest",
            "expected_database_identity_digest",
            "expected_physical_identity_digest",
            "expected_target_identity_digest",
            "expected_qualification_digest",
            "expected_immutable_provenance_digest",
            "expected_role_manifest_digest",
            "expected_runtime_privilege_digest",
            "expected_fence_digest",
        ):
            _digest(str(getattr(self, label)), label)
        for label in (
            "environment_key",
            "provider_backup_id",
            "expected_database_name",
        ):
            _name(str(getattr(self, label)), label)
        if (
            not isinstance(self.operator_identity, str)
            or _OPERATOR.fullmatch(self.operator_identity) is None
        ):
            raise RecoveryValidationError("recovery_metadata_mismatch")
        if (
            not self.expected_system_identifier.isdigit()
            or not 0 <= int(self.expected_system_identifier) <= 2**64 - 1
            or not isinstance(self.expected_database_oid, int)
            or self.expected_database_oid <= 0
        ):
            raise RecoveryValidationError("recovery_metadata_mismatch")
        _lsn(self.expected_recovery_lsn, "expected_recovery_lsn")
        if not isinstance(self.expected_timeline, int) or self.expected_timeline < 1:
            raise RecoveryValidationError("recovery_metadata_mismatch")
        if not 160000 <= self.expected_server_version_num < 170000:
            raise RecoveryValidationError("postgres_revision_mismatch")
        if self.expected_schema_revision != CURRENT_RUNTIME_SCHEMA_REVISION:
            raise RecoveryValidationError("schema_revision_mismatch")
        if self.expected_fence_mode not in {
            "closed_prequalification",
            "closed_cutover",
        }:
            raise RecoveryValidationError("fence_mismatch")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RecoveryExpectation":
        expected = {field.name for field in cls.__dataclass_fields__.values()}
        if set(value) != expected:
            raise RecoveryValidationError("recovery_metadata_mismatch")
        try:
            result = cls(**dict(value))
        except TypeError:
            raise RecoveryValidationError("recovery_metadata_mismatch") from None
        result.validate()
        return result


@dataclass(frozen=True)
class RestoreRequest:
    """The bounded input accepted by the Docker Compose/pgBackRest adapter."""

    operation_id: str
    operation_directory: Path
    compose_file: Path
    compose_project: str
    restore_service: str
    postgres_service: str
    stanza: str
    provider_backup_id: str
    recovery_target_lsn: str

    def validate(self) -> None:
        _uuid(self.operation_id, "operation_id")
        if (
            not self.operation_directory.is_absolute()
            or not self.operation_directory.is_dir()
            or self.operation_directory.is_symlink()
            or not self.compose_file.is_absolute()
            or not self.compose_file.is_file()
            or self.compose_file.is_symlink()
        ):
            raise RecoveryValidationError("recovery_metadata_mismatch")
        for label in (
            "compose_project",
            "restore_service",
            "postgres_service",
            "stanza",
            "provider_backup_id",
        ):
            _name(str(getattr(self, label)), label)
        _lsn(self.recovery_target_lsn, "recovery_target_lsn")


@dataclass(frozen=True)
class ProviderRestoreEvidence:
    operation_id: str
    provider_contract_version: str
    recovery_method: str
    provider_backup_id: str
    requested_lsn: str
    request_digest: str
    started_at: str
    completed_at: str
    restore_command_digest: str
    startup_command_digest: str
    restore_stdout_digest: str
    restore_stdout_bytes: int
    restore_stderr_digest: str
    restore_stderr_bytes: int
    startup_stdout_digest: str
    startup_stdout_bytes: int
    startup_stderr_digest: str
    startup_stderr_bytes: int
    completed: bool

    def validate(self) -> None:
        _uuid(self.operation_id, "operation_id")
        if (
            self.provider_contract_version != RECOVERY_PROVIDER_VERSION
            or self.recovery_method != RECOVERY_METHOD
            or not self.completed
        ):
            raise RecoveryValidationError("provider_completion_failed")
        _name(self.provider_backup_id, "provider_backup_id")
        _lsn(self.requested_lsn, "requested_lsn")
        started_at = _parse_timestamp(self.started_at)
        completed_at = _parse_timestamp(self.completed_at)
        if completed_at < started_at:
            raise RecoveryValidationError("recovery_metadata_mismatch")
        for label in (
            "request_digest",
            "restore_command_digest",
            "startup_command_digest",
            "restore_stdout_digest",
            "restore_stderr_digest",
            "startup_stdout_digest",
            "startup_stderr_digest",
        ):
            _digest(str(getattr(self, label)), label)
        for label in (
            "restore_stdout_bytes",
            "restore_stderr_bytes",
            "startup_stdout_bytes",
            "startup_stderr_bytes",
        ):
            value = getattr(self, label)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 0 <= value <= _COMMAND_STREAM_MAXIMUM_BYTES
            ):
                raise RecoveryValidationError("recovery_metadata_mismatch")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ProviderRestoreEvidence":
        expected = {field.name for field in cls.__dataclass_fields__.values()}
        if set(value) != expected:
            raise RecoveryValidationError("recovery_metadata_mismatch")
        try:
            result = cls(**dict(value))
        except TypeError:
            raise RecoveryValidationError("recovery_metadata_mismatch") from None
        result.validate()
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
        }


class RecoveryProvider(Protocol):
    def restore(self, request: RestoreRequest) -> ProviderRestoreEvidence:
        """Execute or reconcile one idempotently identified restore."""


@dataclass(frozen=True)
class CommandExecution:
    """Bounded command result containing hashes and counts, never raw output."""

    returncode: int
    stdout_digest: str
    stdout_bytes: int
    stderr_digest: str
    stderr_bytes: int

    def validate(self) -> None:
        if not isinstance(self.returncode, int) or isinstance(self.returncode, bool):
            raise RecoveryValidationError("provider_completion_failed")
        for label in ("stdout_digest", "stderr_digest"):
            _digest(str(getattr(self, label)), label)
        for label in ("stdout_bytes", "stderr_bytes"):
            value = getattr(self, label)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 0 <= value <= _COMMAND_STREAM_MAXIMUM_BYTES
            ):
                raise RecoveryValidationError("provider_completion_failed")


class _CommandOutputLimitError(subprocess.SubprocessError):
    pass


CommandRunner = Callable[[Sequence[str]], CommandExecution]
Clock = Callable[[], datetime]


def _default_runner(argv: Sequence[str]) -> CommandExecution:
    """Hash both output streams incrementally and discard their raw bytes."""

    process = subprocess.Popen(
        list(argv),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    if process.stdout is None or process.stderr is None:
        process.kill()
        process.wait()
        raise subprocess.SubprocessError("command output pipes unavailable")

    hashes = [sha256(), sha256()]
    counts = [0, 0]
    overflow = threading.Event()
    drain_errors: list[BaseException] = []

    def drain(stream: Any, index: int) -> None:
        try:
            while chunk := stream.read(_OUTPUT_CHUNK_BYTES):
                counts[index] += len(chunk)
                if counts[index] > _COMMAND_STREAM_MAXIMUM_BYTES:
                    overflow.set()
                hashes[index].update(chunk)
        except BaseException as exc:  # pragma: no cover - defensive pipe failure
            drain_errors.append(exc)
        finally:
            stream.close()

    threads = (
        threading.Thread(target=drain, args=(process.stdout, 0), daemon=True),
        threading.Thread(target=drain, args=(process.stderr, 1), daemon=True),
    )
    for thread in threads:
        thread.start()

    def kill_process_group() -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            process.kill()

    deadline = time.monotonic() + _COMMAND_TIMEOUT_SECONDS
    timed_out = False
    while process.poll() is None:
        if overflow.is_set():
            kill_process_group()
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            kill_process_group()
            break
        try:
            process.wait(timeout=min(0.05, remaining))
        except subprocess.TimeoutExpired:
            continue
    process.wait()
    for thread in threads:
        thread.join(timeout=5)
    if any(thread.is_alive() for thread in threads):
        kill_process_group()
        raise subprocess.SubprocessError("command output pipes did not close")
    if timed_out:
        raise subprocess.TimeoutExpired(list(argv), _COMMAND_TIMEOUT_SECONDS)
    if overflow.is_set():
        raise _CommandOutputLimitError("command output exceeded its stream limit")
    if drain_errors:
        raise subprocess.SubprocessError("unable to hash command output")
    return CommandExecution(
        returncode=process.returncode,
        stdout_digest=hashes[0].hexdigest(),
        stdout_bytes=counts[0],
        stderr_digest=hashes[1].hexdigest(),
        stderr_bytes=counts[1],
    )


@dataclass(frozen=True)
class _ProviderRequestPlan:
    document: Mapping[str, Any]
    request_digest: str
    restore_argv: tuple[str, ...]
    startup_argv: tuple[str, ...]


def _read_compose_identity(path: Path) -> dict[str, Any]:
    try:
        resolved_path = path.resolve(strict=True)
    except OSError:
        raise RecoveryValidationError("recovery_metadata_mismatch") from None
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(resolved_path, flags)
    except OSError:
        raise RecoveryValidationError("recovery_metadata_mismatch") from None
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size < 1
            or before.st_size > _COMPOSE_MAXIMUM_BYTES
        ):
            raise RecoveryValidationError("recovery_metadata_mismatch")
        digest = sha256()
        total = 0
        while True:
            chunk = os.read(
                descriptor,
                min(_OUTPUT_CHUNK_BYTES, _COMPOSE_MAXIMUM_BYTES + 1 - total),
            )
            if not chunk:
                break
            total += len(chunk)
            if total > _COMPOSE_MAXIMUM_BYTES:
                raise RecoveryValidationError("recovery_metadata_mismatch")
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (
            total != before.st_size
            or before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
        ):
            raise RecoveryValidationError("recovery_metadata_mismatch")
        return {
            "byte_count": total,
            "resolved_path": str(resolved_path),
            "sha256": digest.hexdigest(),
        }
    finally:
        os.close(descriptor)


def _build_provider_request_plan(request: RestoreRequest) -> _ProviderRequestPlan:
    request.validate()
    compose_file = _read_compose_identity(request.compose_file)
    compose = (
        "docker",
        "compose",
        "--project-name",
        request.compose_project,
        "--file",
        compose_file["resolved_path"],
    )
    restore_argv = (
        *compose,
        "run",
        "--rm",
        "--no-deps",
        request.restore_service,
        "pgbackrest",
        f"--stanza={request.stanza}",
        f"--repo={_PGBACKREST_REPOSITORY_NUMBER}",
        f"--set={request.provider_backup_id}",
        f"--type={_RECOVERY_TYPE}",
        f"--target={request.recovery_target_lsn}",
        f"--target-action={_TARGET_ACTION}",
        "restore",
    )
    startup_argv = (*compose, "up", "--detach", request.postgres_service)
    document = {
        "commands": {
            "restore": {"argv": list(restore_argv)},
            "startup": {"argv": list(startup_argv)},
        },
        "compose_file": compose_file,
        "compose_project": request.compose_project,
        "operation_id": request.operation_id,
        "postgres_service": request.postgres_service,
        "provider_backup_id": request.provider_backup_id,
        "provider_contract_version": RECOVERY_PROVIDER_VERSION,
        "recovery_method": RECOVERY_METHOD,
        "recovery_type": _RECOVERY_TYPE,
        "repository_number": _PGBACKREST_REPOSITORY_NUMBER,
        "restore_service": request.restore_service,
        "stanza": request.stanza,
        "target_action": _TARGET_ACTION,
        "target_lsn": request.recovery_target_lsn,
    }
    return _ProviderRequestPlan(
        document=document,
        request_digest=canonical_digest(document),
        restore_argv=restore_argv,
        startup_argv=startup_argv,
    )


def _read_private_journal(path: Path) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise RecoveryValidationError("recovery_metadata_mismatch") from None
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size < 2
            or metadata.st_size > _JOURNAL_MAXIMUM_BYTES
            or stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            raise RecoveryValidationError("recovery_metadata_mismatch")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(
                descriptor,
                min(_OUTPUT_CHUNK_BYTES, _JOURNAL_MAXIMUM_BYTES + 1 - total),
            )
            if not chunk:
                break
            total += len(chunk)
            if total > _JOURNAL_MAXIMUM_BYTES:
                raise RecoveryValidationError("recovery_metadata_mismatch")
            chunks.append(chunk)
        document = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(document) != metadata.st_size
            or metadata.st_dev != after.st_dev
            or metadata.st_ino != after.st_ino
            or metadata.st_size != after.st_size
            or metadata.st_mtime_ns != after.st_mtime_ns
        ):
            raise RecoveryValidationError("recovery_metadata_mismatch")
        return document
    finally:
        os.close(descriptor)


def _write_private_journal(path: Path, document: bytes) -> None:
    """Publish an exclusive complete file without exposing a partial journal."""

    temporary = path.with_name(f".{path.name}.pending.{uuid4()}")
    try:
        write_private_file(
            temporary,
            document,
            maximum_bytes=_JOURNAL_MAXIMUM_BYTES,
        )
        os.link(temporary, path, follow_symlinks=False)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except (OSError, Phase5C4EvidenceError):
        raise Phase5C4EvidenceError("Unable to publish private journal") from None
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


class DockerComposePgBackRestRecoveryProvider:
    """One approved local-portfolio recovery provider.

    pgBackRest repository credentials and PostgreSQL configuration remain in
    the Compose service. They are never accepted as command arguments or
    copied into evidence.
    """

    def __init__(
        self,
        *,
        runner: CommandRunner = _default_runner,
        clock: Clock = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._runner = runner
        self._clock = clock

    @staticmethod
    def _digest_command(argv: Sequence[str]) -> str:
        return canonical_digest({"argv": list(argv)})

    @staticmethod
    def _state_paths(request: RestoreRequest) -> tuple[Path, Path]:
        return (
            request.operation_directory / f"{request.operation_id}.intent.json",
            request.operation_directory / f"{request.operation_id}.complete.json",
        )

    @staticmethod
    def _read_intent(
        plan: _ProviderRequestPlan,
        path: Path,
    ) -> str:
        try:
            document = _read_private_journal(path)
            value = json.loads(document)
            if not isinstance(value, dict) or set(value) != {
                "contract_version",
                "created_at",
                "operation_id",
                "request",
                "request_digest",
            }:
                raise ValueError
            if canonical_json(value).encode("utf-8") != document:
                raise ValueError
            if (
                value["contract_version"] != RECOVERY_PROVIDER_VERSION
                or _uuid(value["operation_id"], "operation_id")
                != plan.document["operation_id"]
            ):
                raise ValueError
            created_at = str(value["created_at"])
            _parse_timestamp(created_at)
            request_document = value["request"]
            request_digest = _digest(
                value["request_digest"],
                "request_digest",
            )
            if (
                not isinstance(request_document, dict)
                or canonical_digest(request_document) != request_digest
            ):
                raise ValueError
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
            RecoveryValidationError,
        ):
            raise RecoveryValidationError("recovery_metadata_mismatch") from None
        if (
            request_digest != plan.request_digest
            or request_document != plan.document
        ):
            raise RecoveryValidationError("provider_request_conflict")
        return created_at

    @staticmethod
    def _read_completion(
        plan: _ProviderRequestPlan,
        path: Path,
        *,
        intent_created_at: str,
    ) -> ProviderRestoreEvidence:
        try:
            document = _read_private_journal(path)
            value = json.loads(document)
            if (
                not isinstance(value, dict)
                or canonical_json(value).encode("utf-8") != document
            ):
                raise ValueError
            evidence = ProviderRestoreEvidence.from_mapping(value)
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
            RecoveryValidationError,
        ):
            raise RecoveryValidationError("recovery_metadata_mismatch") from None
        if evidence.request_digest != plan.request_digest:
            raise RecoveryValidationError("provider_request_conflict")
        if (
            evidence.operation_id != plan.document["operation_id"]
            or evidence.provider_backup_id != plan.document["provider_backup_id"]
            or evidence.requested_lsn != plan.document["target_lsn"]
            or evidence.restore_command_digest
            != DockerComposePgBackRestRecoveryProvider._digest_command(
                plan.restore_argv
            )
            or evidence.startup_command_digest
            != DockerComposePgBackRestRecoveryProvider._digest_command(
                plan.startup_argv
            )
            or _parse_timestamp(evidence.started_at)
            < _parse_timestamp(intent_created_at)
        ):
            raise RecoveryValidationError("recovery_metadata_mismatch")
        return evidence

    @classmethod
    def _reconcile(
        cls,
        plan: _ProviderRequestPlan,
        intent_path: Path,
        completion_path: Path,
    ) -> ProviderRestoreEvidence:
        if not os.path.lexists(intent_path):
            raise RecoveryValidationError("recovery_metadata_mismatch")
        intent_created_at = cls._read_intent(plan, intent_path)
        if not os.path.lexists(completion_path):
            raise RecoveryValidationError("recovery_interrupted")
        return cls._read_completion(
            plan,
            completion_path,
            intent_created_at=intent_created_at,
        )

    def _execute(self, argv: Sequence[str]) -> CommandExecution:
        try:
            result = self._runner(argv)
        except _CommandOutputLimitError:
            raise RecoveryValidationError("provider_completion_failed") from None
        except (OSError, subprocess.SubprocessError):
            raise RecoveryValidationError("recovery_interrupted") from None
        if not isinstance(result, CommandExecution):
            raise RecoveryValidationError("provider_completion_failed")
        result.validate()
        if result.returncode != 0:
            raise RecoveryValidationError("provider_completion_failed")
        return result

    def restore(self, request: RestoreRequest) -> ProviderRestoreEvidence:
        plan = _build_provider_request_plan(request)
        intent_path, completion_path = self._state_paths(request)
        if os.path.lexists(intent_path) or os.path.lexists(completion_path):
            return self._reconcile(plan, intent_path, completion_path)
        intent_created_at = _timestamp(self._clock())
        intent = {
            "contract_version": RECOVERY_PROVIDER_VERSION,
            "created_at": intent_created_at,
            "operation_id": request.operation_id,
            "request": plan.document,
            "request_digest": plan.request_digest,
        }
        try:
            _write_private_journal(
                intent_path,
                canonical_json(intent).encode("utf-8"),
            )
        except Phase5C4EvidenceError:
            if os.path.lexists(intent_path) or os.path.lexists(completion_path):
                return self._reconcile(plan, intent_path, completion_path)
            raise RecoveryValidationError("recovery_interrupted") from None
        started_at = _timestamp(self._clock())
        if _parse_timestamp(started_at) < _parse_timestamp(intent_created_at):
            raise RecoveryValidationError("recovery_metadata_mismatch")
        restore_result = self._execute(plan.restore_argv)
        startup_result = self._execute(plan.startup_argv)
        if _build_provider_request_plan(request).request_digest != plan.request_digest:
            raise RecoveryValidationError("provider_request_conflict")
        evidence = ProviderRestoreEvidence(
            operation_id=request.operation_id,
            provider_contract_version=RECOVERY_PROVIDER_VERSION,
            recovery_method=RECOVERY_METHOD,
            provider_backup_id=request.provider_backup_id,
            requested_lsn=request.recovery_target_lsn,
            request_digest=plan.request_digest,
            started_at=started_at,
            completed_at=_timestamp(self._clock()),
            restore_command_digest=self._digest_command(plan.restore_argv),
            startup_command_digest=self._digest_command(plan.startup_argv),
            restore_stdout_digest=restore_result.stdout_digest,
            restore_stdout_bytes=restore_result.stdout_bytes,
            restore_stderr_digest=restore_result.stderr_digest,
            restore_stderr_bytes=restore_result.stderr_bytes,
            startup_stdout_digest=startup_result.stdout_digest,
            startup_stdout_bytes=startup_result.stdout_bytes,
            startup_stderr_digest=startup_result.stderr_digest,
            startup_stderr_bytes=startup_result.stderr_bytes,
            completed=True,
        )
        evidence.validate()
        try:
            _write_private_journal(
                completion_path,
                canonical_json(evidence.to_dict()).encode("utf-8"),
            )
        except Phase5C4EvidenceError:
            raise RecoveryValidationError("recovery_interrupted") from None
        return evidence


def _collect_observation(connection: Connection) -> dict[str, Any]:
    database = dict(
        connection.execute(
            text(
                """
                SELECT current_database()::text AS database_name,
                       (SELECT oid::bigint FROM pg_catalog.pg_database
                        WHERE datname = current_database()) AS database_oid,
                       (pg_catalog.pg_control_system()).system_identifier::text
                           AS system_identifier,
                       current_setting('server_version_num')::integer
                           AS server_version_num,
                       (pg_catalog.pg_control_checkpoint()).timeline_id::bigint
                           AS timeline,
                       pg_catalog.pg_is_in_recovery() AS in_recovery,
                       CASE WHEN pg_catalog.pg_is_in_recovery()
                            THEN pg_catalog.pg_last_wal_replay_lsn()::text
                            ELSE pg_catalog.pg_current_wal_lsn()::text
                       END AS observed_lsn,
                       pg_catalog.clock_timestamp() AS observed_at
                """
            )
        )
        .mappings()
        .one()
    )
    database["database_oid"] = int(database["database_oid"])
    database["server_version_num"] = int(database["server_version_num"])
    database["timeline"] = int(database["timeline"])
    database["observed_at"] = _timestamp(database["observed_at"])
    qualification_error = None
    try:
        qualification = qualify_immutable_provenance_connection(connection).to_dict()
    except ImmutableProvenanceQualificationError:
        qualification = {}
        qualification_error = "integrity_qualification_failed"
    role = qualify_source_role_policy(
        connection,
        expected_state="normal",
        policy_revision=CURRENT_RUNTIME_SCHEMA_REVISION,
    )
    return {
        "database": database,
        "qualification": qualification,
        "qualification_error": qualification_error,
        "role": role,
    }


def collect_recovery_database_observation(database_url: str) -> dict[str, Any]:
    """Collect all restored-database assertions in one protected snapshot."""

    try:
        url = make_url(database_url)
    except (ArgumentError, TypeError, ValueError):
        raise RecoveryValidationError("validation_database_unavailable") from None
    if url.get_backend_name() != "postgresql":
        raise RecoveryValidationError("validation_database_unavailable")
    engine = create_engine(
        database_url,
        poolclass=NullPool,
        hide_parameters=True,
        isolation_level="REPEATABLE READ",
        connect_args=database_connect_args(database_url),
    )
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            boundary = connection.execute(
                text(
                    "SELECT session_user::text, current_user::text, "
                    "current_setting('transaction_read_only'), "
                    "current_setting('transaction_isolation')"
                )
            ).one()
            if tuple(boundary) != (
                "nutrition_qualifier",
                "nutrition_qualifier",
                "on",
                "repeatable read",
            ):
                raise RecoveryValidationError("integrity_qualification_failed")
            connection.execute(
                text("SELECT pg_catalog.pg_advisory_xact_lock_shared(:lock_id)"),
                {"lock_id": MIGRATION_ADVISORY_LOCK_KEY},
            )
            return _collect_observation(connection)
    except RecoveryValidationError:
        raise
    except ImmutableProvenanceQualificationError:
        raise RecoveryValidationError("integrity_qualification_failed") from None
    except SQLAlchemyError:
        raise RecoveryValidationError("validation_database_unavailable") from None
    finally:
        engine.dispose()


def _check_receipt_shape(receipt: Mapping[str, Any]) -> None:
    expected = {
        "attempt_id",
        "backup",
        "checks",
        "contract_version",
        "database",
        "environment_id",
        "environment_key",
        "evidence_digest",
        "expected",
        "observed_at",
        "operator_identity",
        "observed",
        "outcome",
        "provider",
        "reason_code",
        "recovery_id",
        "recovery_method",
        "recovery_target",
        "request_id",
        "target_database_instance_id",
    }
    if set(receipt) != expected:
        raise RecoveryValidationError("recovery_metadata_mismatch")
    if receipt["contract_version"] != RECOVERY_VALIDATION_VERSION:
        raise RecoveryValidationError("recovery_metadata_mismatch")
    for label in (
        "recovery_id",
        "request_id",
        "environment_id",
        "attempt_id",
        "target_database_instance_id",
    ):
        _uuid(str(receipt[label]), label)
    if set(receipt["checks"]) != set(RECOVERY_CHECKS) or any(
        not isinstance(value, bool) for value in receipt["checks"].values()
    ):
        raise RecoveryValidationError("recovery_metadata_mismatch")
    if receipt["outcome"] not in {"passed", "failed"}:
        raise RecoveryValidationError("recovery_metadata_mismatch")
    if receipt["outcome"] == "passed":
        if receipt["reason_code"] != "none" or not all(receipt["checks"].values()):
            raise RecoveryValidationError("recovery_metadata_mismatch")
    elif receipt["reason_code"] not in RECOVERY_FAILURE_CODES:
        raise RecoveryValidationError("recovery_metadata_mismatch")
    if (
        not isinstance(receipt["observed_at"], str)
        or _TIMESTAMP.fullmatch(receipt["observed_at"]) is None
    ):
        raise RecoveryValidationError("recovery_metadata_mismatch")
    _digest(str(receipt["evidence_digest"]), "evidence_digest")
    if receipt["evidence_digest"] != canonical_digest(
        {key: value for key, value in receipt.items() if key != "evidence_digest"}
    ):
        raise RecoveryValidationError("recovery_metadata_mismatch")


@dataclass(frozen=True)
class RecoveryValidationReceipt:
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        _check_receipt_shape(self.payload)

    @property
    def evidence_digest(self) -> str:
        return str(self.payload["evidence_digest"])

    @property
    def passed(self) -> bool:
        return self.payload["outcome"] == "passed"

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)

    def to_bytes(self) -> bytes:
        return canonical_json(self.payload).encode("utf-8")

    def to_json(self) -> str:
        return canonical_json(self.payload)


def build_recovery_validation_receipt(
    expectation: RecoveryExpectation,
    provider: ProviderRestoreEvidence,
    observation: Mapping[str, Any],
) -> RecoveryValidationReceipt:
    """Compare operator expectations with one atomic restored-DB observation."""

    expectation.validate()
    provider.validate()
    try:
        database = dict(observation["database"])
        qualification = dict(observation["qualification"])
        qualification_error = observation.get("qualification_error")
        if qualification_error not in {None, "integrity_qualification_failed"}:
            raise ValueError
        role = dict(observation["role"])
        observed_lsn = _lsn(str(database["observed_lsn"]), "observed_lsn")
        observed_at = str(database["observed_at"])
        if _TIMESTAMP.fullmatch(observed_at) is None:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise RecoveryValidationError("recovery_metadata_mismatch") from None

    checks = {
        "backup_metadata": (
            provider.provider_backup_id == expectation.provider_backup_id
        ),
        "database_identity": (
            database.get("database_name") == expectation.expected_database_name
            and database.get("database_oid") == expectation.expected_database_oid
            and str(database.get("system_identifier"))
            == expectation.expected_system_identifier
        ),
        "environment": bool(expectation.environment_key),
        "fence": (
            qualification.get("fence_event_chain_digest")
            == expectation.expected_fence_digest
            and qualification.get("fence_mode") == expectation.expected_fence_mode
        ),
        "immutable_provenance": (
            qualification.get("immutable_provenance_manifest_digest")
            == expectation.expected_immutable_provenance_digest
        ),
        "integrity_qualification": (
            qualification.get("qualification_digest")
            == expectation.expected_qualification_digest
            and qualification.get("resource_membership_integrity_valid") is True
            and qualification.get("immutable_provenance_integrity_valid") is True
        ),
        "postgres_revision": (
            database.get("server_version_num")
            == expectation.expected_server_version_num
            and database.get("server_version_num", 0) // 10000
            == EXPECTED_POSTGRES_MAJOR
        ),
        "provider_completion": (
            provider.completed
            and provider.provider_contract_version == RECOVERY_PROVIDER_VERSION
            and provider.recovery_method == RECOVERY_METHOD
        ),
        "recovery_metadata": (
            database.get("timeline") == expectation.expected_timeline
            and database.get("in_recovery") is False
        ),
        "recovery_target": (
            provider.requested_lsn == expectation.expected_recovery_lsn
            and _lsn_value(observed_lsn)
            >= _lsn_value(expectation.expected_recovery_lsn)
        ),
        "role_policy": (
            role.get("qualified") is True
            and role.get("privilege_manifest_digest")
            == expectation.expected_role_manifest_digest
        ),
        "runtime_privileges": (
            qualification.get("runtime_privilege_digest")
            == expectation.expected_runtime_privilege_digest
        ),
        "schema_revision": (
            qualification.get("schema_revision")
            == expectation.expected_schema_revision
        ),
        "target_identity": (
            qualification.get("target_identity_digest")
            == expectation.expected_target_identity_digest
        ),
    }
    precedence = (
        ("provider_completion", "provider_completion_failed"),
        ("backup_metadata", "backup_metadata_mismatch"),
        ("recovery_metadata", "recovery_metadata_mismatch"),
        ("environment", "environment_mismatch"),
        ("database_identity", "database_identity_mismatch"),
        ("target_identity", "target_identity_mismatch"),
        ("recovery_target", "recovery_target_mismatch"),
        ("postgres_revision", "postgres_revision_mismatch"),
        ("schema_revision", "schema_revision_mismatch"),
        ("immutable_provenance", "immutable_provenance_mismatch"),
        ("role_policy", "role_policy_mismatch"),
        ("runtime_privileges", "runtime_privilege_mismatch"),
        ("fence", "fence_mismatch"),
        ("integrity_qualification", "integrity_qualification_failed"),
    )
    reason_code = (
        "integrity_qualification_failed"
        if qualification_error is not None
        else next(
            (reason for check, reason in precedence if not checks[check]),
            "none",
        )
    )
    unsigned: dict[str, Any] = {
        "attempt_id": expectation.attempt_id,
        "backup": {
            "artifact_digest": expectation.backup_artifact_digest,
            "artifact_id": expectation.backup_artifact_id,
            "provider_backup_id": expectation.provider_backup_id,
            "restore_artifact_digest": expectation.restore_artifact_digest,
            "restore_artifact_id": expectation.restore_artifact_id,
        },
        "checks": checks,
        "contract_version": RECOVERY_VALIDATION_VERSION,
        "database": {
            "observed_identity_digest": canonical_digest(
                {
                    "database_name": database.get("database_name"),
                    "database_oid": database.get("database_oid"),
                    "system_identifier": str(database.get("system_identifier")),
                }
            ),
            "database_name": database.get("database_name"),
            "database_oid": database.get("database_oid"),
            "in_recovery": database.get("in_recovery"),
            "server_version_num": database.get("server_version_num"),
            "system_identifier": str(database.get("system_identifier")),
            "timeline": database.get("timeline"),
        },
        "environment_id": expectation.environment_id,
        "environment_key": expectation.environment_key,
        "expected": {
            "database_name": expectation.expected_database_name,
            "database_oid": expectation.expected_database_oid,
            "fence_digest": expectation.expected_fence_digest,
            "fence_mode": expectation.expected_fence_mode,
            "immutable_provenance_digest": (
                expectation.expected_immutable_provenance_digest
            ),
            "physical_identity_digest": expectation.expected_physical_identity_digest,
            "qualification_digest": expectation.expected_qualification_digest,
            "role_manifest_digest": expectation.expected_role_manifest_digest,
            "runtime_privilege_digest": expectation.expected_runtime_privilege_digest,
            "safe_database_identity_digest": (
                expectation.expected_database_identity_digest
            ),
            "schema_revision": expectation.expected_schema_revision,
            "server_version_num": expectation.expected_server_version_num,
            "system_identifier": expectation.expected_system_identifier,
            "target_identity_digest": expectation.expected_target_identity_digest,
            "timeline": expectation.expected_timeline,
        },
        "observed": {
            "fence_digest": qualification.get("fence_event_chain_digest"),
            "fence_mode": qualification.get("fence_mode"),
            "immutable_provenance_digest": qualification.get(
                "immutable_provenance_manifest_digest"
            ),
            "immutable_provenance_integrity_valid": qualification.get(
                "immutable_provenance_integrity_valid"
            ),
            "qualification_digest": qualification.get("qualification_digest"),
            "qualification_error": qualification_error,
            "resource_membership_integrity_valid": qualification.get(
                "resource_membership_integrity_valid"
            ),
            "role_manifest_digest": role.get("privilege_manifest_digest"),
            "role_qualification_digest": role.get("qualification_digest"),
            "role_qualified": role.get("qualified"),
            "runtime_privilege_digest": qualification.get(
                "runtime_privilege_digest"
            ),
            "schema_revision": qualification.get("schema_revision"),
            "target_identity_digest": qualification.get("target_identity_digest"),
        },
        "observed_at": observed_at,
        "operator_identity": expectation.operator_identity,
        "outcome": "passed" if reason_code == "none" else "failed",
        "provider": provider.to_dict(),
        "reason_code": reason_code,
        "recovery_id": expectation.recovery_id,
        "recovery_method": RECOVERY_METHOD,
        "recovery_target": {
            "observed_lsn": observed_lsn,
            "requested_lsn": expectation.expected_recovery_lsn,
        },
        "request_id": expectation.request_id,
        "target_database_instance_id": expectation.target_database_instance_id,
    }
    return RecoveryValidationReceipt(
        {**unsigned, "evidence_digest": canonical_digest(unsigned)}
    )


def admit_recovery_validation(
    control_database_url: str,
    receipt: RecoveryValidationReceipt,
    *,
    retries: int = 3,
) -> dict[str, str]:
    """Atomically admit or replay one immutable recovery receipt."""

    try:
        url = make_url(control_database_url)
    except (ArgumentError, TypeError, ValueError):
        raise RecoveryValidationError("validation_database_unavailable") from None
    if url.get_backend_name() != "postgresql":
        raise RecoveryValidationError("validation_database_unavailable")
    engine = create_engine(
        control_database_url,
        poolclass=NullPool,
        hide_parameters=True,
        isolation_level="SERIALIZABLE",
        connect_args={"connect_timeout": 5},
    )
    try:
        for attempt in range(retries):
            try:
                with engine.begin() as connection:
                    row = (
                        connection.execute(
                            text(
                                "SELECT * FROM "
                                "phase5c4_api.admit_recovery_validation_v1(:receipt)"
                            ),
                            {"receipt": receipt.to_bytes()},
                        )
                        .mappings()
                        .one()
                    )
                    result = str(row["result"])
                    evidence_digest = str(row["evidence_digest"])
                    if (
                        result not in {"accepted", "idempotent_replay"}
                        or evidence_digest != receipt.evidence_digest
                    ):
                        raise RecoveryValidationError("recovery_metadata_mismatch")
                    return {
                        "result": result,
                        "evidence_digest": evidence_digest,
                    }
            except DBAPIError as exc:
                sqlstate = str(getattr(exc.orig, "sqlstate", ""))
                if sqlstate in {"40001", "40P01"} and attempt + 1 < retries:
                    continue
                raise RecoveryValidationError("recovery_metadata_mismatch") from None
    finally:
        engine.dispose()
    raise RecoveryValidationError("recovery_metadata_mismatch")


def audit_recovery_validation(
    control_database_url: str,
    recovery_id: str,
) -> RecoveryValidationReceipt:
    _uuid(recovery_id, "recovery_id")
    engine = create_engine(
        control_database_url,
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={"connect_timeout": 5},
    )
    try:
        with engine.connect() as connection:
            document = connection.scalar(
                text(
                    "SELECT phase5c4_api.read_recovery_validation_v1("
                    "CAST(:recovery_id AS uuid))"
                ),
                {"recovery_id": recovery_id},
            )
            if document is None:
                raise RecoveryValidationError("recovery_metadata_mismatch")
            return RecoveryValidationReceipt(
                json.loads(bytes(document).decode("utf-8"))
            )
    except SQLAlchemyError:
        raise RecoveryValidationError("validation_database_unavailable") from None
    finally:
        engine.dispose()
