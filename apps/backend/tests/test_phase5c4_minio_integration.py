from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
import ipaddress
import os
from pathlib import Path
import subprocess
import time
from typing import Any
from uuid import uuid4

from minio import Minio
from minio.commonconfig import COMPLIANCE, ENABLED
from minio.error import S3Error
from minio.objectlockconfig import DAYS, ObjectLockConfig
from minio.retention import Retention
import pytest

from app.operators import phase5c_contracts as canonical
from app.operators.phase5c4_minio import (
    AUDIT_BUCKET,
    DEFAULT_RETENTION_DAYS,
    EVIDENCE_BUCKET,
    Phase5C4MinioAdapter,
    Phase5C4MinioError,
    audit_object_key,
    evidence_object_key,
)


pytestmark = pytest.mark.phase5c4_minio
DISPOSABLE_CONFIRMATION = "nutrition_phase5c4_test_only"
BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parents[1]
COMPOSE_FILE = REPOSITORY_ROOT / "docker-compose.phase5c4.yml"


class _LostAcknowledgement(RuntimeError):
    code = "PreconditionFailed"


class _CapturingClient:
    def __init__(self, client: Minio, *, lose_acknowledgement: bool = False) -> None:
        self.client = client
        self.lose_acknowledgement = lose_acknowledgement
        self.put_headers: dict[str, str] | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.client, name)

    def _put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: bytes,
        headers: dict[str, str] | None = None,
        query_params: dict[str, str] | None = None,
    ) -> Any:
        self.put_headers = dict(headers or {})
        result = self.client._put_object(
            bucket_name,
            object_name,
            data,
            headers=headers,
            query_params=query_params,
        )
        if self.lose_acknowledgement:
            raise _LostAcknowledgement("simulated response loss after committed PUT")
        return result


def _loopback_endpoint(value: str) -> tuple[str, int]:
    if not value or "://" in value or "@" in value or "/" in value:
        raise ValueError("invalid endpoint")
    if value.startswith("["):
        closing = value.find("]")
        if closing < 1 or closing + 1 >= len(value) or value[closing + 1] != ":":
            raise ValueError("invalid endpoint")
        host = value[1:closing]
        port_text = value[closing + 2 :]
    else:
        host, separator, port_text = value.rpartition(":")
        if not separator:
            raise ValueError("invalid endpoint")
    try:
        port = int(port_text)
    except ValueError:
        raise ValueError("invalid endpoint") from None
    if not 1 <= port <= 65535:
        raise ValueError("invalid endpoint")
    if host != "localhost":
        try:
            if not ipaddress.ip_address(host).is_loopback:
                raise ValueError("endpoint is not loopback")
        except ValueError as exc:
            if str(exc) == "endpoint is not loopback":
                raise
            raise ValueError("endpoint is not loopback") from None
    return host, port


@pytest.fixture(scope="module")
def minio_client() -> Minio:
    if (
        os.getenv("NUTRITION_PHASE5C4_TEST_MINIO_DISPOSABLE")
        != DISPOSABLE_CONFIRMATION
    ):
        pytest.skip("requires explicit disposable Phase 5C4 MinIO confirmation")
    endpoint = os.getenv("NUTRITION_PHASE5C4_TEST_MINIO_ENDPOINT", "127.0.0.1:59000")
    try:
        _loopback_endpoint(endpoint)
    except ValueError:
        pytest.fail("Phase 5C4 MinIO integration endpoint must be loopback", pytrace=False)
    access_key = os.getenv("NUTRITION_PHASE5C4_TEST_MINIO_ROOT_USER", "")
    secret_key = os.getenv("NUTRITION_PHASE5C4_TEST_MINIO_ROOT_PASSWORD", "")
    if len(access_key) < 3 or len(secret_key) < 8:
        pytest.fail("disposable Phase 5C4 MinIO credentials are missing", pytrace=False)
    client = Minio(
        endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=False,
    )
    try:
        client.list_buckets()
    except Exception:
        pytest.fail("disposable Phase 5C4 MinIO server is unavailable", pytrace=False)
    for bucket in (EVIDENCE_BUCKET, AUDIT_BUCKET):
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket, object_lock=True)
            client.set_object_lock_config(
                bucket,
                ObjectLockConfig(COMPLIANCE, DEFAULT_RETENTION_DAYS, DAYS),
            )
        versioning = client.get_bucket_versioning(bucket)
        lock = client.get_object_lock_config(bucket)
        assert versioning.status == ENABLED
        assert lock.mode == COMPLIANCE
        assert lock.duration == DEFAULT_RETENTION_DAYS
        assert lock.duration_unit == DAYS
    return client


