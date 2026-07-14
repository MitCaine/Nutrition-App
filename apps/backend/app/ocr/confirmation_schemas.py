from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.catalog.nutrients import NUTRIENT_CATALOG
from app.ocr.parser import NUTRITION_LABEL_PARSER_VERSION
from app.schemas.food import FoodCreateRequest, FoodResponse

TRACE_SCHEMA_VERSION = "ocr_nutrition_confirmation_v1"
MAX_TRACE_BYTES = 48_000
CANONICAL_IDS = {item.id for item in NUTRIENT_CATALOG}
EXPECTED_UNITS = {item.id: item.default_unit for item in NUTRIENT_CATALOG}
FIELD_KEYS = {
    "food.name", "food.brand", "food.notes", "serving.display",
    "serving.quantity", "serving.unit", "serving.gram_weight", "calories",
}


class TraceFieldDecision(BaseModel):
    field_key: str = Field(min_length=1, max_length=80)
    nutrient_id: str | None = None
    suggested_value: str | None = Field(default=None, max_length=256)
    confirmed_value: str | None = Field(default=None, max_length=256)
    unit: str | None = Field(default=None, max_length=16)
    decision: Literal["accepted", "edited", "omitted"]
    parse_status: Literal["parsed", "ambiguous", "missing", "unsupported"]
    comparison: Literal["less_than"] | None = None
    confidence: Decimal = Field(ge=0, le=1)
    source_text: str = Field(default="", max_length=2_000)
    source_observation_ids: list[str] = Field(default_factory=list, max_length=20)
    warning_codes: list[str] = Field(default_factory=list, max_length=20)
    resolution: str | None = Field(default=None, max_length=256)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_decision(self) -> "TraceFieldDecision":
        if any(not value or len(value) > 128 for value in self.source_observation_ids):
            raise ValueError("source observation IDs must be 1-128 characters")
        if any(not value or len(value) > 100 for value in self.warning_codes):
            raise ValueError("warning codes must be 1-100 characters")
        if self.nutrient_id is None:
            if self.field_key not in FIELD_KEYS:
                raise ValueError(f"unsupported trace field key: {self.field_key}")
        else:
            if self.nutrient_id not in CANONICAL_IDS:
                raise ValueError(f"unsupported nutrient ID: {self.nutrient_id}")
            if self.field_key != f"nutrient.{self.nutrient_id}":
                raise ValueError("nutrient field key must match nutrient ID")
            if self.unit != EXPECTED_UNITS[self.nutrient_id]:
                raise ValueError("trace nutrient unit does not match canonical unit")
        if self.decision == "omitted" and self.confirmed_value is not None:
            raise ValueError("omitted fields cannot have a confirmed value")
        if self.decision != "omitted" and self.confirmed_value is None:
            raise ValueError("accepted or edited fields require a confirmed value")
        if self.comparison == "less_than" and self.decision == "accepted":
            raise ValueError("less-than suggestions require an edit or omission")
        if self.parse_status == "ambiguous" and not self.resolution:
            raise ValueError("ambiguous fields require an explicit resolution")
        return self


class UnknownNutrientTrace(BaseModel):
    original_name: str = Field(min_length=1, max_length=160)
    source_text: str = Field(max_length=2_000)
    source_observation_ids: list[str] = Field(default_factory=list, max_length=20)
    warning_codes: list[str] = Field(default_factory=list, max_length=20)
    decision: Literal["dismissed"]

    model_config = ConfigDict(extra="forbid")


class OcrNutritionConfirmationRequest(BaseModel):
    parser_version: str = Field(max_length=64)
    image_source_type: Literal["camera", "photo_library"]
    client_request_id: UUID
    food: FoodCreateRequest
    field_decisions: list[TraceFieldDecision] = Field(min_length=1, max_length=40)
    unknown_nutrients: list[UnknownNutrientTrace] = Field(default_factory=list, max_length=30)
    parser_warning_codes: list[str] = Field(default_factory=list, max_length=50)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_confirmation(self) -> "OcrNutritionConfirmationRequest":
        if self.parser_version != NUTRITION_LABEL_PARSER_VERSION:
            raise ValueError("unsupported parser version")
        if not self.food.name.strip():
            raise ValueError("food name is required")
        keys = [item.field_key for item in self.field_decisions]
        if len(keys) != len(set(keys)):
            raise ValueError("trace field decisions must have unique keys")
        by_key = {item.field_key: item for item in self.field_decisions}
        required_fields = {
            "food.name", "food.brand", "food.notes", "serving.display",
            "serving.quantity", "serving.unit", "serving.gram_weight",
        }
        if not required_fields.issubset(by_key):
            raise ValueError("confirmation trace is missing Food or serving decisions")
        default_serving = next(item for item in self.food.serving_definitions if item.is_default)
        expected_values = {
            "food.name": self.food.name.strip(),
            "food.brand": self.food.brand.strip() if self.food.brand else None,
            "food.notes": self.food.notes,
            "serving.display": default_serving.label,
            "serving.quantity": str(default_serving.quantity),
            "serving.unit": default_serving.unit,
            "serving.gram_weight": str(default_serving.gram_weight) if default_serving.gram_weight is not None else None,
        }
        for key, expected in expected_values.items():
            if by_key[key].confirmed_value != expected:
                raise ValueError(f"confirmed {key} differs from Food payload")
        calories = by_key.get("calories") or by_key.get("nutrient.calories")
        if calories is None or calories.decision == "omitted":
            raise ValueError("calories must be explicitly reviewed and retained")
        nutrient_decisions = {
            item.nutrient_id: item for item in self.field_decisions if item.nutrient_id
        }
        food_nutrients = {item.nutrient_id: item for item in self.food.nutrients}
        if len(food_nutrients) != len(self.food.nutrients):
            raise ValueError("confirmed nutrients must be unique")
        retained = {
            nutrient_id: item for nutrient_id, item in nutrient_decisions.items()
            if item.decision != "omitted"
        }
        if set(retained) != set(food_nutrients):
            raise ValueError("confirmed Food nutrients must match retained trace decisions")
        for nutrient_id, decision in retained.items():
            nutrient = food_nutrients[nutrient_id]
            if nutrient.unit != decision.unit:
                raise ValueError("confirmed nutrient unit differs from trace")
            expected = Decimal(decision.confirmed_value or "")
            if nutrient.amount != expected:
                raise ValueError("confirmed nutrient amount differs from trace")
            if expected < 0:
                raise ValueError("confirmed nutrient amounts cannot be negative")
        snapshot = self.trace_snapshot()
        if len(json.dumps(snapshot, separators=(",", ":")).encode()) > MAX_TRACE_BYTES:
            raise ValueError("confirmation trace exceeds size limit")
        if any(re.search(r"(?:file://|/private/|/var/|/users/)", item.source_text, re.I)
               for item in [*self.field_decisions, *self.unknown_nutrients]):
            raise ValueError("raw image paths are not allowed in confirmation provenance")
        return self

    def trace_snapshot(self) -> dict:
        return {
            "schema_version": TRACE_SCHEMA_VERSION,
            "field_decisions": [item.model_dump(mode="json") for item in self.field_decisions],
            "unknown_nutrients": [item.model_dump(mode="json") for item in self.unknown_nutrients],
            "parser_warning_codes": self.parser_warning_codes,
        }


class OcrNutritionConfirmationResponse(BaseModel):
    food: FoodResponse
    trace_id: UUID

    model_config = ConfigDict(extra="forbid")
