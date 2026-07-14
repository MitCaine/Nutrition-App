from __future__ import annotations

import json
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.food import OcrNutritionConfirmationTrace
from app.ocr.confirmation_schemas import (
    OcrNutritionConfirmationRequest,
    TRACE_SCHEMA_VERSION,
)
from app.repositories.food_repository import FoodRepository
from app.services.food_service import FoodService


class OcrConfirmationIdempotencyConflict(ValueError):
    pass


def _fingerprint(payload: OcrNutritionConfirmationRequest) -> str:
    value = payload.model_dump(mode="json", exclude={"client_request_id"})
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class OcrConfirmationService:
    def __init__(self, db: Session):
        self.db = db
        self.foods = FoodRepository(db)

    def _existing(self, user_id: UUID, request_id: UUID) -> OcrNutritionConfirmationTrace | None:
        return self.db.scalars(
            select(OcrNutritionConfirmationTrace).where(
                OcrNutritionConfirmationTrace.user_id == user_id,
                OcrNutritionConfirmationTrace.client_request_id == request_id,
            )
        ).first()

    def confirm(self, user_id: UUID, payload: OcrNutritionConfirmationRequest):
        fingerprint = _fingerprint(payload)
        existing = self._existing(user_id, payload.client_request_id)
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise OcrConfirmationIdempotencyConflict(
                    "This confirmation ID was already used with different values."
                )
            return self.foods.get_required(existing.food_item_id, user_id), existing
        try:
            food = FoodService(self.db).build_manual_food(user_id, payload.food)
            created = self.foods.add(food)
            self._after_food_creation(created)
            trace = OcrNutritionConfirmationTrace(
                id=uuid4(),
                user_id=user_id,
                food_item_id=created.id,
                parser_version=payload.parser_version,
                image_source_type=payload.image_source_type,
                schema_version=TRACE_SCHEMA_VERSION,
                trace_snapshot=payload.trace_snapshot(),
                client_request_id=payload.client_request_id,
                request_fingerprint=fingerprint,
            )
            self.db.add(trace)
            self.db.flush()
            self._after_trace_creation(trace)
            self.db.commit()
            return self.foods.get_required(created.id, user_id), trace
        except IntegrityError:
            self.db.rollback()
            existing = self._existing(user_id, payload.client_request_id)
            if existing is None:
                raise
            if existing.request_fingerprint != fingerprint:
                raise OcrConfirmationIdempotencyConflict(
                    "This confirmation ID was already used with different values."
                )
            return self.foods.get_required(existing.food_item_id, user_id), existing
        except Exception:
            self.db.rollback()
            raise

    def get_trace(self, user_id: UUID, trace_id: UUID) -> OcrNutritionConfirmationTrace:
        trace = self.db.scalars(
            select(OcrNutritionConfirmationTrace).where(
                OcrNutritionConfirmationTrace.id == trace_id,
                OcrNutritionConfirmationTrace.user_id == user_id,
            )
        ).first()
        if trace is None:
            raise LookupError("OCR confirmation trace not found")
        return trace

    def _after_food_creation(self, _food) -> None:
        """Test seam before trace persistence."""

    def _after_trace_creation(self, _trace) -> None:
        """Test seam before the single transaction commits."""
