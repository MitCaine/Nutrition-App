from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.dependencies.user import ensure_dev_user
from app.models.food import FoodItem
from app.models.recipe import Recipe
from app.models.recipe import RecipeIngredient
from app.models.recipe_publication import RecipePublicationAmountDefinition
from app.models.user import User
from app.repositories.recipe_publication_repository import RecipePublicationRepository
from app.repositories.recipe_repository import RecipeRepository
from app.services.recipe_service import RecipeService
from tests.test_recipe_dependency_deletion import _projection_state
from tests.test_recipe_revision_logging import _published


def _serving(food: dict, *, default: bool) -> dict:
    return next(row for row in food["serving_definitions"] if row["is_default"] is default)


def _parent(
    client: TestClient,
    child_food: dict,
    *,
    name: str = "Parent",
    amount_unit: str = "serving",
    serving_id: str | None = None,
    positions: tuple[int, ...] = (0,),
    publish: bool = False,
) -> dict:
    ingredients = [
        {
            "food_item_id": child_food["id"],
            "position": position,
            "amount_quantity": "1.5" if amount_unit == "serving" else "75",
            "amount_unit": amount_unit,
            **(
                {"serving_definition_id": serving_id}
                if amount_unit == "serving"
                else {"amount_display_quantity": "75", "amount_display_unit": "g"}
            ),
            "preparation_note": "keep this note",
        }
        for position in positions
    ]
    created = client.post(
        "/api/v1/recipes",
        json={
            "name": name,
            "serving_count_yield": "2",
            "final_cooked_weight_grams": "300",
            "ingredients": ingredients,
        },
    )
    assert created.status_code == 201, created.text
    result = created.json()
    if publish:
        published = client.post(f"/api/v1/recipes/{result['id']}/publish")
        assert published.status_code == 200, published.text
        result = published.json()["recipe"]
    return result


def test_gram_parent_is_preserved_and_only_published_parent_becomes_stale(
    client: TestClient,
) -> None:
    child_id, child_food = _published(client)
    published = _parent(client, child_food, name="Published gram", amount_unit="g", publish=True)
    unpublished = _parent(client, child_food, name="Draft gram", amount_unit="g")

    response = client.post(f"/api/v1/recipes/{child_id}/publish")

    assert response.status_code == 200, response.text
    published_after = client.get(f"/api/v1/recipes/{published['id']}").json()
    unpublished_after = client.get(f"/api/v1/recipes/{unpublished['id']}").json()
    assert published_after["needs_republish"] is True
    assert unpublished_after["needs_republish"] is False
    for before, after in ((published, published_after), (unpublished, unpublished_after)):
        assert after["ingredients"][0]["amount_quantity"] == before["ingredients"][0]["amount_quantity"]
        assert after["ingredients"][0]["amount_display_quantity"] == "75.000000"
        assert after["ingredients"][0]["preparation_note"] == "keep this note"


@pytest.mark.parametrize("default", [True, False])
def test_serving_parent_remaps_to_exactly_one_equivalent_successor(
    client: TestClient,
    default: bool,
) -> None:
    child_id, child_food = _published(client)
    selected = _serving(child_food, default=default)
    parent = _parent(client, child_food, serving_id=selected["id"])

    response = client.post(f"/api/v1/recipes/{child_id}/publish")

    assert response.status_code == 200, response.text
    parent_after = client.get(f"/api/v1/recipes/{parent['id']}").json()
    remapped_id = parent_after["ingredients"][0]["serving_definition_id"]
    assert remapped_id != selected["id"]
    successor = next(
        row for row in response.json()["food"]["serving_definitions"] if row["id"] == remapped_id
    )
    assert (successor["quantity"], successor["unit"], successor["gram_weight"]) == (
        selected["quantity"], selected["unit"], selected["gram_weight"]
    )
    assert parent_after["ingredients"][0]["amount_quantity"] == "1.500000"
    assert parent_after["ingredients"][0]["preparation_note"] == "keep this note"


def test_serving_label_rename_does_not_change_semantic_identity(
    client: TestClient,
    db_session: Session,
) -> None:
    child_id, child_food = _published(client)
    selected = _serving(child_food, default=True)
    parent = _parent(client, child_food, serving_id=selected["id"])
    projection = db_session.get(FoodItem, UUID(child_food["id"]))
    next(row for row in projection.serving_definitions if row.id == UUID(selected["id"])).label = "renamed"
    db_session.commit()

    response = client.post(f"/api/v1/recipes/{child_id}/publish")

    assert response.status_code == 200, response.text
    remapped = client.get(f"/api/v1/recipes/{parent['id']}").json()["ingredients"][0]
    assert remapped["serving_definition_id"] != selected["id"]


