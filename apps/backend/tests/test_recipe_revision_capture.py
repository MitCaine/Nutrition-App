from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.dependencies.user import ensure_dev_user
from app.models.food import FoodItem
from app.models.recipe import Recipe
from app.models.recipe_publication import RecipePublicationRevision
from app.models.user import User
from app.publication.recipe_revision import (
    apply_revision_to_projection,
    build_revision,
    content_from_recipe_output,
)
from app.services.recipe_revision_capture_service import (
    CAPTURE_APPLY_RETIRED_MESSAGE,
    CAPTURE_CONFIDENCE,
    CAPTURE_ORIGIN,
    CaptureCategory,
    RecipeRevisionCaptureApplyRetiredError,
    RecipeRevisionCaptureService,
)
from app.services.recipe_service import RecipeService
from scripts import capture_recipe_publication_revisions as capture_cli
from tests.test_stage4_recipes import _per_100g_food


def _published_recipe(
    client: TestClient,
    db: Session,
    *,
    name: str = "Captured Soup",
    serving_count: str | None = "2",
    cooked_grams: str | None = "400",
    runtime_publish: bool = False,
    seed_transition_baseline: bool = False,
) -> tuple[Recipe, FoodItem]:
    if runtime_publish and seed_transition_baseline:
        raise ValueError("Choose runtime publication or a seeded transition baseline")
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
            creation_origin=CAPTURE_ORIGIN,
            provenance_confidence=CAPTURE_CONFIDENCE,
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
        apply_revision_to_projection(
            projection,
            transient_revision,
            recipe_id=recipe.id,
            user_id=recipe.user_id,
            updated_at=datetime.now(timezone.utc),
        )
        db.add(projection)
        recipe.published_food_item = projection
        recipe.needs_republish = False
        recipe.updated_at = datetime.now(timezone.utc)
        db.commit()
        if seed_transition_baseline:
            db.add(transient_revision)
            db.flush()
            recipe.active_publication_revision_id = transient_revision.id
            projection.recipe_publication_revision_id = transient_revision.id
            db.commit()
    db.expire_all()
    recipe = db.get(Recipe, recipe_id)
    assert recipe is not None and recipe.published_food_item_id is not None
    projection = db.get(FoodItem, recipe.published_food_item_id)
    assert projection is not None
    return recipe, projection


def _revision_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(RecipePublicationRevision)) or 0


def test_dry_run_report_is_stable_and_executes_no_database_writes(
    client: TestClient,
    db_session: Session,
) -> None:
    eligible, projection = _published_recipe(client, db_session)
    user = ensure_dev_user(db_session)
    unpublished = Recipe(id=uuid4(), user_id=user.id, name="Draft")
    db_session.add(unpublished)
    db_session.commit()
    write_statements: list[str] = []

    def record_database_write(_conn, _cursor, statement, _parameters, _context, _many):
        operation = statement.lstrip().partition(" ")[0].upper()
        if operation in {"INSERT", "UPDATE", "DELETE"}:
            write_statements.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", record_database_write)
    try:
        service = RecipeRevisionCaptureService(db_session)
        first = service.capture_all()
        second = service.capture_all()
    finally:
        event.remove(db_session.bind, "before_cursor_execute", record_database_write)

    assert first.to_dict() == second.to_dict()
    assert first.dry_run is True
    assert first.counts["total_recipes_inspected"] == 2
    assert first.counts["eligible_captures"] == 1
    assert first.counts["unpublished"] == 1
    eligible_result = next(result for result in first.results if result.recipe_id == eligible.id)
    assert eligible_result.category == CaptureCategory.ELIGIBLE
    assert eligible_result.proposed_revision_number == 1
    assert eligible_result.proposed_origin == CAPTURE_ORIGIN
    assert eligible_result.proposed_provenance_confidence == CAPTURE_CONFIDENCE
    assert eligible_result.proposed_content_digest is not None
    assert write_statements == []
    assert not db_session.new
    assert not db_session.dirty
    assert not db_session.deleted
    assert _revision_count(db_session) == 0
    db_session.refresh(eligible)
    db_session.refresh(projection)
    assert eligible.active_publication_revision_id is None
    assert projection.recipe_publication_revision_id is None


