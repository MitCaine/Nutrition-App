from __future__ import annotations

import httpx
import pytest

from app.integrations.usda.client import UsdaClient, UsdaConfigurationError, UsdaUpstreamError


def test_usda_client_requires_api_key() -> None:
    client = UsdaClient(None)
    with pytest.raises(UsdaConfigurationError):
        client.search_foods("banana")


def test_usda_client_maps_search_request() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"foods": [], "totalHits": 0})

    client = UsdaClient("test-key", base_url="https://example.test/fdc/v1", transport=httpx.MockTransport(handler))
    response = client.search_foods("banana", page_size=12, page_number=2)

    assert response["totalHits"] == 0
    assert "query=banana" in captured["url"]
    assert "pageSize=12" in captured["url"]
    assert "pageNumber=2" in captured["url"]
    assert "api_key=test-key" in captured["url"]


def test_usda_client_maps_upstream_errors() -> None:
    client = UsdaClient(
        "test-key",
        base_url="https://example.test/fdc/v1",
        transport=httpx.MockTransport(lambda _request: httpx.Response(429, json={"error": "rate limit"})),
    )

    with pytest.raises(UsdaUpstreamError) as exc_info:
        client.get_food(123)

    assert exc_info.value.status_code == 429
