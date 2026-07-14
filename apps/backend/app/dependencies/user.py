from __future__ import annotations

import secrets
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import DeploymentMode, Settings, get_settings
from app.dependencies.database import get_db
from app.models.user import User

DEV_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
DEV_USER_EMAIL = "dev@nutrition.local"
# Keep the historical fixture identifier so existing deterministic ownership
# assertions remain stable; test mode is still a separate resolver branch.
TEST_USER_ID = DEV_USER_ID
TEST_USER_EMAIL = "test@nutrition.local"

_bearer = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _configured_user(
    db: Session,
    *,
    user_id: UUID,
    email: str,
    display_name: str,
    create_if_missing: bool,
) -> User:
    user = db.get(User, user_id)
    if user is not None:
        return user
    if not create_if_missing:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configured application user is unavailable",
        )
    user = User(id=user_id, email=email, display_name=display_name)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def ensure_dev_user(db: Session) -> User:
    """Explicit test/service helper; API routers must use get_current_user."""
    return _configured_user(
        db,
        user_id=DEV_USER_ID,
        email=DEV_USER_EMAIL,
        display_name="Dev User",
        create_if_missing=True,
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    config: Settings = Depends(get_settings),
) -> User:
    mode = config.deployment_mode
    if mode is DeploymentMode.DEVELOPMENT:
        return ensure_dev_user(db)
    if mode is DeploymentMode.TEST:
        return _configured_user(
            db,
            user_id=TEST_USER_ID,
            email=TEST_USER_EMAIL,
            display_name="Test User",
            create_if_missing=True,
        )
    if mode is DeploymentMode.PRIVATE_SINGLE_USER:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise _unauthorized()
        configured_secret = config.private_auth_secret
        if configured_secret is None or not secrets.compare_digest(
            credentials.credentials.encode("utf-8"),
            configured_secret.get_secret_value().encode("utf-8"),
        ):
            raise _unauthorized()
        assert config.private_user_id is not None
        assert config.private_user_email is not None
        return _configured_user(
            db,
            user_id=config.private_user_id,
            email=config.private_user_email,
            display_name=config.private_user_display_name,
            create_if_missing=config.private_user_create_if_missing,
        )

    # Settings rejects production until a real provider is installed. Keep the
    # request-time boundary fail-closed if construction is ever bypassed.
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Production authentication is unavailable",
    )
