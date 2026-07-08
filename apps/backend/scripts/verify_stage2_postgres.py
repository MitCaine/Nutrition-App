from __future__ import annotations

from datetime import date

from app.core.database import SessionLocal
from app.dependencies.user import ensure_dev_user
from app.schemas.food import FoodCreateRequest, FoodUpdateRequest
from app.schemas.log import DailyLogCreateRequest, DailyLogUpdateRequest
from app.services.food_service import FoodService
from app.services.log_service import LogService


def food_payload(name: str, protein: str, gram_weight: str) -> dict:
    return {
        "name": name,
        "brand": "Postgres Verification",
        "notes": "temporary Stage 2 verification food",
        "serving_definitions": [
            {
                "label": "1 serving",
                "quantity": "1",
                "unit": "serving",
                "gram_weight": gram_weight,
                "is_default": True,
            }
        ],
        "nutrients": [
            {
                "nutrient_id": "calories",
                "amount": "100",
                "unit": "kcal",
                "basis": "per_serving",
                "data_status": "known",
            },
            {
                "nutrient_id": "protein",
                "amount": protein,
                "unit": "g",
                "basis": "per_serving",
                "data_status": "known",
            },
        ],
    }


def protein_total(summary) -> str:
    return str(next(total for total in summary if total.nutrient_id == "protein").amount_known)


def main() -> None:
    with SessionLocal() as db:
        user = ensure_dev_user(db)
        foods = FoodService(db)
        logs = LogService(db)
        logged_date = date(2099, 1, 1)

        food = foods.create_manual_food(
            user.id,
            FoodCreateRequest.model_validate(food_payload("PG Verification Food", "20", "100")),
        )
        log = logs.create_log(
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
        before = protein_total(logs.daily_summary(user.id, logged_date))
        if before != "20.000000":
            raise AssertionError(f"expected initial protein 20.000000, got {before}")

        foods.update_food(
            user.id,
            food.id,
            FoodUpdateRequest.model_validate(food_payload("PG Verification Food Edited", "35", "150")),
        )
        after_food_edit = protein_total(logs.daily_summary(user.id, logged_date))
        if after_food_edit != "20.000000":
            raise AssertionError(
                f"food edit changed historical protein total: {after_food_edit}"
            )

        historical_log = logs.list_logs(user.id, logged_date)[0]
        if historical_log.serving_definition_id is not None:
            raise AssertionError("historical daily log serving_definition_id was not set null")
        if not historical_log.snapshots:
            raise AssertionError("historical snapshots were removed")
        if not any(snapshot.source_food_nutrient_id is None for snapshot in historical_log.snapshots):
            raise AssertionError("deleted nutrient provenance was not set null")
        if not any(snapshot.serving_definition_id is None for snapshot in historical_log.snapshots):
            raise AssertionError("deleted serving provenance was not set null")

        updated_log = logs.update_log(
            user.id,
            log.id,
            DailyLogUpdateRequest.model_validate(
                {"amount_quantity": "2", "amount_unit": "serving"}
            ),
        )
        if len(updated_log.snapshots) != 2:
            raise AssertionError("log update did not rebuild snapshots")
        after_log_update = protein_total(logs.daily_summary(user.id, logged_date))
        if after_log_update != "70.000000":
            raise AssertionError(f"expected updated protein 70.000000, got {after_log_update}")

        logs.delete_log(user.id, log.id)
        if logs.daily_summary(user.id, logged_date):
            raise AssertionError("log deletion left snapshots in daily summary")

        foods.soft_delete_food(user.id, food.id)


if __name__ == "__main__":
    main()
