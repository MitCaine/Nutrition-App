from __future__ import annotations

from datetime import date
from decimal import Decimal
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

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
    / "e4-04"
    / "history-range-parity-fixtures.json"
)

EXPECTED = json.loads(FIXTURE_PATH.read_text())["expected"]


def _assert_postgres_16(db: Session) -> None:
    version = int(db.scalar(text("SHOW server_version_num")) or 0)
    assert 160000 <= version < 170000, "E4-04 qualification requires PostgreSQL 16"


def _seed_owner_food(
    db: Session,
    *,
    user_id: UUID,
    email: str,
) -> UUID:
    db.add(
        User(
            id=user_id,
            email=email,
            display_name="E4-04 PostgreSQL User",
        )
    )
    db.flush()

    establish_test_time_zone(db, user_id, "UTC")

    food = FoodItem(
        id=uuid4(),
        user_id=user_id,
        name="E4-04 PostgreSQL Evidence Food",
        brand=None,
        source_type="manual",
        source_id=None,
        recipe_publication_revision_id=None,
        is_recipe=False,
        notes=None,
    )
    db.add(food)
    db.flush()
    return food.id


def _seed_log(
    db: Session,
    *,
    user_id: UUID,
    food_id: UUID,
    logged_date: date,
) -> DailyLog:
    log = DailyLog(
        id=uuid4(),
        user_id=user_id,
        food_item_id=food_id,
        food_name_snapshot="E4-04 PostgreSQL Evidence Food",
        client_request_id=None,
        client_request_fingerprint=None,
        logged_date=logged_date,
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
    db.flush()
    return log


def _seed_snapshot(
    db: Session,
    *,
    log: DailyLog,
    nutrient_id: str,
    amount: Decimal | None,
    unit: str,
    status: str,
) -> None:
    db.add(
        DailyLogNutrientSnapshot(
            id=uuid4(),
            daily_log_id=log.id,
            source_food_item_id=log.food_item_id,
            source_food_nutrient_id=None,
            serving_definition_id=None,
            nutrient_id=nutrient_id,
            amount=amount,
            unit=unit,
            data_status=status,
            consumed_amount_quantity=Decimal("1.000000"),
            consumed_amount_unit="g",
            consumed_gram_amount=Decimal("1.000000"),
            consumed_package_fraction=None,
            calculation_metadata=None,
        )
    )


def test_postgres_history_range_matches_shared_fixture_and_is_owner_scoped() -> None:
    owner_id = uuid4()
    other_owner_id = uuid4()

    with isolated_postgres_session_factory(
        database_url=POSTGRES_URL,
        schema_prefix="e4_04_history_range",
    ) as factory:
        with factory() as db:
            _assert_postgres_16(db)

            owner_food_id = _seed_owner_food(
                db,
                user_id=owner_id,
                email="e4-04-owner@example.com",
            )
            other_food_id = _seed_owner_food(
                db,
                user_id=other_owner_id,
                email="e4-04-other-owner@example.com",
            )

            # Authority-global firstLoggedDate for the selected owner is before
            # the requested range.
            _seed_log(
                db,
                user_id=owner_id,
                food_id=owner_food_id,
                logged_date=date(2026, 8, 5),
            )

            range_log = _seed_log(
                db,
                user_id=owner_id,
                food_id=owner_food_id,
                logged_date=date(2026, 8, 7),
            )

            # Use a non-canonical source unit here so PostgreSQL qualification
            # proves canonical conversion into the fixture's 1.250000 g.
            _seed_snapshot(
                db,
                log=range_log,
                nutrient_id="protein",
                amount=Decimal("1250.000000"),
                unit="mg",
                status="known",
            )
            _seed_snapshot(
                db,
                log=range_log,
                nutrient_id="protein",
                amount=Decimal("0.500000"),
                unit="g",
                status="estimated",
            )
            _seed_snapshot(
                db,
                log=range_log,
                nutrient_id="protein",
                amount=None,
                unit="g",
                status="unknown",
            )
            _seed_snapshot(
                db,
                log=range_log,
                nutrient_id="added_sugars",
                amount=None,
                unit="g",
                status="zero",
            )
            _seed_snapshot(
                db,
                log=range_log,
                nutrient_id="sodium",
                amount=Decimal("0.000000"),
                unit="mg",
                status="known",
            )
            _seed_snapshot(
                db,
                log=range_log,
                nutrient_id="vitamin_d",
                amount=None,
                unit="mcg",
                status="unknown",
            )

            db.add(
                DailyLogDayCompletion(
                    user_id=owner_id,
                    logged_date=date(2026, 8, 7),
                )
            )

            # Conflicting evidence belonging to another owner must affect
            # neither the requested gap nor firstLoggedDate/Complete metadata.
            _seed_log(
                db,
                user_id=other_owner_id,
                food_id=other_food_id,
                logged_date=date(2026, 8, 1),
            )
            other_gap_log = _seed_log(
                db,
                user_id=other_owner_id,
                food_id=other_food_id,
                logged_date=date(2026, 8, 6),
            )
            _seed_snapshot(
                db,
                log=other_gap_log,
                nutrient_id="protein",
                amount=Decimal("999.000000"),
                unit="g",
                status="known",
            )
            db.add(
                DailyLogDayCompletion(
                    user_id=other_owner_id,
                    logged_date=date(2026, 8, 6),
                )
            )

            db.commit()

            result = LogService(db).history_range(
                owner_id,
                "2026-08-06",
                "2026-08-08",
            )

            assert result.model_dump(mode="json") == EXPECTED

            # Make the isolation evidence explicit rather than relying only on
            # fixture equality.
            assert result.first_logged_date == date(2026, 8, 5)
            assert result.days[0].date == date(2026, 8, 6)
            assert result.days[0].has_logs is False
            assert result.days[0].is_complete is False
            assert result.days[0].nutrients == []
            assert result.days[1].date == date(2026, 8, 7)
            assert result.days[1].has_logs is True
            assert result.days[1].is_complete is True
