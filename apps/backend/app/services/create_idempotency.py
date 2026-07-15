from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.create_idempotency import CreateOperationIdempotency


CREATE_IDEMPOTENCY_CONSTRAINT = "uq_create_idempotency_user_operation_request"


class CreateOperationIdempotencyConflictError(ValueError):
    code = "create_idempotency_payload_conflict"
    message = (
        "This create request was already submitted with different details. "
        "Start a new create operation and try again."
    )

    def __init__(self) -> None:
        super().__init__(self.message)

    def detail(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class CreateOperationResultUnavailableError(ValueError):
    code = "create_idempotency_result_unavailable"
    message = (
        "The result of this create request is no longer available. "
        "Start a new create operation if another resource is required."
    )

    def __init__(self) -> None:
        super().__init__(self.message)

    def detail(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def create_fingerprint(
    payload: BaseModel | dict[str, Any] | None,
    *,
    context: dict[str, Any] | None = None,
) -> str:
    if isinstance(payload, BaseModel):
        value: dict[str, Any] = payload.model_dump(
            mode="python", exclude={"client_request_id"}
        )
    else:
        value = dict(payload or {})
        value.pop("client_request_id", None)
    canonical = _canonicalize({"context": context or {}, "payload": value})
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _canonicalize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Enum):
        return _canonicalize(value.value)
    if isinstance(value, dict):
        return {str(key): _canonicalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    return value


def is_create_idempotency_conflict(exc: IntegrityError) -> bool:
    diagnostic = getattr(exc.orig, "diag", None)
    if getattr(diagnostic, "constraint_name", None) == CREATE_IDEMPOTENCY_CONSTRAINT:
        return True
    message = str(exc.orig).lower()
    return (
        "create_operation_idempotency.user_id, "
        "create_operation_idempotency.operation, "
        "create_operation_idempotency.client_request_id"
    ) in message or CREATE_IDEMPOTENCY_CONSTRAINT in message


class CreateIdempotencyCoordinator:
    def __init__(self, db: Session):
        self.db = db

    def find(
        self,
        user_id: UUID,
        operation: str,
        client_request_id: UUID,
        fingerprint: str,
    ) -> CreateOperationIdempotency | None:
        receipt = self.db.scalar(
            select(CreateOperationIdempotency).where(
                CreateOperationIdempotency.user_id == user_id,
                CreateOperationIdempotency.operation == operation,
                CreateOperationIdempotency.client_request_id == client_request_id,
            )
        )
        if receipt is not None and receipt.request_fingerprint != fingerprint:
            raise CreateOperationIdempotencyConflictError()
        return receipt

    def reserve(
        self,
        user_id: UUID,
        operation: str,
        client_request_id: UUID,
        fingerprint: str,
        resource_id: UUID,
    ) -> CreateOperationIdempotency:
        receipt = CreateOperationIdempotency(
            id=uuid4(),
            user_id=user_id,
            operation=operation,
            client_request_id=client_request_id,
            request_fingerprint=fingerprint,
            resource_id=resource_id,
        )
        self.db.add(receipt)
        # Establish the unique reservation before domain work. PostgreSQL makes a
        # concurrent retry wait for this transaction, then either replay its
        # commit or proceed after its rollback.
        self.db.flush()
        return receipt

    @staticmethod
    def complete(
        receipt: CreateOperationIdempotency,
        response_snapshot: dict[str, Any],
    ) -> None:
        receipt.response_snapshot = response_snapshot
        receipt.completed_at = datetime.now(timezone.utc)

    @staticmethod
    def replay_snapshot(receipt: CreateOperationIdempotency) -> dict[str, Any]:
        if receipt.response_snapshot is None or receipt.completed_at is None:
            raise CreateOperationResultUnavailableError()
        return receipt.response_snapshot
