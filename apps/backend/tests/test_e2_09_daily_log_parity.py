from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.nutrition import NutrientBasis, NutrientDataStatus, NutrientSnapshot
from app.nutrition.aggregation import aggregate_snapshots
from app.nutrition.calculations import build_log_snapshots, build_revision_log_snapshots
from app.nutrition.resolution import UnsupportedNutritionAmountError, resolve_nutrition
from app.nutrition.revision_resolution import (
    ResolvedRevisionNutrient,
    ResolvedRevisionNutrition,
    map_projection_log_amount,
    resolve_revision_nutrition,
)
from app.schemas.log import DailyLogCreateRequest
from app.services.log_service import (
    LogService,
    LogSourceAmountChangedError,
    LogSourceChangedError,
    _creation_fingerprint,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "shared-contracts"
    / "e2-09"
    / "daily-log-parity-fixtures.json"
)
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
NUMERIC_14_6 = Decimal("0.000001")


def _food(*, gram_equivalent: str, nutrient_amount: str, nutrient_basis: str):
    food_id = uuid4()
    serving = SimpleNamespace(
        id=uuid4(),
        label="Parity serving",
        gram_weight=Decimal(gram_equivalent),
        is_default=True,
    )
    nutrient = SimpleNamespace(
        id=uuid4(),
        nutrient_id="protein",
        amount=Decimal(nutrient_amount),
        unit="g",
        basis=nutrient_basis,
        data_status="known",
    )
    return SimpleNamespace(
        id=food_id,
        serving_definitions=[serving],
        nutrients=[nutrient],
    )


@pytest.mark.parametrize(
    ("fixture_name", "amount_unit"),
    [
        ("food_serving_per_100g", "serving"),
        ("food_gram_per_serving", "g"),
    ],
)
def test_daily_log_fixture_matches_backend_decimal_and_snapshot_authorities(
    fixture_name: str,
    amount_unit: str,
) -> None:
    case = FIXTURE[fixture_name]
    food = _food(
        gram_equivalent=case["gram_equivalent"],
        nutrient_amount=case["nutrient_amount"],
        nutrient_basis=case["nutrient_basis"],
    )
    resolved = resolve_nutrition(
        food,
        Decimal(case["amount_quantity"]),
        amount_unit,
        food.serving_definitions[0].id,
    )
    snapshot = build_log_snapshots(food, resolved)[0]

    assert str(resolved.amount.gram_amount) == case["raw_gram_amount"]
    assert str(resolved.amount.serving_multiplier) == case["raw_serving_multiplier"]
    assert format(resolved.amount.gram_amount.quantize(NUMERIC_14_6), "f") == case[
        "persisted_gram_amount"
    ]
    assert format(snapshot.amount.quantize(NUMERIC_14_6), "f") == case[
        "persisted_snapshot_amount"
    ]
    assert snapshot.calculation_metadata == case["calculation_metadata"]


def test_daily_summary_fixture_matches_backend_aggregation_authority() -> None:
    summary = FIXTURE["summary"]
    fine = summary["fine_scale_conversion"]
    fine_total = aggregate_snapshots(
        [
            NutrientSnapshot(
                nutrient_id="protein",
                amount=Decimal(fine["amount"]),
                unit=fine["source_unit"],
                data_status=NutrientDataStatus.KNOWN,
            )
        ]
    )[0]
    assert str(fine_total.amount_known) == fine["amount_known"]
    assert str(fine_total.amount_estimated) == fine["amount_estimated"]

    for case in summary["representation_cases"]:
        total = aggregate_snapshots(
            [
                NutrientSnapshot(
                    nutrient_id=case["nutrient_id"],
                    amount=Decimal(case["amount"]),
                    unit=case["source_unit"],
                    data_status=NutrientDataStatus.KNOWN,
                )
            ]
        )[0]
        assert total.unit == case["target_unit"]
        assert str(total.amount_known) == case["amount_known"]

    large = summary["aggregate_above_numeric_14_6"]
    large_total = aggregate_snapshots(
        [
            NutrientSnapshot(
                nutrient_id="protein",
                amount=Decimal(amount),
                unit="g",
                data_status=NutrientDataStatus.KNOWN,
            )
            for amount in large["inputs"]
        ]
    )[0]
    assert str(large_total.amount_known) == large["amount_known"]

    status_rows = [
        ("known", Decimal("1.250000"), NutrientDataStatus.KNOWN),
        ("estimated", Decimal("2.500000"), NutrientDataStatus.ESTIMATED),
        ("zero", Decimal("0.000000"), NutrientDataStatus.ZERO),
        ("unknown", None, NutrientDataStatus.UNKNOWN),
    ]
    totals = {
        total.nutrient_id: {
            "amount_known": str(total.amount_known),
            "amount_estimated": str(total.amount_estimated),
            "unknown_contributor_count": total.unknown_contributor_count,
        }
        for total in aggregate_snapshots(
            [
                NutrientSnapshot(
                    nutrient_id=nutrient_id,
                    amount=amount,
                    unit="g",
                    data_status=status,
                )
                for nutrient_id, amount, status in status_rows
            ]
        )
    }
    assert totals == summary["status_totals"]


