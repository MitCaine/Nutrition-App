from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.v1.routers.usda import get_usda_service
from app.integrations.usda.client import UsdaConfigurationError
from app.main import app
from app.services.usda_service import UsdaService
from tests.test_stage3_usda_import import FakeUsdaClient
from tests.test_stage3_usda_mapper import usda_banana_payload


class MissingKeyService:
    def search(self, query: str, *, page_size: int = 25, page_number: int = 1):
        raise UsdaConfigurationError("USDA_FDC_API_KEY is required for FoodData Central features")


def test_usda_search_endpoint_fails_clearly_without_api_key(client: TestClient) -> None:
    app.dependency_overrides[get_usda_service] = lambda: MissingKeyService()
    response = client.get("/api/v1/usda/foods/search", params={"query": "banana"})
    app.dependency_overrides.pop(get_usda_service, None)

    assert response.status_code == 503
    assert "USDA_FDC_API_KEY" in response.json()["detail"]


def test_usda_import_endpoint_returns_existing_active_duplicate(
    client: TestClient,
    db_session: Session,
) -> None:
    app.dependency_overrides[get_usda_service] = lambda: UsdaService(
        db_session,
        FakeUsdaClient(usda_banana_payload()),
    )
    first = client.post("/api/v1/usda/foods/1105314/import")
    second = client.post("/api/v1/usda/foods/1105314/import")
    app.dependency_overrides.pop(get_usda_service, None)

    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    assert second.headers["X-Nutrition-App-Duplicate-Import"] == "true"
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["source_type"] == "usda"
    assert second.json()["source_id"] == "1105314"
