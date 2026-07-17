from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.v1.routers import health as health_router
from app.core.config import DeploymentMode, Settings, get_settings
from app.core.database import engine
from app.core.database_identity import database_identity, redacted_database_url
from app.dependencies.user import DEV_USER_ID, TEST_USER_ID, get_current_user
from app.main import app
from app.models.user import User
from app.operators.phase5c4_prerequisites import LocalReadiness, READINESS_REASONS


PRIVATE_USER_ID = UUID("10000000-0000-0000-0000-000000000001")
PRIVATE_SECRET = "private-test-credential-at-least-32-characters"


def _settings(mode: DeploymentMode, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "deployment_mode": mode,
        "database_url": "sqlite+pysqlite:///:memory:",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _private_settings() -> Settings:
    return _settings(
        DeploymentMode.PRIVATE_SINGLE_USER,
        private_auth_secret=PRIVATE_SECRET,
        private_user_id=PRIVATE_USER_ID,
        private_user_email="private-user@example.test",
        private_user_create_if_missing=True,
    )


def test_deployment_mode_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NUTRITION_DEPLOYMENT_MODE", raising=False)
    with pytest.raises(ValidationError, match="deployment_mode"):
        Settings(_env_file=None, database_url="sqlite+pysqlite:///:memory:")


def test_development_and_test_modes_resolve_deterministic_users(
    client, db_session: Session
) -> None:
    app.dependency_overrides[get_settings] = lambda: _settings(DeploymentMode.DEVELOPMENT)
    assert client.get("/api/v1/nutrients").status_code == 200
    assert db_session.get(User, DEV_USER_ID) is not None

    app.dependency_overrides[get_settings] = lambda: _settings(DeploymentMode.TEST)
    assert client.get("/api/v1/nutrients").status_code == 200
    assert db_session.get(User, TEST_USER_ID) is not None


def test_private_mode_requires_valid_bearer_credential(client, db_session: Session) -> None:
    app.dependency_overrides[get_settings] = _private_settings

    missing = client.get("/api/v1/nutrients")
    malformed = client.get("/api/v1/nutrients", headers={"Authorization": "Basic invalid"})
    invalid = client.get("/api/v1/nutrients", headers={"Authorization": "Bearer wrong-credential"})
    valid = client.get("/api/v1/nutrients", headers={"Authorization": f"Bearer {PRIVATE_SECRET}"})

    assert missing.status_code == malformed.status_code == invalid.status_code == 401
    assert (
        missing.json()
        == malformed.json()
        == invalid.json()
        == {"detail": "Authentication required"}
    )
    assert missing.headers["www-authenticate"] == malformed.headers["www-authenticate"]
    assert missing.headers["www-authenticate"] == invalid.headers["www-authenticate"] == "Bearer"
    assert valid.status_code == 200
    assert db_session.get(User, PRIVATE_USER_ID) is not None
    assert PRIVATE_SECRET not in repr(missing.json())


def test_private_mode_configuration_fails_without_secret() -> None:
    with pytest.raises(ValidationError, match="PRIVATE_AUTH_SECRET"):
        _settings(
            DeploymentMode.PRIVATE_SINGLE_USER,
            private_user_id=PRIVATE_USER_ID,
            private_user_email="private-user@example.test",
        )


def test_private_mode_rejects_short_secret_and_missing_user_configuration() -> None:
    with pytest.raises(ValidationError, match="at least 32 characters"):
        _settings(
            DeploymentMode.PRIVATE_SINGLE_USER,
            private_auth_secret="too-short",
            private_user_id=PRIVATE_USER_ID,
            private_user_email="private-user@example.test",
        )
    with pytest.raises(ValidationError, match="PRIVATE_USER_ID"):
        _settings(
            DeploymentMode.PRIVATE_SINGLE_USER,
            private_auth_secret=PRIVATE_SECRET,
        )


def test_private_user_bootstrap_is_explicit(client, db_session: Session) -> None:
    disabled = _settings(
        DeploymentMode.PRIVATE_SINGLE_USER,
        private_auth_secret=PRIVATE_SECRET,
        private_user_id=PRIVATE_USER_ID,
        private_user_email="private-user@example.test",
        private_user_create_if_missing=False,
    )
    app.dependency_overrides[get_settings] = lambda: disabled
    unavailable = client.get(
        "/api/v1/nutrients", headers={"Authorization": f"Bearer {PRIVATE_SECRET}"}
    )
    assert unavailable.status_code == 503
    assert unavailable.json() == {"detail": "Configured application user is unavailable"}
    assert db_session.get(User, PRIVATE_USER_ID) is None

    app.dependency_overrides[get_settings] = _private_settings
    assert (
        client.get(
            "/api/v1/nutrients", headers={"Authorization": f"Bearer {PRIVATE_SECRET}"}
        ).status_code
        == 200
    )
    assert db_session.get(User, PRIVATE_USER_ID) is not None


def test_production_mode_fails_without_installed_provider() -> None:
    with pytest.raises(ValidationError, match="none is installed"):
        _settings(DeploymentMode.PRODUCTION)
    with pytest.raises(ValidationError, match="none is installed"):
        _settings(DeploymentMode.PRODUCTION, production_auth_provider="invented")


def test_configuration_errors_hide_database_credentials() -> None:
    password = "database-password-that-must-not-appear"
    with pytest.raises(ValidationError) as captured:
        Settings(
            _env_file=None,
            deployment_mode="invalid",
            database_url=f"not a url://user:{password}@host/db?token=private",
        )
    assert password not in str(captured.value)


def test_database_url_redaction_and_runtime_identity() -> None:
    raw = "postgresql+psycopg://private-user:private-password@db.example:5433/nutrition?sslkey=x"
    redacted = redacted_database_url(raw)
    assert redacted == "postgresql://db.example:5433/nutrition"
    assert "private-user" not in redacted
    assert "private-password" not in redacted
    assert "sslkey" not in redacted
    assert database_identity(engine.url) == database_identity("sqlite+pysqlite:///:memory:")


def test_alembic_has_no_independent_operational_url() -> None:
    ini = Path("alembic.ini").read_text()
    env_source = Path("app/migrations/env.py").read_text()
    assert "sqlalchemy.url =" not in ini
    assert "settings.database_url" in env_source


def test_every_application_route_has_current_user_dependency() -> None:
    included_routers = [route for route in app.routes if hasattr(route, "include_context")]
    prefixes = {route.include_context.prefix for route in included_routers}
    assert "/api/v1" in prefixes
    assert {
        "/api/v1/nutrients",
        "/api/v1/foods",
        "/api/v1/logs",
        "/api/v1/targets",
        "/api/v1/recipes",
        "/api/v1/usda",
        "/api/v1/ocr/nutrition-label",
    } <= prefixes
    for included in included_routers:
        dependencies = included.include_context.dependencies
        if included.include_context.prefix == "/api/v1":
            assert not dependencies
        else:
            assert any(item.dependency is get_current_user for item in dependencies), (
                included.include_context.prefix
            )


def test_routers_do_not_import_legacy_development_user_dependency() -> None:
    for router in Path("app/api/v1/routers").glob("*.py"):
        assert "ensure_dev_user" not in router.read_text(), router


def test_health_and_readiness_are_public_and_non_sensitive(client) -> None:
    app.dependency_overrides[get_settings] = _private_settings
    health = client.get("/api/v1/health")
    ready = client.get("/api/v1/ready")
    assert health.status_code == ready.status_code == 200
    assert health.json() == {"status": "ok"}
    assert ready.json() == {"status": "ready"}
    assert PRIVATE_SECRET not in health.text + ready.text


def test_readiness_returns_safe_503_when_database_check_fails(client) -> None:
    class UnavailableDatabase:
        def execute(self, _statement) -> None:
            raise SQLAlchemyError("internal database detail")

    from app.dependencies.database import get_db

    app.dependency_overrides[get_db] = lambda: UnavailableDatabase()
    response = client.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "Service is not ready"}
    assert response.headers["X-Nutrition-Readiness-Reason"] == "database_unavailable"
    assert "internal database detail" not in response.text


