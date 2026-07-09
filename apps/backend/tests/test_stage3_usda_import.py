from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.dependencies.user import ensure_dev_user
from app.models.food import FoodItem, FoodNutrient, ServingDefinition
from app.repositories.food_repository import FoodRepository
from app.schemas.log import DailyLogCreateRequest
from app.services.log_service import LogService
from app.services.usda_service import UsdaService
from tests.test_stage3_usda_mapper import (
    usda_banana_payload,
    usda_branded_bar_payload,
    usda_branded_full_macro_payload,
)


class FakeUsdaClient:
    def __init__(self, payload: dict):
        self.payload = payload
        self.detail_calls = 0

    def search_foods(self, query: str, *, page_size: int = 25, page_number: int = 1) -> dict:
        return {
            "totalHits": 1,
            "foods": [
                {
                    "fdcId": self.payload["fdcId"],
                    "description": self.payload["description"],
                    "dataType": self.payload["dataType"],
                }
            ],
        }

    def get_food(self, fdc_id: int) -> dict:
        self.detail_calls += 1
        assert fdc_id == self.payload["fdcId"]
        return self.payload


def test_usda_import_persists_source_metadata_and_prevents_active_duplicates(
    db_session: Session,
) -> None:
    user = ensure_dev_user(db_session)
    db_session.commit()
    service = UsdaService(db_session, FakeUsdaClient(usda_banana_payload()))

    food, duplicate = service.import_food(user.id, 1105314)
    same_food, second_duplicate = service.import_food(user.id, 1105314)

    assert duplicate is False
    assert second_duplicate is True
    assert same_food.id == food.id
    assert food.source_type == "usda"
    assert food.source_id == "1105314"
    assert food.sources[0].source_type == "usda_fdc"
    assert food.sources[0].source_metadata["fdc_id"] == 1105314
    assert any(nutrient.nutrient_id == "vitamin_d" and nutrient.data_status == "unknown" for nutrient in food.nutrients)


def test_usda_import_persists_normalized_nutrients_exactly_as_mapped(
    db_session: Session,
) -> None:
    user = ensure_dev_user(db_session)
    db_session.commit()
    food, duplicate = UsdaService(db_session, FakeUsdaClient(usda_banana_payload())).import_food(user.id, 1105314)
    nutrients = {nutrient.nutrient_id: nutrient for nutrient in food.nutrients}

    assert duplicate is False
    assert nutrients["calories"].amount == Decimal("89.000000")
    assert nutrients["calories"].unit == "kcal"
    assert nutrients["calories"].basis == "per_100g"
    assert nutrients["calories"].data_status == "known"
    assert nutrients["calories"].source == "usda_fdc"
    assert nutrients["calories"].is_user_confirmed is False
    assert nutrients["calories"].original_amount == Decimal("89.000000")
    assert nutrients["calories"].original_unit == "KCAL"
    assert nutrients["calories"].original_text == "1008"

    assert nutrients["cholesterol"].amount == Decimal("0.000000")
    assert nutrients["cholesterol"].data_status == "zero"
    assert nutrients["cholesterol"].source == "usda_fdc"
    assert nutrients["cholesterol"].is_user_confirmed is False

    assert nutrients["vitamin_d"].amount is None
    assert nutrients["vitamin_d"].unit == "mcg"
    assert nutrients["vitamin_d"].basis == "per_100g"
    assert nutrients["vitamin_d"].data_status == "unknown"
    assert nutrients["vitamin_d"].source == "usda_fdc"
    assert nutrients["vitamin_d"].is_user_confirmed is False


def test_soft_deleted_usda_import_can_be_reimported(db_session: Session) -> None:
    user = ensure_dev_user(db_session)
    db_session.commit()
    service = UsdaService(db_session, FakeUsdaClient(usda_banana_payload()))

    food, _duplicate = service.import_food(user.id, 1105314)
    food.deleted_at = datetime(2026, 7, 8, tzinfo=timezone.utc)
    db_session.commit()
    reimported, duplicate = service.import_food(user.id, 1105314)

    assert duplicate is False
    assert reimported.id != food.id


