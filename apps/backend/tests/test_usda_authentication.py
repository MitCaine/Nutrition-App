from __future__ import annotations

from uuid import UUID

from app.api.v1.routers.usda import get_usda_service
from app.core.config import DeploymentMode, Settings, get_settings
from app.main import app


class CountingUsdaService:
    def __init__(self) -> None:
        self.search_calls = 0
        self.preview_calls = 0
        self.import_calls = 0

    def search(self, *_args, **_kwargs):
        self.search_calls += 1
        raise AssertionError("unauthorized search reached USDA service")

    def preview(self, *_args, **_kwargs):
        self.preview_calls += 1
        raise AssertionError("unauthorized preview reached USDA service")

    def import_food(self, *_args, **_kwargs):
        self.import_calls += 1
        raise AssertionError("unauthorized import reached USDA service")


def test_unauthorized_callers_cannot_consume_usda_quota(client) -> None:
    service = CountingUsdaService()
    config = Settings(
        _env_file=None,
        deployment_mode=DeploymentMode.PRIVATE_SINGLE_USER,
        database_url="sqlite+pysqlite:///:memory:",
        private_auth_secret="private-test-credential-at-least-32-characters",
        private_user_id=UUID("10000000-0000-0000-0000-000000000002"),
        private_user_email="usda-private@example.test",
    )
    app.dependency_overrides[get_settings] = lambda: config
    app.dependency_overrides[get_usda_service] = lambda: service

    assert client.get("/api/v1/usda/foods/search?query=apple").status_code == 401
    assert client.get("/api/v1/usda/foods/123").status_code == 401
    assert client.post("/api/v1/usda/foods/123/import").status_code == 401
    assert (service.search_calls, service.preview_calls, service.import_calls) == (0, 0, 0)