@pytest.mark.parametrize("change", ["weight", "removed", "missing_identity"])
def test_no_safe_serving_successor_is_structured_and_fully_atomic(
    client: TestClient,
    db_session: Session,
    change: str,
) -> None:
    child_id, child_food = _published(client)
    selected = _serving(child_food, default=change != "removed")
    parent = _parent(client, child_food, serving_id=selected["id"], publish=True)
    db_session.expire_all()
    child = db_session.get(Recipe, child_id)
    parent_row = db_session.get(Recipe, UUID(parent["id"]))
    projection = child.published_food_item
    history_before = len(RecipePublicationRepository(db_session).list_for_recipe(child.id, child.user_id))
    active_before = child.active_publication_revision_id
    projection_before = deepcopy(_projection_state(projection))
    parent_projection_before = deepcopy(_projection_state(parent_row.published_food_item))
    parent_active_before = parent_row.active_publication_revision_id
    if change == "weight":
        update = client.patch(
            f"/api/v1/recipes/{child_id}", json={"final_cooked_weight_grams": "600"}
        )
        assert update.status_code == 200
    elif change == "removed":
        update = client.patch(
            f"/api/v1/recipes/{child_id}", json={"final_cooked_weight_grams": None}
        )
        assert update.status_code == 200
    else:
        db_session.get(Recipe, UUID(parent["id"])).ingredients[0].serving_definition_id = None
        db_session.commit()

    response = client.post(f"/api/v1/recipes/{child_id}/publish")

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "recipe_publication_parent_amount_conflict"
    assert detail["affected_recipes"] == [
        {
            "recipe_id": parent["id"],
            "recipe_name": "Parent",
            "ingredient_positions": [0],
        }
    ]
    db_session.expire_all()
    child = db_session.get(Recipe, child_id)
    parent_row = db_session.get(Recipe, UUID(parent["id"]))
    assert len(RecipePublicationRepository(db_session).list_for_recipe(child.id, child.user_id)) == history_before
    assert child.active_publication_revision_id == active_before
    assert _projection_state(child.published_food_item) == projection_before
    assert parent_row.active_publication_revision_id == parent_active_before
    assert _projection_state(parent_row.published_food_item) == parent_projection_before
    assert parent_row.needs_republish is False


def test_multiple_occurrences_are_remapped_and_published_parent_projection_is_unchanged(
    client: TestClient,
    db_session: Session,
) -> None:
    child_id, child_food = _published(client)
    selected = _serving(child_food, default=True)
    parent = _parent(
        client,
        child_food,
        serving_id=selected["id"],
        positions=(0, 2),
        publish=True,
    )
    db_session.expire_all()
    parent_row = db_session.get(Recipe, UUID(parent["id"]))
    active_before = parent_row.active_publication_revision_id
    projection_before = deepcopy(_projection_state(parent_row.published_food_item))

    response = client.post(f"/api/v1/recipes/{child_id}/publish")

    assert response.status_code == 200, response.text
    db_session.expire_all()
    parent_row = db_session.get(Recipe, parent_row.id)
    assert len({row.serving_definition_id for row in parent_row.ingredients}) == 1
    assert all(row.serving_definition_id != UUID(selected["id"]) for row in parent_row.ingredients)
    assert parent_row.needs_republish is True
    assert parent_row.active_publication_revision_id == active_before
    assert _projection_state(parent_row.published_food_item) == projection_before


