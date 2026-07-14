from __future__ import annotations

from copy import deepcopy
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.dependencies.user import ensure_dev_user
from app.models.food import FoodItem
from app.models.log import DailyLog, DailyLogNutrientSnapshot
from app.models.recipe import Recipe
from app.models.recipe_publication import RecipePublicationRevision
from app.models.user import User
from app.services.recipe_revision_capture_service import RecipeRevisionCaptureService
from app.services.retention_audit_service import (
    RetentionAuditService,
    RetentionCategory,
)
from tests.test_recipe_revision_capture import _published_recipe as _legacy_published_recipe
from tests.test_recipe_revision_logging import _post_log, _published


def _record(report, entity_type: str, entity_id: UUID | str):
    return next(
        row
        for row in report.records
        if row.entity_type == entity_type and row.entity_id == UUID(str(entity_id))
    )


def _default_serving(food: dict) -> dict:
    return next(row for row in food["serving_definitions"] if row["is_default"])


def test_revision_retention_categories_protect_active_historical_and_superseded(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe_id, projection = _published(client)
    recipe = db_session.get(Recipe, recipe_id)
    first_revision_id = recipe.active_publication_revision_id
    logged = _post_log(
        client,
        projection,
        serving_definition_id=_default_serving(projection)["id"],
    )
    assert logged.status_code == 201, logged.text
    assert client.post(f"/api/v1/recipes/{recipe_id}/publish").status_code == 200
    db_session.expire_all()
    second_revision_id = db_session.get(Recipe, recipe_id).active_publication_revision_id
    assert client.post(f"/api/v1/recipes/{recipe_id}/publish").status_code == 200
    db_session.expire_all()
    active_revision_id = db_session.get(Recipe, recipe_id).active_publication_revision_id
    owner_id = db_session.get(Recipe, recipe_id).user_id

    report = RetentionAuditService(db_session).audit_owner(owner_id)
    historical = _record(report, "publication_revision", first_revision_id)
    superseded = _record(report, "publication_revision", second_revision_id)
    active = _record(report, "publication_revision", active_revision_id)
    active_projection = _record(report, "food_projection", projection["id"])

    assert historical.category == RetentionCategory.HISTORICALLY_REFERENCED
    assert historical.reference_counts["daily_logs"] == 1
    assert historical.reference_counts["daily_log_amounts"] == 1
    assert superseded.category == RetentionCategory.SUPERSEDED_UNREFERENCED
    assert "valid_superseded_revision_retained" in superseded.reason_codes
    assert active.category == RetentionCategory.ACTIVE
    assert active_projection.category == RetentionCategory.ACTIVE
    assert all(row.protected and not row.purge_eligible for row in report.records)
    assert report.counts["purge_candidates"] == 0


def test_deleted_recipe_history_and_deleted_projection_references_remain_protected(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe_id, projection = _published(client)
    log_response = _post_log(
        client,
        projection,
        serving_definition_id=_default_serving(projection)["id"],
    )
    assert log_response.status_code == 201
    log_id = UUID(log_response.json()["id"])
    assert client.delete(f"/api/v1/recipes/{recipe_id}").status_code == 204
    db_session.expire_all()
    recipe = db_session.get(Recipe, recipe_id)

    report = RetentionAuditService(db_session).audit_owner(recipe.user_id)
    revision = _record(report, "publication_revision", recipe.active_publication_revision_id)
    retained_projection = _record(report, "food_projection", projection["id"])

    assert "deleted_recipe_history" in revision.reason_codes
    assert revision.protected
    assert retained_projection.category == RetentionCategory.HISTORICALLY_REFERENCED
    assert "soft_deleted_projection" in retained_projection.reason_codes
    assert retained_projection.reference_counts["daily_logs"] == 1
    assert retained_projection.reference_counts["snapshots"] > 0

    context = client.get(f"/api/v1/logs/{log_id}/edit-context")
    edited = client.patch(f"/api/v1/logs/{log_id}", json={"amount_quantity": "2"})
    assert context.status_code == 200
    assert edited.status_code == 200, edited.text


def test_projection_ingredient_snapshot_and_duplicate_provenance_are_protected(
    client: TestClient,
    db_session: Session,
) -> None:
    _, projection = _published(client)
    parent = client.post(
        "/api/v1/recipes",
        json={
            "name": "Projection Parent",
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
    assert parent.status_code == 201
    logged = _post_log(
        client,
        projection,
        serving_definition_id=_default_serving(projection)["id"],
    )
    assert logged.status_code == 201
    duplicate = client.post(f"/api/v1/foods/{projection['id']}/duplicate")
    assert duplicate.status_code == 201
    owner = ensure_dev_user(db_session)

    record = _record(
        RetentionAuditService(db_session).audit_owner(owner.id),
        "food_projection",
        projection["id"],
    )

    assert record.protected and not record.purge_eligible
    assert record.reference_counts["recipe_ingredients"] == 1
    assert record.reference_counts["daily_logs"] == 1
    assert record.reference_counts["snapshots"] > 0
    assert record.reference_counts["provenance_foods"] == 1
    assert "duplicated_food_provenance_reference" in record.reason_codes


def test_orphan_projection_is_conservative_and_cross_user_corruption_is_unsafe(
    db_session: Session,
) -> None:
    owner = ensure_dev_user(db_session)
    orphan = FoodItem(
        id=uuid4(),
        user_id=owner.id,
        name="Uncertain orphan",
        source_type="recipe",
        source_id=str(uuid4()),
        is_recipe=True,
    )
    other = User(id=uuid4(), email=f"retention-other-{uuid4()}@example.test")
    db_session.add_all([orphan, other])
    db_session.flush()
    cross_linked = FoodItem(
        id=uuid4(),
        user_id=owner.id,
        name="Cross-linked owner food",
        source_type="manual",
        is_recipe=False,
    )
    db_session.add(cross_linked)
    db_session.flush()
    foreign_recipe = Recipe(
        id=uuid4(),
        user_id=other.id,
        name="Foreign Recipe",
        published_food_item_id=cross_linked.id,
    )
    db_session.add(foreign_recipe)
    db_session.commit()

    report = RetentionAuditService(db_session).audit_operator()
    orphan_record = _record(report, "food_projection", orphan.id)
    foreign_record = _record(report, "food_projection", cross_linked.id)

    assert orphan_record.category == RetentionCategory.ORPHANED_INCONSISTENT
    assert "no_positive_purge_proof" in orphan_record.reason_codes
    assert foreign_record.category == RetentionCategory.ORPHANED_INCONSISTENT
    assert "cross_user_reference_inconsistent" in foreign_record.reason_codes
    assert not orphan_record.purge_eligible
    assert not foreign_record.purge_eligible


def test_capture_origin_revision_is_retained_as_provenance(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe, _projection = _legacy_published_recipe(client, db_session)
    captured = RecipeRevisionCaptureService(db_session).capture_one(recipe.id, dry_run=False)
    assert captured.captured

    record = _record(
        RetentionAuditService(db_session).audit_owner(recipe.user_id),
        "publication_revision",
        captured.captured_revision_id,
    )

    assert "capture_baseline_provenance" in record.reason_codes
    assert record.protected and not record.purge_eligible


def test_retention_audit_is_read_only_stable_and_owner_scoped(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe_id, projection = _published(client)
    owner = ensure_dev_user(db_session)
    other = User(id=uuid4(), email=f"audit-owner-{uuid4()}@example.test")
    db_session.add(other)
    db_session.flush()
    foreign_projection = FoodItem(
        id=uuid4(),
        user_id=other.id,
        name="Foreign Retention Projection",
        source_type="recipe",
        source_id=str(uuid4()),
        is_recipe=True,
    )
    db_session.add(foreign_projection)
    db_session.commit()
    before = {
        "recipes": db_session.scalar(select(func.count()).select_from(Recipe)),
        "foods": db_session.scalar(select(func.count()).select_from(FoodItem)),
        "revisions": db_session.scalar(
            select(func.count()).select_from(RecipePublicationRevision)
        ),
        "logs": db_session.scalar(select(func.count()).select_from(DailyLog)),
        "snapshots": db_session.scalar(
            select(func.count()).select_from(DailyLogNutrientSnapshot)
        ),
    }

    service = RetentionAuditService(db_session)
    first = service.audit_owner(owner.id)
    second = service.audit_owner(owner.id)
    operator = service.audit_operator()
    after = {
        "recipes": db_session.scalar(select(func.count()).select_from(Recipe)),
        "foods": db_session.scalar(select(func.count()).select_from(FoodItem)),
        "revisions": db_session.scalar(
            select(func.count()).select_from(RecipePublicationRevision)
        ),
        "logs": db_session.scalar(select(func.count()).select_from(DailyLog)),
        "snapshots": db_session.scalar(
            select(func.count()).select_from(DailyLogNutrientSnapshot)
        ),
    }

    assert first.to_dict() == second.to_dict()
    assert before == after
    assert first.dry_run and not first.operator_scope
    assert all(row.owner_id == owner.id for row in first.records)
    assert operator.operator_scope
    assert {row.owner_id for row in operator.records if row.owner_id is not None} == {
        owner.id,
        other.id,
    }
    assert _record(first, "food_projection", projection["id"]).protected
    assert _record(first, "publication_revision", db_session.get(Recipe, recipe_id).active_publication_revision_id).protected


def test_retention_audit_query_count_is_bounded(
    client: TestClient,
    db_session: Session,
) -> None:
    for _index in range(4):
        _published(client)
    owner_id = ensure_dev_user(db_session).id
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", capture)
    try:
        RetentionAuditService(db_session).audit_owner(owner_id)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", capture)

    assert len(statements) == 11


def test_audit_preserves_historical_totals_and_snapshot_rows(
    client: TestClient,
    db_session: Session,
) -> None:
    _, projection = _published(client)
    logged = _post_log(
        client,
        projection,
        serving_definition_id=_default_serving(projection)["id"],
    )
    assert logged.status_code == 201
    log_id = UUID(logged.json()["id"])
    before_log = db_session.get(DailyLog, log_id)
    before_snapshots = deepcopy(
        [(row.id, row.nutrient_id, row.amount) for row in before_log.snapshots]
    )
    before_summary = client.get(
        "/api/v1/logs/daily-summary",
        params={"date": logged.json()["logged_date"]},
    ).json()

    RetentionAuditService(db_session).audit_owner(before_log.user_id)

    db_session.expire_all()
    after_log = db_session.get(DailyLog, log_id)
    after_snapshots = [(row.id, row.nutrient_id, row.amount) for row in after_log.snapshots]
    after_summary = client.get(
        "/api/v1/logs/daily-summary",
        params={"date": logged.json()["logged_date"]},
    ).json()
    assert after_snapshots == before_snapshots
    assert after_summary == before_summary