def _versions(client: Minio, bucket: str, key: str) -> list[Any]:
    return [
        item
        for item in client.list_objects(
            bucket,
            prefix=key,
            recursive=True,
            include_version=True,
        )
        if item.object_name == key
    ]


def _read_exact(client: Minio, bucket: str, key: str, version_id: str) -> bytes:
    response = client.get_object(bucket, key, version_id=version_id)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def _payload(label: str) -> bytes:
    return canonical.canonical_json(
        {"contract_version": "phase5c4_minio_test_v1", "label": label, "nonce": uuid4()}
    ).encode("utf-8")


@pytest.mark.parametrize(
    "endpoint",
    ("127.0.0.1:59000", "localhost:59000", "[::1]:59000"),
)
def test_disposable_minio_endpoint_guard_accepts_only_loopback(endpoint: str) -> None:
    assert _loopback_endpoint(endpoint)[1] == 59000
    for rejected in (
        "192.0.2.1:59000",
        "minio.example:59000",
        "http://127.0.0.1:59000",
        "user@127.0.0.1:59000",
        "127.0.0.1:59000/path",
    ):
        with pytest.raises(ValueError):
            _loopback_endpoint(rejected)


def test_disposable_compose_pins_image_and_requires_credentials() -> None:
    compose = COMPOSE_FILE.read_text(encoding="utf-8")
    assert (
        "minio/minio:RELEASE.2025-09-07T16-13-09Z@sha256:"
        "14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e"
        in compose
    )
    assert "NUTRITION_PHASE5C4_TEST_MINIO_ROOT_USER:?" in compose
    assert "NUTRITION_PHASE5C4_TEST_MINIO_ROOT_PASSWORD:?" in compose
    assert '"127.0.0.1:${NUTRITION_PHASE5C4_TEST_MINIO_PORT:-59000}:9000"' in compose
    assert "minioadmin" not in compose


def test_real_minio_capabilities_and_exact_evidence_delivery(
    minio_client: Minio,
) -> None:
    payload = _payload("exact-evidence")
    key = evidence_object_key(
        "phase5c4_minio_test_v1", canonical.sha256_digest_bytes(payload)
    )
    capturing = _CapturingClient(minio_client)
    receipt = Phase5C4MinioAdapter(client=capturing).deliver(
        bucket=EVIDENCE_BUCKET,
        key=key,
        payload=payload,
    )

    assert receipt.object_version
    assert receipt.payload_digest == canonical.sha256_digest_bytes(payload)
    assert _read_exact(minio_client, EVIDENCE_BUCKET, key, receipt.object_version) == payload
    retention = minio_client.get_object_retention(
        EVIDENCE_BUCKET,
        key,
        version_id=receipt.object_version,
    )
    assert retention.mode == COMPLIANCE
    assert capturing.put_headers is not None
    assert capturing.put_headers["If-None-Match"] == "*"
    expected_retention = datetime.fromisoformat(
        capturing.put_headers["X-Amz-Object-Lock-Retain-Until-Date"].replace("Z", "+00:00")
    )
    assert retention.retain_until_date == expected_retention
    assert receipt.retain_until == expected_retention


def test_real_minio_audit_delivery_and_duplicate_do_not_create_new_versions(
    minio_client: Minio,
) -> None:
    payload = _payload("audit-duplicate")
    key = audit_object_key(str(uuid4()), 1, canonical.sha256_digest_bytes(payload))
    adapter = Phase5C4MinioAdapter(client=minio_client)

    first = adapter.deliver(bucket=AUDIT_BUCKET, key=key, payload=payload)
    versions_after_first = _versions(minio_client, AUDIT_BUCKET, key)
    second = adapter.deliver(bucket=AUDIT_BUCKET, key=key, payload=payload)
    versions_after_second = _versions(minio_client, AUDIT_BUCKET, key)

    assert first.object_version == second.object_version
    assert len(versions_after_first) == len(versions_after_second) == 1
    assert _read_exact(minio_client, AUDIT_BUCKET, key, second.object_version) == payload


