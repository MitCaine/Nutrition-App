from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP, localcontext
import json
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from app.operators.phase5c_contracts import canonical_json


ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = ROOT / "packages" / "shared-contracts" / "e2-02" / "parity-fixtures.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

SPECS = {
    "numeric_14_6": (14, 6),
    "numeric_8_3": (8, 3),
    "numeric_5_4": (5, 4),
}


def _stored_decimal(value: str, spec_name: str) -> str:
    _precision, scale = SPECS[spec_name]
    with localcontext() as context:
        context.prec = 50
        quantized = Decimal(value).quantize(
            Decimal(1).scaleb(-scale),
            rounding=ROUND_HALF_UP,
        )
    return format(quantized, f".{scale}f")


def test_decimal_fixtures_match_postgresql_numeric_rounding_and_serialization() -> None:
    for case in FIXTURE["decimal_cases"]:
        assert _stored_decimal(case["input"], case["spec"]) == case["canonical"]


def test_arithmetic_fixtures_match_decimal_results() -> None:
    for case in FIXTURE["arithmetic_cases"]:
        left = Decimal(case["left"])
        right = Decimal(case["right"])
        if case["operation"] == "add":
            result = left + right
        elif case["operation"] == "subtract":
            result = left - right
        elif case["operation"] == "multiply":
            result = left * right
        elif case["operation"] == "divide":
            result = left / right
        else:
            result = (left > right) - (left < right)

        if case["operation"] == "compare":
            assert result == case["canonical"]
        else:
            assert _stored_decimal(format(result, "f"), case["spec"]) == case["canonical"]


def test_derived_response_decimal_fixtures_match_backend_decimal_context() -> None:
    for case in FIXTURE["response_decimal_cases"]:
        left = Decimal(case["left"])
        right = Decimal(case["right"])
        result = left * right if case["operation"] == "multiply" else left / right
        assert str(result) == case["canonical"]


def test_scalar_fixtures_match_backend_canonical_forms() -> None:
    scalar = FIXTURE["scalar_cases"]
    assert str(UUID(scalar["uuid"]["input"])) == scalar["uuid"]["canonical"]
    assert date.fromisoformat(scalar["date_only"]["input"]).isoformat() == scalar["date_only"]["canonical"]

    instant = datetime.fromisoformat(scalar["instant"]["input"].replace("Z", "+00:00"))
    assert instant.isoformat(timespec="auto").replace("+00:00", "Z") == scalar["instant"]["canonical"]

    candidate = scalar["iana_time_zone"]["input"].strip()
    ZoneInfo(candidate)
    assert candidate == scalar["iana_time_zone"]["canonical"]
    assert scalar["boolean"]["input"] is scalar["boolean"]["canonical"] is True


def test_pydantic_response_serialization_preserves_value_classes() -> None:
    class ResponseValues(BaseModel):
        identifier: UUID
        instant: datetime
        date_only: date
        amount: Decimal
        enabled: bool

    values = ResponseValues(
        identifier=UUID(FIXTURE["scalar_cases"]["uuid"]["canonical"]),
        instant=datetime.fromisoformat("2026-02-28T23:59:59.100000+00:00"),
        date_only=date(2026, 2, 28),
        amount=Decimal("22.000000"),
        enabled=True,
    ).model_dump(mode="json")
    assert values == {
        "identifier": "a0b1c2d3-e4f5-4678-9012-abcdef123456",
        "instant": "2026-02-28T23:59:59.100000Z",
        "date_only": "2026-02-28",
        "amount": "22.000000",
        "enabled": True,
    }


def test_json_and_behavior_fixtures_match_current_backend_canonical_json() -> None:
    for case in FIXTURE["json_cases"]:
        assert canonical_json(case["value"]) == case["canonical"]

    kinds = {fixture["kind"] for fixture in FIXTURE["behavioral_fixtures"]}
    assert {
        "food",
        "recipe_publication",
        "daily_log_snapshot",
        "unknown_nutrient",
        "idempotent_replay",
        "failure_outcomes",
    } <= kinds
    for fixture in FIXTURE["behavioral_fixtures"]:
        assert canonical_json(fixture["payload"])


def test_runtime_error_code_vocabulary_is_frozen_in_fixture() -> None:
    assert FIXTURE["runtime_error_codes"] == [
        "ownership_denied",
        "validation_failed",
        "conflict",
        "constraint_failed",
        "dependency_unavailable",
        "mutation_unresolved",
    ]