def test_imported_usda_food_logs_by_serving_and_grams_with_snapshots(
    db_session: Session,
) -> None:
    user = ensure_dev_user(db_session)
    db_session.commit()
    food, _duplicate = UsdaService(db_session, FakeUsdaClient(usda_banana_payload())).import_food(user.id, 1105314)
    log_service = LogService(db_session)

    serving_log = log_service.create_log(
        user.id,
        DailyLogCreateRequest(
            food_item_id=food.id,
            logged_date=date(2026, 7, 8),
            amount_quantity="1",
            amount_unit="serving",
        ),
    )
    gram_log = log_service.create_log(
        user.id,
        DailyLogCreateRequest(
            food_item_id=food.id,
            logged_date=date(2026, 7, 8),
            amount_quantity="50",
            amount_unit="g",
        ),
    )

    serving_calories = next(snapshot for snapshot in serving_log.snapshots if snapshot.nutrient_id == "calories")
    gram_calories = next(snapshot for snapshot in gram_log.snapshots if snapshot.nutrient_id == "calories")
    vitamin_d = next(snapshot for snapshot in serving_log.snapshots if snapshot.nutrient_id == "vitamin_d")

    assert serving_calories.amount == Decimal("89.000000")
    assert gram_calories.amount == Decimal("44.500000")
    assert vitamin_d.amount is None
    assert vitamin_d.data_status == "unknown"

    totals = {total.nutrient_id: total for total in log_service.daily_summary(user.id, date(2026, 7, 8))}
    assert totals["calories"].amount_known == serving_calories.amount + gram_calories.amount
    assert totals["vitamin_d"].has_unknown_contributors is True


def test_imported_branded_usda_food_logs_by_selected_default_serving(
    db_session: Session,
) -> None:
    user = ensure_dev_user(db_session)
    db_session.commit()
    food, _duplicate = UsdaService(db_session, FakeUsdaClient(usda_branded_bar_payload())).import_food(user.id, 555000)
    default_serving = next(serving for serving in food.serving_definitions if serving.is_default)

    log = LogService(db_session).create_log(
        user.id,
        DailyLogCreateRequest(
            food_item_id=food.id,
            logged_date=date(2026, 7, 8),
            amount_quantity="1",
            amount_unit="serving",
        ),
    )
    calories = next(snapshot for snapshot in log.snapshots if snapshot.nutrient_id == "calories")

    assert default_serving.label == "1 bar"
    assert default_serving.gram_weight == Decimal("40.000000")
    assert calories.serving_definition_id == default_serving.id
    assert calories.consumed_gram_amount == Decimal("40.000000")
    assert calories.amount == Decimal("100.000000")


def test_imported_branded_default_serving_survives_repository_retrieval(
    db_session: Session,
) -> None:
    user = ensure_dev_user(db_session)
    db_session.commit()
    food, _duplicate = UsdaService(db_session, FakeUsdaClient(usda_branded_bar_payload())).import_food(user.id, 555000)

    retrieved = FoodRepository(db_session).get_required(food.id, user.id)
    defaults = [serving for serving in retrieved.serving_definitions if serving.is_default]

    assert len(defaults) == 1
    assert defaults[0].label == "1 bar"
    assert defaults[0].gram_weight == Decimal("40.000000")
    assert defaults[0].source == "usda_fdc"
    assert defaults[0].is_user_confirmed is False
    assert any(serving.label == "100 g" and not serving.is_default for serving in retrieved.serving_definitions)


def test_imported_branded_serving_preserves_per_100g_nutrient_basis(
    db_session: Session,
) -> None:
    user = ensure_dev_user(db_session)
    db_session.commit()
    food, _duplicate = UsdaService(db_session, FakeUsdaClient(usda_branded_full_macro_payload())).import_food(user.id, 555001)
    default_serving = next(serving for serving in food.serving_definitions if serving.is_default)

    log = LogService(db_session).create_log(
        user.id,
        DailyLogCreateRequest(
            food_item_id=food.id,
            logged_date=date(2026, 7, 8),
            amount_quantity="1",
            amount_unit="serving",
        ),
    )
    nutrients = {snapshot.nutrient_id: snapshot for snapshot in log.snapshots}

    assert default_serving.label == "1 bar"
    assert default_serving.gram_weight == Decimal("50.000000")
    assert next(nutrient for nutrient in food.nutrients if nutrient.nutrient_id == "calories").basis == "per_100g"
    assert nutrients["calories"].amount == Decimal("150.000000")
    assert nutrients["protein"].amount == Decimal("9.000000")
    assert nutrients["calcium"].amount == Decimal("100.000000")


