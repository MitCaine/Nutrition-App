from __future__ import annotations

from copy import deepcopy

import pytest

from app.transfer.e2_15 import CONTRACT, SOURCE_SCHEMA
from app.transfer.e2_15_exporter import (
    CURRENT_EXPORT_SOURCE_REVISION,
    TransferExportError,
    project_current_source_tables_to_frozen_contract,
)


def _current_tables() -> dict:
    return deepcopy(SOURCE_SCHEMA["tables"])


def test_current_0027_source_uses_the_v2_pg_0027_contract_without_projection() -> None:
    assert CURRENT_EXPORT_SOURCE_REVISION == "0027_serving_reference_measurement"
    assert CONTRACT["format_version"] == "2"
    assert CONTRACT["source"]["alembic_revision"] == "0027_serving_reference_measurement"
    assert SOURCE_SCHEMA["alembic_revision"] == "0027_serving_reference_measurement"
    serving_columns = [row["name"] for row in SOURCE_SCHEMA["tables"]["serving_definitions"]["columns"]]
    assert serving_columns[6:9] == [
        "reference_quantity",
        "reference_unit",
        "reference_gram_weight",
    ]

    assert project_current_source_tables_to_frozen_contract(_current_tables()) == SOURCE_SCHEMA["tables"]


def test_current_contract_rejects_missing_food_integrity_check() -> None:
    tables = _current_tables()
    tables["food_nutrients"]["checks"] = [
        item for item in tables["food_nutrients"]["checks"]
        if item["name"] != "ck_food_nutrients_amount_nonnegative"
    ]
    with pytest.raises(TransferExportError) as caught:
        project_current_source_tables_to_frozen_contract(tables)
    assert caught.value.code == "source_schema_invalid"


def test_current_contract_rejects_changed_food_integrity_check() -> None:
    tables = _current_tables()
    for item in tables["food_nutrients"]["checks"]:
        if item["name"] == "ck_food_nutrients_amount_nonnegative":
            item["expression"] = "amount >= 0::numeric"
    with pytest.raises(TransferExportError) as caught:
        project_current_source_tables_to_frozen_contract(tables)
    assert caught.value.code == "source_schema_invalid"


def test_current_contract_rejects_missing_serving_reference_column() -> None:
    tables = _current_tables()
    tables["serving_definitions"]["columns"] = [
        item for item in tables["serving_definitions"]["columns"]
        if item["name"] != "reference_gram_weight"
    ]
    with pytest.raises(TransferExportError) as caught:
        project_current_source_tables_to_frozen_contract(tables)
    assert caught.value.code == "source_schema_invalid"


def test_current_contract_rejects_unexpected_current_schema_extension() -> None:
    tables = _current_tables()
    tables["food_nutrients"]["checks"].append(
        {"expression": "amount <= 999999::numeric", "name": "unexpected_food_nutrient_check"}
    )
    with pytest.raises(TransferExportError) as caught:
        project_current_source_tables_to_frozen_contract(tables)
    assert caught.value.code == "source_schema_invalid"