def test_parent_remap_mutation_seam_rolls_back_child_and_parent(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_id, child_food = _published(client)
    selected = _serving(child_food, default=True)
    parent = _parent(client, child_food, serving_id=selected["id"], publish=True)
    user = ensure_dev_user(db_session)
    child = db_session.get(Recipe, child_id)
    history_before = len(RecipePublicationRepository(db_session).list_for_recipe(child.id, user.id))

    def fail(*_args) -> None:
        raise RuntimeError("forced parent remap failure")

    monkeypatch.setattr(RecipeService, "_after_parent_serving_remaps", fail)
    with pytest.raises(RuntimeError, match="forced parent remap failure"):
        RecipeService(db_session).publish(user.id, child_id)

    db_session.expire_all()
    child = db_session.get(Recipe, child_id)
    parent_row = db_session.get(Recipe, UUID(parent["id"]))
    assert len(RecipePublicationRepository(db_session).list_for_recipe(child.id, user.id)) == history_before
    assert parent_row.ingredients[0].serving_definition_id == UUID(selected["id"])
    assert parent_row.needs_republish is False


def test_ambiguous_equivalent_successors_abort_publication(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_id, child_food = _published(client)
    selected = _serving(child_food, default=True)
    _parent(client, child_food, serving_id=selected["id"])
    from app.services import recipe_service as module

    original_build_revision = module.build_revision

    def ambiguous_revision(**kwargs):
        revision = original_build_revision(**kwargs)
        source = next(row for row in revision.amount_definitions if row.is_default)
        revision.amount_definitions.append(
            RecipePublicationAmountDefinition(
                id=uuid4(),
                display_order=99,
                display_label="presentation duplicate",
                semantic_mode=source.semantic_mode,
                display_quantity=source.display_quantity,
                display_unit=source.display_unit,
                gram_equivalent=source.gram_equivalent,
                is_default=False,
            )
        )
        return revision

    monkeypatch.setattr(module, "build_revision", ambiguous_revision)

    response = client.post(f"/api/v1/recipes/{child_id}/publish")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "recipe_publication_parent_amount_conflict"


def test_foreign_owner_parent_is_neither_reported_nor_changed(
    client: TestClient,
    db_session: Session,
) -> None:
    child_id, child_food = _published(client)
    selected = _serving(child_food, default=True)
    visible = _parent(client, child_food, name="Visible Parent", serving_id=selected["id"])
    owner = User(id=uuid4(), email="nested-foreign@example.test")
    db_session.add(owner)
    db_session.flush()
    foreign_parent = Recipe(id=uuid4(), user_id=owner.id, name="Secret Parent")
    foreign_parent.ingredients.append(
        RecipeIngredient(
            id=uuid4(),
            food_item_id=UUID(child_food["id"]),
            position=0,
            amount_quantity=Decimal("1"),
            amount_unit="serving",
            serving_definition_id=UUID(selected["id"]),
            resolved_gram_amount=Decimal(selected["gram_weight"]),
        )
    )
    db_session.add(foreign_parent)
    db_session.commit()
    changed = client.patch(
        f"/api/v1/recipes/{child_id}", json={"final_cooked_weight_grams": "600"}
    )
    assert changed.status_code == 200

    response = client.post(f"/api/v1/recipes/{child_id}/publish")

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["affected_recipes"][0]["recipe_id"] == visible["id"]
    assert "Secret Parent" not in response.text
    db_session.expire_all()
    stored = db_session.get(Recipe, foreign_parent.id)
    assert stored.ingredients[0].serving_definition_id == UUID(selected["id"])
    assert stored.needs_republish is False


def test_dependency_change_restarts_with_complete_recipe_lock_set(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_id, child_food = _published(client)
    first = _parent(client, child_food, name="First", amount_unit="g")
    second = _parent(client, child_food, name="Second", amount_unit="g")
    original_dependencies = RecipeService._dependent_recipe_ids
    original_lock_many = RecipeRepository.get_many_for_update
    scans = 0
    lock_sets: list[set[UUID]] = []

    def changing_dependencies(service, user_id, projection_id):
        nonlocal scans
        scans += 1
        if scans == 1:
            return {UUID(first["id"])}
        return original_dependencies(service, user_id, projection_id)

    def record_locks(repository, recipe_ids, user_id):
        lock_sets.append(set(recipe_ids))
        return original_lock_many(repository, recipe_ids, user_id)

    monkeypatch.setattr(RecipeService, "_dependent_recipe_ids", changing_dependencies)
    monkeypatch.setattr(RecipeRepository, "get_many_for_update", record_locks)

    response = client.post(f"/api/v1/recipes/{child_id}/publish")

    assert response.status_code == 200, response.text
    assert lock_sets == [
        {child_id, UUID(first["id"])},
        {child_id, UUID(first["id"]), UUID(second["id"])},
    ]


def test_dependency_restart_limit_returns_predictable_structured_failure(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_id, child_food = _published(client)
    parent = _parent(client, child_food, amount_unit="g")
    child = db_session.get(Recipe, child_id)
    history_before = len(
        RecipePublicationRepository(db_session).list_for_recipe(child.id, child.user_id)
    )
    scans = 0

    def unstable_dependencies(_service, _user_id, _projection_id):
        nonlocal scans
        scans += 1
        return {UUID(parent["id"])} if scans % 2 else set()

    monkeypatch.setattr(RecipeService, "_dependent_recipe_ids", unstable_dependencies)

    response = client.post(f"/api/v1/recipes/{child_id}/publish")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "recipe_publication_dependencies_unstable",
        "message": (
            "Recipe dependencies changed repeatedly during publication. "
            "Try again when parent Recipe edits are complete."
        ),
    }
    db_session.expire_all()
    child = db_session.get(Recipe, child_id)
    assert len(
        RecipePublicationRepository(db_session).list_for_recipe(child.id, child.user_id)
    ) == history_before
