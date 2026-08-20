from __future__ import annotations

from datetime import date
from decimal import Decimal
import json
import os
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.food import FoodItem
from app.models.log import (
    DailyLog,
    DailyLogDayCompletion,
    DailyLogNutrientSnapshot,
)
from app.models.user import User
from app.services.log_service import LogService
from tests.postgres_test_support import isolated_postgres_session_factory
from tests.time_zone_test_support import establish_test_time_zone


pytestmark = pytest.mark.postgres_concurrency

POSTGRES_URL = os.getenv(
    "NUTRITION_TEST_POSTGRES_URL",
    "postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app",
)
FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "shared-contracts"
    / "e4-16"
    / "history-parity-fixtures.json"
)


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text())


def _seed_fixture(db: Session, fixture: dict[str, object]) -> None:
    owners = fixture["owners"]
    foods = fixture["foods"]
    logs = fixture["logs"]
    snapshots = fixture["snapshots"]
    completions = fixture["completions"]

    for label, owner_id in owners.items():
        db.add(
            User(
                id=UUID(owner_id),
                email=f"e4-16-{label}@example.com",
                display_name=f"E4-16 {label} owner",
            )
        )
        db.flush()
        establish_test_time_zone(db, UUID(owner_id), "UTC")

    for item in foods:
        db.add(
            FoodItem(
                id=UUID(item["id"]),
                user_id=UUID(item["ownerId"]),
                name=item["name"],
                brand=None,
                source_type="manual",
                source_id=None,
                recipe_publication_revision_id=None,
                is_recipe=False,
                notes=None,
            )
        )
    db.flush()

    log_by_id: dict[str, DailyLog] = {}
    for item in logs:
        log = DailyLog(
            id=UUID(item["id"]),
            user_id=UUID(item["ownerId"]),
            food_item_id=UUID(item["foodId"]),
            food_name_snapshot="E4-16 parity evidence",
            client_request_id=None,
            client_request_fingerprint=None,
            logged_date=date.fromisoformat(item["loggedDate"]),
            meal_type=None,
            amount_quantity=Decimal("1.000000"),
            amount_unit="g",
            serving_definition_id=None,
            recipe_publication_revision_id=None,
            recipe_publication_amount_definition_id=None,
            gram_amount=Decimal("1.000000"),
            package_fraction=None,
            notes=None,
        )
        db.add(log)
        log_by_id[item["id"]] = log
    db.flush()

    for item in snapshots:
        log = log_by_id[item["logId"]]
        db.add(
            DailyLogNutrientSnapshot(
                id=UUID(item["id"]),
                daily_log_id=log.id,
                source_food_item_id=log.food_item_id,
                source_food_nutrient_id=None,
                serving_definition_id=None,
                nutrient_id=item["nutrientId"],
                amount=(
                    None
                    if item["amount"] is None
                    else Decimal(item["amount"])
                ),
                unit=item["unit"],
                data_status=item["status"],
                consumed_amount_quantity=Decimal("1.000000"),
                consumed_amount_unit="g",
                consumed_gram_amount=Decimal("1.000000"),
                consumed_package_fraction=None,
                calculation_metadata=None,
            )
        )

    for item in completions:
        db.add(
            DailyLogDayCompletion(
                user_id=UUID(item["ownerId"]),
                logged_date=date.fromisoformat(item["loggedDate"]),
            )
        )
    db.commit()


def test_postgres_fixture_matches_selected_owner_and_no_history_contracts() -> None:
    fixture = _fixture()
    owners = fixture["owners"]
    range_contract = fixture["range"]

    with isolated_postgres_session_factory(
        database_url=POSTGRES_URL,
        schema_prefix="e4_16_history_parity",
    ) as factory:
        with factory() as db:
            version = int(db.scalar(text("SHOW server_version_num")) or 0)
            assert 160000 <= version < 170000, "E4-16 requires PostgreSQL 16"
            _seed_fixture(db, fixture)

            selected = LogService(db).history_range(
                UUID(owners["selected"]),
                range_contract["startDate"],
                range_contract["endDate"],
            )
            assert selected.model_dump(mode="json") == fixture["expectedRemoteEvidence"]

            no_history = LogService(db).history_range(
                UUID(owners["noHistory"]),
                range_contract["startDate"],
                range_contract["endDate"],
            )
            assert no_history.model_dump(mode="json") == fixture["expectedNoHistoryEvidence"]

            selected_dump = selected.model_dump(mode="json")
            assert selected_dump["first_logged_date"] == range_contract["firstLoggedDate"]
            assert selected_dump["days"][0] == {
                "date": range_contract["startDate"],
                "has_logs": False,
                "is_complete": False,
                "nutrients": [],
            }
