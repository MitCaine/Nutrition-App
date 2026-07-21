from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.dependencies.user import ensure_dev_user
from app.models.food import FoodItem
from app.models.log import DailyLog
from app.models.recipe import Recipe, RecipeIngredient
from app.models.user import User
from app.repositories.recipe_publication_repository import RecipePublicationRepository
from app.repositories.recipe_repository import RecipeRepository
from app.services.recipe_service import (
    RECIPE_DELETE_DEPENDENCY_RESTART_LIMIT,
    RecipeService,
)
from tests.test_recipe_revision_logging import _post_log, _published
from tests.test_stage2_foods import create_food


def _parent_recipe(
    client: TestClient,
    child_food: dict,
    name: str,
    *,
    positions: tuple[int, ...] = (0,),
    publish: bool = False,
) -> dict:
    response = client.post(
        "/api/v1/recipes",
        json={
            "name": name,
            "serving_count_yield": "2",
            "ingredients": [
                {
                    "food_item_id": child_food["id"],
                    "position": position,
                    "amount_quantity": "50",
                    "amount_unit": "g",
                }
                for position in positions
            ],
        },
    )
    assert response.status_code == 201, response.text
    recipe = response.json()
    if publish:
        published = client.post(f"/api/v1/recipes/{recipe['id']}/publish")
        assert published.status_code == 200, published.text
        recipe = published.json()["recipe"]
    return recipe


def _projection_state(projection: FoodItem) -> tuple:
    return (
        projection.id,
        projection.deleted_at,
        projection.recipe_publication_revision_id,
        tuple(
            (row.id, row.label, row.quantity, row.unit, row.gram_weight)
            for row in projection.serving_definitions
        ),
        tuple((row.id, row.nutrient_id, row.amount, row.basis) for row in projection.nutrients),
    )


def test_delete_unused_recipe_retires_recipe_and_projection(client: TestClient) -> None:
    recipe_id, food = _published(client)

    response = client.delete(f"/api/v1/recipes/{recipe_id}")

    assert response.status_code == 204
    assert client.get(f"/api/v1/recipes/{recipe_id}").status_code == 404
    assert client.get(f"/api/v1/foods/{food['id']}").status_code == 404


def test_recipe_delete_dependency_conflict_is_structured_and_non_mutating(
    client: TestClient,
) -> None:
    child_id, child_food = _published(client)
    parent = _parent_recipe(client, child_food, "Parent Recipe")

    response = client.delete(f"/api/v1/recipes/{child_id}")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "recipe_delete_dependencies_exist",
        "message": "This Recipe is used by other Recipes. Confirm deletion to remove it from those Recipes.",
        "recipe_id": str(child_id),
        "projection_food_item_id": child_food["id"],
        "active_dependent_recipe_count": 1,
        "affected_recipes": [
            {
                "recipe_id": parent["id"],
                "recipe_name": "Parent Recipe",
                "ingredient_occurrence_count": 1,
                "is_published": False,
                "will_require_republish": False,
            }
        ],
        "total_ingredient_rows_affected": 1,
    }
    assert client.get(f"/api/v1/recipes/{child_id}").status_code == 200
    assert client.get(f"/api/v1/foods/{child_food['id']}").status_code == 200
    assert len(client.get(f"/api/v1/recipes/{parent['id']}").json()["ingredients"]) == 1


def test_dependency_conflict_reports_multiple_parents_and_duplicate_occurrences(
    client: TestClient,
) -> None:
    child_id, child_food = _published(client)
    first = _parent_recipe(client, child_food, "First Parent", positions=(0, 2))
    second = _parent_recipe(client, child_food, "Second Parent", publish=True)

    response = client.delete(f"/api/v1/recipes/{child_id}")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["active_dependent_recipe_count"] == 2
    assert detail["total_ingredient_rows_affected"] == 3
    assert {
        value["recipe_id"]: (
            value["ingredient_occurrence_count"],
            value["is_published"],
            value["will_require_republish"],
        )
        for value in detail["affected_recipes"]
    } == {
        first["id"]: (2, False, False),
        second["id"]: (1, True, True),
    }