def test_dry_run_preserves_stale_draft_and_classifies_projection_content(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe, projection = _published_recipe(client, db_session, name="Published Name")
    response = client.patch(
        f"/api/v1/recipes/{recipe.id}",
        json={"name": "Unpublished Draft Name", "notes": "draft notes"},
    )
    assert response.status_code == 200

    result = RecipeRevisionCaptureService(db_session).capture_one(recipe.id)

    assert result.category == CaptureCategory.STALE_ELIGIBLE
    assert result.stale_state_preserved is True
    assert result.captured is False
    assert _revision_count(db_session) == 0
    db_session.expire_all()
    refreshed_recipe = db_session.get(Recipe, recipe.id)
    refreshed_projection = db_session.get(FoodItem, projection.id)
    assert refreshed_recipe.name == "Unpublished Draft Name"
    assert refreshed_recipe.notes == "draft notes"
    assert refreshed_recipe.needs_republish is True
    assert refreshed_projection.name == "Published Name"
    assert refreshed_projection.notes == "published projection notes"


def test_dry_run_classifies_unpublished_and_deleted_recipes_without_writes(
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


def test_dry_run_reports_deleted_projection_without_reactivating_it(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe, projection = _published_recipe(client, db_session)
    projection.deleted_at = datetime.now(timezone.utc)
    db_session.commit()

    result = RecipeRevisionCaptureService(db_session).capture_one(recipe.id)

    assert result.category == CaptureCategory.DELETED_PROJECTION
    assert result.captured is False
    db_session.refresh(projection)
    assert projection.deleted_at is not None
    assert recipe.active_publication_revision_id is None
    assert _revision_count(db_session) == 0


def test_dry_run_reports_missing_projection_without_fabricating_history(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recipe, _projection = _published_recipe(client, db_session)
    service = RecipeRevisionCaptureService(db_session)
    monkeypatch.setattr(service, "_load_projection", lambda _food_id, _user_id: None)

    result = service.capture_one(recipe.id)

    assert result.category == CaptureCategory.MISSING_PROJECTION
    assert _revision_count(db_session) == 0


@pytest.mark.parametrize("inconsistency", ["owner", "source_type", "source_id"])
def test_dry_run_reports_inconsistent_projection_linkage(
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

    result = RecipeRevisionCaptureService(db_session).capture_one(recipe.id)

    assert result.category == (
        CaptureCategory.MISSING_PROJECTION
        if inconsistency == "owner"
        else CaptureCategory.INCONSISTENT_LINKAGE
    )
    assert result.captured is False
    assert _revision_count(db_session) == 0


def test_dry_run_reports_ambiguous_independent_projection_edit(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe, projection = _published_recipe(client, db_session)
    projection.serving_definitions[0].source = "manual"
    db_session.commit()

    result = RecipeRevisionCaptureService(db_session).capture_one(recipe.id)

    assert result.category == CaptureCategory.AMBIGUOUS
    assert result.captured is False
    assert recipe.active_publication_revision_id is None
    assert projection.recipe_publication_revision_id is None
    assert _revision_count(db_session) == 0


def test_dry_run_reports_invalid_projection_without_creating_revision(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe, projection = _published_recipe(client, db_session)
    for serving in projection.serving_definitions:
        serving.is_default = False
    db_session.commit()

    result = RecipeRevisionCaptureService(db_session).capture_one(recipe.id)

    assert result.category == CaptureCategory.FAILED_VALIDATION
    assert result.captured is False
    assert _revision_count(db_session) == 0


def test_dry_run_reports_already_managed_runtime_publication(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe, _projection = _published_recipe(client, db_session, runtime_publish=True)

    result = RecipeRevisionCaptureService(db_session).capture_one(recipe.id)

    assert result.category == CaptureCategory.ALREADY_MANAGED
    assert result.captured is False
    assert result.captured_revision_id == recipe.active_publication_revision_id
    assert _revision_count(db_session) == 1


@pytest.mark.parametrize("entry_point", ["capture_one", "capture_all"])
def test_apply_entry_points_fail_before_any_database_operation(entry_point: str) -> None:
    db = Mock(spec=Session)
    service = RecipeRevisionCaptureService(db)

    with pytest.raises(
        RecipeRevisionCaptureApplyRetiredError,
        match="only dry-run inspection is supported",
    ) as exc_info:
        if entry_point == "capture_one":
            service.capture_one(uuid4(), dry_run=False)
        else:
            service.capture_all(dry_run=False)

    assert str(exc_info.value) == CAPTURE_APPLY_RETIRED_MESSAGE
    db.scalars.assert_not_called()
    db.add.assert_not_called()
    db.flush.assert_not_called()
    db.commit.assert_not_called()
    db.rollback.assert_not_called()


def test_cli_apply_fails_before_opening_database_session(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session_factory = Mock(side_effect=AssertionError("database session must not be opened"))
    monkeypatch.setattr(capture_cli, "SessionLocal", session_factory)
    monkeypatch.setattr(sys, "argv", ["capture_recipe_publication_revisions.py", "--apply"])

    with pytest.raises(SystemExit) as exc_info:
        capture_cli.main()

    assert exc_info.value.code == 2
    assert capsys.readouterr().err.strip() == CAPTURE_APPLY_RETIRED_MESSAGE
    session_factory.assert_not_called()


def test_runtime_publish_and_new_logs_are_revision_backed(
    client: TestClient,
    db_session: Session,
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
