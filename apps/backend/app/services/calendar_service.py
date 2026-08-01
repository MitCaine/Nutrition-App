from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

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
    """Read and establish the owner-scoped authoritative calendar.

    Initial establishment is intentionally the only write supported here.
    Changing an already established zone belongs to E1-02, where impact review
    and active-workflow revalidation are defined.
    """

    def __init__(self, db: Session):
        self.db = db

    def state(self, user_id: UUID) -> CalendarState:
        profile = self.db.get(UserProfile, user_id)
        zone = (profile.authoritative_time_zone or None) if profile is not None else None
        return CalendarState(is_established=bool(zone), authoritative_time_zone=zone)

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
