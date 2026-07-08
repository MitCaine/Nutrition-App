from uuid import UUID

from sqlalchemy.orm import Session

from app.models.user import User

DEV_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
DEV_USER_EMAIL = "dev@nutrition.local"


def ensure_dev_user(db: Session) -> User:
    user = db.get(User, DEV_USER_ID)
    if user is not None:
        return user

    user = User(id=DEV_USER_ID, email=DEV_USER_EMAIL, display_name="Dev User")
    db.add(user)
    db.flush()
    return user
