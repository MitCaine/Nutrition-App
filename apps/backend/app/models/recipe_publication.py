from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.db.types import GUID


class RecipePublicationRevision(Base):
    __tablename__ = "recipe_publication_revisions"
    __table_args__ = (
        UniqueConstraint(
            "recipe_id", "revision_number", name="uq_recipe_publication_revision_number"
        ),
        UniqueConstraint(
            "id", "recipe_id", "user_id", name="uq_recipe_publication_revision_identity_owner"
        ),
        UniqueConstraint("id", "user_id", name="uq_recipe_publication_revision_identity_user"),
        CheckConstraint(
            "revision_number > 0", name="ck_recipe_publication_revision_number_positive"
        ),
        CheckConstraint(
            "creation_origin IN ('normal_publication', 'explicit_republish', 'legacy_projection_capture')",
            name="ck_recipe_publication_revision_origin",
        ),
        CheckConstraint(
            "provenance_confidence IN ('complete', 'transition_baseline', 'partial', 'ambiguous')",
            name="ck_recipe_publication_revision_provenance",
        ),
        ForeignKeyConstraint(
            ["recipe_id", "user_id"],
            ["recipes.id", "recipes.user_id"],
            name="fk_recipe_publication_revision_recipe_owner",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[UUID] = mapped_column(GUID(), primary_key=True)
    recipe_id: Mapped[UUID] = mapped_column(GUID(), nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    creation_origin: Mapped[str] = mapped_column(Text, nullable=False)
    provenance_confidence: Mapped[str] = mapped_column(Text, nullable=False)
    published_name: Mapped[str] = mapped_column(Text, nullable=False)
    published_notes: Mapped[Optional[str]] = mapped_column(Text)
    # Diagnostic/integrity evidence only. Equality is not request identity and must
    # never be used to deduplicate retries or intentional identical republishes.
    content_digest: Mapped[str] = mapped_column(Text, nullable=False)

    amount_definitions: Mapped[list[RecipePublicationAmountDefinition]] = relationship(
        back_populates="revision",
        order_by="RecipePublicationAmountDefinition.display_order",
        passive_deletes=True,
    )
    nutrients: Mapped[list[RecipePublicationNutrient]] = relationship(
        back_populates="revision",
        order_by="RecipePublicationNutrient.nutrient_id",
        passive_deletes=True,
    )


class RecipePublicationAmountDefinition(Base):
    __tablename__ = "recipe_publication_amount_definitions"
    __table_args__ = (
        UniqueConstraint(
            "id", "revision_id", name="uq_recipe_publication_amount_identity_revision"
        ),
        UniqueConstraint("revision_id", "display_order", name="uq_recipe_publication_amount_order"),
        UniqueConstraint(
            "revision_id",
            "semantic_mode",
            "display_label",
            name="uq_recipe_publication_amount_semantic_label",
        ),
        CheckConstraint(
            "display_order >= 0", name="ck_recipe_publication_amount_order_nonnegative"
        ),
        CheckConstraint(
            "semantic_mode IN ('serving', 'g')",
            name="ck_recipe_publication_amount_semantic_mode",
        ),
        CheckConstraint(
            "(semantic_mode = 'g' AND display_quantity IS NULL AND display_unit = 'g' "
            "AND gram_equivalent IS NULL) OR "
            "(semantic_mode = 'serving' AND display_quantity IS NOT NULL "
            "AND display_quantity > 0)",
            name="ck_recipe_publication_amount_mode_shape",
        ),
        CheckConstraint(
            "gram_equivalent IS NULL OR gram_equivalent > 0",
            name="ck_recipe_publication_amount_grams_positive",
        ),
        Index(
            "uq_recipe_publication_amount_one_gram_mode",
            "revision_id",
            unique=True,
            sqlite_where=text("semantic_mode = 'g'"),
            postgresql_where=text("semantic_mode = 'g'"),
        ),
        Index(
            "uq_recipe_publication_amount_one_default",
            "revision_id",
            unique=True,
            sqlite_where=text("is_default = true"),
            postgresql_where=text("is_default = true"),
        ),
    )

    id: Mapped[UUID] = mapped_column(GUID(), primary_key=True)
    revision_id: Mapped[UUID] = mapped_column(
        GUID(), ForeignKey("recipe_publication_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    display_label: Mapped[str] = mapped_column(Text, nullable=False)
    semantic_mode: Mapped[str] = mapped_column(Text, nullable=False)
    display_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6))
    display_unit: Mapped[str] = mapped_column(Text, nullable=False)
    gram_equivalent: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6))
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    conversion_metadata: Mapped[Optional[dict]] = mapped_column(JSON)

    revision: Mapped[RecipePublicationRevision] = relationship(back_populates="amount_definitions")


class RecipePublicationNutrient(Base):
    __tablename__ = "recipe_publication_nutrients"
    __table_args__ = (
        UniqueConstraint(
            "revision_id",
            "nutrient_id",
            "basis",
            name="uq_recipe_publication_nutrient_identity_basis",
        ),
        CheckConstraint(
            "basis IN ('per_serving', 'per_100g', 'per_gram')",
            name="ck_recipe_publication_nutrient_basis",
        ),
        CheckConstraint(
            "data_status IN ('known', 'estimated', 'unknown', 'zero')",
            name="ck_recipe_publication_nutrient_status",
        ),
        CheckConstraint(
            "(data_status = 'unknown' AND amount IS NULL) OR "
            "(data_status = 'zero' AND amount = 0) OR "
            "(data_status IN ('known', 'estimated') AND amount IS NOT NULL)",
            name="ck_recipe_publication_nutrient_status_amount",
        ),
    )

    id: Mapped[UUID] = mapped_column(GUID(), primary_key=True)
    revision_id: Mapped[UUID] = mapped_column(
        GUID(), ForeignKey("recipe_publication_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    nutrient_id: Mapped[str] = mapped_column(
        Text, ForeignKey("nutrients.id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6))
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    basis: Mapped[str] = mapped_column(Text, nullable=False)
    data_status: Mapped[str] = mapped_column(Text, nullable=False)
    diagnostic_provenance: Mapped[Optional[dict]] = mapped_column(JSON)

    revision: Mapped[RecipePublicationRevision] = relationship(back_populates="nutrients")
