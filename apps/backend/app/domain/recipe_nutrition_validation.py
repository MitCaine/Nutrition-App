from __future__ import annotations

from typing import Any


class RecipeNutritionValidationError(ValueError):
    """User-actionable Recipe nutrition failure shared across backend workflows."""

    def __init__(self, code: str, message: str, **context: Any):
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = {key: value for key, value in context.items() if value is not None}

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.context}