def test_recipe_snapshot_metadata_fixture_matches_immutable_revision_authority() -> None:
    case = FIXTURE["recipe_serving_metadata"]
    food = SimpleNamespace(id=uuid4())
    resolved = ResolvedRevisionNutrition(
        amount_definition_id=uuid4(),
        semantic_amount_mode="serving",
        entered_quantity=Decimal(case["amount_quantity"]),
        resolved_grams=Decimal("100"),
        serving_multiplier=Decimal(case["amount_quantity"]),
        nutrients=(
            ResolvedRevisionNutrient(
                nutrient_id="protein",
                amount=Decimal("1"),
                unit="g",
                data_status=NutrientDataStatus.KNOWN,
                source_basis=NutrientBasis.PER_SERVING,
            ),
        ),
    )

    snapshot = build_revision_log_snapshots(food, resolved, None)[0]

    assert snapshot.calculation_metadata == case["calculation_metadata"]


def test_raw_decimal_idempotency_fixture_matches_backend_fingerprint_authority() -> None:
    fixture = FIXTURE["idempotency_decimal"]
    request_id = uuid4()
    food_id = uuid4()

    def fingerprint(amount: str) -> str:
        return _creation_fingerprint(
            DailyLogCreateRequest(
                client_request_id=request_id,
                food_item_id=food_id,
                logged_date="2026-08-09",
                amount_quantity=amount,
                amount_unit="serving",
            )
        )

    distinct = fixture["distinct_after_persistence_rounding"]
    equivalent = fixture["equivalent_spellings"]
    assert fingerprint(distinct[0]) != fingerprint(distinct[1])
    assert fingerprint(equivalent[0]) == fingerprint(equivalent[1])


def test_food_gram_repeat_fixture_uses_current_backend_amount_authority() -> None:
    fixture = FIXTURE["food_gram_repeat"]
    serving = SimpleNamespace(
        id=uuid4(),
        label=fixture["replacement_serving_label"],
        unit="serving",
        gram_weight=Decimal("75.000000"),
        is_default=True,
    )
    nutrient = SimpleNamespace(
        id=uuid4(),
        nutrient_id="protein",
        amount=Decimal("10.000000"),
        unit="g",
        basis="per_serving",
        data_status="known",
    )
    food = SimpleNamespace(serving_definitions=[serving], nutrients=[nutrient])
    entry = SimpleNamespace(
        amount_unit="g",
        amount_quantity=Decimal(fixture["amount_quantity"]),
        serving_definition_id=uuid4(),
    )

    reuse = LogService._food_reuse(entry, food)

    assert reuse == {
        "current_source_loggable": True,
        "current_amount_unit": "g",
        "current_amount_definition_id": serving.id,
        "current_amount_label": fixture["replacement_serving_label"],
        "reuse_status": "exact",
        "historical_serving_label": None,
    }


