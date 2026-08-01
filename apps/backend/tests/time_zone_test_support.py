"""Test setup helpers for behavior that requires an authoritative calendar."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.models.user import UserProfile


def establish_test_time_zone(
    db: Session,
    user_id: UUID,
    time_zone: str = "UTC",
) -> None:
    """Give a test user the authoritative time zone required by log mutations."""

    profile = db.get(UserProfile, user_id)
    if profile is None:
        profile = UserProfile(user_id=user_id)
        db.add(profile)
    profile.authoritative_time_zone = time_zone
    db.flush()
