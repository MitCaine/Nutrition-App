from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.nutrients import NUTRIENT_CATALOG
from app.models.target import NutritionTarget
from app.models.user import User, UserProfile
from app.schemas.target import TargetConfigurationUpdate
from app.services.log_service import LogService
from app.targets.comparison import EffectiveTarget, compare_daily_totals
from app.targets.daily_values import (
    FDA_DAILY_VALUE_CATALOG_VERSION,
    FDA_DAILY_VALUE_STANDARD,
    FDA_DAILY_VALUES,
    TARGET_DIRECTION_SEMANTICS_VERSION,
)
from app.targets.estimation import (
    EnergyEstimate,
    estimate_maintenance_calories,
    height_to_cm,
    weight_to_kg,
)

INFORMATIONAL_NOTICE = (
    "Estimated maintenance calories are general informational estimates, not medical advice."
)
MANUAL_TARGET_UNITS = {
    "calories": "kcal",
    "protein": "g",
    "total_carbohydrate": "g",
    "total_fat": "g",
}
VALUE_BOUNDS = {
    "calories": (Decimal("500"), Decimal("10000")),
    "protein": (Decimal("1"), Decimal("1000")),
    "total_carbohydrate": (Decimal("1"), Decimal("1500")),
    "total_fat": (Decimal("1"), Decimal("500")),
}


class TargetDomainError(ValueError):
    def __init__(self, code: str, message: str, field: str | None = None):
        super().__init__(message)
        self.code = code
        self.field = field

    def detail(self) -> dict:
        detail = {"code": self.code, "message": str(self)}
        if self.field:
            detail["field_errors"] = [
                {"field": self.field, "code": self.code, "message": str(self)}
            ]
        return detail


