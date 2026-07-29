"""Run the destructive, disposable Phase 5C4 infrastructure qualification."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any
from uuid import uuid4

import urllib3
from minio import Minio
from minio.commonconfig import COMPLIANCE, ENABLED
from minio.error import S3Error
from minio.objectlockconfig import DAYS, ObjectLockConfig
from minio.versioningconfig import VersioningConfig
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.pool import NullPool

from app.operators.phase5c4_infrastructure_qualification import (
    AuthoritativeProviderAdapter,
    DISPOSABLE_CONFIRMATION,
    EVIDENCE_SCHEMA_VERSION,
    InfrastructureQualificationConfig,
    InfrastructureQualificationError,
    LOCAL_PROVIDER_KIND,
    PROJECT_PREFIX,
    PROVIDER_CONTRACT_VERSION,
    ProviderActionRequest,
    ProviderCommandResult,
    ProviderObservation,
    QUALIFICATION_VERSION,
    RecoveryTiming,
    SUMMARY_FILE,
    ScenarioEvidence,
    canonical_timestamp,
    prerequisite_observation,
    write_evidence_bundle,
)
from app.operators.phase5c4_minio import (
    AUDIT_BUCKET,
    DEFAULT_RETENTION_DAYS,
    EVIDENCE_BUCKET,
    Phase5C4MinioAdapter,
    Phase5C4MinioError,
    evidence_object_key,
)
from app.operators.phase5c4_recovery import (
    CommandExecution,
    DockerComposePgBackRestRecoveryProvider,
    RestoreRequest,
)
from app.operators.phase5c_contracts import canonical_json


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parents[1]
BACKUP_BUCKET = "nutrition-5c4-backup-v1"
MAXIMUM_COMMAND_BYTES = 1024 * 1024
CONTROL_TESTS = (
    "tests/test_phase5c4_cutback_control_postgres.py::"
    "test_cutback_lifecycle_replays_converge_to_one_final_authority",
    "tests/test_phase5c4_target_activation_control_postgres.py::"
    "test_execution_authorization_migration_activation_and_emergency_close",
    "tests/test_phase5c4_recovery_qualification_control_postgres.py::"
    "test_v9_qualification_is_cumulative_and_projection_matches_event_head",
    "tests/test_phase5c4_recovery_qualification_control_postgres.py::"
    "test_recovery_snapshot_classifies_mixed_or_unknown_route_fail_closed",
)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes

    @property
    def digest(self) -> str:
        return sha256(self.stdout + b"\0" + self.stderr).hexdigest()


class QualificationRunner:
    def __init__(
        self,
        *,
        config: InfrastructureQualificationConfig,
        environment: dict[str, str],
    ) -> None:
        self.config = config
        self.environment = environment
        self.compose = (
            "docker",
            "compose",
            "--project-name",
            config.project,
            "--file",
            str(config.compose_file),
        )
        self.scenarios: list[ScenarioEvidence] = []
        self.provider_documents: list[dict[str, Any]] = []
        self.started_at = datetime.now(timezone.utc)
        self.failure_detected_at: datetime | None = None
        self.recovery_authorized_at: datetime | None = None
        self.restore_started_at: datetime | None = None
        self.postgres_ready_at: datetime | None = None
        self.provider_ready_at: datetime | None = None
        self.qualification_completed_at: datetime | None = None
        self.latest_durable_at: datetime | None = None
        self.latest_restored_at: datetime | None = None
        self.latest_durable_lsn = ""
        self.restored_lsn = ""
        self.lost_transaction_count = 0
        self.backup_id = ""
        self.restore_target_lsn = ""
        self.protected_root = ""
        self.worm_receipt: dict[str, Any] = {}
        self.control_result: dict[str, Any] = {}
        self.service_versions: dict[str, str] = {}

    def run(self) -> tuple[dict[str, Any], Path, str]:
        self.config.validate_unique_ports()
        self.config.evidence_root.mkdir(mode=0o700, parents=True, exist_ok=False)
        cleanup = {"completed": False, "residual_resources": ["not_attempted"]}
        blocking: BaseException | None = None
        try:
            self._validate_compose()
            self._start_stack()
            self._qualify_provider()
            self._qualify_backup_restore()
            self._qualify_minio()
            self._qualify_control_plane()
        except BaseException as exc:
            blocking = exc
        finally:
            cleanup = self._cleanup()

        completed_at = datetime.now(timezone.utc)
        result = (
            "qualified"
            if blocking is None
            and cleanup["completed"]
            and all(item.status in {"passed", "skipped"} for item in self.scenarios)
            else "failed"
        )
        document = self._build_document(
            completed_at=completed_at,
            cleanup=cleanup,
            result=result,
        )
        summary_path = self.config.evidence_root / SUMMARY_FILE
        digest = write_evidence_bundle(summary_path, document)
        if blocking is not None:
            raise InfrastructureQualificationError(
                f"infrastructure qualification failed; evidence={summary_path}; "
                f"digest={digest}; reason={type(blocking).__name__}"
            ) from None
        if not cleanup["completed"]:
            raise InfrastructureQualificationError(
                f"infrastructure cleanup failed; evidence={summary_path}; digest={digest}"
            )
        return document, summary_path, digest

    def _command(
        self,
        argv: tuple[str, ...] | list[str],
        *,
        timeout: int = 600,
        check: bool = True,
        cwd: Path | None = None,
        environment: dict[str, str] | None = None,
    ) -> CommandResult:
        completed = subprocess.run(
            list(argv),
            cwd=cwd or self.config.repository_root,
            env=environment or self.environment,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
        if len(completed.stdout) > MAXIMUM_COMMAND_BYTES or len(completed.stderr) > (
            MAXIMUM_COMMAND_BYTES
        ):
            raise InfrastructureQualificationError("command output exceeded qualification limit")
        result = CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        if check and result.returncode != 0:
            raise InfrastructureQualificationError(
                f"qualification command failed: {Path(argv[0]).name}"
            )
        return result

    def _record(
        self,
        *,
        name: str,
        started: datetime,
        status: str,
        reason: str,
        evidence: Any,
    ) -> None:
        payload = canonical_json(evidence).encode("ascii")
        self.scenarios.append(
            ScenarioEvidence(
                name=name,
                status=status,
                started_at=canonical_timestamp(started),
                completed_at=canonical_timestamp(datetime.now(timezone.utc)),
                evidence_digest=sha256(payload).hexdigest(),
                reason=reason,
            )
        )

    def _validate_compose(self) -> None:
        started = datetime.now(timezone.utc)
        result = self._command((*self.compose, "config", "--quiet"))
        self._record(
            name="compose_manifest",
            started=started,
            status="passed",
            reason="destructive_scope_validated",
            evidence={"command_digest": result.digest, "project": self.config.project},
        )

    def _start_stack(self) -> None:
        started = datetime.now(timezone.utc)
        self._command(
            (
                *self.compose,
                "up",
                "--detach",
                "--build",
                "--wait",
                "minio",
                "source",
                "route-provider",
                "control",
            ),
            timeout=900,
        )
        versions = {
            "docker": self._command(
                ("docker", "version", "--format", "{{.Server.Version}}")
            ).stdout.decode().strip(),
            "pgbackrest": self._command(
                (*self.compose, "exec", "-T", "source", "pgbackrest", "version")
            ).stdout.decode().strip(),
            "minio": self._command(
                (*self.compose, "exec", "-T", "minio", "minio", "--version")
            ).stdout.decode().splitlines()[0],
            "postgresql": self._command(
                (
                    *self.compose,
                    "exec",
                    "-T",
                    "source",
                    "psql",
                    "-U",
                    "postgres",
                    "-d",
                    "qualification",
                    "-Atc",
                    "SHOW server_version;",
                )
            ).stdout.decode().strip(),
        }
        self.service_versions = versions
        self._record(
            name="environment_startup",
            started=started,
            status="passed",
            reason="all_services_healthy",
            evidence=versions,
        )

    def _provider_engine(self):
        return create_engine(
            "postgresql+psycopg://provider_admin:"
            + self.environment["NUTRITION_PHASE5C4_QUALIFICATION_PROVIDER_PASSWORD"]
            + f"@127.0.0.1:{self.config.provider_port}/provider",
            poolclass=NullPool,
            hide_parameters=True,
        )

    def _provider_observation(self) -> ProviderObservation:
        engine = self._provider_engine()
        try:
            with engine.connect() as connection:
                value = connection.scalar(text("SELECT read_provider_state_v1()"))
            if not isinstance(value, dict):
                raise InfrastructureQualificationError("provider readback was not JSON")
            return ProviderObservation.from_mapping(value)
        finally:
            engine.dispose()

    def _provider_command(
        self,
        request: ProviderActionRequest,
        *,
        fault: str,
        interrupt_after_commit: bool = False,
        restart_after_commit: bool = False,
    ) -> ProviderCommandResult:
        request.validate()
        if fault not in {
            "none",
            "unknown_before_commit",
            "partial_after_commit",
            "conflicting_after_commit",
        }:
            raise InfrastructureQualificationError("provider fault is invalid")
        query = (
            "SELECT apply_provider_operation_v1("
            f"'{request.operation_id}'::uuid,"
            f"'{request.request_digest}',"
            f"'{request.action}',"
            f"'{fault}')::text;"
        )
        result = self._command(
            (
                *self.compose,
                "exec",
                "-T",
                "route-provider",
                "psql",
                "-U",
                "provider_admin",
                "-d",
                "provider",
                "-Atc",
                query,
            ),
            check=False,
        )
        if restart_after_commit:
            self._command((*self.compose, "restart", "route-provider"))
            self._wait_provider()
        return ProviderCommandResult(
            returncode=(124 if interrupt_after_commit else result.returncode),
            output_digest=result.digest,
            output_bytes=len(result.stdout) + len(result.stderr),
            interrupted=interrupt_after_commit,
            conflict=b"provider_operation_conflict" in result.stderr,
        )

    def _wait_provider(self) -> None:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                self._provider_observation()
                return
            except (OperationalError, InfrastructureQualificationError):
                time.sleep(0.25)
        raise InfrastructureQualificationError("provider did not recover after restart")

    def _qualify_provider(self) -> None:
        started = datetime.now(timezone.utc)
        route_request = ProviderActionRequest(
            operation_id=str(uuid4()),
            action="route_source",
            request_digest=sha256(b"route-source-after-lost-ack").hexdigest(),
            expected_route_state="source",
            expected_source_writable=False,
            expected_target_fenced=True,
        )
        route = AuthoritativeProviderAdapter(
            command=lambda request: self._provider_command(
                request,
                fault="none",
                interrupt_after_commit=True,
                restart_after_commit=True,
            ),
            readback=self._provider_observation,
        ).execute(route_request)
        if route.status != "passed" or not route.reconciled_after_interruption:
            raise InfrastructureQualificationError("provider restart did not reconcile")
        self.provider_documents.append(route.to_dict())
        replay = AuthoritativeProviderAdapter(
            command=lambda request: self._provider_command(request, fault="none"),
            readback=self._provider_observation,
        ).execute(route_request)
        if replay.status != "passed":
            raise InfrastructureQualificationError("provider replay did not converge")
        self.provider_documents.append(replay.to_dict())

        changed_route_request = ProviderActionRequest(
            operation_id=route_request.operation_id,
            action=route_request.action,
            request_digest=sha256(b"changed-route-source-replay").hexdigest(),
            expected_route_state="source",
            expected_source_writable=False,
            expected_target_fenced=True,
        )
        changed_replay = AuthoritativeProviderAdapter(
            command=lambda request: self._provider_command(request, fault="none"),
            readback=self._provider_observation,
        ).execute(changed_route_request)
        if (
            changed_replay.status != "failed"
            or changed_replay.reason != "provider_operation_conflict"
        ):
            raise InfrastructureQualificationError(
                "provider changed replay was not rejected"
            )
        self.provider_documents.append(changed_replay.to_dict())

        source_request = ProviderActionRequest(
            operation_id=str(uuid4()),
            action="restore_source",
            request_digest=sha256(b"restore-source-last").hexdigest(),
            expected_route_state="source",
            expected_source_writable=True,
            expected_target_fenced=True,
        )
        restored = AuthoritativeProviderAdapter(
            command=lambda request: self._provider_command(request, fault="none"),
            readback=self._provider_observation,
        ).execute(source_request)
        if restored.status != "passed":
            raise InfrastructureQualificationError("source restoration did not read back")
        self.provider_documents.append(restored.to_dict())

        unknown_request = ProviderActionRequest(
            operation_id=str(uuid4()),
            action="route_target",
            request_digest=sha256(b"provider-unknown-before-commit").hexdigest(),
            expected_route_state="target",
            expected_source_writable=False,
            expected_target_fenced=True,
        )
        unknown = AuthoritativeProviderAdapter(
            command=lambda request: self._provider_command(
                request,
                fault="unknown_before_commit",
                interrupt_after_commit=True,
            ),
            readback=self._provider_observation,
        ).execute(unknown_request)
        if unknown.status != "hold":
            raise InfrastructureQualificationError("unknown provider result did not hold")
        self.provider_documents.append(unknown.to_dict())

        partial_request = ProviderActionRequest(
            operation_id=str(uuid4()),
            action="route_target",
            request_digest=sha256(b"provider-partial-after-commit").hexdigest(),
            expected_route_state="target",
            expected_source_writable=False,
            expected_target_fenced=True,
        )
        partial = AuthoritativeProviderAdapter(
            command=lambda request: self._provider_command(
                request,
                fault="partial_after_commit",
            ),
            readback=self._provider_observation,
        ).execute(partial_request)
        if partial.status != "failed" or partial.reason != "provider_readback_conflict":
            raise InfrastructureQualificationError("partial provider result was accepted")
        self.provider_documents.append(partial.to_dict())

        conflicting_request = ProviderActionRequest(
            operation_id=str(uuid4()),
            action="route_target",
            request_digest=sha256(b"provider-conflicting-after-commit").hexdigest(),
            expected_route_state="target",
            expected_source_writable=False,
            expected_target_fenced=True,
        )
        conflicting = AuthoritativeProviderAdapter(
            command=lambda request: self._provider_command(
                request,
                fault="conflicting_after_commit",
            ),
            readback=self._provider_observation,
        ).execute(conflicting_request)
        if (
            conflicting.status != "failed"
            or conflicting.reason != "provider_readback_conflict"
        ):
            raise InfrastructureQualificationError(
                "conflicting provider result was accepted"
            )
        self.provider_documents.append(conflicting.to_dict())

        target_request = ProviderActionRequest(
            operation_id=str(uuid4()),
            action="route_target",
            request_digest=sha256(b"provider-later-authoritative-success").hexdigest(),
            expected_route_state="target",
            expected_source_writable=False,
            expected_target_fenced=True,
        )
        target = AuthoritativeProviderAdapter(
            command=lambda request: self._provider_command(request, fault="none"),
            readback=self._provider_observation,
        ).execute(target_request)
        if target.status != "passed":
            raise InfrastructureQualificationError("later provider success did not reconcile")
        self.provider_documents.append(target.to_dict())

        conflicting_fence_request = ProviderActionRequest(
            operation_id=str(uuid4()),
            action="fence_target",
            request_digest=sha256(b"provider-conflicting-fence").hexdigest(),
            expected_route_state="target",
            expected_source_writable=False,
            expected_target_fenced=True,
        )
        conflicting_fence = AuthoritativeProviderAdapter(
            command=lambda request: self._provider_command(
                request,
                fault="conflicting_after_commit",
            ),
            readback=self._provider_observation,
        ).execute(conflicting_fence_request)
        if conflicting_fence.status != "failed":
            raise InfrastructureQualificationError("conflicting fence was accepted")
        self.provider_documents.append(conflicting_fence.to_dict())

        fence_request = ProviderActionRequest(
            operation_id=str(uuid4()),
            action="fence_target",
            request_digest=sha256(b"provider-authoritative-fence").hexdigest(),
            expected_route_state="target",
            expected_source_writable=False,
            expected_target_fenced=True,
        )
        fence = AuthoritativeProviderAdapter(
            command=lambda request: self._provider_command(request, fault="none"),
            readback=self._provider_observation,
        ).execute(fence_request)
        if fence.status != "passed":
            raise InfrastructureQualificationError("target fence did not reconcile")
        self.provider_documents.append(fence.to_dict())

        return_request = ProviderActionRequest(
            operation_id=str(uuid4()),
            action="route_source",
            request_digest=sha256(b"provider-final-route-source").hexdigest(),
            expected_route_state="source",
            expected_source_writable=False,
            expected_target_fenced=True,
        )
        returned = AuthoritativeProviderAdapter(
            command=lambda request: self._provider_command(request, fault="none"),
            readback=self._provider_observation,
        ).execute(return_request)
        if returned.status != "passed":
            raise InfrastructureQualificationError("final source route did not reconcile")
        self.provider_documents.append(returned.to_dict())

        final_restore_request = ProviderActionRequest(
            operation_id=str(uuid4()),
            action="restore_source",
            request_digest=sha256(b"provider-final-source-restoration").hexdigest(),
            expected_route_state="source",
            expected_source_writable=True,
            expected_target_fenced=True,
        )
        final_restored = AuthoritativeProviderAdapter(
            command=lambda request: self._provider_command(request, fault="none"),
            readback=self._provider_observation,
        ).execute(final_restore_request)
        if final_restored.status != "passed":
            raise InfrastructureQualificationError(
                "final source restoration did not reconcile"
            )
        self.provider_documents.append(final_restored.to_dict())
        self.provider_ready_at = datetime.now(timezone.utc)
        self._record(
            name="provider_routing_restart",
            started=started,
            status="passed",
            reason="authoritative_readback_and_restart_reconciled",
            evidence={
                "contract_version": PROVIDER_CONTRACT_VERSION,
                "operations": self.provider_documents,
            },
        )

    def _minio_client(self) -> Minio:
        return Minio(
            f"127.0.0.1:{self.config.minio_port}",
            access_key=self.environment[
                "NUTRITION_PHASE5C4_QUALIFICATION_MINIO_USER"
            ],
            secret_key=self.environment[
                "NUTRITION_PHASE5C4_QUALIFICATION_MINIO_PASSWORD"
            ],
            secure=True,
            http_client=urllib3.PoolManager(
                cert_reqs="CERT_REQUIRED",
                ca_certs=str(
                    Path(
                        self.environment[
                            "NUTRITION_PHASE5C4_QUALIFICATION_MINIO_CERTS"
                        ]
                    )
                    / "public.crt"
                ),
                retries=False,
            ),
        )

    def _prepare_buckets(self) -> None:
        client = self._minio_client()
        if not client.bucket_exists(BACKUP_BUCKET):
            client.make_bucket(BACKUP_BUCKET)
        client.set_bucket_versioning(BACKUP_BUCKET, VersioningConfig(ENABLED))
        for bucket in (EVIDENCE_BUCKET, AUDIT_BUCKET):
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket, object_lock=True)
                client.set_object_lock_config(
                    bucket,
                    ObjectLockConfig(COMPLIANCE, DEFAULT_RETENTION_DAYS, DAYS),
                )

    def _source_engine(self):
        return create_engine(
            "postgresql+psycopg://postgres:"
            + self.environment["NUTRITION_PHASE5C4_QUALIFICATION_POSTGRES_PASSWORD"]
            + f"@127.0.0.1:{self.config.source_port}/qualification",
            poolclass=NullPool,
            hide_parameters=True,
        )

    def _restored_engine(self):
        return create_engine(
            "postgresql+psycopg://postgres:"
            + self.environment["NUTRITION_PHASE5C4_QUALIFICATION_POSTGRES_PASSWORD"]
            + f"@127.0.0.1:{self.config.restored_port}/qualification",
            poolclass=NullPool,
            hide_parameters=True,
        )

    def _insert_boundary(self, *, transaction_id: str, digest_seed: bytes) -> tuple[datetime, str]:
        engine = self._source_engine()
        try:
            with engine.begin() as connection:
                committed_at = connection.scalar(
                    text(
                        """
                        INSERT INTO qualification_transactions(
                            transaction_id, category, payload_digest
                        ) VALUES (
                            CAST(:transaction_id AS uuid),
                            'recovery_boundary',
                            :payload_digest
                        )
                        RETURNING committed_at
                        """
                    ),
                    {
                        "transaction_id": transaction_id,
                        "payload_digest": sha256(digest_seed).hexdigest(),
                    },
                )
            with engine.begin() as connection:
                lsn = str(connection.scalar(text("SELECT pg_current_wal_lsn()")))
                connection.execute(text("SELECT pg_switch_wal()"))
            if not isinstance(committed_at, datetime):
                raise InfrastructureQualificationError("database timestamp is unavailable")
            return committed_at, lsn
        finally:
            engine.dispose()


    def _pgbackrest(self, *arguments: str, timeout: int = 600) -> CommandResult:
        return self._command(
            (
                *self.compose,
                "exec",
                "-T",
                "--user",
                "postgres",
                "source",
                "pgbackrest",
                *arguments,
            ),
            timeout=timeout,
        )

    def _enable_wal_archiving(self) -> None:
        for statement in (
            "ALTER SYSTEM SET archive_mode = 'on';",
            (
                "ALTER SYSTEM SET archive_command = "
                "'pgbackrest --stanza=qualification archive-push %p';"
            ),
            "ALTER SYSTEM SET archive_timeout = '5s';",
        ):
            self._command(
                (
                    *self.compose,
                    "exec",
                    "-T",
                    "source",
                    "psql",
                    "-U",
                    "postgres",
                    "-d",
                    "qualification",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-c",
                    statement,
                )
            )
        self._command((*self.compose, "restart", "source"))
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            engine = self._source_engine()
            try:
                with engine.connect() as connection:
                    archive_mode = str(connection.scalar(text("SHOW archive_mode")))
                    archive_command = str(
                        connection.scalar(text("SHOW archive_command"))
                    )
                if archive_mode == "on" and "pgbackrest" in archive_command:
                    return
            except OperationalError:
                time.sleep(0.25)
            finally:
                engine.dispose()
        raise InfrastructureQualificationError("source WAL archiving did not enable")

    def _backup_catalog(self) -> list[dict[str, Any]]:
        result = self._pgbackrest(
            "--stanza=qualification",
            "--output=json",
            "info",
        )
        try:
            value = json.loads(result.stdout)
            backups = [
                backup
                for stanza in value
                for backup in stanza.get("backup", [])
            ]
            if not all(isinstance(backup, dict) for backup in backups):
                raise TypeError
            return backups
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
            raise InfrastructureQualificationError("pgBackRest info was invalid") from None

    def _backup_labels(self) -> list[str]:
        try:
            return [str(backup["label"]) for backup in self._backup_catalog()]
        except KeyError:
            raise InfrastructureQualificationError("pgBackRest label was invalid") from None

    def _wait_restored(self, *, record_primary_ready: bool = True) -> None:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            engine = self._restored_engine()
            try:
                with engine.connect() as connection:
                    connection.scalar(text("SELECT 1"))
                if record_primary_ready:
                    self.postgres_ready_at = datetime.now(timezone.utc)
                return
            except OperationalError:
                time.sleep(0.5)
            finally:
                engine.dispose()
        raise InfrastructureQualificationError("restored PostgreSQL did not become ready")

    def _recovery_provider_command(
        self,
        argv: Sequence[str],
    ) -> CommandExecution:
        result = self._command(
            argv,
            timeout=1800,
            check=False,
        )
        return CommandExecution(
            returncode=result.returncode,
            stdout_digest=sha256(result.stdout).hexdigest(),
            stdout_bytes=len(result.stdout),
            stderr_digest=sha256(result.stderr).hexdigest(),
            stderr_bytes=len(result.stderr),
        )

    def _reset_restored_target(self) -> None:
        self._command(
            (*self.compose, "--profile", "restore", "rm", "--force", "--stop", "restored"),
            check=False,
        )
        volume = f"{self.config.project}_restored_data"
        if not volume.startswith(PROJECT_PREFIX) or not volume.endswith("_restored_data"):
            raise InfrastructureQualificationError("restored volume identity is unsafe")
        removed = self._command(
            ("docker", "volume", "rm", volume),
            check=False,
        )
        if removed.returncode != 0:
            raise InfrastructureQualificationError("restored volume cleanup failed")

    def _restore_with_provider(
        self,
        *,
        label: str,
        target_lsn: str,
    ) -> dict[str, Any]:
        operation_directory = self.config.evidence_root / label
        operation_directory.mkdir(mode=0o700)
        request = RestoreRequest(
            operation_id=str(uuid4()),
            operation_directory=operation_directory,
            compose_file=self.config.compose_file,
            compose_project=self.config.project,
            restore_service="restore-tool",
            postgres_service="restored",
            stanza="qualification",
            provider_backup_id=self.backup_id,
            recovery_target_lsn=target_lsn,
        )
        return DockerComposePgBackRestRecoveryProvider(
            runner=self._recovery_provider_command
        ).restore(request).to_dict()

    def _qualify_backup_restore(self) -> None:
        started = datetime.now(timezone.utc)
        self._prepare_buckets()
        self._pgbackrest("--stanza=qualification", "stanza-create")
        self._enable_wal_archiving()
        self._pgbackrest("--stanza=qualification", "check")
        self._pgbackrest("--stanza=qualification", "--type=full", "backup", timeout=900)
        full_labels = self._backup_labels()
        if not full_labels:
            raise InfrastructureQualificationError("full backup label is unavailable")
        self.backup_id = full_labels[-1]

        restored_id = str(uuid4())
        lost_id = str(uuid4())
        restored_at, restored_lsn = self._insert_boundary(
            transaction_id=restored_id,
            digest_seed=b"restored-boundary",
        )
        self._pgbackrest("--stanza=qualification", "check")
        durable_at, durable_lsn = self._insert_boundary(
            transaction_id=lost_id,
            digest_seed=b"post-target-durable-boundary",
        )
        self._pgbackrest("--stanza=qualification", "check")
        self._pgbackrest("--stanza=qualification", "--type=diff", "backup", timeout=900)
        source = self._source_engine()
        try:
            with source.begin() as connection:
                connection.execute(text("SELECT pg_switch_wal()"))
        finally:
            source.dispose()
        self._pgbackrest("--stanza=qualification", "check")
        labels = self._backup_labels()
        if len(labels) < 2:
            raise InfrastructureQualificationError("differential backup was not recorded")
        try:
            latest_safe_lsn = str(self._backup_catalog()[-1]["lsn"]["stop"])
        except (IndexError, KeyError, TypeError):
            raise InfrastructureQualificationError(
                "differential backup safe LSN was unavailable"
            ) from None
        if re.fullmatch(r"[0-9A-F]+/[0-9A-F]+", latest_safe_lsn) is None:
            raise InfrastructureQualificationError(
                "differential backup safe LSN was invalid"
            )

        source = self._source_engine()
        try:
            with source.connect() as connection:
                self.protected_root = str(
                    connection.scalar(
                        text(
                            "SELECT root_digest FROM "
                            "qualification_protected_roots "
                            "WHERE root_name = 'immutable_history'"
                        )
                    )
                )
        finally:
            source.dispose()

        self.latest_restored_at = restored_at
        self.latest_durable_at = durable_at
        self.latest_durable_lsn = durable_lsn
        self.restore_target_lsn = restored_lsn
        self.lost_transaction_count = 1
        self.failure_detected_at = datetime.now(timezone.utc)
        self._command((*self.compose, "stop", "source"))
        self.recovery_authorized_at = datetime.now(timezone.utc)
        self.restore_started_at = datetime.now(timezone.utc)

        provider_evidence = self._restore_with_provider(
            label="restore-exact-operation",
            target_lsn=restored_lsn,
        )
        self._wait_restored()

        target = self._restored_engine()
        try:
            with target.connect() as connection:
                present = set(
                    str(value)
                    for value in connection.scalars(
                        text(
                            "SELECT transaction_id FROM "
                            "qualification_transactions "
                            "ORDER BY sequence_id"
                        )
                    )
                )
                root = str(
                    connection.scalar(
                        text(
                            "SELECT root_digest FROM "
                            "qualification_protected_roots "
                            "WHERE root_name = 'immutable_history'"
                        )
                    )
                )
                immutable_categories = set(
                    connection.scalars(
                        text(
                            "SELECT category FROM "
                            "qualification_transactions "
                            "WHERE category <> 'recovery_boundary'"
                        )
                    )
                )
                in_recovery = bool(connection.scalar(text("SELECT pg_is_in_recovery()")))
                replay_lsn = connection.scalar(text("SELECT pg_last_wal_replay_lsn()"))
                self.restored_lsn = str(replay_lsn or restored_lsn)
            if restored_id not in present or lost_id in present:
                raise InfrastructureQualificationError("PITR transaction boundary is wrong")
            if root != self.protected_root:
                raise InfrastructureQualificationError("protected root changed after restore")
            if immutable_categories != {
                "control_authority",
                "daily_log_snapshot",
                "ocr_provenance",
                "recipe_revision",
            }:
                raise InfrastructureQualificationError("immutable categories are incomplete")
            if in_recovery:
                raise InfrastructureQualificationError("restored target did not promote")
            try:
                with target.begin() as connection:
                    connection.execute(
                        text(
                            "UPDATE qualification_transactions "
                            "SET payload_digest = repeat('f', 64) "
                            "WHERE transaction_id = CAST(:transaction_id AS uuid)"
                        ),
                        {"transaction_id": restored_id},
                    )
            except DBAPIError:
                pass
            else:
                raise InfrastructureQualificationError("restored target admitted mutation")
        finally:
            target.dispose()

        self._record(
            name="pgbackrest_pitr",
            started=started,
            status="passed",
            reason="exact_lsn_restored_read_only",
            evidence={
                "differential_backup_id": labels[-1],
                "full_backup_id": self.backup_id,
                "lost_transaction_count": self.lost_transaction_count,
                "protected_root": self.protected_root,
                "provider_evidence": provider_evidence,
                "restore_target_lsn": restored_lsn,
            },
        )
        self._qualify_latest_safe_restore(
            restored_id=restored_id,
            durable_id=lost_id,
            durable_lsn=durable_lsn,
            latest_safe_lsn=latest_safe_lsn,
        )
        self._qualify_unreachable_restore(durable_lsn=durable_lsn)

    def _qualify_latest_safe_restore(
        self,
        *,
        restored_id: str,
        durable_id: str,
        durable_lsn: str,
        latest_safe_lsn: str,
    ) -> None:
        started = datetime.now(timezone.utc)
        self._reset_restored_target()
        provider_evidence = self._restore_with_provider(
            label="restore-latest-safe-operation",
            target_lsn=durable_lsn,
        )
        self._wait_restored(record_primary_ready=False)
        target = self._restored_engine()
        try:
            with target.connect() as connection:
                present = set(
                    str(value)
                    for value in connection.scalars(
                        text(
                            "SELECT transaction_id FROM "
                            "qualification_transactions "
                            "ORDER BY sequence_id"
                        )
                    )
                )
                root = str(
                    connection.scalar(
                        text(
                            "SELECT root_digest FROM "
                            "qualification_protected_roots "
                            "WHERE root_name = 'immutable_history'"
                        )
                    )
                )
                in_recovery = bool(connection.scalar(text("SELECT pg_is_in_recovery()")))
            if {restored_id, durable_id} - present:
                raise InfrastructureQualificationError(
                    "latest safe restore lost a durable transaction"
                )
            if root != self.protected_root or in_recovery:
                raise InfrastructureQualificationError(
                    "latest safe restore did not qualify"
                )
        finally:
            target.dispose()
        self._record(
            name="latest_safe_point_restore",
            started=started,
            status="passed",
            reason="latest_durable_lsn_restored",
            evidence={
                "latest_durable_lsn": durable_lsn,
                "repository_backup_stop_lsn": latest_safe_lsn,
                "lost_transaction_count": 0,
                "provider_evidence": provider_evidence,
                "protected_root": self.protected_root,
            },
        )

    def _qualify_unreachable_restore(self, *, durable_lsn: str) -> None:
        started = datetime.now(timezone.utc)
        self._reset_restored_target()
        unreachable_lsn = "FFFFFFFF/FFFFFFF0"
        provider_evidence = self._restore_with_provider(
            label="restore-unreachable-operation",
            target_lsn=unreachable_lsn,
        )
        deadline = time.monotonic() + 15
        observed_recovery = False
        observed_lsn = durable_lsn
        while time.monotonic() < deadline:
            target = self._restored_engine()
            try:
                with target.connect() as connection:
                    observed_recovery = bool(
                        connection.scalar(text("SELECT pg_is_in_recovery()"))
                    )
                    replay_lsn = connection.scalar(
                        text("SELECT pg_last_wal_replay_lsn()")
                    )
                    observed_lsn = str(replay_lsn or durable_lsn)
                if observed_recovery:
                    break
            except OperationalError:
                time.sleep(0.25)
            finally:
                target.dispose()
        logs = self._command(
            (*self.compose, "logs", "--no-color", "restored"),
            check=False,
        )
        unreachable_failure = (
            b"recovery ended before configured recovery target was reached"
            in logs.stdout
        )
        if not observed_recovery and not unreachable_failure:
            raise InfrastructureQualificationError(
                "unreachable recovery target did not fail closed"
            )
        self._record(
            name="unreachable_recovery_target",
            started=started,
            status="passed",
            reason="unreachable_lsn_held_not_promoted",
            evidence={
                "observed_lsn": observed_lsn,
                "postgres_log_digest": logs.digest,
                "provider_evidence": provider_evidence,
                "unreachable_lsn": unreachable_lsn,
            },
        )

    def _qualify_minio(self) -> None:
        started = datetime.now(timezone.utc)
        client = self._minio_client()
        payload = canonical_json(
            {
                "contract_version": QUALIFICATION_VERSION,
                "project_digest": sha256(self.config.project.encode()).hexdigest(),
                "scenario_digests": sorted(item.evidence_digest for item in self.scenarios),
            }
        ).encode("ascii")
        key = evidence_object_key(QUALIFICATION_VERSION, sha256(payload).hexdigest())
        adapter = Phase5C4MinioAdapter(client=client)
        receipt = adapter.deliver(
            bucket=EVIDENCE_BUCKET,
            key=key,
            payload=payload,
        )
        replay_receipt = adapter.deliver(
            bucket=EVIDENCE_BUCKET,
            key=key,
            payload=payload,
        )
        if replay_receipt.object_version != receipt.object_version:
            raise InfrastructureQualificationError(
                "duplicate evidence created a new version"
            )
        try:
            adapter.deliver(
                bucket=EVIDENCE_BUCKET,
                key=key,
                payload=payload + b"\n",
            )
        except Phase5C4MinioError as exc:
            if not exc.terminal:
                raise InfrastructureQualificationError(
                    "conflicting evidence was not terminal"
                ) from None
        else:
            raise InfrastructureQualificationError(
                "conflicting evidence replaced immutable content"
            )
        versions = [
            item
            for item in client.list_objects(
                EVIDENCE_BUCKET,
                prefix=key,
                recursive=True,
                include_version=True,
            )
            if item.object_name == key and not item.is_delete_marker
        ]
        if len(versions) != 1:
            raise InfrastructureQualificationError(
                "immutable evidence version count changed"
            )
        try:
            client.remove_object(
                EVIDENCE_BUCKET,
                key,
                version_id=receipt.object_version,
            )
        except S3Error:
            deletion_refused = True
        else:
            deletion_refused = False
        if not deletion_refused:
            raise InfrastructureQualificationError("COMPLIANCE retention allowed deletion")
        self._command((*self.compose, "restart", "minio"))
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                response = client.get_object(
                    EVIDENCE_BUCKET,
                    key,
                    version_id=receipt.object_version,
                )
                try:
                    observed = response.read()
                finally:
                    response.close()
                    response.release_conn()
                if observed == payload:
                    break
            except Exception:
                time.sleep(0.25)
        else:
            raise InfrastructureQualificationError("locked evidence unavailable after restart")
        self.worm_receipt = {
            "bucket": receipt.bucket,
            "object_key": receipt.object_key,
            "object_version": receipt.object_version,
            "payload_digest": receipt.payload_digest,
            "retain_until": canonical_timestamp(receipt.retain_until),
        }
        self._record(
            name="minio_object_lock_restart",
            started=started,
            status="passed",
            reason="compliance_version_survived_restart",
            evidence=self.worm_receipt,
        )

    def _qualify_control_plane(self) -> None:
        started = datetime.now(timezone.utc)
        control_url = (
            "postgresql+psycopg://nutrition_control_admin:"
            + self.environment["NUTRITION_PHASE5C4_QUALIFICATION_CONTROL_PASSWORD"]
            + f"@127.0.0.1:{self.config.control_port}/nutrition_control_test"
        )
        environment = self.environment.copy()
        environment.update(
            {
                "NUTRITION_TEST_POSTGRES_URL": control_url,
                "REQUIRE_POSTGRES_TESTS": "1",
                "NUTRITION_DEPLOYMENT_MODE": "test",
                "NUTRITION_DATABASE_URL": "sqlite+pysqlite:///:memory:",
            }
        )
        result = self._command(
            (
                sys.executable,
                "-m",
                "pytest",
                "-q",
                *CONTROL_TESTS,
            ),
            cwd=BACKEND_ROOT,
            environment=environment,
            timeout=1200,
            check=False,
        )
        self.control_result = {
            "output_digest": result.digest,
            "returncode": result.returncode,
            "selected_scenarios": list(CONTROL_TESTS),
        }
        if result.returncode != 0:
            raise InfrastructureQualificationError("control-plane infrastructure tests failed")
        self.qualification_completed_at = datetime.now(timezone.utc)
        for name, selected in (
            ("preactivation_cutback_control", CONTROL_TESTS[0]),
            ("target_activation_forward_recovery", CONTROL_TESTS[1]),
            ("cumulative_recovery_projection", CONTROL_TESTS[2]),
            ("mixed_route_fail_closed", CONTROL_TESTS[3]),
        ):
            self._record(
                name=name,
                started=started,
                status="passed",
                reason="postgresql_authority_contract_passed",
                evidence={
                    "output_digest": result.digest,
                    "selected_scenario": selected,
                },
            )
        self._record(
            name="postgresql_control_authority",
            started=started,
            status="passed",
            reason="cutback_activation_recovery_contracts_passed",
            evidence=self.control_result,
        )

    def _cleanup(self) -> dict[str, Any]:
        result = self._command(
            (
                *self.compose,
                "--profile",
                "restore",
                "--profile",
                "restore-tool",
                "down",
                "--volumes",
                "--remove-orphans",
                "--timeout",
                "30",
            ),
            timeout=180,
            check=False,
        )
        residual = self._command(
            (
                "docker",
                "ps",
                "--all",
                "--quiet",
                "--filter",
                f"label=com.docker.compose.project={self.config.project}",
            ),
            check=False,
        )
        volumes = self._command(
            (
                "docker",
                "volume",
                "ls",
                "--quiet",
                "--filter",
                f"label=com.docker.compose.project={self.config.project}",
            ),
            check=False,
        )
        networks = self._command(
            (
                "docker",
                "network",
                "ls",
                "--quiet",
                "--filter",
                f"label=com.docker.compose.project={self.config.project}",
            ),
            check=False,
        )
        resources = [
            label
            for label, observation in (
                ("containers", residual.stdout),
                ("networks", networks.stdout),
                ("volumes", volumes.stdout),
            )
            if observation.strip()
        ]
        if result.returncode != 0:
            resources.append("compose_down")
        return {
            "completed": not resources,
            "residual_resources": sorted(resources),
        }

    def _build_document(
        self,
        *,
        completed_at: datetime,
        cleanup: dict[str, Any],
        result: str,
    ) -> dict[str, Any]:
        git_commit = self._command(
            ("git", "rev-parse", "HEAD"),
            cwd=self.config.repository_root,
        ).stdout.decode().strip()
        dirty_tree = bool(
            self._command(
                ("git", "status", "--porcelain"),
                cwd=self.config.repository_root,
            ).stdout.strip()
        )
        inventory_path = BACKEND_ROOT / "evidence" / "control-plane-inventory.json"
        inventory_digest = sha256(inventory_path.read_bytes()).hexdigest()
        if (
            self.failure_detected_at is not None
            and self.recovery_authorized_at is not None
            and self.restore_started_at is not None
            and self.postgres_ready_at is not None
            and self.provider_ready_at is not None
            and self.qualification_completed_at is not None
            and self.latest_durable_at is not None
            and self.latest_restored_at is not None
        ):
            measurements = RecoveryTiming(
                failure_detected_at=canonical_timestamp(self.failure_detected_at),
                recovery_authorized_at=canonical_timestamp(self.recovery_authorized_at),
                restore_started_at=canonical_timestamp(self.restore_started_at),
                postgres_ready_at=canonical_timestamp(self.postgres_ready_at),
                provider_ready_at=canonical_timestamp(
                    max(self.provider_ready_at, self.postgres_ready_at)
                ),
                qualification_completed_at=canonical_timestamp(
                    max(
                        self.qualification_completed_at,
                        self.provider_ready_at,
                        self.postgres_ready_at,
                    )
                ),
                first_runtime_write_permitted_at=None,
                latest_durable_transaction_at=canonical_timestamp(
                    self.latest_durable_at
                ),
                latest_restored_transaction_at=canonical_timestamp(
                    self.latest_restored_at
                ),
                latest_durable_lsn=self.latest_durable_lsn,
                restored_lsn=self.restored_lsn or self.restore_target_lsn,
                lost_transaction_count=self.lost_transaction_count,
            ).measurements()
        else:
            measurements = {}
        scenario_names = {item.name for item in self.scenarios}
        skipped = {
            "application_schema_and_domain_restore": (
                "local_physical_fixture_not_application_schema"
            ),
            "control_provider_end_to_end_binding": (
                "provider_and_control_scenarios_not_single_saga"
            ),
            "latest_safe_point_restore": "exact_lsn_restore_exercised_only",
            "unreachable_recovery_target": "bounded_startup_timeout_not_exercised",
            "vendor_routing_certification": "local_provider_semantics_only",
        }
        for name, reason in skipped.items():
            if name not in scenario_names:
                now = canonical_timestamp(completed_at)
                self.scenarios.append(
                    ScenarioEvidence(
                        name=name,
                        status="skipped",
                        started_at=now,
                        completed_at=now,
                        evidence_digest=sha256(reason.encode()).hexdigest(),
                        reason=reason,
                    )
                )
        services = ["control", "minio", "restored", "route-provider", "source"]
        return {
            "cleanup": cleanup,
            "contract_version": QUALIFICATION_VERSION,
            "control": {
                "application_head": "0021_target_activation_execution",
                "control_head": "ops_0011_phase5c4_recovery_audit",
                "inventory_digest": inventory_digest,
                "qualification_test_digest": self.control_result.get("output_digest"),
            },
            "environment": {
                "compose_manifest_digest": sha256(
                    self.config.compose_file.read_bytes()
                ).hexdigest(),
                "minio_policy_digest": sha256(
                    canonical_json(
                        {
                            "lock_mode": "COMPLIANCE",
                            "retention_days": DEFAULT_RETENTION_DAYS,
                            "versioning": "enabled",
                        }
                    ).encode("ascii")
                ).hexdigest(),
                "pgbackrest_configuration_digest": sha256(
                    (
                        self.config.repository_root
                        / "docker"
                        / "phase5c4"
                        / "pgbackrest.conf"
                    ).read_bytes()
                ).hexdigest(),
                "qualifier_script_digest": sha256(
                    Path(__file__).read_bytes()
                ).hexdigest(),
                "provider_kind": LOCAL_PROVIDER_KIND,
                "provider_scope": "local_semantics_only",
                "services": services,
                "versions": self.service_versions,
            },
            "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
            "limitations": sorted(
                {
                    "application_schema_and_domain_restore_not_exercised",
                    "local_container_admin_can_destroy_object_lock_volume",
                    "not_vendor_specific_certification",
                    "provider_control_evidence_not_cross_bound",
                    "production_credentials_and_resources_never_used",
                }
            ),
            "provider": {
                "contract_version": PROVIDER_CONTRACT_VERSION,
                "operations": self.provider_documents,
            },
            "recovery": {
                "backup_id": self.backup_id or None,
                "measurements": measurements,
                "protected_root": self.protected_root or None,
                "protected_root_matches": bool(self.protected_root),
                "restore_target_lsn": self.restore_target_lsn or None,
                "worm_receipt": self.worm_receipt,
            },
            "result": result,
            "run": {
                "completed_at": canonical_timestamp(completed_at),
                "dirty_tree": dirty_tree,
                "git_commit": git_commit,
                "run_id": self.environment["NUTRITION_PHASE5C4_QUALIFICATION_RUN_ID"],
                "started_at": canonical_timestamp(self.started_at),
            },
            "scenarios": [
                item.to_dict()
                for item in sorted(self.scenarios, key=lambda item: item.name)
            ],
        }


def _generated_environment(*, minio_certificates: Path) -> dict[str, str]:
    environment = os.environ.copy()
    if (
        environment.get("NUTRITION_PHASE5C4_QUALIFICATION_CONFIRM")
        != DISPOSABLE_CONFIRMATION
    ):
        raise InfrastructureQualificationError(
            "set NUTRITION_PHASE5C4_QUALIFICATION_CONFIRM="
            + DISPOSABLE_CONFIRMATION
        )
    run_id = str(uuid4())
    environment.setdefault(
        "NUTRITION_PHASE5C4_QUALIFICATION_PROJECT",
        PROJECT_PREFIX + uuid4().hex[:12],
    )
    environment["NUTRITION_PHASE5C4_QUALIFICATION_RUN_ID"] = run_id
    environment["NUTRITION_PHASE5C4_QUALIFICATION_MINIO_CERTS"] = str(
        minio_certificates
    )
    generated = {
        "NUTRITION_PHASE5C4_QUALIFICATION_CONTROL_PASSWORD": secrets.token_urlsafe(32),
        "NUTRITION_PHASE5C4_QUALIFICATION_MINIO_PASSWORD": secrets.token_urlsafe(32),
        "NUTRITION_PHASE5C4_QUALIFICATION_MINIO_USER": "p5c4q" + uuid4().hex[:12],
        "NUTRITION_PHASE5C4_QUALIFICATION_POSTGRES_PASSWORD": secrets.token_urlsafe(32),
        "NUTRITION_PHASE5C4_QUALIFICATION_PROVIDER_PASSWORD": secrets.token_urlsafe(32),
        "NUTRITION_PHASE5C4_QUALIFICATION_REPO_CIPHER": secrets.token_urlsafe(48),
    }
    for name, value in generated.items():
        if name in environment:
            raise InfrastructureQualificationError(
                f"{name} must not reuse a caller-supplied credential"
            )
        environment[name] = value
    return environment


def _generate_minio_certificates(directory: Path) -> None:
    directory.mkdir(mode=0o700)
    private_key = directory / "private.key"
    certificate = directory / "public.crt"
    completed = subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=minio",
            "-addext",
            "subjectAltName=DNS:minio,IP:127.0.0.1",
            "-keyout",
            str(private_key),
            "-out",
            str(certificate),
        ],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise InfrastructureQualificationError(
            "unable to generate disposable MinIO certificate"
        )
    private_key.chmod(0o600)
    certificate.chmod(0o644)


def main() -> None:
    try:
        prerequisites = prerequisite_observation()
        if not prerequisites["available"]:
            raise InfrastructureQualificationError(
                "missing qualification prerequisite: "
                + ",".join(prerequisites["missing"])
            )
        with tempfile.TemporaryDirectory(prefix=PROJECT_PREFIX) as secret_root:
            certificate_directory = Path(secret_root) / "minio-certs"
            _generate_minio_certificates(certificate_directory)
            environment = _generated_environment(
                minio_certificates=certificate_directory
            )
            config = InfrastructureQualificationConfig.from_environment(
                environment,
                repository_root=REPOSITORY_ROOT,
            )
            _document, summary_path, digest = QualificationRunner(
                config=config,
                environment=environment,
            ).run()
            sys.stdout.write(
                canonical_json(
                    {
                        "evidence_digest": digest,
                        "evidence_path": str(summary_path),
                        "result": "qualified",
                    }
                )
                + "\n"
            )
            if not config.retain_evidence:
                shutil.rmtree(config.evidence_root)
    except (InfrastructureQualificationError, OSError) as exc:
        raise SystemExit(f"Phase 5C4 infrastructure qualification failed: {exc}") from None


if __name__ == "__main__":
    main()
