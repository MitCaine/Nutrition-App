from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.food import (
    FoodCreateRequest,
    FoodNutrientInput,
    FoodUpdateRequest,
)


def _nutrient(
    *,
    basis: str = "per_100g",
    amount: str | None = "10",
    status: str = "known",
) -> dict:
    return {
        "nutrient_id": "protein",
        "amount": amount,
        "unit": "g",
        "basis": basis,
        "data_status": status,
    }


def _create_payload(nutrients: list[dict]) -> dict:
    return {
        "name": "Integrity Food",
        "brand": None,
        "notes": None,
        "serving_definitions": [
            {
                "label": "100 g",
                "quantity": "100",
                "unit": "g",
                "gram_weight": "100",
                "is_default": True,
            }
        ],
        "nutrients": nutrients,
    }


def test_negative_authoritative_nutrient_is_rejected() -> None:
    with pytest.raises(
        ValidationError,
        match="nutrient amounts must be non-negative",
    ):
        FoodNutrientInput.model_validate(
            _nutrient(amount="-0.000001")
        )


def test_create_rejects_duplicate_same_basis_identity() -> None:
    with pytest.raises(
        ValidationError,
        match="duplicate nutrient identities",
    ):
        FoodCreateRequest.model_validate(
            _create_payload(
                [
                    _nutrient(basis="per_100g"),
                    _nutrient(basis="per_100g", amount="20"),
                ]
            )
        )


def test_update_rejects_duplicate_same_basis_identity() -> None:
    with pytest.raises(
        ValidationError,
        match="duplicate nutrient identities",
    ):
        FoodUpdateRequest.model_validate(
            {
                "nutrients": [
                    _nutrient(basis="per_serving"),
                    _nutrient(
                        basis="per_serving",
                        amount="20",
                    ),
                ]
            }
        )


def test_same_nutrient_at_distinct_bases_is_valid() -> None:
    request = FoodCreateRequest.model_validate(
        _create_payload(
            [
                _nutrient(
                    basis="per_100g",
                    amount="10",
                ),
                _nutrient(
                    basis="per_serving",
                    amount="20",
                ),
            ]
        )
    )

    assert {
        nutrient.basis.value
        for nutrient in request.nutrients
    } == {
        "per_100g",
        "per_serving",
    }


def test_zero_and_unknown_semantics_remain_unchanged() -> None:
    zero = FoodNutrientInput.model_validate(
        _nutrient(
            amount="7",
            status="zero",
        )
    )
    unknown = FoodNutrientInput.model_validate(
        _nutrient(
            amount=None,
            status="unknown",
        )
    )

    assert zero.amount == Decimal("0")
    assert unknown.amount is None
