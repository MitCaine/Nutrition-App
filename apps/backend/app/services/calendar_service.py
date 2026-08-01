from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.log import DailyLog
from app.models.user import User, UserProfile


class CalendarDomainError(ValueError):
    """A stable, client-actionable calendar validation failure."""

    def __init__(self, code: str, message: str, field: str | None = None):
        super().__init__(message)
        self.code = code
        self.field = field

    def detail(self) -> dict[str, object]:
        detail: dict[str, object] = {"code": self.code, "message": str(self)}
        if self.field:
            detail["field_errors"] = [
                {"field": self.field, "code": self.code, "message": str(self)}
            ]
        return detail


class AuthoritativeTimeZoneRequiredError(ValueError):
    """Raised when a Daily Log mutation precedes calendar establishment."""

    code = "authoritative_time_zone_required"
    message = "Confirm an authoritative time zone before changing the Daily Log."

    def detail(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class CalendarState:
    """The persisted calendar state exposed to one authenticated owner."""

    is_established: bool
    authoritative_time_zone: str | None
    calendar_revision: int


@dataclass(frozen=True)
class CalendarImpactPreview:
    """Stable, owner-scoped impact data used by the review UI."""

    calendar_revision: int
    current_time_zone: str
    proposed_time_zone: str
    current_today: date
    proposed_today: date
    today_changes: bool
    affected_entries: tuple[DailyLog, ...]

    @property
    def affected_dates(self) -> list[date]:
        return sorted({entry.logged_date for entry in self.affected_entries})

    @property
    def preview_token(self) -> str:
        """Return a deterministic identity for the reviewed consequences.

        The token is intentionally derived from the complete preview rather
        than persisted as a server-side session.  Confirmation can therefore
        prove that the owner reviewed the same dates and affected entries,
        even when those consequences change without a calendar revision.
        """

        payload = {
            "calendar_revision": self.calendar_revision,
            "current_time_zone": self.current_time_zone,
            "proposed_time_zone": self.proposed_time_zone,
            "current_today": self.current_today.isoformat(),
            "proposed_today": self.proposed_today.isoformat(),
            "affected_entries": [
                {
                    "id": str(entry.id),
                    "logged_date": entry.logged_date.isoformat(),
                    "food_name_snapshot": entry.food_name_snapshot,
                    "meal_type": entry.meal_type,
                    "amount_quantity": str(entry.amount_quantity),
                    "amount_unit": entry.amount_unit,
                }
                for entry in self.affected_entries
            ],
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_iana_time_zone(value: str) -> str:
    """Validate and return an IANA time-zone key.

    ``ZoneInfo`` is the standard-library authority for available IANA keys on
    the running service.  No device-local default is substituted when the
    value is absent or invalid.
    """

    if not isinstance(value, str):
        raise CalendarDomainError(
            "invalid_time_zone",
            "Time zone must be an IANA identifier.",
            "time_zone",
        )
    candidate = value.strip()
    if not candidate or len(candidate) > 255:
        raise CalendarDomainError(
            "invalid_time_zone",
            "Time zone must be a valid IANA identifier.",
            "time_zone",
        )
    try:
        ZoneInfo(candidate)
    except (ValueError, ZoneInfoNotFoundError):
        raise CalendarDomainError(
            "invalid_time_zone",
            "Time zone must be a valid IANA identifier.",
            "time_zone",
        ) from None
    return candidate


class CalendarService:
    """Read, review, and change the owner-scoped authoritative calendar."""

    def __init__(self, db: Session):
        self.db = db

    def state(self, user_id: UUID) -> CalendarState:
        profile = self.db.get(UserProfile, user_id)
        zone = (profile.authoritative_time_zone or None) if profile is not None else None
        return CalendarState(
            is_established=bool(zone),
            authoritative_time_zone=zone,
            calendar_revision=(profile.calendar_revision or 0) if profile is not None else 0,
        )

    @staticmethod
    def today_in_zone(time_zone: str, now: datetime | None = None) -> date:
        """Return the calendar date at ``now`` in one validated IANA zone."""

        zone = ZoneInfo(validate_iana_time_zone(time_zone))
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(zone).date()

    def preview_change(
        self,
        user_id: UUID,
        proposed_time_zone: str,
        *,
        now: datetime | None = None,
    ) -> CalendarImpactPreview:
        """Calculate consequences without mutating calendar or log data."""

        proposed = validate_iana_time_zone(proposed_time_zone)
        state = self.state(user_id)
        if not state.is_established or state.authoritative_time_zone is None:
            raise CalendarDomainError(
                "time_zone_not_established",
                "Establish an authoritative time zone before reviewing a change.",
                "time_zone",
            )
        return self._preview_from_values(
            user_id,
            state.calendar_revision,
            state.authoritative_time_zone,
            proposed,
            now=now,
        )

    def confirm_change(
        self,
        user_id: UUID,
        proposed_time_zone: str,
        expected_revision: int,
        preview_token: str | None = None,
        *,
        now: datetime | None = None,
    ) -> CalendarState:
        """Apply a reviewed change only when its owner context is current."""

        proposed = validate_iana_time_zone(proposed_time_zone)
        try:
            locked_user_id = self.db.scalar(
                select(User.id).where(User.id == user_id).with_for_update()
            )
            if locked_user_id is None:
                raise LookupError("User not found")
            profile = self.db.get(UserProfile, user_id)
            if profile is None or not profile.authoritative_time_zone:
                raise CalendarDomainError(
                    "time_zone_not_established",
                    "Establish an authoritative time zone before changing it.",
                    "time_zone",
                )
            if profile.calendar_revision != expected_revision:
                raise CalendarDomainError(
                    "stale_calendar_preview",
                    "This time-zone review is stale. Review the current impact again.",
                )
            if not preview_token:
                raise CalendarDomainError(
                    "stale_calendar_preview",
                    "This time-zone review is stale. Review the current impact again.",
                )
            current_preview = self._preview_from_values(
                user_id,
                profile.calendar_revision or 0,
                profile.authoritative_time_zone,
                proposed,
                now=now,
            )
            if current_preview.preview_token != preview_token:
                raise CalendarDomainError(
                    "stale_calendar_preview",
                    "This time-zone review is stale. Review the current impact again.",
                )
            if profile.authoritative_time_zone == proposed:
                self.db.commit()
                return self.state(user_id)
            profile.authoritative_time_zone = proposed
            profile.calendar_revision = (profile.calendar_revision or 0) + 1
            self.db.flush()
            result = self.state(user_id)
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise

    def validate_mutation_context(
        self,
        user_id: UUID,
        expected_revision: int,
        logged_date: date,
    ) -> None:
        """Lock and validate an active flow's retained calendar context."""

        locked_user_id = self.db.scalar(select(User.id).where(User.id == user_id).with_for_update())
        if locked_user_id is None:
            raise LookupError("User not found")
        profile = self.db.get(UserProfile, user_id)
        if profile is None or not profile.authoritative_time_zone:
            raise AuthoritativeTimeZoneRequiredError()
        if profile.calendar_revision != expected_revision:
            raise CalendarDomainError(
                "calendar_context_changed",
                "The authoritative calendar changed. Review this entry again before saving.",
            )
        if logged_date > self.today_in_zone(profile.authoritative_time_zone):
            raise CalendarDomainError(
                "future_dated_mutation_blocked",
                "This entry date is now in the future under the authoritative time zone.",
            )

    def _preview_from_values(
        self,
        user_id: UUID,
        calendar_revision: int,
        current_time_zone: str,
        proposed_time_zone: str,
        *,
        now: datetime | None = None,
    ) -> CalendarImpactPreview:
        current_today = self.today_in_zone(current_time_zone, now)
        proposed_today = self.today_in_zone(proposed_time_zone, now)
        entries = tuple(
            self.db.scalars(
                select(DailyLog)
                .where(
                    DailyLog.user_id == user_id,
                    DailyLog.logged_date <= current_today,
                    DailyLog.logged_date > proposed_today,
                )
                .order_by(DailyLog.logged_date, DailyLog.created_at, DailyLog.id)
            ).all()
        )
        return CalendarImpactPreview(
            calendar_revision=calendar_revision,
            current_time_zone=current_time_zone,
            proposed_time_zone=proposed_time_zone,
            current_today=current_today,
            proposed_today=proposed_today,
            today_changes=current_today != proposed_today,
            affected_entries=entries,
        )

    def establish(self, user_id: UUID, proposed_time_zone: str) -> CalendarState:
        zone = validate_iana_time_zone(proposed_time_zone)
        try:
            # Match the existing Target owner lock order.  This serializes two
            # first confirmations without changing any DailyLog transaction.
            locked_user_id = self.db.scalar(
                select(User.id).where(User.id == user_id).with_for_update()
            )
            if locked_user_id is None:
                raise LookupError("User not found")

            profile = self.db.get(UserProfile, user_id)
            if profile is None:
                profile = UserProfile(user_id=user_id)
                self.db.add(profile)
            elif profile.authoritative_time_zone:
                if profile.authoritative_time_zone != zone:
                    raise CalendarDomainError(
                        "time_zone_change_requires_review",
                        "Changing the authoritative time zone requires impact review.",
                        "time_zone",
                    )
                # Repeating the same explicit confirmation is idempotent.
                self.db.commit()
                return self.state(user_id)

            profile.authoritative_time_zone = zone
            profile.calendar_revision = (profile.calendar_revision or 0) + 1
            self.db.flush()
            result = self.state(user_id)
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise


def require_authoritative_time_zone(db: Session, user_id: UUID) -> str:
    """Return the confirmed owner zone or reject a Daily Log mutation."""

    profile = db.get(UserProfile, user_id)
    if profile is None or not profile.authoritative_time_zone:
        raise AuthoritativeTimeZoneRequiredError()
    return profile.authoritative_time_zone
