from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.db.types import GUID


class CreateOperationIdempotency(Base):
    __tablename__ = "create_operation_idempotency"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "operation",
            "client_request_id",
            name="uq_create_idempotency_user_operation_request",
        ),
        CheckConstraint(
            "(response_snapshot IS NULL AND completed_at IS NULL) OR "
            "(response_snapshot IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_create_idempotency_completion_paired",
        ),
    )

    id: Mapped[UUID] = mapped_column(GUID(), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    client_request_id: Mapped[UUID] = mapped_column(GUID(), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(GUID(), nullable=False)
    response_snapshot: Mapped[dict | None] = mapped_column(JSON)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