def test_real_minio_lost_acknowledgement_reconciles_committed_version(
    minio_client: Minio,
) -> None:
    payload = _payload("lost-acknowledgement")
    key = evidence_object_key(
        "phase5c4_minio_test_v1", canonical.sha256_digest_bytes(payload)
    )
    receipt = Phase5C4MinioAdapter(
        client=_CapturingClient(minio_client, lose_acknowledgement=True)
    ).deliver(bucket=EVIDENCE_BUCKET, key=key, payload=payload)

    assert len(_versions(minio_client, EVIDENCE_BUCKET, key)) == 1
    assert _read_exact(minio_client, EVIDENCE_BUCKET, key, receipt.object_version) == payload


def test_real_minio_different_bytes_are_terminal_without_an_adapter_overwrite(
    minio_client: Minio,
) -> None:
    expected = _payload("expected")
    different = _payload("different")
    key = evidence_object_key(
        "phase5c4_minio_test_v1", canonical.sha256_digest_bytes(expected)
    )
    injected = minio_client.put_object(
        EVIDENCE_BUCKET,
        key,
        BytesIO(different),
        len(different),
        retention=Retention(
            COMPLIANCE,
            datetime.now(timezone.utc) + timedelta(days=DEFAULT_RETENTION_DAYS),
        ),
    )
    assert injected.version_id

    with pytest.raises(Phase5C4MinioError) as rejected:
        Phase5C4MinioAdapter(client=minio_client).deliver(
            bucket=EVIDENCE_BUCKET,
            key=key,
            payload=expected,
        )
    assert rejected.value.terminal is True
    assert len(_versions(minio_client, EVIDENCE_BUCKET, key)) == 1


def test_real_minio_compliance_locked_version_cannot_be_deleted(
    minio_client: Minio,
) -> None:
    payload = _payload("delete-denial")
    key = evidence_object_key(
        "phase5c4_minio_test_v1", canonical.sha256_digest_bytes(payload)
    )
    receipt = Phase5C4MinioAdapter(client=minio_client).deliver(
        bucket=EVIDENCE_BUCKET,
        key=key,
        payload=payload,
    )

    with pytest.raises(S3Error):
        minio_client.remove_object(
            EVIDENCE_BUCKET,
            key,
            version_id=receipt.object_version,
        )
    assert _read_exact(minio_client, EVIDENCE_BUCKET, key, receipt.object_version) == payload


@pytest.mark.phase5c4_docker_integration
def test_docker_minio_restart_preserves_exact_locked_version(
    minio_client: Minio,
) -> None:
    if (
        os.getenv("NUTRITION_PHASE5C4_TEST_DOCKER_RESTART")
        != DISPOSABLE_CONFIRMATION
    ):
        pytest.skip("requires explicit disposable Phase 5C4 Docker restart confirmation")
    payload = _payload("docker-restart")
    key = evidence_object_key(
        "phase5c4_minio_test_v1", canonical.sha256_digest_bytes(payload)
    )
    receipt = Phase5C4MinioAdapter(client=minio_client).deliver(
        bucket=EVIDENCE_BUCKET,
        key=key,
        payload=payload,
    )

    environment = os.environ.copy()
    restarted = subprocess.run(
        [
            "docker",
            "compose",
            "-p",
            "nutrition-5c4-evidence",
            "-f",
            str(COMPOSE_FILE),
            "--profile",
            "phase5c4-evidence",
            "restart",
            "minio",
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert restarted.returncode == 0
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if minio_client.bucket_exists(EVIDENCE_BUCKET):
                break
        except Exception:
            time.sleep(0.25)
    else:
        pytest.fail("disposable MinIO did not become ready after restart", pytrace=False)

    assert _read_exact(minio_client, EVIDENCE_BUCKET, key, receipt.object_version) == payload
    retention = minio_client.get_object_retention(
        EVIDENCE_BUCKET,
        key,
        version_id=receipt.object_version,
    )
    assert retention.mode == COMPLIANCE
    assert retention.retain_until_date == receipt.retain_until