def test_dependency_metadata_describes_future_republish_even_when_already_stale(
    client: TestClient,
) -> None:
    child_id, child_food = _published(client)
    parent = _parent_recipe(client, child_food, "Already Stale Parent", publish=True)
    changed = client.patch(
        f"/api/v1/recipes/{parent['id']}",
        json={"name": "Already Stale Parent Updated"},
    )
    assert changed.status_code == 200
    assert changed.json()["needs_republish"] is True

    response = client.delete(f"/api/v1/recipes/{child_id}")

    assert response.status_code == 409
    affected = response.json()["detail"]["affected_recipes"][0]
    assert affected["is_published"] is True
    assert affected["will_require_republish"] is True
    assert "needs_republish" not in affected


def test_dependency_rediscovery_restarts_and_reacquires_complete_sorted_lock_set(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_id, child_food = _published(client)
    first = _parent_recipe(client, child_food, "Initially Visible Parent")
    second = _parent_recipe(client, child_food, "Racing Parent")
    original_dependencies = RecipeService._dependent_recipe_ids
    original_lock_many = RecipeRepository.get_many_for_update
    dependency_scans = 0
    lock_sets: list[set[UUID]] = []

    def changing_dependencies(service, user_id, projection_id):
        nonlocal dependency_scans
        dependency_scans += 1
        if dependency_scans == 1:
            return {UUID(first["id"])}
        return original_dependencies(service, user_id, projection_id)

    def record_lock_set(repository, recipe_ids, user_id):
        lock_sets.append(set(recipe_ids))
        return original_lock_many(repository, recipe_ids, user_id)

    monkeypatch.setattr(RecipeService, "_dependent_recipe_ids", changing_dependencies)
    monkeypatch.setattr(RecipeRepository, "get_many_for_update", record_lock_set)

    response = client.delete(
        f"/api/v1/recipes/{child_id}",
        params={"remove_from_recipes": "true"},
    )

    assert response.status_code == 204, response.text
    assert lock_sets == [
        {UUID(str(child_id)), UUID(first["id"])},
        {UUID(str(child_id)), UUID(first["id"]), UUID(second["id"])},
    ]
    assert client.get(f"/api/v1/recipes/{first['id']}").json()["ingredients"] == []
    assert client.get(f"/api/v1/recipes/{second['id']}").json()["ingredients"] == []


def test_dependency_rediscovery_exhaustion_is_bounded_non_mutating_and_retryable_later(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_id, child_food = _published(client)
    first = _parent_recipe(client, child_food, "Initially Visible Parent")
    second = _parent_recipe(client, child_food, "Rediscovered Parent")
    original_dependencies = RecipeService._dependent_recipe_ids
    dependency_scans = 0

    def never_stable(service, user_id, projection_id):
        nonlocal dependency_scans
        dependency_scans += 1
        if dependency_scans % 2:
            return {UUID(first["id"])}
        return {UUID(first["id"]), UUID(second["id"])}

    monkeypatch.setattr(RecipeService, "_dependent_recipe_ids", never_stable)
    exhausted = client.delete(
        f"/api/v1/recipes/{child_id}",
        params={"remove_from_recipes": "true"},
    )

    assert exhausted.status_code == 409
    assert exhausted.json() == {
        "detail": {
            "code": "recipe_dependencies_unstable",
            "message": (
                "Recipe dependencies changed repeatedly during deletion. "
                "Try again when Recipe edits are complete."
            ),
        }
    }
    assert dependency_scans == RECIPE_DELETE_DEPENDENCY_RESTART_LIMIT * 2
    assert client.get(f"/api/v1/recipes/{child_id}").status_code == 200
    assert len(client.get(f"/api/v1/recipes/{first['id']}").json()["ingredients"]) == 1
    assert len(client.get(f"/api/v1/recipes/{second['id']}").json()["ingredients"]) == 1

    monkeypatch.setattr(RecipeService, "_dependent_recipe_ids", original_dependencies)
    retried = client.delete(
        f"/api/v1/recipes/{child_id}",
        params={"remove_from_recipes": "true"},
    )

    assert retried.status_code == 204
    assert client.get(f"/api/v1/recipes/{first['id']}").json()["ingredients"] == []
    assert client.get(f"/api/v1/recipes/{second['id']}").json()["ingredients"] == []


def test_confirmed_delete_preserves_parent_order_and_published_state(
    client: TestClient,
    db_session: Session,
) -> None:
    child_id, child_food = _published(client)
    first_kept = create_food(client, "First Kept")
    second_kept = create_food(client, "Second Kept")
    parent_response = client.post(
        "/api/v1/recipes",
        json={
            "name": "Published Parent",
            "serving_count_yield": "2",
            "ingredients": [
                {
                    "food_item_id": first_kept["id"],
                    "position": 0,
                    "amount_quantity": "20",
                    "amount_unit": "g",
                },
                {
                    "food_item_id": child_food["id"],
                    "position": 1,
                    "amount_quantity": "50",
                    "amount_unit": "g",
                },
                {
                    "food_item_id": second_kept["id"],
                    "position": 2,
                    "amount_quantity": "30",
                    "amount_unit": "g",
                },
                {
                    "food_item_id": child_food["id"],
                    "position": 3,
                    "amount_quantity": "25",
                    "amount_unit": "g",
                },
            ],
        },
    )
    parent = parent_response.json()
    published = client.post(f"/api/v1/recipes/{parent['id']}/publish").json()
    parent_recipe = db_session.get(Recipe, UUID(parent["id"]))
    active_revision_id = parent_recipe.active_publication_revision_id
    parent_projection = parent_recipe.published_food_item
    projection_before = deepcopy(_projection_state(parent_projection))

    response = client.delete(
        f"/api/v1/recipes/{child_id}",
        params={"remove_from_recipes": "true"},
    )

    assert response.status_code == 204, response.text
    retrieved = client.get(f"/api/v1/recipes/{parent['id']}").json()
    assert [(row["food_item_id"], row["position"]) for row in retrieved["ingredients"]] == [
        (first_kept["id"], 0),
        (second_kept["id"], 1),
    ]
    assert retrieved["needs_republish"] is True
    db_session.expire_all()
    refreshed_parent = db_session.get(Recipe, UUID(parent["id"]))
    assert refreshed_parent.active_publication_revision_id == active_revision_id
    assert _projection_state(refreshed_parent.published_food_item) == projection_before
    assert published["food"]["id"] == str(parent_projection.id)


def test_confirmed_delete_rechecks_dependencies_and_handles_unpublished_parent(
    client: TestClient,
) -> None:
    child_id, child_food = _published(client)
    first = _parent_recipe(client, child_food, "Initially Shown")
    assert client.delete(f"/api/v1/recipes/{child_id}").status_code == 409
    second = _parent_recipe(client, child_food, "Added Before Confirmation")

    confirmed = client.delete(
        f"/api/v1/recipes/{child_id}",
        params={"remove_from_recipes": "true"},
    )

    assert confirmed.status_code == 204
    for parent in (first, second):
        retrieved = client.get(f"/api/v1/recipes/{parent['id']}").json()
        assert retrieved["ingredients"] == []
        assert retrieved["needs_republish"] is False


def test_deleted_parent_is_ignored_and_its_retained_ingredient_is_not_mutated(
    client: TestClient,
    db_session: Session,
) -> None:
    child_id, child_food = _published(client)
    parent = _parent_recipe(client, child_food, "Archived Parent")
    assert client.delete(f"/api/v1/recipes/{child_id}").status_code == 409
    assert client.delete(f"/api/v1/recipes/{parent['id']}").status_code == 204
    archived = db_session.get(Recipe, UUID(parent["id"]))
    ingredient_ids = [row.id for row in archived.ingredients]

    response = client.delete(f"/api/v1/recipes/{child_id}")

    assert response.status_code == 204
    db_session.expire_all()
    assert [row.id for row in db_session.get(Recipe, archived.id).ingredients] == ingredient_ids


def test_confirmed_delete_observes_parent_edit_and_child_republication(
    client: TestClient,
) -> None:
    child_id, child_food = _published(client)
    parent = _parent_recipe(client, child_food, "Edited During Confirmation")
    assert client.delete(f"/api/v1/recipes/{child_id}").status_code == 409

    updated_parent = client.patch(
        f"/api/v1/recipes/{parent['id']}",
        json={"ingredients": []},
    )
    assert updated_parent.status_code == 200, updated_parent.text
    republished_child = client.post(f"/api/v1/recipes/{child_id}/publish")
    assert republished_child.status_code == 200, republished_child.text

    confirmed = client.delete(
        f"/api/v1/recipes/{child_id}",
        params={"remove_from_recipes": "true"},
    )

    assert confirmed.status_code == 204
    assert client.get(f"/api/v1/recipes/{parent['id']}").json()["ingredients"] == []


def test_child_revision_logs_and_snapshots_survive_confirmed_deletion(
    client: TestClient,
    db_session: Session,
) -> None:
    child_id, child_food = _published(client)
    serving = next(row for row in child_food["serving_definitions"] if row["is_default"])
    logged = _post_log(client, child_food, serving_definition_id=serving["id"])
    log_id = UUID(logged.json()["id"])
    stored_log = db_session.get(DailyLog, log_id)
    revision_id = stored_log.recipe_publication_revision_id
    amount_id = stored_log.recipe_publication_amount_definition_id
    snapshot_ids = {row.id for row in stored_log.snapshots}
    _parent_recipe(client, child_food, "Historical Parent")

    response = client.delete(
        f"/api/v1/recipes/{child_id}",
        params={"remove_from_recipes": "true"},
    )

    assert response.status_code == 204
    db_session.expire_all()
    preserved_log = db_session.get(DailyLog, log_id)
    revision = RecipePublicationRepository(db_session).get_required(
        revision_id,
        preserved_log.user_id,
    )
    assert preserved_log.recipe_publication_revision_id == revision.id
    assert preserved_log.recipe_publication_amount_definition_id == amount_id
    assert {row.id for row in preserved_log.snapshots} == snapshot_ids
    assert any(row.id == amount_id for row in revision.amount_definitions)
    context = client.get(f"/api/v1/logs/{log_id}/edit-context")
    assert context.status_code == 200, context.text
    assert context.json()["source_food_available"] is False
    edited = client.patch(f"/api/v1/logs/{log_id}", json={"amount_quantity": "2"})
    assert edited.status_code == 200, edited.text


@pytest.mark.parametrize(
    "failure_seam",
    [
        "_after_dependent_ingredient_removal",
        "_after_parent_staleness_update",
        "_after_child_recipe_soft_delete",
        "_after_projection_soft_delete",
    ],
)
def test_confirmed_delete_rolls_back_every_mutation_boundary(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    failure_seam: str,
) -> None:
    child_id, child_food = _published(client)
    parent = _parent_recipe(client, child_food, "Rollback Parent", publish=True)
    user = ensure_dev_user(db_session)

    def fail(*_args) -> None:
        raise RuntimeError("forced deletion failure")

    monkeypatch.setattr(RecipeService, failure_seam, fail)
    with pytest.raises(RuntimeError, match="forced deletion failure"):
        RecipeService(db_session).soft_delete_recipe(
            user.id,
            child_id,
            remove_from_recipes=True,
        )

    db_session.expire_all()
    assert db_session.get(Recipe, child_id).deleted_at is None
    assert db_session.get(FoodItem, UUID(child_food["id"])).deleted_at is None
    restored_parent = db_session.get(Recipe, UUID(parent["id"]))
    assert len(restored_parent.ingredients) == 1
    assert restored_parent.needs_republish is False


def test_inconsistent_projection_linkage_blocks_recipe_deletion(
    client: TestClient,
    db_session: Session,
) -> None:
    child_id, child_food = _published(client)
    projection = db_session.get(FoodItem, UUID(child_food["id"]))
    projection.recipe_publication_revision_id = None
    db_session.commit()

    response = client.delete(f"/api/v1/recipes/{child_id}")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "recipe_projection_integrity_invalid"
    assert db_session.get(Recipe, child_id).deleted_at is None
    assert projection.deleted_at is None


def test_cross_user_dependencies_are_not_exposed_or_mutated(
    client: TestClient,
    db_session: Session,
) -> None:
    child_id, child_food = _published(client)
    other_user = User(id=uuid4(), email="other-recipe-dependency@example.test")
    db_session.add(other_user)
    db_session.flush()
    foreign_parent = Recipe(
        id=uuid4(),
        user_id=other_user.id,
        name="Foreign Parent",
        ingredients=[
            RecipeIngredient(
                id=uuid4(),
                food_item_id=UUID(child_food["id"]),
                position=0,
                amount_quantity=Decimal("1"),
                amount_unit="g",
            )
        ],
    )
    db_session.add(foreign_parent)
    db_session.commit()

    response = client.delete(f"/api/v1/recipes/{child_id}")

    assert response.status_code == 204
    db_session.expire_all()
    assert len(db_session.get(Recipe, foreign_parent.id).ingredients) == 1


def test_cross_user_dependency_is_omitted_when_same_user_dependency_blocks(
    client: TestClient,
    db_session: Session,
) -> None:
    child_id, child_food = _published(client)
    same_user_parent = _parent_recipe(client, child_food, "Visible Parent")
    other_user = User(id=uuid4(), email="hidden-parent@example.test")
    db_session.add(other_user)
    db_session.flush()
    foreign_parent = Recipe(
        id=uuid4(),
        user_id=other_user.id,
        name="Secret Foreign Parent",
        ingredients=[
            RecipeIngredient(
                id=uuid4(),
                food_item_id=UUID(child_food["id"]),
                position=0,
                amount_quantity=Decimal("1"),
                amount_unit="g",
            )
        ],
    )
    db_session.add(foreign_parent)
    db_session.commit()

    blocked = client.delete(f"/api/v1/recipes/{child_id}")

    assert blocked.status_code == 409
    assert [row["recipe_id"] for row in blocked.json()["detail"]["affected_recipes"]] == [
        same_user_parent["id"]
    ]
    assert str(foreign_parent.id) not in blocked.text
    assert "Secret Foreign Parent" not in blocked.text

    confirmed = client.delete(
        f"/api/v1/recipes/{child_id}",
        params={"remove_from_recipes": "true"},
    )

    assert confirmed.status_code == 204
    assert client.get(f"/api/v1/recipes/{same_user_parent['id']}").json()["ingredients"] == []
    db_session.expire_all()
    assert len(db_session.get(Recipe, foreign_parent.id).ingredients) == 1


def test_repeated_confirmed_delete_returns_existing_not_found_semantics(
    client: TestClient,
) -> None:
    child_id, _ = _published(client)
    assert (
        client.delete(
            f"/api/v1/recipes/{child_id}",
            params={"remove_from_recipes": "true"},
        ).status_code
        == 204
    )

    repeated = client.delete(
        f"/api/v1/recipes/{child_id}",
        params={"remove_from_recipes": "true"},
    )

    assert repeated.status_code == 404
