from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.nutrients import NUTRIENT_CATALOG
from app.models.target import NutritionTarget
from app.models.user import User, UserProfile
from app.schemas.target import TargetConfigurationUpdate
from app.services.calendar_service import CalendarService
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
from app.targets.dri import DriRecommendation, resolve_dri_recommendation
from app.targets.dri_data import (
    DRI_DATASET_VERSION,
    DRI_NO_GOAL,
)

INFORMATIONAL_NOTICE = (
    "Estimated maintenance calories are general informational estimates, not medical advice."
)
NUTRIENT_BY_ID = {
    nutrient.id: nutrient
    for nutrient in NUTRIENT_CATALOG
}
MANUAL_TARGET_UNITS = {
    nutrient.id: nutrient.default_unit
    for nutrient in NUTRIENT_CATALOG
}
TARGET_AMOUNT_QUANTUM = Decimal("0.000001")
GENERIC_TARGET_MAX = Decimal("99999999.999999")

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

    def _current_utc_instant(self) -> datetime:
        """Return the UTC instant used to resolve one current Target date."""

        return datetime.now(timezone.utc)

    def _current_target_date(self, user_id: UUID) -> date:
        """Resolve current Target date from owner calendar authority."""

        profile = self._profile(user_id)
        time_zone = (
            "UTC"
            if profile is None or profile.authoritative_time_zone is None
            else profile.authoritative_time_zone
        )
        return CalendarService.today_in_zone(
            time_zone,
            self._current_utc_instant(),
        )

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

    def _preference_rows(
        self,
        user_id: UUID,
    ) -> list[NutritionTarget]:
        return list(
            self.db.scalars(
                select(NutritionTarget)
                .where(
                    NutritionTarget.user_id == user_id,
                    NutritionTarget.target_type
                    == "tracking_preference",
                )
                .order_by(
                    NutritionTarget.nutrient_id
                )
            )
        )

    def _tracking_preferences(
        self,
        user_id: UUID,
    ) -> dict[str, str]:
        result: dict[str, str] = {}

        for row in self._preference_rows(
            user_id
        ):
            nutrient = NUTRIENT_BY_ID.get(
                row.nutrient_id
            )
            metadata = row.target_metadata

            if (
                nutrient is None
                or row.target_amount is not None
                or row.unit
                != nutrient.default_unit
                or row.basis != "tracking"
                or row.source != "user"
                or not isinstance(metadata, dict)
                or metadata.get("mode")
                not in {
                    "amount_only",
                    "ignored",
                }
            ):
                raise RuntimeError(
                    "Stored nutrient tracking "
                    "preference is invalid."
                )

            result[row.nutrient_id] = (
                metadata["mode"]
            )

        return result

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

    @staticmethod
    def _has_target_profile_values(profile: UserProfile | None) -> bool:
        """Distinguish target configuration from a calendar-only profile row."""

        if profile is None:
            return False
        return any(
            value is not None
            for value in (
                profile.birth_date,
                profile.biological_sex_for_reference_calculations,
                profile.height_cm,
                profile.weight_kg,
                profile.activity_level,
            )
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
        manual_values = (
            payload.manual_overrides.model_dump()
        )

        for nutrient_id, value in (
            manual_values.items()
        ):
            nutrient = NUTRIENT_BY_ID.get(
                nutrient_id
            )

            if nutrient is None:
                raise TargetDomainError(
                    "target_nutrient_invalid",
                    "This nutrient is not part of "
                    "the canonical nutrient catalog.",
                    f"manual_overrides.{nutrient_id}",
                )

            if value is None:
                continue

            if value.as_tuple().exponent < -6:
                raise TargetDomainError(
                    "target_value_out_of_range",
                    "Custom targets support at most "
                    "six decimal places.",
                    f"manual_overrides.{nutrient_id}",
                )

            bounds = VALUE_BOUNDS.get(
                nutrient_id
            )

            if bounds is not None:
                minimum, maximum = bounds
                valid = (
                    minimum <= value <= maximum
                )
                message = (
                    "Value must be between "
                    f"{minimum} and {maximum}."
                )
            else:
                valid = (
                    value > 0
                    and value <= GENERIC_TARGET_MAX
                )
                message = (
                    "Value must be greater than zero "
                    f"and no more than "
                    f"{GENERIC_TARGET_MAX}."
                )

            if not valid:
                raise TargetDomainError(
                    "target_value_out_of_range",
                    message,
                    f"manual_overrides.{nutrient_id}",
                )

        preference_values = (
            None
            if payload.tracking_preferences
            is None
            else payload
            .tracking_preferences
            .model_dump()
        )

        if preference_values is not None:
            for nutrient_id in (
                preference_values
            ):
                if nutrient_id not in (
                    NUTRIENT_BY_ID
                ):
                    raise TargetDomainError(
                        "target_nutrient_invalid",
                        "This nutrient is not part "
                        "of the canonical nutrient "
                        "catalog.",
                        "tracking_preferences."
                        f"{nutrient_id}",
                    )

                if (
                    manual_values.get(
                        nutrient_id
                    )
                    is not None
                ):
                    raise TargetDomainError(
                        "target_preference_conflict",
                        "A nutrient cannot use a "
                        "custom target and an "
                        "amount-only or ignored "
                        "preference at the same time.",
                        "tracking_preferences."
                        f"{nutrient_id}",
                    )

    def update(
        self,
        user_id: UUID,
        payload: TargetConfigurationUpdate,
        as_of: date | None = None,
    ):
        """Own one serialized Target update transaction for this user."""

        if as_of is not None:
            self._validate_update(payload, as_of)

        try:
            self._lock_target_owner(user_id)
            effective_as_of = (
                as_of
                if as_of is not None
                else self._current_target_date(user_id)
            )
            if as_of is None:
                self._validate_update(
                    payload,
                    effective_as_of,
                )
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

            existing = {
                item.nutrient_id: item
                for item in self._overrides(
                    user_id
                )
            }
            existing_preferences = {
                item.nutrient_id: item
                for item in self._preference_rows(
                    user_id
                )
            }

            manual_values = (
                payload.manual_overrides
                .model_dump()
            )

            preference_values = (
                None
                if payload.tracking_preferences
                is None
                else payload
                .tracking_preferences
                .model_dump()
            )

            # Manual overrides are patch-like for compatibility
            # with clients that do not know every canonical
            # nutrient.  Explicit null deletes that nutrient's
            # override; an omitted key is left untouched.
            for nutrient_id, amount in (
                manual_values.items()
            ):
                row = existing.get(
                    nutrient_id
                )

                if amount is None:
                    if row is not None:
                        self.db.delete(row)
                    continue

                preference_row = (
                    existing_preferences.get(
                        nutrient_id
                    )
                )
                if preference_row is not None:
                    self.db.delete(
                        preference_row
                    )
                    existing_preferences.pop(
                        nutrient_id,
                        None,
                    )

                if row is None:
                    row = NutritionTarget(
                        user_id=user_id,
                        target_type=(
                            "manual_override"
                        ),
                        nutrient_id=nutrient_id,
                        unit=(
                            MANUAL_TARGET_UNITS[
                                nutrient_id
                            ]
                        ),
                        basis="per_day",
                        source="user",
                    )
                    self.db.add(row)

                row.target_amount = amount
                row.unit = (
                    MANUAL_TARGET_UNITS[
                        nutrient_id
                    ]
                )
                row.basis = "per_day"
                row.source = "user"
                row.target_metadata = None

            # Tracking preferences are replacement state only
            # when the field is supplied.  This lets a new client
            # send {} to restore all nutrients to dynamic defaults,
            # while an older client that omits the field cannot
            # erase preferences it does not understand.
            if preference_values is not None:
                for nutrient_id, row in list(
                    existing_preferences.items()
                ):
                    if (
                        nutrient_id
                        not in preference_values
                    ):
                        self.db.delete(row)

                for nutrient_id, mode in (
                    preference_values.items()
                ):
                    manual_row = existing.get(
                        nutrient_id
                    )
                    if manual_row is not None:
                        self.db.delete(
                            manual_row
                        )

                    row = (
                        existing_preferences.get(
                            nutrient_id
                        )
                    )
                    if row is None:
                        row = NutritionTarget(
                            user_id=user_id,
                            target_type=(
                                "tracking_preference"
                            ),
                            nutrient_id=(
                                nutrient_id
                            ),
                            unit=(
                                MANUAL_TARGET_UNITS[
                                    nutrient_id
                                ]
                            ),
                            basis="tracking",
                            source="user",
                        )
                        self.db.add(row)

                    row.min_amount = None
                    row.target_amount = None
                    row.max_amount = None
                    row.unit = (
                        MANUAL_TARGET_UNITS[
                            nutrient_id
                        ]
                    )
                    row.basis = "tracking"
                    row.source = "user"
                    row.target_metadata = {
                        "mode": mode
                    }

            self.db.flush()
            self._after_target_update_flush(user_id)
            self.db.expire_all()
            result = self.configuration(user_id, effective_as_of)
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise

    def reset_override(
        self,
        user_id: UUID,
        nutrient_id: str,
        as_of: date | None = None,
    ):
        """Own one serialized Target reset transaction for this user."""

        if nutrient_id not in MANUAL_TARGET_UNITS:
            raise TargetDomainError(
                "target_unit_invalid",
                "This nutrient does not support a personal override.",
                "nutrient_id",
            )
        try:
            self._lock_target_owner(user_id)
            effective_as_of = (
                as_of
                if as_of is not None
                else self._current_target_date(user_id)
            )
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
            result = self.configuration(user_id, effective_as_of)
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

    def _dri_recommendations(
        self,
        profile: UserProfile | None,
        as_of: date,
    ) -> list[DriRecommendation]:
        birth_date = None if profile is None else profile.birth_date
        sex = (
            None
            if profile is None
            else profile.biological_sex_for_reference_calculations
        )
        life_stage = (
            "general_adult"
            if profile is None
            else profile.energy_estimation_context
        )
        weight_kg = None if profile is None else profile.weight_kg

        return [
            resolve_dri_recommendation(
                nutrient.id,
                birth_date=birth_date,
                sex=sex,
                life_stage=life_stage,
                weight_kg=weight_kg,
                as_of=as_of,
            )
            for nutrient in NUTRIENT_CATALOG
        ]

    @staticmethod
    def _serialize_dri_recommendation(
        recommendation: DriRecommendation,
    ) -> dict:
        upper_limit = recommendation.upper_limit

        return {
            "nutrient_id": recommendation.nutrient_id,
            "availability": recommendation.availability,
            "amount": (
                None
                if recommendation.amount is None
                else recommendation.amount.quantize(
                    TARGET_AMOUNT_QUANTUM
                )
            ),
            "unit": recommendation.unit,
            "reference_type": recommendation.reference_type,
            "source_version": recommendation.source_version,
            "source_id": recommendation.source_id,
            "age": recommendation.age,
            "sex": recommendation.sex,
            "life_stage": recommendation.life_stage,
            "calculation_basis": recommendation.calculation_basis,
            "weight_kg": recommendation.weight_kg,
            "upper_limit": (
                None
                if upper_limit is None
                else {
                    "amount": upper_limit.amount.quantize(
                        TARGET_AMOUNT_QUANTUM
                    ),
                    "unit": upper_limit.unit,
                    "source_version": upper_limit.source_version,
                    "source_id": upper_limit.source_id,
                    "scope": upper_limit.scope,
                    "comparable_to_recommendation": (
                        upper_limit.comparable_to_recommendation
                    ),
                }
            ),
            "reason_code": recommendation.reason_code,
        }

    def effective_targets(
        self,
        user_id: UUID,
        as_of: date,
    ) -> list[EffectiveTarget]:
        profile = self._profile(user_id)
        overrides = {
            item.nutrient_id: item
            for item in self._overrides(
                user_id
            )
        }
        preferences = (
            self._tracking_preferences(
                user_id
            )
        )
        estimate = self._estimate(
            profile,
            as_of,
        )
        daily_values = {
            item.nutrient_id: item
            for item in FDA_DAILY_VALUES
        }
        dri_values = {
            item.nutrient_id: item
            for item in (
                self._dri_recommendations(
                    profile,
                    as_of,
                )
            )
        }

        result: list[
            EffectiveTarget
        ] = []

        for nutrient in (
            NUTRIENT_CATALOG
        ):
            nutrient_id = nutrient.id
            preference = preferences.get(
                nutrient_id
            )
            override = overrides.get(
                nutrient_id
            )
            daily_value = (
                daily_values[nutrient_id]
            )
            dri = dri_values[nutrient_id]

            if preference == "ignored":
                result.append(
                    EffectiveTarget(
                        nutrient_id,
                        None,
                        nutrient.default_unit,
                        "unavailable",
                        "unavailable",
                        "target_ignored_preference",
                        tracking_mode="ignored",
                    )
                )
                continue

            if preference == "amount_only":
                result.append(
                    EffectiveTarget(
                        nutrient_id,
                        None,
                        nutrient.default_unit,
                        "unavailable",
                        "unavailable",
                        (
                            "target_amount_only_"
                            "preference"
                        ),
                        tracking_mode="amount_only",
                    )
                )
                continue

            if override is not None:
                result.append(
                    EffectiveTarget(
                        nutrient_id,
                        override.target_amount,
                        override.unit,
                        "manual_override",
                        "target",
                        tracking_mode="custom",
                    )
                )
                continue

            if (
                nutrient_id == "calories"
                and estimate.available
            ):
                result.append(
                    EffectiveTarget(
                        nutrient_id,
                        estimate.amount,
                        "kcal",
                        "calculated_estimate",
                        "target",
                        tracking_mode="recommended",
                    )
                )
                continue

            if (
                dri.availability
                == "available"
            ):
                result.append(
                    EffectiveTarget(
                        nutrient_id,
                        (
                            None
                            if dri.amount is None
                            else dri.amount.quantize(
                                TARGET_AMOUNT_QUANTUM
                            )
                        ),
                        (
                            dri.unit
                            or nutrient.default_unit
                        ),
                        "dri",
                        "target",
                        None,
                        None,
                        dri.reference_type,
                        dri.source_version,
                        dri.source_id,
                        dri.calculation_basis,
                        "recommended",
                    )
                )
                continue

            if daily_value.available:
                result.append(
                    EffectiveTarget(
                        nutrient_id,
                        daily_value.amount,
                        daily_value.unit,
                        "daily_value",
                        daily_value.direction,
                        None,
                        daily_value.note_code,
                        tracking_mode="recommended",
                    )
                )
                continue

            # A nutrient that truly has no established DRI
            # recommendation and no FDA reference defaults to
            # neutral amount-only presentation.  A potentially
            # supported DRI that is merely missing profile inputs
            # remains "recommended" but unavailable so the UI can
            # explain that distinction.
            if (
                nutrient_id != "calories"
                and nutrient_id
                in DRI_NO_GOAL
            ):
                result.append(
                    EffectiveTarget(
                        nutrient_id,
                        None,
                        nutrient.default_unit,
                        "unavailable",
                        "unavailable",
                        (
                            "target_reference_"
                            "not_established"
                        ),
                        daily_value.note_code,
                        tracking_mode="amount_only",
                    )
                )
                continue

            reason = (
                estimate.reason_code
                if nutrient_id == "calories"
                else (
                    dri.reason_code
                    or daily_value.note_code
                )
            )

            result.append(
                EffectiveTarget(
                    nutrient_id,
                    None,
                    nutrient.default_unit,
                    "unavailable",
                    "unavailable",
                    reason,
                    daily_value.note_code,
                    tracking_mode="recommended",
                )
            )

        return result

    def configuration(
        self,
        user_id: UUID,
        as_of: date | None = None,
    ) -> dict:
        effective_as_of = (
            as_of
            if as_of is not None
            else self._current_target_date(user_id)
        )
        profile = self._profile(user_id)
        estimate = self._estimate(
            profile,
            effective_as_of,
        )
        overrides = self._overrides(user_id)
        tracking_preferences = (
            self._tracking_preferences(
                user_id
            )
        )
        dri_recommendations = self._dri_recommendations(
            profile,
            effective_as_of,
        )

        return {
            "profile": (
                None
                if not self._has_target_profile_values(profile)
                else {
                    "birth_date": profile.birth_date,
                    "sex_for_equation": (
                        profile.biological_sex_for_reference_calculations
                    ),
                    "height_cm": profile.height_cm,
                    "height_unit": "cm",
                    "weight_kg": profile.weight_kg,
                    "weight_unit": "kg",
                    "activity_level": profile.activity_level,
                    "energy_estimation_context": (
                        profile.energy_estimation_context
                    ),
                }
            ),
            "estimated_maintenance_calories": {
                "availability": (
                    "available"
                    if estimate.available
                    else "unavailable"
                ),
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
                    "reference_type": None,
                    "source_version": None,
                    "source_id": None,
                    "calculation_basis": None,
                    "tracking_mode": "custom",
                }
                for item in overrides
            ],
            "tracking_preferences": (
                tracking_preferences
            ),
            "effective_targets": [
                item.__dict__
                for item in self.effective_targets(
                    user_id,
                    effective_as_of,
                )
            ],
            "daily_value_catalog_version": (
                FDA_DAILY_VALUE_CATALOG_VERSION
            ),
            "daily_value_standard": (
                FDA_DAILY_VALUE_STANDARD
            ),
            "dri_dataset_version": DRI_DATASET_VERSION,
            "target_direction_semantics_version": (
                TARGET_DIRECTION_SEMANTICS_VERSION
            ),
            "daily_values": [
                {
                    "nutrient_id": item.nutrient_id,
                    "amount": item.amount,
                    "unit": item.unit,
                    "availability": (
                        "available"
                        if item.available
                        else "unavailable"
                    ),
                    "direction": item.direction,
                    "note_code": item.note_code,
                }
                for item in FDA_DAILY_VALUES
            ],
            "dri_recommendations": [
                self._serialize_dri_recommendation(
                    recommendation
                )
                for recommendation in dri_recommendations
            ],
            "limitations": (
                []
                if estimate.available
                else [estimate.reason_code]
            ),
            "informational_notice": INFORMATIONAL_NOTICE,
        }

    def daily_comparison(
        self,
        user_id: UUID,
        logged_date: date,
    ) -> dict:
        totals = LogService(self.db).daily_summary(
            user_id,
            logged_date,
        )
        comparisons = compare_daily_totals(
            totals,
            self.effective_targets(
                user_id,
                logged_date,
            ),
        )

        return {
            "date": logged_date,
            "daily_value_catalog_version": (
                FDA_DAILY_VALUE_CATALOG_VERSION
            ),
            "dri_dataset_version": DRI_DATASET_VERSION,
            "target_direction_semantics_version": (
                TARGET_DIRECTION_SEMANTICS_VERSION
            ),
            "comparisons": [
                item.__dict__
                for item in comparisons
            ],
        }