@pytest.mark.parametrize("default_grams", ["75.000000", None])
def test_recipe_gram_metadata_fixture_uses_complete_revision_authority(
    default_grams: str | None,
) -> None:
    fixture = FIXTURE["recipe_gram_metadata"]
    default = SimpleNamespace(
        id=uuid4(),
        semantic_mode="serving",
        display_label="1 serving",
        display_quantity=Decimal("1.000000"),
        display_unit="serving",
        gram_equivalent=Decimal(default_grams) if default_grams is not None else None,
        is_default=True,
    )
    canonical = SimpleNamespace(
        id=uuid4(),
        semantic_mode="g",
        display_label="g",
        display_quantity=Decimal("1.000000"),
        display_unit="g",
        gram_equivalent=Decimal("1.000000"),
        is_default=False,
    )
    revision = SimpleNamespace(
        amount_definitions=[default, canonical],
        nutrients=[
            SimpleNamespace(
                id=uuid4(),
                nutrient_id="protein",
                amount=Decimal("30.000000"),
                unit="g",
                basis="per_100g",
                data_status="known",
            )
        ],
    )
    resolved = resolve_revision_nutrition(
        revision,
        canonical.id,
        Decimal(fixture["amount_quantity"]),
        semantic_amount_mode="g",
    )
    snapshot = build_revision_log_snapshots(SimpleNamespace(id=uuid4()), resolved, None)[0]
    expected = (
        fixture["calculation_metadata"]
        if default_grams is not None
        else fixture["null_conversion_metadata"]
    )

    assert str(resolved.resolved_grams) == fixture["amount_quantity"]
    assert snapshot.calculation_metadata == expected


def test_projection_mapping_fixture_requires_exact_backend_label_and_unit() -> None:
    fixture = FIXTURE["projection_serving_mapping"]
    serving = SimpleNamespace(
        id=uuid4(),
        label=fixture["label"],
        quantity=Decimal(fixture["quantity"]),
        unit=fixture["unit"],
        gram_weight=Decimal(fixture["gram_equivalent"]),
        is_default=fixture["is_default"],
    )

    def revision_amount(*, label: str, unit: str):
        return SimpleNamespace(
            id=uuid4(),
            semantic_mode="serving",
            display_label=label,
            display_quantity=Decimal(fixture["quantity"]),
            display_unit=unit,
            gram_equivalent=Decimal(fixture["gram_equivalent"]),
            is_default=fixture["is_default"],
        )

    exact = revision_amount(label=fixture["label"], unit=fixture["unit"])
    selection = map_projection_log_amount(
        SimpleNamespace(serving_definitions=[serving]),
        SimpleNamespace(amount_definitions=[exact]),
        "serving",
        serving.id,
    )
    assert selection.revision_amount is exact
    assert selection.compatibility_serving is serving

    for mismatch in (
        revision_amount(label="Different label", unit=fixture["unit"]),
        revision_amount(label=fixture["label"], unit=fixture["unit"].upper()),
    ):
        with pytest.raises(UnsupportedNutritionAmountError):
            map_projection_log_amount(
                SimpleNamespace(serving_definitions=[serving]),
                SimpleNamespace(amount_definitions=[mismatch]),
                "serving",
                serving.id,
            )


def test_reviewed_missing_serving_fixture_uses_log_service_stale_amount_authority() -> None:
    food = SimpleNamespace(serving_definitions=[])
    payload = SimpleNamespace(
        amount_unit="serving",
        serving_definition_id=None,
        source_food_updated_at=object(),
        source_recipe_publication_revision_id=None,
    )

    with pytest.raises(LogSourceAmountChangedError) as raised:
        LogService._validate_food_source_precondition(food, payload)

    assert raised.value.code == FIXTURE["reviewed_stale_amount"]["error_code"]


def test_reviewed_food_precondition_fixture_matches_backend_error_precedence() -> None:
    fixture = FIXTURE["reviewed_precondition_precedence"]
    current_serving_id = uuid4()
    current_time = datetime(2026, 8, 9, 13, tzinfo=timezone.utc)
    reviewed_time = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
    food = SimpleNamespace(
        serving_definitions=[SimpleNamespace(id=current_serving_id)],
        updated_at=current_time,
    )

    with pytest.raises(LogSourceAmountChangedError) as serving_error:
        LogService._validate_food_source_precondition(
            food,
            SimpleNamespace(
                amount_unit="serving",
                serving_definition_id=uuid4(),
                source_food_updated_at=reviewed_time,
                source_recipe_publication_revision_id=None,
            ),
        )
    assert serving_error.value.code == fixture["serving_error_code"]

    with pytest.raises(LogSourceChangedError) as gram_error:
        LogService._validate_food_source_precondition(
            food,
            SimpleNamespace(
                amount_unit="g",
                serving_definition_id=uuid4(),
                source_food_updated_at=reviewed_time,
                source_recipe_publication_revision_id=None,
            ),
        )
    assert gram_error.value.code == fixture["gram_error_code"]
