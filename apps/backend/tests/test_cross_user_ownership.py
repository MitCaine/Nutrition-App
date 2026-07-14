from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.dependencies.user import ensure_dev_user
from app.models.food import FoodItem
from app.models.log import DailyLog
from app.models.recipe import Recipe, RecipeIngredient
from app.models.recipe_publication import (
    RecipePublicationAmountDefinition,
    RecipePublicationRevision,
)
from app.models.user import User
from app.services.food_service import FoodService
from app.services.recipe_revision_capture_service import (
    CaptureCategory,
    RecipeRevisionCaptureService,
)
from tests.test_recipe_revision_log_editing import _create_serving_log
from tests.test_recipe_revision_logging import _published


def _other_user(db: Session, label: str) -> User:
    user = User(id=uuid4(), email=f"{label}-{uuid4()}@example.test")
    db.add(user)
    db.flush()
    return user


def _foreign_food(db: Session, user: User, *, recipe_marker: bool = False) -> FoodItem:
    food = FoodItem(
        id=uuid4(),
        user_id=user.id,
        name="Foreign private food",
        source_type="recipe" if recipe_marker else "manual",
        source_id=str(uuid4()) if recipe_marker else None,
        is_recipe=recipe_marker,
    )
    db.add(food)
    db.flush()
    return food