@pytest.mark.parametrize("reason_code", sorted(READINESS_REASONS))
def test_readiness_exposes_only_the_documented_reason_allowlist(
    client,
    monkeypatch: pytest.MonkeyPatch,
    reason_code: str,
) -> None:
    monkeypatch.setattr(
        health_router,
        "evaluate_local_readiness",
        lambda _db: LocalReadiness(False, reason_code),
    )
    response = client.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "Service is not ready"}
    assert response.headers["X-Nutrition-Readiness-Reason"] == reason_code


def test_readiness_is_evaluated_fresh_on_every_request(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = iter(
        (
            LocalReadiness(False, "write_fence_closed_prequalification"),
            LocalReadiness(True),
        )
    )
    calls = 0

    def evaluate(_db) -> LocalReadiness:
        nonlocal calls
        calls += 1
        return next(observations)

    monkeypatch.setattr(health_router, "evaluate_local_readiness", evaluate)
    closed = client.get("/api/v1/ready")
    opened = client.get("/api/v1/ready")

    assert calls == 2
    assert closed.status_code == 503
    assert closed.headers["X-Nutrition-Readiness-Reason"] == ("write_fence_closed_prequalification")
    assert opened.status_code == 200
    assert opened.json() == {"status": "ready"}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/nutrients"),
        ("GET", "/api/v1/foods"),
        ("GET", "/api/v1/foods/favorites"),
        ("GET", "/api/v1/foods/recent"),
        ("GET", "/api/v1/logs?date=2026-07-14"),
        ("GET", "/api/v1/logs/daily-summary?date=2026-07-14"),
        ("GET", "/api/v1/recipes"),
        ("GET", "/api/v1/targets"),
        ("POST", "/api/v1/ocr/nutrition-label/parse"),
        ("POST", "/api/v1/ocr/nutrition-label/confirm"),
        ("GET", "/api/v1/usda/foods/search?query=apple"),
        ("GET", "/api/v1/usda/foods/123"),
        ("POST", "/api/v1/usda/foods/123/import"),
    ],
)
def test_private_mode_rejects_unauthorized_requests_across_every_router(
    client, method: str, path: str
) -> None:
    app.dependency_overrides[get_settings] = _private_settings
    response = client.request(method, path)
    assert response.status_code == 401, path
    assert response.json() == {"detail": "Authentication required"}
