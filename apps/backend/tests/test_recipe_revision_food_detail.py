from __future__ import annotations

from copy import deepcopy
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.dependencies.user import ensure_dev_user
from app.models.food import FoodItem
from app.models.recipe import Recipe
from app.models.recipe_publication import RecipePublicationRevision
from app.models.user import User
from app.nutrition.revision_resolution import resolve_revision_nutrition
from app.repositories.recipe_publication_repository import RecipePublicationRepository
from app.services.food_service import FoodService
from tests.test_recipe_revision_logging import _published
from tests.test_stage2_foods import create_food


def _managed_detail(client: TestClient, food_id: str) -> dict:
    response = client.get(f"/api/v1/foods/{food_id}/resolved-nutrition")
    assert response.status_code == 200, response.text
    return response.json()


def test_managed_food_detail_uses_active_revision_despite_stale_projection_rows(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe_id, food_data = _published(client)
    recipe = db_session.get(Recipe, recipe_id)
    revision = RecipePublicationRepository(db_session).get_required(
        recipe.active_publication_revision_id,
        recipe.user_id,
    )
    revision_amounts = [
        amount for amount in revision.amount_definitions if amount.semantic_mode == "serving"
    ]
    default_amount = next(amount for amount in revision_amounts if amount.is_default)
    expected = resolve_revision_nutrition(
        revision,
        default_amount.id,
        default_amount.display_quantity,
        semantic_amount_mode="serving",
    )
    expected_protein = next(
        nutrient.amount for nutrient in expected.nutrients if nutrient.nutrient_id == "protein"
    )

    projection = db_session.get(FoodItem, UUID(food_data["id"]))
    next(row for row in projection.nutrients if row.nutrient_id == "protein").amount = 999
    projection.serving_definitions[0].label = "Stale projection amount"
    projection.serving_definitions[0].gram_weight = 1
    db_session.commit()

    detail = _managed_detail(client, food_data["id"])
    selected = next(amount for amount in detail["amounts"] if amount["is_default"])
    protein = next(
        nutrient for nutrient in selected["nutrients"] if nutrient["nutrient_id"] == "protein"
    )

    assert detail["nutrition_authority"] == "recipe_publication_revision"
    assert detail["recipe_id"] == str(recipe_id)
    assert detail["recipe_publication_revision_id"] == str(revision.id)
    assert {UUID(amount["amount_definition_id"]) for amount in detail["amounts"]} == {
        amount.id for amount in revision_amounts
    }
    assert [amount["display_label"] for amount in detail["amounts"]] == [
        amount.display_label for amount in revision_amounts
    ]
    assert protein["amount"] == f"{expected_protein:.6f}"
    assert protein["amount"] != "999.000000"
    assert "Stale projection amount" not in [
        amount["display_label"] for amount in detail["amounts"]
    ]


def test_republish_switches_detail_authority_without_mutating_old_revision(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe_id, food = _published(client)
    first_detail = _managed_detail(client, food["id"])
    first_revision = RecipePublicationRepository(db_session).get_required(
        UUID(first_detail["recipe_publication_revision_id"]),
        ensure_dev_user(db_session).id,
    )
    old_revision_state = deepcopy(
        (
            first_revision.published_name,
            [(row.id, row.display_label, row.is_default) for row in first_revision.amount_definitions],
            [(row.id, row.nutrient_id, row.amount) for row in first_revision.nutrients],
        )
    )

    assert client.patch(
        f"/api/v1/recipes/{recipe_id}",
        json={"serving_count_yield": "4"},
    ).status_code == 200
    assert client.post(f"/api/v1/recipes/{recipe_id}/publish").status_code == 200

    second_detail = _managed_detail(client, food["id"])
    db_session.expire_all()
    old_revision = RecipePublicationRepository(db_session).get_required(
        first_revision.id,
        first_revision.user_id,
    )

    assert second_detail["recipe_publication_revision_id"] != first_detail[
        "recipe_publication_revision_id"
    ]
    assert second_detail["amounts"] != first_detail["amounts"]
    assert (
        old_revision.published_name,
        [(row.id, row.display_label, row.is_default) for row in old_revision.amount_definitions],
        [(row.id, row.nutrient_id, row.amount) for row in old_revision.nutrients],
    ) == old_revision_state


def test_partial_recipe_markers_fail_resolved_detail_conservatively(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe_id, food = _published(client)
    projection = db_session.get(FoodItem, UUID(food["id"]))
    projection.recipe_publication_revision_id = None
    db_session.commit()

    response = client.get(f"/api/v1/foods/{food['id']}/resolved-nutrition")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "recipe_projection_integrity_invalid",
        "message": "This food appears to be generated from a Recipe, but its ownership links are inconsistent. Republish the Recipe or repair the projection before viewing published nutrition.",
        "food_item_id": food["id"],
        "recipe_id": str(recipe_id),
        "food_name": projection.name,
        "operation": "read",
    }


def test_cross_user_recipe_linkage_is_rejected(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    recipe_id, food = _published(client)
    projection = db_session.get(FoodItem, UUID(food["id"]))
    recipe = db_session.get(Recipe, recipe_id)
    revision = RecipePublicationRepository(db_session).get_required(
        recipe.active_publication_revision_id,
        recipe.user_id,
    )
    other_user = User(id=uuid4(), email="other-detail-owner@example.test")
    foreign_projection = FoodItem(
        id=uuid4(),
        user_id=other_user.id,
        name="Other user's food",
        source_type="manual",
        is_recipe=False,
    )
    db_session.add(other_user)
    db_session.flush()
    db_session.add(foreign_projection)
    db_session.commit()
    foreign_recipe = Recipe(
        id=recipe.id,
        user_id=other_user.id,
        name=recipe.name,
        published_food_item_id=projection.id,
        active_publication_revision_id=revision.id,
    )
    monkeypatch.setattr(
        FoodService,
        "_food_detail_authorities",
        lambda _self, _user_id, _food_id: (projection, foreign_recipe, revision),
    )

    response = client.get(f"/api/v1/foods/{food['id']}/resolved-nutrition")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "recipe_projection_integrity_invalid"

    foreign_revision = RecipePublicationRevision(
        id=revision.id,
        recipe_id=recipe.id,
        user_id=other_user.id,
        revision_number=revision.revision_number,
        creation_origin=revision.creation_origin,
        provenance_confidence=revision.provenance_confidence,
        published_name=revision.published_name,
        published_notes=revision.published_notes,
        content_digest=revision.content_digest,
    )
    monkeypatch.setattr(
        FoodService,
        "_food_detail_authorities",
        lambda _self, _user_id, _food_id: (projection, recipe, foreign_revision),
    )
    foreign_revision_response = client.get(
        f"/api/v1/foods/{food['id']}/resolved-nutrition"
    )

    assert foreign_revision_response.status_code == 409
    assert foreign_revision_response.json()["detail"]["code"] == (
        "recipe_projection_integrity_invalid"
    )

    monkeypatch.undo()
    foreign_projection_response = client.get(
        f"/api/v1/foods/{foreign_projection.id}/resolved-nutrition"
    )
    assert foreign_projection_response.status_code == 404


def test_manual_and_unmanaged_legacy_detail_keep_food_item_authority(
    client: TestClient,
    db_session: Session,
) -> None:
    manual = create_food(client, "Compatibility Detail")
    manual_detail = _managed_detail(client, manual["id"])

    legacy = db_session.get(FoodItem, UUID(manual["id"]))
    legacy.source_type = "legacy_import"
    db_session.commit()
    legacy_detail = _managed_detail(client, manual["id"])

    for detail in (manual_detail, legacy_detail):
        assert detail["nutrition_authority"] == "food_item"
        assert detail["recipe_id"] is None
        assert detail["recipe_publication_revision_id"] is None
        assert detail["amounts"][0]["amount_definition_id"] == manual[
            "serving_definitions"
        ][0]["id"]


def test_revision_detail_keeps_logging_and_independent_duplication_available(
    client: TestClient,
) -> None:
    _, food = _published(client)
    detail = _managed_detail(client, food["id"])
    selected = next(amount for amount in detail["amounts"] if amount["is_default"])

    logged = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": "2026-07-13",
            "amount_quantity": "1",
            "amount_unit": selected["semantic_amount_mode"],
            "serving_definition_id": selected["amount_definition_id"],
        },
    )
    duplicate = client.post(f"/api/v1/foods/{food['id']}/duplicate")

    assert logged.status_code == 201, logged.text
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["source_type"] == "manual"
    assert duplicate.json()["is_recipe"] is False


def test_deleted_managed_projection_retains_unavailable_read_semantics(
    client: TestClient,
) -> None:
    recipe_id, food = _published(client)
    assert client.delete(f"/api/v1/recipes/{recipe_id}").status_code == 204

    response = client.get(f"/api/v1/foods/{food['id']}/resolved-nutrition")

    assert response.status_code == 404
    assert response.json()["detail"] == "Food not found"
