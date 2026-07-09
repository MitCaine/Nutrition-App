from __future__ import annotations

from typing import Any

import httpx


class UsdaConfigurationError(RuntimeError):
    pass


class UsdaUpstreamError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class UsdaClient:
    def __init__(
        self,
        api_key: str | None,
        *,
        base_url: str = "https://api.nal.usda.gov/fdc/v1",
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(timeout_seconds)
        self.transport = transport

    def search_foods(self, query: str, *, page_size: int = 25, page_number: int = 1) -> dict[str, Any]:
        return self._get(
            "/foods/search",
            {
                "query": query,
                "pageSize": page_size,
                "pageNumber": page_number,
            },
        )

    def get_food(self, fdc_id: int) -> dict[str, Any]:
        return self._get(f"/food/{fdc_id}", {"format": "full"})

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise UsdaConfigurationError("USDA_FDC_API_KEY is required for FoodData Central features")

        request_params = {**params, "api_key": self.api_key}
        try:
            with httpx.Client(base_url=self.base_url, timeout=self.timeout, transport=self.transport) as client:
                response = client.get(path, params=request_params)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise UsdaUpstreamError("FoodData Central request timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise UsdaUpstreamError(
                f"FoodData Central returned HTTP {exc.response.status_code}",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.HTTPError as exc:
            raise UsdaUpstreamError("FoodData Central request failed") from exc
        except ValueError as exc:
            raise UsdaUpstreamError("FoodData Central returned malformed JSON") from exc

        if not isinstance(data, dict):
            raise UsdaUpstreamError("FoodData Central returned an unexpected response shape")
        return data
