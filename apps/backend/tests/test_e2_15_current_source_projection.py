from __future__ import annotations

from copy import deepcopy

import pytest

from app.transfer.e2_15 import CONTRACT, SOURCE_SCHEMA
from app.transfer.e2_15_exporter import (
    CURRENT_EXPORT_SOURCE_REVISION,
    EXPECTED_0026_FOOD_NUTRIENT_CHECK,
    EXPECTED_0026_FOOD_NUTRIENT_UNIQUE,
    TransferExportError,
    project_current_source_tables_to_frozen_contract,
)


def _current_tables() -> dict:
    tables = deepcopy(SOURCE_SCHEMA["tables"])
    food = tables["food_nutrients"]
    food["checks"].append(
        deepcopy(EXPECTED_0026_FOOD_NUTRIENT_CHECK)
    )
    food["unique_constraints"].append(
        deepcopy(EXPECTED_0026_FOOD_NUTRIENT_UNIQUE)
    )
    food["checks"].sort(
        key=lambda item: (item["name"] or "", item["expression"])
    )
    food["unique_constraints"].sort(
        key=lambda item: (item["name"] or "", item["columns"])
    )
    return tables


def test_current_0026_source_projects_exactly_to_frozen_pg_0025() -> None:
    assert CURRENT_EXPORT_SOURCE_REVISION == "0026_food_nutrient_integrity"
    assert CONTRACT["source"]["alembic_revision"] == (
        "0025_immutable_validator_head"
    )
    assert SOURCE_SCHEMA["alembic_revision"] == (
        "0025_immutable_validator_head"
    )

    assert (
        project_current_source_tables_to_frozen_contract(
            _current_tables()
        )
        == SOURCE_SCHEMA["tables"]
    )


def test_projection_rejects_missing_0026_check() -> None:
    tables = _current_tables()
    tables["food_nutrients"]["checks"] = [
        item
        for item in tables["food_nutrients"]["checks"]
        if item["name"]
        != "ck_food_nutrients_amount_nonnegative"
    ]

    with pytest.raises(TransferExportError) as caught:
        project_current_source_tables_to_frozen_contract(tables)

    assert caught.value.code == "source_schema_invalid"


def test_projection_rejects_changed_0026_check() -> None:
    tables = _current_tables()

    for item in tables["food_nutrients"]["checks"]:
        if item["name"] == "ck_food_nutrients_amount_nonnegative":
            item["expression"] = "amount >= 0::numeric"

    with pytest.raises(TransferExportError) as caught:
        project_current_source_tables_to_frozen_contract(tables)

    assert caught.value.code == "source_schema_invalid"


def test_projection_rejects_missing_0026_unique() -> None:
    tables = _current_tables()
    tables["food_nutrients"]["unique_constraints"] = [
        item
        for item in tables["food_nutrients"]["unique_constraints"]
        if item["name"] != "uq_food_nutrients_food_nutrient_basis"
    ]

    with pytest.raises(TransferExportError) as caught:
        project_current_source_tables_to_frozen_contract(tables)

    assert caught.value.code == "source_schema_invalid"


def test_projection_rejects_unexpected_current_schema_extension() -> None:
    tables = _current_tables()
    tables["food_nutrients"]["checks"].append(
        {
            "expression": "amount <= 999999::numeric",
            "name": "unexpected_food_nutrient_check",
        }
    )

    with pytest.raises(TransferExportError) as caught:
        project_current_source_tables_to_frozen_contract(tables)

    assert caught.value.code == "source_schema_invalid"