def test_generic_food_logging_uses_default_serving_grams_with_per_100g_nutrients(
    db_session: Session,
) -> None:
    user = ensure_dev_user(db_session)
    db_session.commit()
    food = FoodItem(
        id=uuid4(),
        user_id=user.id,
        name="Generic Per 100g Food",
        brand=None,
        notes=None,
        source_type="manual",
        source_id=None,
        is_recipe=False,
    )
    food.serving_definitions.append(
        ServingDefinition(
            id=uuid4(),
            label="1 slice",
            quantity=Decimal("1"),
            unit="slice",
            gram_weight=Decimal("30"),
            is_default=True,
            source="manual",
            is_user_confirmed=True,
        )
    )
    food.nutrients.append(
        FoodNutrient(
            id=uuid4(),
            nutrient_id="protein",
            amount=Decimal("10"),
            unit="g",
            basis="per_100g",
            data_status="known",
            source="manual",
            is_user_confirmed=True,
        )
    )
    db_session.add(food)
    db_session.commit()

    log = LogService(db_session).create_log(
        user.id,
        DailyLogCreateRequest(
            food_item_id=food.id,
            logged_date=date(2026, 7, 8),
            amount_quantity="2",
            amount_unit="serving",
        ),
    )
    protein = next(snapshot for snapshot in log.snapshots if snapshot.nutrient_id == "protein")

    assert protein.consumed_gram_amount == Decimal("60.000000")
    assert protein.amount == Decimal("6.000000")


def test_imported_usda_food_retrieves_through_normal_food_repository(db_session: Session) -> None:
    user = ensure_dev_user(db_session)
    db_session.commit()
    food, _duplicate = UsdaService(db_session, FakeUsdaClient(usda_banana_payload())).import_food(user.id, 1105314)

    retrieved = FoodRepository(db_session).get_required(food.id, user.id)

    assert isinstance(retrieved, FoodItem)
    assert retrieved.name == "Bananas, raw"
    assert retrieved.source_type == "usda"
    assert len(retrieved.serving_definitions) >= 1
    assert len(retrieved.nutrients) >= 1


def test_usda_import_recovers_from_source_identity_race(
    db_session: Session,
    monkeypatch,
) -> None:
    user = ensure_dev_user(db_session)
    db_session.commit()
    service = UsdaService(db_session, FakeUsdaClient(usda_banana_payload()))
    repository = FoodRepository(db_session)
    lookup_count = 0

    class Diag:
        constraint_name = "ix_food_items_active_source_identity"

    class UniqueViolation(Exception):
        diag = Diag()
        sqlstate = "23505"

        def __str__(self) -> str:
            return "duplicate key value violates unique constraint ix_food_items_active_source_identity"

    def raced_find(user_id, source_type, source_id):
        nonlocal lookup_count
        lookup_count += 1
        if lookup_count == 1:
            return None
        return repository.find_active_by_source(user_id, source_type, source_id)

    def raced_add(_food):
        existing = FoodItem(
            id=_food.id,
            user_id=user.id,
            name="Bananas, raw",
            brand=None,
            notes=None,
            source_type="usda",
            source_id="1105314",
            is_recipe=False,
        )
        existing.serving_definitions.append(
            ServingDefinition(
                id=_food.serving_definitions[0].id,
                label="100 g",
                quantity=Decimal("100"),
                unit="g",
                gram_weight=Decimal("100"),
                is_default=True,
                source="usda_fdc",
                is_user_confirmed=False,
            )
        )
        db_session.add(existing)
        db_session.commit()
        raise IntegrityError("insert", {}, UniqueViolation())

    monkeypatch.setattr(service.foods, "find_active_by_source", raced_find)
    monkeypatch.setattr(service.foods, "add", raced_add)

    food, duplicate = service.import_food(user.id, 1105314)

    assert duplicate is True
    assert food.source_type == "usda"
    assert food.source_id == "1105314"