@pytest.mark.parametrize("duplicate_occurrences", [False, True])
def test_recipe_create_rejects_foreign_food_without_disclosure(
    client: TestClient,
    db_session: Session,
    duplicate_occurrences: bool,
) -> None:
    foreign = _foreign_food(db_session, _other_user(db_session, "ingredient-create"))
    db_session.commit()
    ingredients = [
        {
            "food_item_id": str(foreign.id),
            "position": index,
            "amount_quantity": "10",
            "amount_unit": "g",
        }
        for index in range(2 if duplicate_occurrences else 1)
    ]

    response = client.post(
        "/api/v1/recipes",
        json={"name": "Private boundary", "ingredients": ingredients},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Food not found"
    assert "Foreign private food" not in response.text


def test_recipe_update_rejects_foreign_managed_projection(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe = client.post(
        "/api/v1/recipes",
        json={"name": "Owned Recipe", "ingredients": []},
    ).json()
    foreign = _foreign_food(
        db_session,
        _other_user(db_session, "ingredient-update"),
        recipe_marker=True,
    )
    db_session.commit()

    response = client.patch(
        f"/api/v1/recipes/{recipe['id']}",
        json={
            "ingredients": [
                {
                    "food_item_id": str(foreign.id),
                    "position": 0,
                    "amount_quantity": "1",
                    "amount_unit": "g",
                }
            ]
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Food not found"
    assert client.get(f"/api/v1/recipes/{recipe['id']}").json()["ingredients"] == []


def test_same_user_nested_recipe_projection_remains_valid(client: TestClient) -> None:
    _, projection = _published(client)

    response = client.post(
        "/api/v1/recipes",
        json={
            "name": "Same-owner parent",
            "ingredients": [
                {
                    "food_item_id": projection["id"],
                    "position": 0,
                    "amount_quantity": "25",
                    "amount_unit": "g",
                }
            ],
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["ingredients"][0]["food_item_id"] == projection["id"]


def test_corrupted_foreign_ingredient_cannot_influence_recipe_nutrition(
    client: TestClient,
    db_session: Session,
) -> None:
    owner = ensure_dev_user(db_session)
    foreign = _foreign_food(db_session, _other_user(db_session, "corrupt-ingredient"))
    recipe = Recipe(
        id=uuid4(),
        user_id=owner.id,
        name="Corrupted Recipe",
        ingredients=[
            RecipeIngredient(
                id=uuid4(),
                food_item_id=foreign.id,
                position=0,
                amount_quantity=Decimal("1"),
                amount_unit="g",
            )
        ],
    )
    db_session.add(recipe)
    db_session.commit()

    response = client.get(f"/api/v1/recipes/{recipe.id}/nutrition")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "ingredient_food_unavailable"
    assert "Foreign private food" not in response.text


def test_logging_and_duplication_reject_foreign_food(
    client: TestClient,
    db_session: Session,
) -> None:
    foreign = _foreign_food(db_session, _other_user(db_session, "log-duplicate"))
    db_session.commit()

    logged = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": str(foreign.id),
            "logged_date": "2026-07-13",
            "amount_quantity": "1",
            "amount_unit": "g",
        },
    )
    duplicated = client.post(f"/api/v1/foods/{foreign.id}/duplicate")

    assert logged.status_code == 400
    assert logged.json()["detail"] == "Food not found"
    assert duplicated.status_code == 404
    assert duplicated.json()["detail"] == "Food not found"


def test_foreign_revision_amount_is_unavailable_to_log_update(
    client: TestClient,
    db_session: Session,
) -> None:
    _, _, log = _create_serving_log(client, db_session)
    other = _other_user(db_session, "foreign-amount")
    foreign_recipe = Recipe(id=uuid4(), user_id=other.id, name="Foreign Recipe")
    foreign_revision = RecipePublicationRevision(
        id=uuid4(),
        recipe_id=foreign_recipe.id,
        user_id=other.id,
        revision_number=1,
        creation_origin="normal_publication",
        provenance_confidence="complete",
        published_name=foreign_recipe.name,
        content_digest="foreign",
    )
    foreign_amount = RecipePublicationAmountDefinition(
        id=uuid4(),
        revision_id=foreign_revision.id,
        display_order=0,
        display_label="1 serving",
        semantic_mode="serving",
        display_quantity=Decimal("1"),
        display_unit="serving",
        gram_equivalent=Decimal("100"),
        is_default=True,
    )
    db_session.add(foreign_recipe)
    db_session.flush()
    db_session.add(foreign_revision)
    db_session.flush()
    db_session.add(foreign_amount)
    db_session.commit()

    response = client.patch(
        f"/api/v1/logs/{log.id}",
        json={"serving_definition_id": str(foreign_amount.id)},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "recipe_log_serving_not_in_revision"
    assert str(foreign_revision.id) not in response.text


def test_corrupted_foreign_log_source_is_reported_unavailable_without_state_leak(
    client: TestClient,
    db_session: Session,
) -> None:
    owner = ensure_dev_user(db_session)
    foreign = _foreign_food(db_session, _other_user(db_session, "foreign-log-source"))
    log = DailyLog(
        id=uuid4(),
        user_id=owner.id,
        food_item_id=foreign.id,
        food_name_snapshot="Historical entry",
        logged_date=date(2026, 7, 14),
        amount_quantity=Decimal("1"),
        amount_unit="g",
    )
    db_session.add(log)
    db_session.commit()

    listed = client.get("/api/v1/logs", params={"date": "2026-07-14"})
    context = client.get(f"/api/v1/logs/{log.id}/edit-context")
    updated = client.patch(f"/api/v1/logs/{log.id}", json={"notes": "change"})

    assert listed.status_code == 200
    assert listed.json()["logs"][0]["source_food_available"] is False
    assert listed.json()["logs"][0]["is_editable"] is False
    assert context.status_code == 200
    assert context.json()["source_food_available"] is False
    assert updated.status_code == 409
    assert "Foreign private food" not in listed.text + context.text + updated.text


def test_revision_log_edit_rejects_corrupted_foreign_source_food(
    client: TestClient,
    db_session: Session,
) -> None:
    _, _, log = _create_serving_log(client, db_session)
    foreign = _foreign_food(db_session, _other_user(db_session, "revision-log-source"))
    log.food_item_id = foreign.id
    db_session.commit()
    db_session.expire_all()

    response = client.patch(f"/api/v1/logs/{log.id}", json={"amount_quantity": "2"})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "recipe_log_source_food_unavailable"
    assert "Foreign private food" not in response.text


def test_capture_ignores_foreign_source_candidate_and_keeps_same_user_scan_clean(
    db_session: Session,
) -> None:
    owner = ensure_dev_user(db_session)
    recipe = Recipe(id=uuid4(), user_id=owner.id, name="Unpublished owner Recipe")
    other = _other_user(db_session, "capture-source")
    foreign_candidate = FoodItem(
        id=uuid4(),
        user_id=other.id,
        name="Foreign candidate",
        source_type="recipe",
        source_id=str(recipe.id),
        is_recipe=True,
    )
    db_session.add_all([recipe, foreign_candidate])
    db_session.commit()

    result = RecipeRevisionCaptureService(db_session).capture_one(recipe.id)

    assert result.category == CaptureCategory.UNPUBLISHED
    assert result.user_id == owner.id


def test_foreign_source_marker_is_not_disclosed_by_projection_error(
    client: TestClient,
    db_session: Session,
) -> None:
    from tests.test_stage2_foods import create_food

    food = create_food(client, "Owned inconsistent marker")
    foreign_recipe_id = uuid4()
    row = db_session.get(FoodItem, UUID(food["id"]))
    row.is_recipe = True
    row.source_type = "recipe"
    row.source_id = str(foreign_recipe_id)
    db_session.commit()

    response = client.get(f"/api/v1/foods/{food['id']}/resolved-nutrition")
    direct = client.get(f"/api/v1/foods/{food['id']}")

    assert response.status_code == 409
    assert direct.status_code == 409
    assert response.json()["detail"]["code"] == "recipe_projection_integrity_invalid"
    assert direct.json()["detail"]["code"] == "recipe_projection_integrity_invalid"
    assert "recipe_id" not in response.json()["detail"]
    assert "recipe_id" not in direct.json()["detail"]
    assert str(foreign_recipe_id) not in response.text + direct.text


def test_foreign_food_cannot_be_loaded_for_duplication_service(
    db_session: Session,
) -> None:
    owner = ensure_dev_user(db_session)
    foreign = _foreign_food(db_session, _other_user(db_session, "duplicate-service"))
    db_session.commit()

    with pytest.raises(LookupError, match="Food not found"):
        FoodService(db_session).duplicate_food(owner.id, foreign.id)
