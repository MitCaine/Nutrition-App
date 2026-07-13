from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dependencies.user import ensure_dev_user
from app.models.food import FoodItem
from app.models.recipe import Recipe
from app.models.recipe_publication import RecipePublicationRevision
from app.models.user import User
from app.nutrition.resolution import resolve_nutrition
from app.nutrition.revision_resolution import resolve_revision_nutrition
from app.publication.recipe_revision import (
    apply_revision_to_projection,
    build_revision,
    content_from_recipe_output,
)
from app.services.recipe_service import RecipeService
from app.services.recipe_revision_capture_service import (
    CAPTURE_CONFIDENCE,
    CAPTURE_ORIGIN,
    CaptureCategory,
    RecipeRevisionCaptureService,
)
from tests.test_stage4_recipes import _per_100g_food


def _published_recipe(
    client: TestClient,
    db: Session,
    *,
    name: str = "Captured Soup",
    serving_count: str | None = "2",
    cooked_grams: str | None = "400",
    runtime_publish: bool = False,
) -> tuple[Recipe, FoodItem]:
    ingredient = _per_100g_food(client, name=f"{name} ingredient")
    payload = {
        "name": name,
        "notes": "published projection notes",
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
    }
    created = client.post("/api/v1/recipes", json=payload)
    assert created.status_code == 201, created.text
    recipe_id = UUID(created.json()["id"])
    if runtime_publish:
        published = client.post(f"/api/v1/recipes/{recipe_id}/publish")
        assert published.status_code == 200, published.text
    else:
        db.expire_all()
        recipe = db.get(Recipe, recipe_id)
        service = RecipeService(db)
        totals = service._calculate_totals(recipe)
        per_serving = service._divide_totals(totals, recipe.serving_count_yield)
        per_100g = service._divide_totals(
            totals,
            (
                recipe.final_cooked_weight_grams / Decimal("100")
                if recipe.final_cooked_weight_grams
                else None
            ),
        )
        transient_revision = build_revision(
            recipe_id=recipe.id,
            user_id=recipe.user_id,
            revision_number=1,
            creation_origin="legacy_projection_capture",
            provenance_confidence="transition_baseline",
            content=content_from_recipe_output(
                published_name=recipe.name,
                published_notes=recipe.notes,
                serving_count_yield=recipe.serving_count_yield,
                final_cooked_weight_grams=recipe.final_cooked_weight_grams,
                per_serving=per_serving,
                per_100g=per_100g,
            ),
        )
        projection = FoodItem(
            id=uuid4(),
            user_id=recipe.user_id,
            name=recipe.name,
            source_type="recipe",
            source_id=str(recipe.id),
            is_recipe=True,
        )
        projection_time = datetime.now(timezone.utc)
        apply_revision_to_projection(
            projection,
            transient_revision,
            recipe_id=recipe.id,
            user_id=recipe.user_id,
            updated_at=projection_time,
        )
        db.add(projection)
        recipe.published_food_item = projection
        recipe.needs_republish = False
        recipe.updated_at = datetime.now(timezone.utc)
        db.commit()
    db.expire_all()
    recipe = db.get(Recipe, recipe_id)
    assert recipe is not None and recipe.published_food_item_id is not None
    projection = db.get(FoodItem, recipe.published_food_item_id)
    assert projection is not None
    return recipe, projection


def _revision_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(RecipePublicationRevision)) or 0


def _nutrient_values(resolved) -> list[tuple]:
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


def test_eligible_projection_captures_complete_transition_baseline(
    client: TestClient, db_session: Session
) -> None:
    recipe, projection = _published_recipe(client, db_session)
    original_stale = recipe.needs_republish

    result = RecipeRevisionCaptureService(db_session).capture_one(recipe.id, dry_run=False)

    assert result.category == CaptureCategory.ELIGIBLE
    assert result.captured is True
    assert result.proposed_origin == CAPTURE_ORIGIN
    assert result.proposed_provenance_confidence == CAPTURE_CONFIDENCE
    db_session.expire_all()
    recipe = db_session.get(Recipe, recipe.id)
    projection = db_session.get(FoodItem, projection.id)
    revision = db_session.get(RecipePublicationRevision, result.captured_revision_id)
    assert recipe.active_publication_revision_id == revision.id
    assert projection.recipe_publication_revision_id == revision.id
    assert recipe.needs_republish is original_stale
    assert revision.published_name == projection.name
    assert revision.published_notes == projection.notes
    assert revision.creation_origin == "legacy_projection_capture"
    assert revision.provenance_confidence == "transition_baseline"
    assert {row.basis for row in revision.nutrients} == {"per_serving", "per_100g"}
    assert len([row for row in revision.amount_definitions if row.semantic_mode == "g"]) == 1
    gram = next(row for row in revision.amount_definitions if row.semantic_mode == "g")
    assert gram.display_quantity is None
    assert gram.gram_equivalent is None


