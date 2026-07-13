from __future__ import annotations

from decimal import Decimal
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.models.food import FoodItem
from app.models.log import DailyLog
from app.models.recipe import Recipe
from app.models.recipe_publication import RecipePublicationRevision
from app.nutrition.resolution import resolve_nutrition
from app.nutrition.revision_resolution import resolve_revision_nutrition
from app.publication.recipe_revision import (
    PublishedAmountContent,
    PublishedNutrientContent,
    RecipePublicationContent,
    apply_revision_to_projection,
    build_revision,
    projection_matches_revision,
    revision_content_digest,
    validate_revision_resolver_input,
)
from app.repositories.recipe_publication_repository import RecipePublicationRepository
from app.repositories.recipe_repository import RecipeRepository
from app.services.recipe_revision_capture_service import RecipeRevisionCaptureService
from app.services.recipe_service import RecipeService
from tests.test_recipe_revision_capture import _published_recipe as _legacy_published_recipe
from tests.test_stage4_recipes import _per_100g_food


def _create_recipe(
    client: TestClient,
    *,
    name: str = "Managed Recipe",
    serving_count: str | None = "2",
    cooked_grams: str | None = "400",
) -> UUID:
    ingredient = _per_100g_food(client, name=f"{name} ingredient")
    response = client.post(
        "/api/v1/recipes",
        json={
            "name": name,
            "notes": "managed notes",
            "serving_count_yield": serving_count,
            "final_cooked_weight_grams": cooked_grams,
            "ingredients": [
                {
                    "food_item_id": ingredient["id"],
                    "position": 0,
                    "amount_quantity": "200",
                    "amount_unit": "g",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


def _publish(client: TestClient, recipe_id: UUID) -> dict:
    response = client.post(f"/api/v1/recipes/{recipe_id}/publish")
    assert response.status_code == 200, response.text
    return response.json()


def _history(db: Session, recipe: Recipe) -> list[RecipePublicationRevision]:
    return RecipePublicationRepository(db).list_for_recipe(recipe.id, recipe.user_id)


def _revision_snapshot(revision: RecipePublicationRevision) -> tuple:
    return (
        revision.id,
        revision.revision_number,
        revision.creation_origin,
        revision.provenance_confidence,
        revision.published_name,
        revision.published_notes,
        revision.content_digest,
        tuple(
            (
                amount.id,
                amount.display_order,
                amount.display_label,
                amount.semantic_mode,
                amount.display_quantity,
                amount.display_unit,
                amount.gram_equivalent,
                amount.is_default,
            )
            for amount in revision.amount_definitions
        ),
        tuple(
            (
                nutrient.id,
                nutrient.nutrient_id,
                nutrient.amount,
                nutrient.unit,
                nutrient.basis,
                nutrient.data_status,
            )
            for nutrient in revision.nutrients
        ),
    )


def _projection_snapshot(projection: FoodItem) -> tuple:
    return (
        projection.id,
        projection.name,
        projection.notes,
        projection.source_type,
        projection.source_id,
        projection.recipe_publication_revision_id,
        tuple(
            (
                serving.label,
                serving.quantity,
                serving.unit,
                serving.gram_weight,
                serving.is_default,
            )
            for serving in projection.serving_definitions
        ),
        tuple(
            (
                nutrient.nutrient_id,
                nutrient.amount,
                nutrient.unit,
                nutrient.basis,
                nutrient.data_status,
            )
            for nutrient in projection.nutrients
        ),
    )


def _resolved_values(resolved) -> list[tuple]:
    return [
        (
            nutrient.nutrient_id,
            nutrient.amount,
            nutrient.unit,
            nutrient.data_status.value,
            nutrient.source_basis.value,
        )
        for nutrient in resolved.nutrients
    ]


def test_first_publish_creates_revision_one_and_projection_from_revision(
    client: TestClient, db_session: Session
) -> None:
    recipe_id = _create_recipe(client)

    response = _publish(client, recipe_id)
    db_session.expire_all()
    recipe = db_session.get(Recipe, recipe_id)
    projection = db_session.get(FoodItem, UUID(response["food"]["id"]))
    history = _history(db_session, recipe)

    assert len(history) == 1
    revision = history[0]
    assert revision.revision_number == 1
    assert revision.creation_origin == "normal_publication"
    assert revision.provenance_confidence == "complete"
    assert revision.content_digest == revision_content_digest(revision)
    assert recipe.active_publication_revision_id == revision.id
    assert recipe.published_food_item_id == projection.id
    assert projection.recipe_publication_revision_id == revision.id
    assert projection_matches_revision(projection, revision)
    assert recipe.needs_republish is False
    assert response["recipe"]["published_food_item_id"] == str(projection.id)
    assert "active_publication_revision_id" not in response["recipe"]


def test_republish_appends_revision_and_never_mutates_previous_revision(
    client: TestClient, db_session: Session
) -> None:
    recipe_id = _create_recipe(client)
    first_response = _publish(client, recipe_id)
    db_session.expire_all()
    recipe = db_session.get(Recipe, recipe_id)
    first = _history(db_session, recipe)[0]
    first_snapshot = _revision_snapshot(first)
    projection_id = UUID(first_response["food"]["id"])

    update = client.patch(
        f"/api/v1/recipes/{recipe_id}",
        json={"name": "Managed Recipe Updated"},
    )
    assert update.status_code == 200
    assert update.json()["needs_republish"] is True
    second_response = _publish(client, recipe_id)

    db_session.expire_all()
    recipe = db_session.get(Recipe, recipe_id)
    history = _history(db_session, recipe)
    projection = db_session.get(FoodItem, projection_id)
    assert [revision.revision_number for revision in history] == [1, 2]
    assert _revision_snapshot(history[0]) == first_snapshot
    assert history[1].creation_origin == "explicit_republish"
    assert history[1].published_name == "Managed Recipe Updated"
    assert recipe.active_publication_revision_id == history[1].id
    assert projection.recipe_publication_revision_id == history[1].id
    assert projection_matches_revision(projection, history[1])
    assert second_response["food"]["id"] == str(projection_id)
    assert recipe.needs_republish is False


def test_identical_republish_creates_distinct_revision_with_equal_digest(
    client: TestClient, db_session: Session
) -> None:
    recipe_id = _create_recipe(client)
    _publish(client, recipe_id)
    _publish(client, recipe_id)
    db_session.expire_all()
    recipe = db_session.get(Recipe, recipe_id)
    history = _history(db_session, recipe)

    assert [revision.revision_number for revision in history] == [1, 2]
    assert history[0].id != history[1].id
    assert history[0].content_digest == history[1].content_digest
    assert recipe.active_publication_revision_id == history[1].id


def test_count_only_and_gram_capable_publications_preserve_amount_semantics(
    client: TestClient, db_session: Session
) -> None:
    count_recipe_id = _create_recipe(client, name="Count Only", cooked_grams=None)
    count_response = _publish(client, count_recipe_id)
    gram_recipe_id = _create_recipe(client, name="Gram Recipe")
    gram_response = _publish(client, gram_recipe_id)
    db_session.expire_all()

    count_recipe = db_session.get(Recipe, count_recipe_id)
    count_revision = _history(db_session, count_recipe)[0]
    assert all(amount.semantic_mode != "g" for amount in count_revision.amount_definitions)
    count_serving = count_revision.amount_definitions[0]
    assert count_serving.gram_equivalent is None
    count_detail = client.get(f"/api/v1/foods/{count_response['food']['id']}/resolved-nutrition")
    assert count_detail.status_code == 200
    assert count_detail.json()["amounts"][0]["semantic_amount_mode"] == "serving"

    gram_recipe = db_session.get(Recipe, gram_recipe_id)
    gram_revision = _history(db_session, gram_recipe)[0]
    canonical = [
        amount for amount in gram_revision.amount_definitions if amount.semantic_mode == "g"
    ]
    assert len(canonical) == 1
    assert canonical[0].display_quantity is None
    assert canonical[0].gram_equivalent is None
    projection = db_session.get(FoodItem, UUID(gram_response["food"]["id"]))
    assert {
        (row.nutrient_id, row.amount, row.unit, row.basis, row.data_status)
        for row in projection.nutrients
    } == {
        (row.nutrient_id, row.amount, row.unit, row.basis, row.data_status)
        for row in gram_revision.nutrients
    }


def test_projection_builder_preserves_statuses_units_and_mixed_bases() -> None:
    recipe_id = uuid4()
    user_id = uuid4()
    content = RecipePublicationContent(
        published_name="Status Recipe",
        published_notes=None,
        amount_definitions=(
            PublishedAmountContent(
                display_order=0,
                display_label="1 serving",
                semantic_mode="serving",
                display_quantity=Decimal("1"),
                display_unit="serving",
                gram_equivalent=Decimal("50"),
                is_default=True,
            ),
            PublishedAmountContent(
                display_order=1,
                display_label="g",
                semantic_mode="g",
                display_quantity=None,
                display_unit="g",
                gram_equivalent=None,
                is_default=False,
            ),
        ),
        nutrients=(
            PublishedNutrientContent("protein", Decimal("10"), "g", "per_serving", "known"),
            PublishedNutrientContent("protein", Decimal("20"), "g", "per_100g", "known"),
            PublishedNutrientContent("added_sugars", Decimal("0"), "g", "per_serving", "zero"),
            PublishedNutrientContent("calcium", Decimal("40"), "mg", "per_serving", "estimated"),
            PublishedNutrientContent("vitamin_d", None, "mcg", "per_serving", "unknown"),
        ),
    )
    revision = build_revision(
        recipe_id=recipe_id,
        user_id=user_id,
        revision_number=1,
        creation_origin="normal_publication",
        provenance_confidence="complete",
        content=content,
    )
    validate_revision_resolver_input(revision)
    projection = FoodItem(
        id=uuid4(),
        user_id=user_id,
        name="pending",
        source_type="recipe",
        source_id=str(recipe_id),
        is_recipe=True,
    )
    from datetime import datetime, timezone

    apply_revision_to_projection(
        projection,
        revision,
        recipe_id=recipe_id,
        user_id=user_id,
        updated_at=datetime.now(timezone.utc),
    )
    assert projection_matches_revision(projection, revision)
    serving = next(
        amount for amount in revision.amount_definitions if amount.semantic_mode == "serving"
    )
    source_serving = projection.serving_definitions[0]
    assert _resolved_values(
        resolve_revision_nutrition(revision, serving.id, Decimal("1"))
    ) == _resolved_values(resolve_nutrition(projection, Decimal("1"), "serving", source_serving.id))


def test_publish_after_transition_baseline_uses_next_revision_number(
    client: TestClient, db_session: Session
) -> None:
    recipe, _projection = _legacy_published_recipe(client, db_session)
    captured = RecipeRevisionCaptureService(db_session).capture_one(recipe.id, dry_run=False)
    assert captured.captured is True
    db_session.expire_all()
    recipe = db_session.get(Recipe, recipe.id)
    baseline = _history(db_session, recipe)[0]
    baseline_snapshot = _revision_snapshot(baseline)
    update = client.patch(f"/api/v1/recipes/{recipe.id}", json={"name": "Post-baseline"})
    assert update.status_code == 200

    _publish(client, recipe.id)

    db_session.expire_all()
    recipe = db_session.get(Recipe, recipe.id)
    history = _history(db_session, recipe)
    assert [revision.revision_number for revision in history] == [1, 2]
    assert _revision_snapshot(history[0]) == baseline_snapshot
    assert history[1].creation_origin == "explicit_republish"
    assert recipe.active_publication_revision_id == history[1].id


def test_soft_deleted_projection_is_not_resurrected_during_republish(
    client: TestClient, db_session: Session
) -> None:
    recipe_id = _create_recipe(client)
    first = _publish(client, recipe_id)
    old_projection_id = UUID(first["food"]["id"])
    old_projection = db_session.get(FoodItem, old_projection_id)
    from datetime import datetime, timezone

    old_projection.deleted_at = datetime.now(timezone.utc)
    db_session.commit()
    update = client.patch(f"/api/v1/recipes/{recipe_id}", json={"name": "Repair publish"})
    assert update.status_code == 200

    repaired = _publish(client, recipe_id)

    new_projection_id = UUID(repaired["food"]["id"])
    assert new_projection_id != old_projection_id
    db_session.expire_all()
    old_projection = db_session.get(FoodItem, old_projection_id)
    new_projection = db_session.get(FoodItem, new_projection_id)
    recipe = db_session.get(Recipe, recipe_id)
    history = _history(db_session, recipe)
    assert old_projection.deleted_at is not None
    assert new_projection.deleted_at is None
    assert new_projection.recipe_publication_revision_id == history[-1].id
    assert recipe.published_food_item_id == new_projection.id


def test_unrelated_legacy_projection_is_not_reused_or_mutated(
    client: TestClient, db_session: Session
) -> None:
    recipe_id = _create_recipe(client)
    recipe = db_session.get(Recipe, recipe_id)
    unrelated = FoodItem(
        id=uuid4(),
        user_id=recipe.user_id,
        name="Unrelated Manual Food",
        source_type="manual",
        source_id=None,
        is_recipe=False,
    )
    db_session.add(unrelated)
    db_session.flush()
    recipe.published_food_item_id = unrelated.id
    db_session.commit()

    response = _publish(client, recipe_id)

    db_session.expire_all()
    unrelated = db_session.get(FoodItem, unrelated.id)
    recipe = db_session.get(Recipe, recipe_id)
    projection = db_session.get(FoodItem, UUID(response["food"]["id"]))
    assert projection.id != unrelated.id
    assert unrelated.name == "Unrelated Manual Food"
    assert unrelated.source_type == "manual"
    assert unrelated.recipe_publication_revision_id is None
    assert recipe.published_food_item_id == projection.id
    assert projection.source_type == "recipe"


def test_conflicting_active_projections_abort_without_revision_or_repair(
    client: TestClient, db_session: Session
) -> None:
    recipe_id = _create_recipe(client)
    recipe = db_session.get(Recipe, recipe_id)
    projections = [
        FoodItem(
            id=uuid4(),
            user_id=recipe.user_id,
            name=f"Conflict {index}",
            source_type="recipe",
            source_id=str(recipe.id),
            is_recipe=True,
        )
        for index in range(2)
    ]
    db_session.add_all(projections)
    db_session.commit()

    with pytest.raises(ValueError, match="multiple active"):
        RecipeService(db_session).publish(recipe.user_id, recipe.id)

    db_session.expire_all()
    recipe = db_session.get(Recipe, recipe_id)
    assert _history(db_session, recipe) == []
    assert recipe.active_publication_revision_id is None
    assert recipe.published_food_item_id is None
    assert all(projection.recipe_publication_revision_id is None for projection in projections)


def test_soft_deleted_recipe_cannot_publish(client: TestClient, db_session: Session) -> None:
    recipe_id = _create_recipe(client)
    deleted = client.delete(f"/api/v1/recipes/{recipe_id}")
    assert deleted.status_code == 204

    response = client.post(f"/api/v1/recipes/{recipe_id}/publish")

    assert response.status_code == 404
    recipe = db_session.get(Recipe, recipe_id)
    assert _history(db_session, recipe) == []


@pytest.mark.parametrize(
    "failure_stage",
    [
        "after_header",
        "after_children",
        "after_active",
        "after_projection_mutation",
        "after_projection_link",
    ],
)
def test_publication_failure_stages_roll_back_every_effect(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    recipe_id = _create_recipe(client)
    first_response = _publish(client, recipe_id)
    projection_id = UUID(first_response["food"]["id"])
    update = client.patch(f"/api/v1/recipes/{recipe_id}", json={"name": "Unpublished change"})
    assert update.status_code == 200
    db_session.expire_all()
    recipe = db_session.get(Recipe, recipe_id)
    baseline = _history(db_session, recipe)[0]
    baseline_revision = _revision_snapshot(baseline)
    baseline_active = recipe.active_publication_revision_id
    projection = db_session.get(FoodItem, projection_id)
    baseline_projection = _projection_snapshot(projection)
    service = RecipeService(db_session)
    listener = None

    def fail(*_args) -> None:
        raise RuntimeError(f"injected {failure_stage} failure")

    if failure_stage == "after_header":

        def listener(_conn, _cursor, statement, _parameters, _context, _executemany):
            if "INSERT INTO recipe_publication_amount_definitions" in statement:
                raise RuntimeError("injected failure after revision header insertion")

        event.listen(db_session.get_bind(), "before_cursor_execute", listener)
    elif failure_stage == "after_children":
        monkeypatch.setattr(service, "_after_revision_insert", fail)
    elif failure_stage == "after_active":
        monkeypatch.setattr(service, "_after_active_revision_assignment", fail)
    elif failure_stage == "after_projection_mutation":
        monkeypatch.setattr(service, "_after_projection_refresh", fail)
    else:
        monkeypatch.setattr(service, "_after_projection_link", fail)

    try:
        with pytest.raises(RuntimeError):
            service.publish(recipe.user_id, recipe.id)
    finally:
        if listener is not None:
            event.remove(db_session.get_bind(), "before_cursor_execute", listener)

    db_session.expire_all()
    recipe = db_session.get(Recipe, recipe_id)
    projection = db_session.get(FoodItem, projection_id)
    history = _history(db_session, recipe)
    assert len(history) == 1
    assert _revision_snapshot(history[0]) == baseline_revision
    assert recipe.active_publication_revision_id == baseline_active
    assert recipe.needs_republish is True
    assert _projection_snapshot(projection) == baseline_projection


def test_separate_successful_publications_allocate_consecutive_numbers_and_one_projection(
    client: TestClient, db_session: Session
) -> None:
    recipe_id = _create_recipe(client)
    first = _publish(client, recipe_id)
    second = _publish(client, recipe_id)
    third = _publish(client, recipe_id)
    db_session.expire_all()
    recipe = db_session.get(Recipe, recipe_id)
    history = _history(db_session, recipe)

    assert [revision.revision_number for revision in history] == [1, 2, 3]
    assert recipe.active_publication_revision_id == history[-1].id
    assert first["food"]["id"] == second["food"]["id"] == third["food"]["id"]
    active_projections = RecipeService(db_session).foods.list_active_by_source(
        recipe.user_id,
        "recipe",
        str(recipe.id),
    )
    assert len(active_projections) == 1
    assert active_projections[0].recipe_publication_revision_id == history[-1].id


def test_publication_recipe_load_uses_postgres_row_lock() -> None:
    db = Mock()
    sentinel_recipe = object()
    db.scalars.return_value.first.return_value = sentinel_recipe
    repository = RecipeRepository(db)

    assert repository.get_for_update(uuid4(), uuid4()) is sentinel_recipe

    statement = db.scalars.call_args.args[0]
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in compiled


def test_new_recipe_logs_associate_with_revision_backed_publish(
    client: TestClient, db_session: Session
) -> None:
    recipe_id = _create_recipe(client)
    response = _publish(client, recipe_id)
    food = response["food"]
    serving = next(value for value in food["serving_definitions"] if value["is_default"])
    logged = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": "2026-07-13",
            "amount_quantity": "1",
            "amount_unit": "serving",
            "serving_definition_id": serving["id"],
        },
    )
    assert logged.status_code == 201
    log = db_session.get(DailyLog, UUID(logged.json()["id"]))
    assert log.recipe_publication_revision_id is not None
    assert log.recipe_publication_amount_definition_id is not None
