from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace

import pytest

from app.operators import phase5c_contracts as canonical
from app.operators.phase5c4_minio import (
    EVIDENCE_BUCKET,
    Phase5C4MinioAdapter,
    Phase5C4MinioError,
    audit_object_key,
    evidence_object_key,
)


class Response(BytesIO):
    def __init__(self, value: bytes) -> None:
        super().__init__(value)
        self.released = False

    def release_conn(self) -> None:
        self.released = True


class FakeMinio:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str, str], bytes] = {}
        self.retentions: dict[tuple[str, str, str], datetime] = {}
        self.created_at: dict[tuple[str, str, str], datetime] = {}
        self.put_count = 0
        self.raise_after_put = False
        self.delete_marker = False
        self.lock_mode = "COMPLIANCE"
        self.versioning = "Enabled"
        self.responses: list[Response] = []

    def get_bucket_versioning(self, _bucket: str):
        return SimpleNamespace(status=self.versioning)

    def get_object_lock_config(self, _bucket: str):
        return SimpleNamespace(mode=self.lock_mode)

    def list_objects(self, bucket: str, *, prefix: str, **_kwargs):
        values = [
            SimpleNamespace(
                object_name=key,
                version_id=version,
                etag="etag-" + version,
                is_delete_marker=False,
                last_modified=self.created_at.get(
                    (stored_bucket, key, version), datetime.now(timezone.utc)
                ),
            )
            for stored_bucket, key, version in self.objects
            if stored_bucket == bucket and key == prefix
        ]
        if self.delete_marker:
            values.append(
                SimpleNamespace(
                    object_name=prefix,
                    version_id="delete-marker",
                    etag="",
                    is_delete_marker=True,
                )
            )
        return values

    def get_object(self, bucket: str, key: str, *, version_id: str):
        response = Response(self.objects[(bucket, key, version_id)])
        self.responses.append(response)
        return response

    def get_object_retention(self, bucket: str, key: str, *, version_id: str):
        return SimpleNamespace(
            mode="COMPLIANCE",
            retain_until_date=self.retentions[(bucket, key, version_id)],
        )

    def _put_object(self, bucket: str, key: str, payload: bytes, *, headers: dict):
        assert headers["If-None-Match"] == "*"
        self.put_count += 1
        version = f"version-{self.put_count}"
        self.objects[(bucket, key, version)] = payload
        self.created_at[(bucket, key, version)] = datetime.now(timezone.utc)
        self.retentions[(bucket, key, version)] = datetime.now(timezone.utc) + timedelta(
            days=180
        )
        if self.raise_after_put:
            error = RuntimeError("lost acknowledgement")
            error.code = "PreconditionFailed"  # type: ignore[attr-defined]
            raise error
        return SimpleNamespace(version_id=version, etag="etag-" + version)


def test_deterministic_object_keys() -> None:
    digest = "a" * 64
    assert evidence_object_key("phase5c_promotion_policy_v1", digest) == (
        f"evidence/v1/phase5c_promotion_policy_v1/{digest}.json"
    )
    assert audit_object_key("00000000-0000-0000-0000-000000000001", 7, digest) == (
        "audit/v1/00000000-0000-0000-0000-000000000001/"
        f"00000000000000000007-{digest}.json"
    )


def test_delivery_verifies_exact_version_and_replays_without_put() -> None:
    client = FakeMinio()
    adapter = Phase5C4MinioAdapter(client=client)
    payload = b'{"contract_version":"fixture_v1"}'
    key = evidence_object_key("fixture_v1", canonical.sha256_digest_bytes(payload))
    first = adapter.deliver(bucket=EVIDENCE_BUCKET, key=key, payload=payload)
    second = adapter.deliver(bucket=EVIDENCE_BUCKET, key=key, payload=payload)
    assert first.object_version == second.object_version == "version-1"
    assert client.put_count == 1
    assert all(response.closed and response.released for response in client.responses)
    assert canonical.parse_canonical_json(first.canonical_bytes())["receipt_digest"]


def test_lost_acknowledgement_reconciles_exact_version() -> None:
    client = FakeMinio()
    client.raise_after_put = True
    adapter = Phase5C4MinioAdapter(client=client)
    payload = b'{"fixture":true}'
    key = evidence_object_key("fixture_v1", canonical.sha256_digest_bytes(payload))
    receipt = adapter.deliver(bucket=EVIDENCE_BUCKET, key=key, payload=payload)
    assert receipt.object_version == "version-1"
    assert client.put_count == 1


def test_existing_different_bytes_are_terminal_mismatch_without_put() -> None:
    client = FakeMinio()
    key = evidence_object_key("fixture_v1", "a" * 64)
    client.objects[(EVIDENCE_BUCKET, key, "version-existing")] = b"different"
    client.retentions[(EVIDENCE_BUCKET, key, "version-existing")] = datetime.now(
        timezone.utc
    ) + timedelta(days=180)
    with pytest.raises(Phase5C4MinioError) as rejected:
        Phase5C4MinioAdapter(client=client).deliver(
            bucket=EVIDENCE_BUCKET, key=key, payload=b'{"expected":true}'
        )
    assert rejected.value.terminal is True
    assert client.put_count == 0


def test_delayed_duplicate_uses_original_version_retention_horizon() -> None:
    client = FakeMinio()
    payload = b'{"fixture":"delayed-replay"}'
    key = evidence_object_key("fixture_v1", canonical.sha256_digest_bytes(payload))
    version = "version-existing"
    created_at = datetime.now(timezone.utc) - timedelta(days=30)
    client.objects[(EVIDENCE_BUCKET, key, version)] = payload
    client.created_at[(EVIDENCE_BUCKET, key, version)] = created_at
    client.retentions[(EVIDENCE_BUCKET, key, version)] = created_at + timedelta(days=180)

    receipt = Phase5C4MinioAdapter(client=client).deliver(
        bucket=EVIDENCE_BUCKET, key=key, payload=payload
    )

    assert receipt.object_version == version
    assert client.put_count == 0


def test_existing_exact_version_with_short_original_retention_is_rejected() -> None:
    client = FakeMinio()
    payload = b'{"fixture":"short-retention"}'
    key = evidence_object_key("fixture_v1", canonical.sha256_digest_bytes(payload))
    version = "version-existing"
    created_at = datetime.now(timezone.utc) - timedelta(days=30)
    client.objects[(EVIDENCE_BUCKET, key, version)] = payload
    client.created_at[(EVIDENCE_BUCKET, key, version)] = created_at
    client.retentions[(EVIDENCE_BUCKET, key, version)] = (
        created_at + timedelta(days=180, minutes=-2)
    )

    with pytest.raises(Phase5C4MinioError) as rejected:
        Phase5C4MinioAdapter(client=client).deliver(
            bucket=EVIDENCE_BUCKET, key=key, payload=payload
        )

    assert rejected.value.terminal is True
    assert client.put_count == 0


@pytest.mark.parametrize("tamper", ("delete", "versioning", "lock"))
def test_capability_and_delete_marker_tamper_fail_closed(tamper: str) -> None:
    client = FakeMinio()
    if tamper == "delete":
        client.delete_marker = True
    elif tamper == "versioning":
        client.versioning = "Suspended"
    else:
        client.lock_mode = "GOVERNANCE"
    with pytest.raises(Phase5C4MinioError) as rejected:
        Phase5C4MinioAdapter(client=client).deliver(
            bucket=EVIDENCE_BUCKET,
            key=evidence_object_key("fixture_v1", "a" * 64),
            payload=b'{"fixture":true}',
        )
    assert rejected.value.terminal is True