def test_stale_recipe_captures_projection_not_authored_draft(
    client: TestClient, db_session: Session
) -> None:
    recipe, projection = _published_recipe(client, db_session, name="Published Name")
    response = client.patch(
        f"/api/v1/recipes/{recipe.id}",
        json={"name": "Unpublished Draft Name", "notes": "draft notes"},
    )
    assert response.status_code == 200
    assert response.json()["needs_republish"] is True

    result = RecipeRevisionCaptureService(db_session).capture_one(recipe.id, dry_run=False)

    assert result.category == CaptureCategory.STALE_ELIGIBLE
    db_session.expire_all()
    refreshed = db_session.get(Recipe, recipe.id)
    revision = db_session.get(RecipePublicationRevision, result.captured_revision_id)
    assert refreshed.name == "Unpublished Draft Name"
    assert refreshed.needs_republish is True
    assert revision.published_name == projection.name == "Published Name"
    assert revision.published_notes == projection.notes == "published projection notes"


def test_unpublished_and_deleted_recipe_are_classified_without_writes(
    db_session: Session,
) -> None:
    user = ensure_dev_user(db_session)
    unpublished = Recipe(id=uuid4(), user_id=user.id, name="Draft")
    deleted = Recipe(
        id=uuid4(),
        user_id=user.id,
        name="Deleted",
        deleted_at=datetime.now(timezone.utc),
    )
    db_session.add_all([unpublished, deleted])
    db_session.commit()
    service = RecipeRevisionCaptureService(db_session)

    assert service.capture_one(unpublished.id).category == CaptureCategory.UNPUBLISHED
    assert service.capture_one(deleted.id).category == CaptureCategory.DELETED_RECIPE
    assert _revision_count(db_session) == 0


def test_deleted_projection_is_not_reactivated_or_captured(
    client: TestClient, db_session: Session
) -> None:
    recipe, projection = _published_recipe(client, db_session)
    projection.deleted_at = datetime.now(timezone.utc)
    db_session.commit()

    result = RecipeRevisionCaptureService(db_session).capture_one(recipe.id, dry_run=False)

    assert result.category == CaptureCategory.DELETED_PROJECTION
    assert result.captured is False
    db_session.refresh(projection)
    assert projection.deleted_at is not None
    assert recipe.active_publication_revision_id is None
    assert _revision_count(db_session) == 0


