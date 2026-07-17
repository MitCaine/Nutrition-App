"""Bounded MinIO WORM adapter for Stage 5C4.3 evidence and audit bytes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import hashlib
from io import BytesIO
import os
import re
from typing import Any, Protocol

from pydantic import SecretStr

from app.operators.phase5c_contracts import canonical_json, canonical_digest
from app.operators.phase5c4_control_contracts import SINK_RECEIPT_VERSION, utc_timestamp


EVIDENCE_BUCKET = "nutrition-5c4-evidence-v1"
AUDIT_BUCKET = "nutrition-5c4-audit-v1"
DEFAULT_RETENTION_DAYS = 180
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class Phase5C4MinioError(RuntimeError):
    def __init__(self, reason: str, *, retryable: bool = False, terminal: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable
        self.terminal = terminal


@dataclass(frozen=True)
class Phase5C4MinioConfig:
    endpoint: str
    access_key: SecretStr
    secret_key: SecretStr
    secure: bool = True
    region: str | None = None

    @classmethod
    def from_environment(cls) -> "Phase5C4MinioConfig":
        endpoint = os.environ.get("NUTRITION_PHASE5C4_MINIO_ENDPOINT", "")
        access = os.environ.get("NUTRITION_PHASE5C4_MINIO_ACCESS_KEY", "")
        secret = os.environ.get("NUTRITION_PHASE5C4_MINIO_SECRET_KEY", "")
        secure_value = os.environ.get("NUTRITION_PHASE5C4_MINIO_SECURE", "true").lower()
        if (
            not endpoint
            or not access
            or not secret
            or "://" in endpoint
            or "@" in endpoint
            or secure_value not in {"true", "false"}
        ):
            raise Phase5C4MinioError("object_store_unavailable")
        return cls(
            endpoint=endpoint,
            access_key=SecretStr(access),
            secret_key=SecretStr(secret),
            secure=secure_value == "true",
            region=os.environ.get("NUTRITION_PHASE5C4_MINIO_REGION") or None,
        )


class MinioClient(Protocol):
    def get_bucket_versioning(self, bucket_name: str) -> Any: ...
    def get_object_lock_config(self, bucket_name: str) -> Any: ...
    def list_objects(self, bucket_name: str, **kwargs: Any) -> Any: ...
    def get_object(self, bucket_name: str, object_name: str, **kwargs: Any) -> Any: ...
    def get_object_retention(self, bucket_name: str, object_name: str, **kwargs: Any) -> Any: ...
    def put_object(self, bucket_name: str, object_name: str, data: Any, length: int, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class WormReceipt:
    bucket: str
    object_key: str
    object_version: str
    etag: str
    byte_count: int
    payload_digest: str
    lock_mode: str
    retain_until: datetime
    observed_at: datetime

    def payload(self) -> dict[str, Any]:
        unsigned = {
            "bucket": self.bucket,
            "byte_count": self.byte_count,
            "contract_version": SINK_RECEIPT_VERSION,
            "etag": self.etag,
            "lock_mode": self.lock_mode,
            "object_key": self.object_key,
            "object_version": self.object_version,
            "observed_at": utc_timestamp(self.observed_at),
            "payload_digest": self.payload_digest,
            "retain_until": utc_timestamp(self.retain_until),
        }
        return {**unsigned, "receipt_digest": canonical_digest(unsigned)}

    def canonical_bytes(self) -> bytes:
        return canonical_json(self.payload()).encode("utf-8")


def evidence_object_key(artifact_type: str, digest: str) -> str:
    if not artifact_type or len(artifact_type) > 128 or "/" in artifact_type:
        raise Phase5C4MinioError("object_store_mismatch", terminal=True)
    if _DIGEST.fullmatch(digest) is None:
        raise Phase5C4MinioError("object_store_mismatch", terminal=True)
    return f"evidence/v1/{artifact_type}/{digest}.json"


def audit_object_key(environment_id: str, sequence: int, digest: str) -> str:
    from uuid import UUID

    try:
        environment = str(UUID(environment_id))
    except (ValueError, TypeError, AttributeError):
        raise Phase5C4MinioError("object_store_mismatch", terminal=True) from None
    if sequence < 1 or _DIGEST.fullmatch(digest) is None:
        raise Phase5C4MinioError("object_store_mismatch", terminal=True)
    return f"audit/v1/{environment}/{sequence:020d}-{digest}.json"


def _provider_error(exc: Exception) -> Phase5C4MinioError:
    code = str(getattr(exc, "code", ""))
    if code in {
        "RequestTimeout",
        "SlowDown",
        "ServiceUnavailable",
        "InternalError",
        "XMinioServerNotInitialized",
    } or isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return Phase5C4MinioError("object_store_unavailable", retryable=True)
    if code in {"PreconditionFailed", "ConditionalRequestConflict"}:
        return Phase5C4MinioError("object_store_race", retryable=True)
    return Phase5C4MinioError("object_store_mismatch", terminal=True)


class Phase5C4MinioAdapter:
    def __init__(
        self,
        config: Phase5C4MinioConfig | None = None,
        *,
        client: MinioClient | None = None,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ) -> None:
        if retention_days < 1:
            raise Phase5C4MinioError("object_store_mismatch", terminal=True)
        self.config = config
        self.retention_days = retention_days
        if client is None:
            config = config or Phase5C4MinioConfig.from_environment()
            try:
                from minio import Minio
            except ImportError:
                raise Phase5C4MinioError("object_store_unavailable") from None
            client = Minio(
                config.endpoint,
                access_key=config.access_key.get_secret_value(),
                secret_key=config.secret_key.get_secret_value(),
                secure=config.secure,
                region=config.region,
            )
        self.client = client

    def _verify_bucket(self, bucket: str) -> None:
        try:
            versioning = self.client.get_bucket_versioning(bucket)
            status = str(getattr(versioning, "status", "")).lower()
            if status != "enabled":
                raise Phase5C4MinioError("object_store_mismatch", terminal=True)
            lock = self.client.get_object_lock_config(bucket)
            mode = str(getattr(lock, "mode", "")).upper()
            if mode != "COMPLIANCE":
                raise Phase5C4MinioError("object_store_mismatch", terminal=True)
        except Phase5C4MinioError:
            raise
        except Exception as exc:
            raise _provider_error(exc) from None

    def _read_exact(self, bucket: str, key: str, version_id: str) -> bytes:
        response = None
        try:
            response = self.client.get_object(bucket, key, version_id=version_id)
            document = response.read()
            if not isinstance(document, bytes):
                raise Phase5C4MinioError("object_store_mismatch", terminal=True)
            return document
        except Phase5C4MinioError:
            raise
        except Exception as exc:
            raise _provider_error(exc) from None
        finally:
            if response is not None:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
                release = getattr(response, "release_conn", None)
                if callable(release):
                    release()

    def _verify_retention(
        self,
        bucket: str,
        key: str,
        version_id: str,
        minimum: datetime,
    ) -> datetime:
        try:
            retention = self.client.get_object_retention(
                bucket, key, version_id=version_id
            )
            mode = str(getattr(retention, "mode", "")).upper()
            retain_until = getattr(
                retention,
                "retain_until_date",
                getattr(retention, "retain_until", None),
            )
            if mode != "COMPLIANCE" or not isinstance(retain_until, datetime):
                raise Phase5C4MinioError("object_store_mismatch", terminal=True)
            if retain_until.tzinfo is None:
                retain_until = retain_until.replace(tzinfo=timezone.utc)
            retain_until = retain_until.astimezone(timezone.utc)
            if retain_until < minimum:
                raise Phase5C4MinioError("object_store_mismatch", terminal=True)
            return retain_until
        except Phase5C4MinioError:
            raise
        except Exception as exc:
            raise _provider_error(exc) from None

    def _existing_versions(self, bucket: str, key: str) -> list[Any]:
        try:
            versions = [
                item
                for item in self.client.list_objects(
                    bucket,
                    prefix=key,
                    recursive=True,
                    include_version=True,
                )
                if getattr(item, "object_name", None) == key
            ]
        except Exception as exc:
            raise _provider_error(exc) from None
        if any(bool(getattr(item, "is_delete_marker", False)) for item in versions):
            raise Phase5C4MinioError("object_store_mismatch", terminal=True)
        return sorted(versions, key=lambda item: str(getattr(item, "version_id", "")))

    def _reconcile(
        self,
        bucket: str,
        key: str,
        payload: bytes,
        observed_at: datetime,
    ) -> WormReceipt | None:
        versions = self._existing_versions(bucket, key)
        if not versions:
            return None
        expected_digest = hashlib.sha256(payload).hexdigest()
        exact: list[tuple[Any, datetime]] = []
        for item in versions:
            version_id = str(getattr(item, "version_id", ""))
            created_at = getattr(item, "last_modified", None)
            if not version_id or not isinstance(created_at, datetime):
                raise Phase5C4MinioError("object_store_mismatch", terminal=True)
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            created_at = created_at.astimezone(timezone.utc)
            document = self._read_exact(bucket, key, version_id)
            if document != payload:
                raise Phase5C4MinioError("object_store_mismatch", terminal=True)
            required_horizon = created_at + timedelta(days=self.retention_days) - timedelta(
                minutes=1
            )
            retain_until = self._verify_retention(
                bucket, key, version_id, max(observed_at, required_horizon)
            )
            exact.append((item, retain_until))
        item, retain_until = exact[0]
        return WormReceipt(
            bucket=bucket,
            object_key=key,
            object_version=str(item.version_id),
            etag=str(getattr(item, "etag", "")),
            byte_count=len(payload),
            payload_digest=expected_digest,
            lock_mode="COMPLIANCE",
            retain_until=retain_until,
            observed_at=datetime.now(timezone.utc),
        )

    def deliver(self, *, bucket: str, key: str, payload: bytes) -> WormReceipt:
        if bucket not in {EVIDENCE_BUCKET, AUDIT_BUCKET} or not payload:
            raise Phase5C4MinioError("object_store_mismatch", terminal=True)
        self._verify_bucket(bucket)
        now = datetime.now(timezone.utc)
        retain_until = now + timedelta(days=self.retention_days)
        existing = self._reconcile(bucket, key, payload, now)
        if existing is not None:
            return existing
        try:
            private_put = getattr(self.client, "_put_object", None)
            if callable(private_put):
                result = private_put(
                    bucket,
                    key,
                    payload,
                    headers={
                        "Content-MD5": base64.b64encode(
                            hashlib.md5(payload, usedforsecurity=False).digest()
                        ).decode("ascii"),
                        "Content-Type": "application/json",
                        "If-None-Match": "*",
                        "X-Amz-Object-Lock-Mode": "COMPLIANCE",
                        "X-Amz-Object-Lock-Retain-Until-Date": retain_until.isoformat(
                            timespec="seconds"
                        ).replace("+00:00", "Z"),
                    },
                )
            else:
                from minio.commonconfig import COMPLIANCE
                from minio.retention import Retention

                result = self.client.put_object(
                    bucket,
                    key,
                    BytesIO(payload),
                    len(payload),
                    retention=Retention(COMPLIANCE, retain_until),
                )
        except Exception as exc:
            error = _provider_error(exc)
            if error.reason == "object_store_race":
                reconciled = self._reconcile(
                    bucket, key, payload, now
                )
                if reconciled is not None:
                    return reconciled
            raise error from None
        version_id = str(getattr(result, "version_id", ""))
        if not version_id:
            raise Phase5C4MinioError("object_store_mismatch", terminal=True)
        document = self._read_exact(bucket, key, version_id)
        if document != payload:
            raise Phase5C4MinioError("object_store_mismatch", terminal=True)
        verified_until = self._verify_retention(
            bucket, key, version_id, retain_until - timedelta(minutes=1)
        )
        return WormReceipt(
            bucket=bucket,
            object_key=key,
            object_version=version_id,
            etag=str(getattr(result, "etag", "")),
            byte_count=len(payload),
            payload_digest=hashlib.sha256(payload).hexdigest(),
            lock_mode="COMPLIANCE",
            retain_until=verified_until,
            observed_at=datetime.now(timezone.utc),
        )
