from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ParseStatus = Literal["parsed", "ambiguous", "missing", "unsupported"]


class NormalizedBoundingBox(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_bounds(self) -> "NormalizedBoundingBox":
        if self.x + self.width > 1.000001 or self.y + self.height > 1.000001:
            raise ValueError("bounding box must remain within normalized image bounds")
        return self


class OcrObservationInput(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    text: str = Field(max_length=2_000)
    confidence: float = Field(ge=0, le=1)
    bounding_box: NormalizedBoundingBox | None = None

    model_config = ConfigDict(extra="forbid")


class NutritionLabelParseInput(BaseModel):
    full_text: str = Field(max_length=50_000)
    observations: list[OcrObservationInput] = Field(default_factory=list, max_length=500)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_unique_observation_ids(self) -> "NutritionLabelParseInput":
        ids = [observation.id for observation in self.observations]
        if len(ids) != len(set(ids)):
            raise ValueError("observation IDs must be unique")
        return self


class ParsedSourceLine(BaseModel):
    id: str
    text: str
    source_observation_ids: list[str]
    confidence: float
    reason: str | None = None


class ParsedField(BaseModel):
    value: Decimal | str | bool | None
    comparison: Literal["less_than"] | None = None
    source_text: str
    source_observation_ids: list[str]
    confidence: float = Field(ge=0, le=1)
    status: ParseStatus
    warning_codes: list[str] = Field(default_factory=list)


class ParsedServingInfo(BaseModel):
    servings_per_container: ParsedField
    serving_size_display: ParsedField
    serving_quantity: ParsedField
    serving_unit: ParsedField
    gram_weight: ParsedField
    approximate: ParsedField


class ParsedNutrient(BaseModel):
    nutrient_id: str | None
    original_name: str
    amount: ParsedField
    unit: ParsedField
    daily_value_percent: ParsedField | None
    source_observation_ids: list[str]
    confidence: float = Field(ge=0, le=1)
    status: ParseStatus
    warning_codes: list[str] = Field(default_factory=list)


class ParseWarning(BaseModel):
    code: str
    message: str
    source_observation_ids: list[str] = Field(default_factory=list)


class ParsedNutritionLabel(BaseModel):
    serving: ParsedServingInfo | None
    calories: ParsedField
    nutrients: list[ParsedNutrient]
    unparsed_lines: list[ParsedSourceLine]
    warnings: list[ParseWarning]
    parser_version: str