class TargetService:
    def __init__(self, db: Session):
        self.db = db

    def _profile(self, user_id: UUID) -> UserProfile | None:
        return self.db.get(UserProfile, user_id)

    def _overrides(self, user_id: UUID) -> list[NutritionTarget]:
        return list(
            self.db.scalars(
                select(NutritionTarget)
                .where(
                    NutritionTarget.user_id == user_id,
                    NutritionTarget.target_type == "manual_override",
                )
                .order_by(NutritionTarget.nutrient_id)
            )
        )

    def _estimate(self, profile: UserProfile | None, as_of: date) -> EnergyEstimate:
        if profile is None:
            return EnergyEstimate(False, None, reason_code="target_profile_incomplete")
        return estimate_maintenance_calories(
            birth_date=profile.birth_date,
            sex=profile.biological_sex_for_reference_calculations,
            height_cm=profile.height_cm,
            weight_kg=profile.weight_kg,
            activity_level=profile.activity_level,
            context=profile.energy_estimation_context,
            as_of=as_of,
        )

    def _validate_update(self, payload: TargetConfigurationUpdate, as_of: date) -> None:
        profile = payload.profile
        height_cm = height_to_cm(profile.height_cm, profile.height_unit)
        weight_kg = weight_to_kg(profile.weight_kg, profile.weight_unit)
        if profile.birth_date and profile.birth_date > as_of:
            raise TargetDomainError(
                "target_value_out_of_range",
                "Birth date cannot be in the future.",
                "profile.birth_date",
            )
        if profile.birth_date and as_of.year - profile.birth_date.year > 120:
            raise TargetDomainError(
                "target_value_out_of_range",
                "Birth date is outside the supported input range.",
                "profile.birth_date",
            )
        for field, value, minimum, maximum in (
            ("profile.height_cm", height_cm, Decimal("100"), Decimal("250")),
            ("profile.weight_kg", weight_kg, Decimal("30"), Decimal("300")),
        ):
            if value is not None and not minimum <= value <= maximum:
                raise TargetDomainError(
                    "target_value_out_of_range",
                    f"Value must be between {minimum} and {maximum}.",
                    field,
                )
        for nutrient_id, value in payload.manual_overrides.model_dump().items():
            if value is None:
                continue
            minimum, maximum = VALUE_BOUNDS[nutrient_id]
            if not minimum <= value <= maximum:
                raise TargetDomainError(
                    "target_value_out_of_range",
                    f"Value must be between {minimum} and {maximum}.",
                    f"manual_overrides.{nutrient_id}",
                )

    def update(self, user_id: UUID, payload: TargetConfigurationUpdate, as_of: date):
        """Own one serialized Target update transaction for this user."""
        self._validate_update(payload, as_of)
        try:
            self._lock_target_owner(user_id)
            profile = self._profile(user_id)
            if profile is None:
                profile = UserProfile(user_id=user_id)
                self.db.add(profile)
            profile.birth_date = payload.profile.birth_date
            profile.biological_sex_for_reference_calculations = payload.profile.sex_for_equation
            profile.height_cm = height_to_cm(payload.profile.height_cm, payload.profile.height_unit)
            profile.weight_kg = weight_to_kg(payload.profile.weight_kg, payload.profile.weight_unit)
            profile.activity_level = payload.profile.activity_level
            profile.energy_estimation_context = payload.profile.energy_estimation_context

            existing = {item.nutrient_id: item for item in self._overrides(user_id)}
            for nutrient_id, amount in payload.manual_overrides.model_dump().items():
                row = existing.get(nutrient_id)
                if amount is None:
                    if row is not None:
                        self.db.delete(row)
                    continue
                if row is None:
                    row = NutritionTarget(
                        user_id=user_id,
                        target_type="manual_override",
                        nutrient_id=nutrient_id,
                        unit=MANUAL_TARGET_UNITS[nutrient_id],
                        basis="per_day",
                        source="user",
                    )
                    self.db.add(row)
                row.target_amount = amount
            self.db.flush()
            self._after_target_update_flush(user_id)
            self.db.expire_all()
            result = self.configuration(user_id, as_of)
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise

    def reset_override(self, user_id: UUID, nutrient_id: str, as_of: date):
        """Own one serialized Target reset transaction for this user."""
        if nutrient_id not in MANUAL_TARGET_UNITS:
            raise TargetDomainError(
                "target_unit_invalid",
                "This nutrient does not support a personal override.",
                "nutrient_id",
            )
        try:
            self._lock_target_owner(user_id)
            row = self.db.scalars(
                select(NutritionTarget).where(
                    NutritionTarget.user_id == user_id,
                    NutritionTarget.target_type == "manual_override",
                    NutritionTarget.nutrient_id == nutrient_id,
                )
            ).first()
            if row is not None:
                self.db.delete(row)
            self.db.flush()
            self._after_target_reset_flush(user_id, nutrient_id)
            self.db.expire_all()
            result = self.configuration(user_id, as_of)
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise

    def _lock_target_owner(self, user_id: UUID) -> None:
        """Serialize Target rows in User-before-profile/Target lock order."""
        locked_user_id = self.db.scalar(select(User.id).where(User.id == user_id).with_for_update())
        if locked_user_id is None:
            raise LookupError("User not found")
        self._after_target_owner_lock(user_id)

    def _after_target_owner_lock(self, _user_id: UUID) -> None:
        """Test seam after the per-user Target serialization lock."""

    def _after_target_update_flush(self, _user_id: UUID) -> None:
        """Test seam after profile and override changes are flushed."""

    def _after_target_reset_flush(self, _user_id: UUID, _nutrient_id: str) -> None:
        """Test seam after an override reset is flushed."""

    def effective_targets(self, user_id: UUID, as_of: date) -> list[EffectiveTarget]:
        overrides = {item.nutrient_id: item for item in self._overrides(user_id)}
        estimate = self._estimate(self._profile(user_id), as_of)
        daily_values = {item.nutrient_id: item for item in FDA_DAILY_VALUES}
        result = []
        for nutrient in NUTRIENT_CATALOG:
            override = overrides.get(nutrient.id)
            daily_value = daily_values[nutrient.id]
            if override is not None:
                result.append(
                    EffectiveTarget(
                        nutrient.id,
                        override.target_amount,
                        override.unit,
                        "manual_override",
                        "target",
                    )
                )
            elif nutrient.id == "calories" and estimate.available:
                result.append(
                    EffectiveTarget(
                        nutrient.id, estimate.amount, "kcal", "calculated_estimate", "target"
                    )
                )
            elif daily_value.available:
                result.append(
                    EffectiveTarget(
                        nutrient.id,
                        daily_value.amount,
                        daily_value.unit,
                        "daily_value",
                        daily_value.direction,
                        None,
                        daily_value.note_code,
                    )
                )
            else:
                reason = (
                    estimate.reason_code if nutrient.id == "calories" else daily_value.note_code
                )
                result.append(
                    EffectiveTarget(
                        nutrient.id,
                        None,
                        nutrient.default_unit,
                        "unavailable",
                        "unavailable",
                        reason,
                        daily_value.note_code,
                    )
                )
        return result

    def configuration(self, user_id: UUID, as_of: date) -> dict:
        profile = self._profile(user_id)
        estimate = self._estimate(profile, as_of)
        overrides = self._overrides(user_id)
        return {
            "profile": None
            if profile is None
            else {
                "birth_date": profile.birth_date,
                "sex_for_equation": profile.biological_sex_for_reference_calculations,
                "height_cm": profile.height_cm,
                "height_unit": "cm",
                "weight_kg": profile.weight_kg,
                "weight_unit": "kg",
                "activity_level": profile.activity_level,
                "energy_estimation_context": profile.energy_estimation_context,
            },
            "estimated_maintenance_calories": {
                "availability": "available" if estimate.available else "unavailable",
                "amount": estimate.amount,
                "unit": estimate.unit,
                "authority": estimate.authority,
                "reason_code": estimate.reason_code,
                "equation": estimate.equation,
            },
            "manual_overrides": [
                {
                    "nutrient_id": item.nutrient_id,
                    "amount": item.target_amount,
                    "unit": item.unit,
                    "authority": "manual_override",
                    "direction": "target",
                    "reason_code": None,
                    "note_code": None,
                }
                for item in overrides
            ],
            "effective_targets": [item.__dict__ for item in self.effective_targets(user_id, as_of)],
            "daily_value_catalog_version": FDA_DAILY_VALUE_CATALOG_VERSION,
            "daily_value_standard": FDA_DAILY_VALUE_STANDARD,
            "target_direction_semantics_version": TARGET_DIRECTION_SEMANTICS_VERSION,
            "daily_values": [
                {
                    "nutrient_id": item.nutrient_id,
                    "amount": item.amount,
                    "unit": item.unit,
                    "availability": "available" if item.available else "unavailable",
                    "direction": item.direction,
                    "note_code": item.note_code,
                }
                for item in FDA_DAILY_VALUES
            ],
            "limitations": [] if estimate.available else [estimate.reason_code],
            "informational_notice": INFORMATIONAL_NOTICE,
        }

    def daily_comparison(self, user_id: UUID, logged_date: date) -> dict:
        totals = LogService(self.db).daily_summary(user_id, logged_date)
        comparisons = compare_daily_totals(totals, self.effective_targets(user_id, logged_date))
        return {
            "date": logged_date,
            "daily_value_catalog_version": FDA_DAILY_VALUE_CATALOG_VERSION,
            "target_direction_semantics_version": TARGET_DIRECTION_SEMANTICS_VERSION,
            "comparisons": [item.__dict__ for item in comparisons],
        }
