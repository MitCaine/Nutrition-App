from __future__ import annotations

from decimal import Decimal
from importlib import import_module
from uuid import UUID, uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.models.food import ServingDefinition
from app.models.food import FoodItem
from app.models.recipe import Recipe, RecipeIngredient
from app.models.user import User


integrity_migration = import_module(
    "app.migrations.versions.0013_food_recipe_dependency_integrity"
)


def _two_serving_food(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/foods",
        json={
            "name": "Two Serving Food",
            "serving_definitions": [
                {
                    "label": "1 cup",
                    "quantity": "1",
                    "unit": "cup",
                    "gram_weight": "100",
                    "is_default": True,
                },
                {
                    "label": "1 scoop",
                    "quantity": "1",
                    "unit": "scoop",
                    "gram_weight": "30",
                    "is_default": False,
                },
            ],
            "nutrients": [
                {
                    "nutrient_id": "calories",
                    "amount": "100",
                    "unit": "kcal",
                    "basis": "per_100g",
                    "data_status": "known",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _calories(client: TestClient, recipe_id: str) -> Decimal:
    response = client.get(f"/api/v1/recipes/{recipe_id}/nutrition")
    assert response.status_code == 200, response.text
    calories = next(row for row in response.json()["totals"] if row["nutrient_id"] == "calories")
    return Decimal(calories["amount_known"])


def _recipe(client: TestClient, food: dict, serving_id: str | None, *, published: bool) -> dict:
    ingredient = {
        "food_item_id": food["id"],
        "position": 0,
        "amount_quantity": "1" if serving_id else "30",
        "amount_unit": "serving" if serving_id else "g",
    }
    if serving_id:
        ingredient["serving_definition_id"] = serving_id
    response = client.post(
        "/api/v1/recipes",
        json={
            "name": "Published Parent" if published else "Draft Parent",
            "serving_count_yield": "1",
            "ingredients": [ingredient],
        },
    )
    assert response.status_code == 201, response.text
    recipe = response.json()
    if published:
        publication = client.post(f"/api/v1/recipes/{recipe['id']}/publish")
        assert publication.status_code == 200, publication.text
        recipe = publication.json()["recipe"]
    return recipe


def test_removed_food_serving_conflicts_and_rolls_back_without_reinterpreting_recipe(
    client: TestClient,
    db_session: Session,
) -> None:
    food = _two_serving_food(client)
    selected = next(row for row in food["serving_definitions"] if not row["is_default"])
    recipe = _recipe(client, food, selected["id"], published=True)
    db_session.expire_all()
    before = db_session.get(Recipe, UUID(recipe["id"]))
    original_revision_id = before.active_publication_revision_id
    original_projection_id = before.published_food_item_id
    assert _calories(client, recipe["id"]) == Decimal("30.000000")

    update = client.patch(
        f"/api/v1/foods/{food['id']}",
        json={
            "serving_definitions": [
                {
                    "label": "1 cup",
                    "quantity": "1",
                    "unit": "cup",
                    "gram_weight": "100",
                    "is_default": True,
                }
            ]
        },
    )

    assert update.status_code == 409, update.text
    assert update.json()["detail"]["code"] == "food_update_recipe_serving_conflict"
    assert update.json()["detail"]["affected_recipes"] == [
        {
            "recipe_id": recipe["id"],
            "recipe_name": "Published Parent",
            "ingredients": [{"position": 0, "old_serving_label": "1 scoop"}],
        }
    ]
    db_session.expire_all()
    stored = db_session.get(Recipe, UUID(recipe["id"]))
    assert db_session.get(ServingDefinition, UUID(selected["id"])) is not None
    assert stored.ingredients[0].serving_definition_id == UUID(selected["id"])
    assert _calories(client, recipe["id"]) == Decimal("30.000000")
    assert stored.needs_republish is False
    assert stored.active_publication_revision_id == original_revision_id
    assert stored.published_food_item_id == original_projection_id


def test_equivalent_serving_label_rename_remaps_and_marks_published_parent_stale(
    client: TestClient,
    db_session: Session,
) -> None:
    food = _two_serving_food(client)
    selected = next(row for row in food["serving_definitions"] if not row["is_default"])
    recipe = _recipe(client, food, selected["id"], published=True)
    db_session.expire_all()
    before = db_session.get(Recipe, UUID(recipe["id"]))
    revision_id = before.active_publication_revision_id
    projection_id = before.published_food_item_id

    update = client.patch(
        f"/api/v1/foods/{food['id']}",
        json={
            "serving_definitions": [
                {
                    "label": "Cup renamed",
                    "quantity": "1.0",
                    "unit": "cup",
                    "gram_weight": "100.0",
                    "is_default": True,
                },
                {
                    "label": "Scoop renamed",
                    "quantity": "1.00",
                    "unit": "scoop",
                    "gram_weight": "30.00",
                    "is_default": False,
                },
            ]
        },
    )

    assert update.status_code == 200, update.text
    successor = next(row for row in update.json()["serving_definitions"] if row["unit"] == "scoop")
    assert successor["id"] != selected["id"]
    db_session.expire_all()
    stored = db_session.get(Recipe, UUID(recipe["id"]))
    assert stored.ingredients[0].serving_definition_id == UUID(successor["id"])
    assert stored.needs_republish is True
    assert stored.active_publication_revision_id == revision_id
    assert stored.published_food_item_id == projection_id
    assert _calories(client, recipe["id"]) == Decimal("30.000000")


def test_changed_or_ambiguous_serving_successor_conflicts(client: TestClient) -> None:
    food = _two_serving_food(client)
    selected = next(row for row in food["serving_definitions"] if not row["is_default"])
    _recipe(client, food, selected["id"], published=False)

    changed = client.patch(
        f"/api/v1/foods/{food['id']}",
        json={
            "serving_definitions": [
                {"label": "Cup", "quantity": "1", "unit": "cup", "gram_weight": "100", "is_default": True},
                {"label": "Scoop", "quantity": "1", "unit": "scoop", "gram_weight": "35", "is_default": False},
            ]
        },
    )
    assert changed.status_code == 409

    ambiguous = client.patch(
        f"/api/v1/foods/{food['id']}",
        json={
            "serving_definitions": [
                {"label": "Cup", "quantity": "1", "unit": "cup", "gram_weight": "100", "is_default": True},
                {"label": "Scoop A", "quantity": "1", "unit": "scoop", "gram_weight": "30", "is_default": False},
                {"label": "Scoop B", "quantity": "1", "unit": "scoop", "gram_weight": "30", "is_default": False},
            ]
        },
    )
    assert ambiguous.status_code == 409


def test_nutrient_change_preserves_gram_ingredient_and_stales_only_published_parent(
    client: TestClient,
    db_session: Session,
) -> None:
    food = _two_serving_food(client)
    published = _recipe(client, food, None, published=True)
    draft = _recipe(client, food, None, published=False)

    update = client.patch(
        f"/api/v1/foods/{food['id']}",
        json={
            "nutrients": [
                {
                    "nutrient_id": "calories",
                    "amount": "200",
                    "unit": "kcal",
                    "basis": "per_100g",
                    "data_status": "known",
                }
            ]
        },
    )
    assert update.status_code == 200, update.text
    db_session.expire_all()
    stored_published = db_session.get(Recipe, UUID(published["id"]))
    stored_draft = db_session.get(Recipe, UUID(draft["id"]))
    assert stored_published.ingredients[0].amount_quantity == Decimal("30")
    assert stored_published.ingredients[0].serving_definition_id is None
    assert stored_published.needs_republish is True
    assert stored_draft.needs_republish is False


def test_sqlite_migration_repairs_multiple_defaults_and_round_trips_indexes(
    db_session: Session,
) -> None:
    connection = db_session.connection()
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        integrity_migration.downgrade()

    db_session.add(
        User(
            id=UUID("00000000-0000-0000-0000-000000000001"),
            email="migration-integrity@example.test",
        )
    )
    db_session.flush()
    food = FoodItem(
        id=UUID("10000000-0000-0000-0000-000000000001"),
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        name="Legacy defaults",
        source_type="manual",
        is_recipe=False,
        serving_definitions=[
            ServingDefinition(
                id=UUID("20000000-0000-0000-0000-000000000001"),
                label="First",
                quantity=Decimal("1"),
                unit="portion",
                gram_weight=Decimal("10"),
                is_default=True,
                source="manual",
                is_user_confirmed=True,
            ),
            ServingDefinition(
                id=UUID("20000000-0000-0000-0000-000000000002"),
                label="Second",
                quantity=Decimal("1"),
                unit="portion",
                gram_weight=Decimal("20"),
                is_default=True,
                source="manual",
                is_user_confirmed=True,
            ),
        ],
    )
    db_session.add(food)
    db_session.flush()

    with Operations.context(context):
        integrity_migration.upgrade()
    db_session.expire_all()
    defaults = list(
        db_session.scalars(
            select(ServingDefinition)
            .where(
                ServingDefinition.food_item_id == food.id,
                ServingDefinition.is_default.is_(True),
            )
            .order_by(ServingDefinition.id)
        )
    )
    assert [row.id for row in defaults] == [UUID("20000000-0000-0000-0000-000000000001")]
    indexes = {row["name"] for row in inspect(connection).get_indexes("serving_definitions")}
    assert "uq_serving_definitions_one_default_per_food" in indexes

    with Operations.context(context):
        integrity_migration.downgrade()
        integrity_migration.upgrade()


def test_foreign_parent_dependency_is_not_exposed_or_mutated(
    client: TestClient,
    db_session: Session,
) -> None:
    food = _two_serving_food(client)
    selected = next(row for row in food["serving_definitions"] if not row["is_default"])
    foreign_user = User(id=uuid4(), email=f"foreign-{uuid4()}@example.test")
    db_session.add(foreign_user)
    db_session.flush()
    foreign_recipe = Recipe(id=uuid4(), user_id=foreign_user.id, name="Secret Recipe")
    foreign_ingredient = RecipeIngredient(
        id=uuid4(),
        recipe=foreign_recipe,
        food_item_id=UUID(food["id"]),
        position=0,
        amount_quantity=Decimal("1"),
        amount_unit="serving",
        serving_definition_id=UUID(selected["id"]),
        resolved_gram_amount=Decimal("30"),
    )
    db_session.add_all([foreign_recipe, foreign_ingredient])
    db_session.commit()

    response = client.patch(
        f"/api/v1/foods/{food['id']}",
        json={
            "serving_definitions": [
                {
                    "label": "Cup",
                    "quantity": "1",
                    "unit": "cup",
                    "gram_weight": "100",
                    "is_default": True,
                }
            ]
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "food_dependencies_unstable",
        "message": (
            "Food dependencies changed repeatedly during this operation. "
            "Try again when Recipe edits are complete."
        ),
    }
    assert "Secret Recipe" not in response.text
    db_session.expire_all()
    stored = db_session.get(RecipeIngredient, foreign_ingredient.id)
    assert stored.serving_definition_id == UUID(selected["id"])
