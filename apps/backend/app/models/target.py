from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, JSON, Numeric, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.db.types import GUID


class NutritionTarget(Base):
    __tablename__ = "nutrition_targets"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "target_type", "nutrient_id", name="uq_nutrition_target_user_type_nutrient"
        ),
    )

    id: Mapped[UUID] = mapped_column(GUID(), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    nutrient_id: Mapped[str] = mapped_column(Text, ForeignKey("nutrients.id"), nullable=False)
    min_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    target_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    max_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    basis: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    target_metadata: Mapped[dict | None] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
