from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core.database import SessionLocal
from app.dependencies.user import ensure_dev_user
from app.schemas.log import DailyLogCreateRequest
from app.services.food_service import FoodService
from app.services.log_service import LogService
from app.services.usda_service import UsdaService


class FakeUsdaClient:
    def __init__(self):
        self.payload = {
            "fdcId": 1105314,
            "description": "Bananas, raw",
            "dataType": "Foundation",
            "publicationDate": "10/30/2020",
            "foodCategory": {"description": "Fruits and Fruit Juices"},
            "foodNutrients": [
                {
                    "nutrient": {"id": 1008, "number": "208", "name": "Energy", "unitName": "KCAL"},
                    "amount": 89,
                },
                {
                    "nutrient": {"id": 1003, "number": "203", "name": "Protein", "unitName": "G"},
                    "amount": 1.09,
                },
                {
                    "nutrient": {"id": 1253, "number": "601", "name": "Cholesterol", "unitName": "MG"},
                    "amount": 0,
                },
            ],
            "foodPortions": [
                {
                    "amount": 1,
                    "gramWeight": 118,
                    "modifier": "medium",
                    "measureUnit": {"name": "banana", "abbreviation": "banana"},
                }
            ],
        }

    def get_food(self, fdc_id: int) -> dict:
        if fdc_id != self.payload["fdcId"]:
            raise AssertionError(f"unexpected fdc_id {fdc_id}")
        return self.payload


class FakeBrandedUsdaClient:
    payload = {
        "fdcId": 555000,
        "description": "Example Protein Bar",
        "dataType": "Branded",
        "brandOwner": "Example Foods",
        "servingSize": 40,
        "servingSizeUnit": "g",
        "householdServingFullText": "1 bar",
        "foodNutrients": [
            {
                "nutrient": {"id": 1008, "number": "208", "name": "Energy", "unitName": "KCAL"},
                "amount": 250,
            },
        ],
    }

    def get_food(self, fdc_id: int) -> dict:
        if fdc_id != self.payload["fdcId"]:
            raise AssertionError(f"unexpected branded fdc_id {fdc_id}")
        return self.payload


def calories_total(summary) -> Decimal:
    return next(total for total in summary if total.nutrient_id == "calories").amount_known


def main() -> None:
    with SessionLocal() as db:
        user = ensure_dev_user(db)
        usda = UsdaService(db, FakeUsdaClient())
        logs = LogService(db)
        foods = FoodService(db)
        logged_date = date(2099, 1, 2)

        food, duplicate = usda.import_food(user.id, 1105314)
        if duplicate:
            raise AssertionError("first USDA import reported duplicate")
        same_food, duplicate = usda.import_food(user.id, 1105314)
        if not duplicate or same_food.id != food.id:
            raise AssertionError("active USDA duplicate import did not return existing food")

        serving_log = logs.create_log(
            user.id,
            DailyLogCreateRequest.model_validate(
                {
                    "food_item_id": food.id,
                    "logged_date": logged_date,
                    "amount_quantity": "1",
                    "amount_unit": "serving",
                }
            ),
        )
        gram_log = logs.create_log(
            user.id,
            DailyLogCreateRequest.model_validate(
                {
                    "food_item_id": food.id,
                    "logged_date": logged_date,
                    "amount_quantity": "50",
                    "amount_unit": "g",
                }
            ),
        )
        if not serving_log.snapshots or not gram_log.snapshots:
            raise AssertionError("USDA logs did not create nutrient snapshots")

        summary = logs.daily_summary(user.id, logged_date)
        if calories_total(summary) != Decimal("133.500000"):
            raise AssertionError(f"unexpected calorie total {calories_total(summary)}")

        vitamin_d = next(total for total in summary if total.nutrient_id == "vitamin_d")
        if not vitamin_d.has_unknown_contributors:
            raise AssertionError("missing USDA nutrient was not preserved as unknown")

        logs.delete_log(user.id, serving_log.id)
        logs.delete_log(user.id, gram_log.id)
        foods.soft_delete_food(user.id, food.id)
        reimported, duplicate = usda.import_food(user.id, 1105314)
        if duplicate or reimported.id == food.id:
            raise AssertionError("soft-deleted USDA import did not create a fresh import")
        foods.soft_delete_food(user.id, reimported.id)

        branded, duplicate = UsdaService(db, FakeBrandedUsdaClient()).import_food(user.id, 555000)
        if duplicate:
            raise AssertionError("first branded USDA import reported duplicate")
        defaults = [serving for serving in branded.serving_definitions if serving.is_default]
        if len(defaults) != 1 or defaults[0].label != "1 bar":
            raise AssertionError("branded USDA serving was not selected as the only default")
        branded_log = logs.create_log(
            user.id,
            DailyLogCreateRequest.model_validate(
                {
                    "food_item_id": branded.id,
                    "logged_date": logged_date,
                    "amount_quantity": "1",
                    "amount_unit": "serving",
                }
            ),
        )
        branded_calories = next(
            snapshot for snapshot in branded_log.snapshots if snapshot.nutrient_id == "calories"
        )
        if branded_calories.amount != Decimal("100.000000"):
            raise AssertionError(f"unexpected branded serving calories {branded_calories.amount}")
        logs.delete_log(user.id, branded_log.id)
        foods.soft_delete_food(user.id, branded.id)


if __name__ == "__main__":
    main()
