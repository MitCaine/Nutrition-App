from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.v1.routers.usda import get_usda_service
from app.integrations.usda.client import UsdaConfigurationError, UsdaUpstreamError
from app.main import app
from app.services.usda_service import UsdaService
from tests.test_stage3_usda_import import FakeUsdaClient
from tests.test_stage3_usda_mapper import usda_banana_payload
from tests.test_stage2_foods import create_food


class MissingKeyService:
    def search(self, query: str, *, page_size: int = 25, page_number: int = 1):
        raise UsdaConfigurationError("USDA_FDC_API_KEY is required for FoodData Central features")


class QueryRejectingService:
    def search(self, query: str, *, page_size: int = 25, page_number: int = 1):
        raise UsdaUpstreamError("FoodData Central returned HTTP 400", status_code=400)


class UnavailableService:
    def search(self, query: str, *, page_size: int = 25, page_number: int = 1):
        raise UsdaUpstreamError("FoodData Central request timed out")


def test_usda_search_endpoint_fails_clearly_without_api_key(client: TestClient) -> None:
    app.dependency_overrides[get_usda_service] = lambda: MissingKeyService()
    response = client.get("/api/v1/usda/foods/search", params={"query": "banana"})
    app.dependency_overrides.pop(get_usda_service, None)

    assert response.status_code == 503
    assert "USDA_FDC_API_KEY" in response.json()["detail"]


def test_usda_search_query_rejection_is_returned_as_empty_results(client: TestClient) -> None:
    app.dependency_overrides[get_usda_service] = lambda: QueryRejectingService()
    response = client.get("/api/v1/usda/foods/search", params={"query": "ground beef 80/30"})
    app.dependency_overrides.pop(get_usda_service, None)

    assert response.status_code == 200
    assert response.json() == {
        "query": "ground beef 80/30",
        "page_number": 1,
        "page_size": 25,
        "total_hits": 0,
        "foods": [],
    }


def test_usda_search_transport_failure_remains_unavailable(client: TestClient) -> None:
    app.dependency_overrides[get_usda_service] = lambda: UnavailableService()
    response = client.get("/api/v1/usda/foods/search", params={"query": "banana"})
    app.dependency_overrides.pop(get_usda_service, None)

    assert response.status_code == 502


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


def test_imported_usda_food_detail_api_preserves_nutrient_and_serving_distinctions(
    client: TestClient,
    db_session: Session,
) -> None:
    app.dependency_overrides[get_usda_service] = lambda: UsdaService(
        db_session,
        FakeUsdaClient(usda_banana_payload()),
    )
    imported = client.post("/api/v1/usda/foods/1105314/import")
    app.dependency_overrides.pop(get_usda_service, None)
    assert imported.status_code == 201, imported.text

    response = client.get(f"/api/v1/foods/{imported.json()['id']}")
    assert response.status_code == 200, response.text
    food = response.json()
    nutrients = {nutrient["nutrient_id"]: nutrient for nutrient in food["nutrients"]}
    servings = {serving["label"]: serving for serving in food["serving_definitions"]}

    assert food["source_type"] == "usda"
    assert food["source_id"] == "1105314"
    assert nutrients["calories"]["amount"] == "89.000000"
    assert nutrients["calories"]["basis"] == "per_100g"
    assert nutrients["calories"]["data_status"] == "known"
    assert nutrients["calories"]["source"] == "usda_fdc"
    assert nutrients["calories"]["is_user_confirmed"] is False
    assert nutrients["calories"]["original_amount"] == "89.000000"
    assert nutrients["calories"]["original_unit"] == "KCAL"
    assert nutrients["calories"]["original_text"] == "1008"

    assert nutrients["cholesterol"]["amount"] == "0.000000"
    assert nutrients["cholesterol"]["data_status"] == "zero"
    assert nutrients["vitamin_d"]["amount"] is None
    assert nutrients["vitamin_d"]["data_status"] == "unknown"
    assert servings["100 g"]["is_default"] is True
    assert servings["100 g"]["gram_weight"] == "100.000000"
    assert servings["100 g"]["source"] == "usda_fdc"
    assert servings["100 g"]["is_user_confirmed"] is False


def test_manual_food_detail_api_uses_same_response_shape(client: TestClient) -> None:
    created = create_food(client)

    response = client.get(f"/api/v1/foods/{created['id']}")
    assert response.status_code == 200, response.text
    food = response.json()
    nutrients = {nutrient["nutrient_id"]: nutrient for nutrient in food["nutrients"]}
    default_servings = [serving for serving in food["serving_definitions"] if serving["is_default"]]

    assert food["source_type"] == "manual"
    assert nutrients["protein"]["amount"] == "20.000000"
    assert nutrients["protein"]["basis"] == "per_serving"
    assert nutrients["protein"]["data_status"] == "known"
    assert nutrients["protein"]["source"] == "manual"
    assert nutrients["protein"]["is_user_confirmed"] is True
    assert nutrients["added_sugars"]["amount"] == "0.000000"
    assert nutrients["added_sugars"]["data_status"] == "zero"
    assert nutrients["vitamin_d"]["amount"] is None
    assert nutrients["vitamin_d"]["data_status"] == "unknown"
    assert len(default_servings) == 1
    assert default_servings[0]["source"] == "manual"
    assert default_servings[0]["is_user_confirmed"] is True