def test_missing_projection_is_reported_without_fabricating_history(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    recipe, _projection = _published_recipe(client, db_session)
    service = RecipeRevisionCaptureService(db_session)
    monkeypatch.setattr(service, "_load_projection", lambda _food_id, lock: None)

    result = service.capture_one(recipe.id, dry_run=False)

    assert result.category == CaptureCategory.MISSING_PROJECTION
    assert _revision_count(db_session) == 0


@pytest.mark.parametrize("inconsistency", ["owner", "source_type", "source_id"])
def test_inconsistent_projection_linkage_creates_no_partial_revision(
    client: TestClient,
    db_session: Session,
    inconsistency: str,
) -> None:
    recipe, projection = _published_recipe(client, db_session)
    if inconsistency == "owner":
        other = User(id=uuid4(), email=f"other-{uuid4()}@example.test")
        db_session.add(other)
        db_session.flush()
        projection.user_id = other.id
    elif inconsistency == "source_type":
        projection.source_type = "manual"
    else:
        projection.source_id = str(uuid4())
    db_session.commit()

    result = RecipeRevisionCaptureService(db_session).capture_one(recipe.id, dry_run=False)

    assert result.category == CaptureCategory.INCONSISTENT_LINKAGE
    assert result.captured is False
    assert _revision_count(db_session) == 0


def test_multiple_active_generated_projections_are_inconsistent(
    client: TestClient, db_session: Session
) -> None:
    recipe, projection = _published_recipe(client, db_session)
    conflict = FoodItem(
        id=uuid4(),
        user_id=recipe.user_id,
        name="Conflicting projection",
        source_type="recipe",
        source_id=str(recipe.id),
        is_recipe=True,
    )
    db_session.add(conflict)
    db_session.commit()

    result = RecipeRevisionCaptureService(db_session).capture_one(recipe.id, dry_run=False)

    assert result.category == CaptureCategory.INCONSISTENT_LINKAGE
    assert projection.recipe_publication_revision_id is None
    assert _revision_count(db_session) == 0


def test_conflicting_existing_revision_linkage_is_not_repaired(
    client: TestClient, db_session: Session
) -> None:
    recipe, projection = _published_recipe(client, db_session)
    other = Recipe(id=uuid4(), user_id=recipe.user_id, name="Other")
    revision = RecipePublicationRevision(
        id=uuid4(),
        recipe_id=other.id,
        user_id=other.user_id,
        revision_number=1,
        creation_origin="normal_publication",
        provenance_confidence="complete",
        published_name="Other",
        content_digest="diagnostic",
    )
    db_session.add_all([other, revision])
    db_session.flush()
    projection.recipe_publication_revision_id = revision.id
    db_session.commit()

    result = RecipeRevisionCaptureService(db_session).capture_one(recipe.id, dry_run=False)

    assert result.category == CaptureCategory.INCONSISTENT_LINKAGE
    assert recipe.active_publication_revision_id is None
    assert _revision_count(db_session) == 1


def test_independently_modified_projection_is_ambiguous_and_unlinked(
    client: TestClient, db_session: Session
) -> None:
    recipe, projection = _published_recipe(client, db_session)
    projection.serving_definitions[0].source = "manual"
    db_session.commit()

    result = RecipeRevisionCaptureService(db_session).capture_one(recipe.id, dry_run=False)

    assert result.category == CaptureCategory.AMBIGUOUS
    assert result.captured is False
    assert recipe.active_publication_revision_id is None
    assert projection.recipe_publication_revision_id is None
    assert _revision_count(db_session) == 0


def test_resolver_invalid_projection_is_reported_as_failed_validation(
    client: TestClient, db_session: Session
) -> None:
    recipe, projection = _published_recipe(client, db_session)
    for serving in projection.serving_definitions:
        serving.is_default = True
    db_session.commit()

    result = RecipeRevisionCaptureService(db_session).capture_one(recipe.id, dry_run=False)

    assert result.category == CaptureCategory.FAILED_VALIDATION
    assert result.captured is False
    assert _revision_count(db_session) == 0


def test_capture_and_dry_run_are_rerunnable_without_duplicate_revision(
    client: TestClient, db_session: Session
) -> None:
    recipe, _projection = _published_recipe(client, db_session)
    service = RecipeRevisionCaptureService(db_session)
    dry_first = service.capture_one(recipe.id)
    dry_second = service.capture_one(recipe.id)
    assert dry_first.proposed_content_digest == dry_second.proposed_content_digest
    assert _revision_count(db_session) == 0

    captured = service.capture_one(recipe.id, dry_run=False)
    rerun = service.capture_one(recipe.id, dry_run=False)
    dry_after = service.capture_one(recipe.id)

    assert captured.captured is True
    assert rerun.category == CaptureCategory.ALREADY_MANAGED
    assert dry_after.category == CaptureCategory.ALREADY_MANAGED
    assert _revision_count(db_session) == 1


def test_already_managed_capture_detects_projection_drift(
    client: TestClient, db_session: Session
) -> None:
    recipe, projection = _published_recipe(client, db_session)
    service = RecipeRevisionCaptureService(db_session)
    captured = service.capture_one(recipe.id, dry_run=False)
    assert captured.captured is True
    calories = next(row for row in projection.nutrients if row.nutrient_id == "calories")
    calories.amount += Decimal("1")
    db_session.commit()

    rerun = service.capture_one(recipe.id)

    assert rerun.category == CaptureCategory.INCONSISTENT_LINKAGE
    assert rerun.captured is False
    assert _revision_count(db_session) == 1


def test_count_only_projection_does_not_fabricate_gram_mode(
    client: TestClient, db_session: Session
) -> None:
    recipe, _projection = _published_recipe(client, db_session, cooked_grams=None)

    result = RecipeRevisionCaptureService(db_session).capture_one(recipe.id, dry_run=False)
    revision = db_session.get(RecipePublicationRevision, result.captured_revision_id)

    assert result.captured is True
    assert all(amount.semantic_mode != "g" for amount in revision.amount_definitions)
    serving = next(
        amount for amount in revision.amount_definitions if amount.semantic_mode == "serving"
    )
    assert serving.gram_equivalent is None


def test_captured_revision_resolution_matches_projection_for_servings_and_grams(
    client: TestClient, db_session: Session
) -> None:
    recipe, projection = _published_recipe(client, db_session)
    calories = [row for row in projection.nutrients if row.nutrient_id == "calories"]
    for row in calories:
        row.data_status = "estimated"
    db_session.commit()

    result = RecipeRevisionCaptureService(db_session).capture_one(recipe.id, dry_run=False)
    revision = db_session.get(RecipePublicationRevision, result.captured_revision_id)
    serving_amount = next(
        amount
        for amount in revision.amount_definitions
        if amount.semantic_mode == "serving" and amount.display_label == "1 serving"
    )
    source_serving = next(
        serving for serving in projection.serving_definitions if serving.label == "1 serving"
    )
    projection_serving = resolve_nutrition(
        projection,
        Decimal("1.5"),
        "serving",
        source_serving.id,
    )
    revision_serving = resolve_revision_nutrition(
        revision,
        serving_amount.id,
        Decimal("1.5"),
    )
    assert _nutrient_values(revision_serving) == _nutrient_values(projection_serving)

    gram_amount = next(
        amount for amount in revision.amount_definitions if amount.semantic_mode == "g"
    )
    projection_grams = resolve_nutrition(projection, Decimal("50"), "g")
    revision_grams = resolve_revision_nutrition(revision, gram_amount.id, Decimal("50"))
    assert _nutrient_values(revision_grams) == _nutrient_values(projection_grams)
    statuses = {nutrient.data_status.value for nutrient in revision_grams.nutrients}
    assert {"estimated", "zero", "unknown"}.issubset(statuses)


def test_capture_transaction_rolls_back_revision_and_links_on_child_failure(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recipe, projection = _published_recipe(client, db_session)
    response = client.patch(f"/api/v1/recipes/{recipe.id}", json={"name": "Stale draft"})
    assert response.status_code == 200
    service = RecipeRevisionCaptureService(db_session)
    original_add = service.revisions.add

    def fail_after_insert(revision):
        original_add(revision)
        raise RuntimeError("injected child failure")

    monkeypatch.setattr(service.revisions, "add", fail_after_insert)
    result = service.capture_one(recipe.id, dry_run=False)

    assert result.category == CaptureCategory.UNEXPECTED_FAILURE
    assert _revision_count(db_session) == 0
    db_session.refresh(recipe)
    db_session.refresh(projection)
    assert recipe.active_publication_revision_id is None
    assert projection.recipe_publication_revision_id is None
    assert recipe.needs_republish is True


def test_capture_transaction_rolls_back_when_link_assignment_is_invalid(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recipe, projection = _published_recipe(client, db_session)
    service = RecipeRevisionCaptureService(db_session)

    def invalid_links(recipe_to_link, projection_to_link, _revision):
        invalid_id = uuid4()
        recipe_to_link.active_publication_revision_id = invalid_id
        projection_to_link.recipe_publication_revision_id = invalid_id

    monkeypatch.setattr(service, "_assign_links", invalid_links)
    result = service.capture_one(recipe.id, dry_run=False)

    assert result.category == CaptureCategory.UNEXPECTED_FAILURE
    assert _revision_count(db_session) == 0
    db_session.refresh(recipe)
    db_session.refresh(projection)
    assert recipe.active_publication_revision_id is None
    assert projection.recipe_publication_revision_id is None


def test_dry_run_report_is_structured_stable_and_writes_nothing(
    client: TestClient, db_session: Session
) -> None:
    eligible, _projection = _published_recipe(client, db_session)
    user = ensure_dev_user(db_session)
    unpublished = Recipe(id=uuid4(), user_id=user.id, name="Draft")
    db_session.add(unpublished)
    db_session.commit()
    service = RecipeRevisionCaptureService(db_session)

    first = service.capture_all()
    second = service.capture_all()

    assert first.to_dict() == second.to_dict()
    assert first.counts["total_recipes_inspected"] == 2
    assert first.counts["eligible_captures"] == 1
    assert first.counts["unpublished"] == 1
    eligible_result = next(result for result in first.results if result.recipe_id == eligible.id)
    assert eligible_result.proposed_revision_number == 1
    assert eligible_result.proposed_origin == "legacy_projection_capture"
    assert eligible_result.proposed_provenance_confidence == "transition_baseline"
    assert eligible_result.proposed_content_digest is not None
    assert _revision_count(db_session) == 0


def test_runtime_publish_and_new_logs_are_revision_backed(
    client: TestClient, db_session: Session
) -> None:
    recipe, projection = _published_recipe(client, db_session, runtime_publish=True)
    assert recipe.active_publication_revision_id is not None
    assert projection.recipe_publication_revision_id == recipe.active_publication_revision_id
    assert _revision_count(db_session) == 1
    serving = next(serving for serving in projection.serving_definitions if serving.is_default)
    response = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": str(projection.id),
            "logged_date": "2026-07-13",
            "amount_quantity": "1",
            "amount_unit": "serving",
            "serving_definition_id": str(serving.id),
        },
    )
    assert response.status_code == 201, response.text
    from app.models.log import DailyLog

    log = db_session.get(DailyLog, UUID(response.json()["id"]))
    assert log.recipe_publication_revision_id == recipe.active_publication_revision_id
    assert log.recipe_publication_amount_definition_id is not None
