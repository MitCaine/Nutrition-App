from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Nutrient(Base):
    __tablename__ = "nutrients"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text)
    nutrient_kind: Mapped[str] = mapped_column(Text)
    default_unit: Mapped[str] = mapped_column(Text)
    parent_nutrient_id: Mapped[Optional[str]] = mapped_column(Text, ForeignKey("nutrients.id"))
    display_order: Mapped[int] = mapped_column(Integer)
