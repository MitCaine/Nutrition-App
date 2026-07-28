"""Narrow control client for Phase 5C4.7b execution authorization."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, DBAPIError, SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.operators.phase5c4_activation_execution import (
    parse_execution_authorization_envelope,
    verify_execution_authorization,
)
from app.operators.phase5c4_authorization import public_key_der_and_id


_T = TypeVar("_T")
_TRANSIENT_SQLSTATES = {"40001", "40P01"}
_PRIMARY_REASONS = {
    "execution_authorization_binding_stale": "execution_authorization_binding_stale",
    "execution_authorization_conflict": "execution_authorization_conflict",
    "execution_authorization_invalid": "execution_authorization_invalid",
    "execution_authorization_key_conflict": "execution_authorization_key_conflict",
    "execution_authorization_key_invalid": "execution_authorization_key_invalid",
    "execution_authorization_key_unknown": "execution_authorization_key_unknown",
    "execution_authorization_key_untrusted": "execution_authorization_key_untrusted",
    "execution_authorization_revoked": "execution_authorization_revoked",
    "execution_authorization_serialization_race": "execution_authorization_retry",
    "execution_authorization_time_invalid": "execution_authorization_time_invalid",
    "phase5c4_control_unauthorized": "execution_authorization_unauthorized",
}


class Phase5C4ExecutionAuthorizationControlError(RuntimeError):
    def __init__(self, reason_code: str, *, retryable: bool = False) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.retryable = retryable


def _validate_url(database_url: str) -> str:
    try:
        url = make_url(database_url)
    except (ArgumentError, TypeError, ValueError):
        raise Phase5C4ExecutionAuthorizationControlError(
            "execution_authorization_database_unavailable",
            retryable=True,
        ) from None
    if url.get_backend_name() != "postgresql":
        raise Phase5C4ExecutionAuthorizationControlError(
            "execution_authorization_database_unavailable",
            retryable=True,
        )
    return database_url


def _engine(database_url: str, *, serializable: bool) -> Engine:
    return create_engine(
        _validate_url(database_url),
        poolclass=NullPool,
        pool_pre_ping=True,
        hide_parameters=True,
        isolation_level="SERIALIZABLE" if serializable else "READ COMMITTED",
        connect_args={"connect_timeout": 5},
    )


def _database_error(
    exc: DBAPIError,
) -> Phase5C4ExecutionAuthorizationControlError:
    sqlstate = str(getattr(exc.orig, "sqlstate", "") or "")
    primary = str(getattr(getattr(exc.orig, "diag", None), "message_primary", ""))
    reason = next(
        (mapped for prefix, mapped in _PRIMARY_REASONS.items() if primary.startswith(prefix)),
        "execution_authorization_internal_failure",
    )
    retryable = sqlstate in _TRANSIENT_SQLSTATES or sqlstate.startswith("08")
    if retryable:
        reason = "execution_authorization_retry"
    elif sqlstate == "42501":
        reason = "execution_authorization_unauthorized"
    return Phase5C4ExecutionAuthorizationControlError(
        reason,
        retryable=retryable,
    )


def _run(
    database_url: str,
    operation: Callable[[Any], _T],
    *,
    serializable: bool = True,
    retries: int = 3,
) -> _T:
    engine = _engine(database_url, serializable=serializable)
    try:
        for attempt in range(retries):
            try:
                with engine.begin() as connection:
                    return operation(connection)
            except DBAPIError as exc:
                error = _database_error(exc)
                if error.retryable and attempt + 1 < retries:
                    continue
                raise error from None
    except Phase5C4ExecutionAuthorizationControlError:
        raise
    except SQLAlchemyError:
        raise Phase5C4ExecutionAuthorizationControlError(
            "execution_authorization_database_unavailable",
            retryable=True,
        ) from None
    finally:
        engine.dispose()
    raise Phase5C4ExecutionAuthorizationControlError(
        "execution_authorization_retry",
        retryable=True,
    )


def read_trusted_execution_public_key(
    database_url: str,
    key_id: str,
) -> dict[str, Any]:
    def operation(connection):
        row = (
            connection.execute(
                text(
                    """
                    SELECT *
                    FROM phase5c4_api.
                        read_execution_authorization_key_v1(:key_id)
                    """
                ),
                {"key_id": key_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise Phase5C4ExecutionAuthorizationControlError("execution_authorization_key_unknown")
        return dict(row)

    return _run(database_url, operation, serializable=False, retries=1)


def verify_execution_with_trust_store(
    database_url: str,
    canonical_bytes: bytes,
) -> dict[str, Any]:
    envelope = parse_execution_authorization_envelope(canonical_bytes)
    key_id = str(envelope["signed"]["key_id"])
    key = read_trusted_execution_public_key(database_url, key_id)
    if (
        key["revoked_at"] is not None
        or key["authority_time"] < key["valid_from"]
        or key["authority_time"] >= key["valid_until"]
    ):
        raise Phase5C4ExecutionAuthorizationControlError("execution_authorization_key_untrusted")
    verified = verify_execution_authorization(
        canonical_bytes,
        bytes(key["public_key_der"]),
    )
    return {
        "authorization_id": str(UUID(verified.envelope["signed"]["payload"]["authorization_id"])),
        "contract_version": str(verified.envelope["signed"]["contract_version"]),
        "envelope_digest": verified.envelope_digest,
        "key_id": verified.key_id,
        "signed_message_digest": verified.signed_message_digest,
        "verified": True,
    }


def verify_and_admit_execution_authorization(
    database_url: str,
    canonical_bytes: bytes,
) -> dict[str, Any]:
    envelope = parse_execution_authorization_envelope(canonical_bytes)
    key_id = str(envelope["signed"]["key_id"])

    def operation(connection):
        key = (
            connection.execute(
                text(
                    """
                    SELECT *
                    FROM phase5c4_api.
                        read_execution_authorization_key_v1(:key_id)
                    """
                ),
                {"key_id": key_id},
            )
            .mappings()
            .one_or_none()
        )
        if key is None:
            raise Phase5C4ExecutionAuthorizationControlError("execution_authorization_key_unknown")
        if (
            key["revoked_at"] is not None
            or key["authority_time"] < key["valid_from"]
            or key["authority_time"] >= key["valid_until"]
        ):
            raise Phase5C4ExecutionAuthorizationControlError(
                "execution_authorization_key_untrusted"
            )
        verified = verify_execution_authorization(
            canonical_bytes,
            bytes(key["public_key_der"]),
        )
        admitted = (
            connection.execute(
                text(
                    """
                    SELECT *
                    FROM phase5c4_api.admit_execution_authorization_v1(
                        :canonical_bytes
                    )
                    """
                ),
                {"canonical_bytes": canonical_bytes},
            )
            .mappings()
            .one()
        )
        return {
            "authorization_id": str(
                UUID(verified.envelope["signed"]["payload"]["authorization_id"])
            ),
            "contract_version": str(verified.envelope["signed"]["contract_version"]),
            "envelope_digest": str(admitted["envelope_digest"]),
            "key_id": verified.key_id,
            "reason": str(admitted["reason"]),
            "result": str(admitted["result"]),
        }

    return _run(database_url, operation)


def bootstrap_execution_authorization_key(
    database_url: str,
    *,
    public_key_der: bytes,
    valid_from: datetime,
    valid_until: datetime,
    bootstrap_reference: str,
) -> dict[str, Any]:
    _, expected_key_id = public_key_der_and_id(public_key_der)

    def operation(connection):
        row = (
            connection.execute(
                text(
                    """
                    SELECT *
                    FROM phase5c4_api.
                        bootstrap_execution_authorization_key_v1(
                            :public_key_der, :valid_from, :valid_until,
                            :bootstrap_reference
                        )
                    """
                ),
                {
                    "public_key_der": public_key_der,
                    "valid_from": valid_from,
                    "valid_until": valid_until,
                    "bootstrap_reference": bootstrap_reference,
                },
            )
            .mappings()
            .one()
        )
        if str(row["key_id"]) != expected_key_id:
            raise Phase5C4ExecutionAuthorizationControlError("execution_authorization_key_invalid")
        return {"key_id": expected_key_id, "result": str(row["result"])}

    return _run(database_url, operation)


def revoke_execution_authorization_key(
    database_url: str,
    *,
    key_id: str,
    reason: str,
    change_reference: str,
) -> dict[str, Any]:
    def operation(connection):
        row = (
            connection.execute(
                text(
                    """
                    SELECT *
                    FROM phase5c4_api.
                        revoke_execution_authorization_key_v1(
                            :key_id, :reason, :change_reference
                        )
                    """
                ),
                {
                    "key_id": key_id,
                    "reason": reason,
                    "change_reference": change_reference,
                },
            )
            .mappings()
            .one()
        )
        return {
            "key_id": key_id,
            "result": str(row["result"]),
            "revoked_at": row["revoked_at"],
        }

    return _run(database_url, operation)


def revoke_execution_authorization(
    database_url: str,
    *,
    authorization_id: str,
    reason: str,
    change_reference: str,
) -> dict[str, Any]:
    canonical_id = str(UUID(authorization_id))

    def operation(connection):
        row = (
            connection.execute(
                text(
                    """
                    SELECT *
                    FROM phase5c4_api.revoke_execution_authorization_v1(
                        CAST(:authorization_id AS uuid),
                        :reason, :change_reference
                    )
                    """
                ),
                {
                    "authorization_id": canonical_id,
                    "reason": reason,
                    "change_reference": change_reference,
                },
            )
            .mappings()
            .one()
        )
        return {
            "authorization_id": canonical_id,
            "result": str(row["result"]),
            "revoked_at": row["revoked_at"],
        }

    return _run(database_url, operation)


def read_execution_authorization_status(
    database_url: str,
    authorization_id: str,
) -> dict[str, Any] | None:
    canonical_id = str(UUID(authorization_id))

    def operation(connection):
        row = (
            connection.execute(
                text(
                    """
                    SELECT *
                    FROM phase5c4_api.read_execution_authorization_v1(
                        CAST(:authorization_id AS uuid)
                    )
                    """
                ),
                {"authorization_id": canonical_id},
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else dict(row)

    return _run(database_url, operation, serializable=False, retries=1)
