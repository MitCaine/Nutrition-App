from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class NutrientDataStatus(str, Enum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    ESTIMATED = "estimated"
    ZERO = "zero"


class NutrientBasis(str, Enum):
    PER_SERVING = "per_serving"
    PER_100G = "per_100g"
    PER_GRAM = "per_gram"


@dataclass(frozen=True)
class NutrientAmount:
    nutrient_id: str
    amount: Decimal | None
    unit: str
    basis: NutrientBasis
    data_status: NutrientDataStatus


@dataclass(frozen=True)
class NutrientSnapshot:
    nutrient_id: str
    amount: Decimal | None
    unit: str
    data_status: NutrientDataStatus


@dataclass(frozen=True)
class AggregatedNutrientTotal:
    nutrient_id: str
    amount_known: Decimal
    amount_estimated: Decimal
    unit: str
    has_unknown_contributors: bool
    unknown_contributor_count: int
