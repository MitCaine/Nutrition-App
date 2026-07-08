from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.db.types import GUID


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(GUID(), primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    profile: Mapped[Optional["UserProfile"]] = relationship(back_populates="user")


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[UUID] = mapped_column(GUID(), ForeignKey("users.id"), primary_key=True)
    birth_date: Mapped[Optional[date]] = mapped_column(Date)
    height_cm: Mapped[Optional[object]] = mapped_column(Numeric(8, 3))
    weight_kg: Mapped[Optional[object]] = mapped_column(Numeric(8, 3))
    biological_sex_for_reference_calculations: Mapped[Optional[str]] = mapped_column(Text)
    activity_level: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="profile")
