from __future__ import annotations

from datetime import date
from decimal import Decimal
from importlib import import_module
import os
from threading import Event, Thread
from uuid import uuid4

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import MetaData, create_engine, func, inspect, select, text
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401
from app.catalog.nutrients import nutrient_seed_rows
from app.core.database import Base
from app.models.food import FoodItem, FoodNutrient, ServingDefinition
from app.models.food import OcrNutritionConfirmationTrace
from app.models.log import DailyLog
from app.models.nutrient import Nutrient
from app.models.recipe import Recipe
from app.models.recipe_publication import RecipePublicationRevision
from app.models.user import User
from app.publication.recipe_revision import (
    PublishedAmountContent,
    PublishedNutrientContent,
    RecipePublicationContent,
    apply_revision_to_projection,
    build_revision,
)
from app.ocr.confirmation_schemas import OcrNutritionConfirmationRequest
from app.ocr.confirmation_service import OcrConfirmationService
from app.schemas.log import DailyLogCreateRequest, DailyLogUpdateRequest
from app.services.log_service import LogService


pytestmark = pytest.mark.postgres_concurrency
POSTGRES_URL = os.getenv(
    "NUTRITION_TEST_POSTGRES_URL",
    "postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app",
)
idempotency_migration = import_module(
    "app.migrations.versions.0009_log_creation_idempotency"
)


@pytest.fixture()
def postgres_sessions():
    admin = create_engine(POSTGRES_URL, pool_pre_ping=True)
    try:
        with admin.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - depends on developer environment.
        pytest.skip(f"PostgreSQL concurrency database unavailable: {exc}")
    schema = f"test_phase3n_{uuid4().hex}"
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        POSTGRES_URL,
        connect_args={"options": f"-csearch_path={schema}"},
        pool_pre_ping=True,
    )
    isolated_metadata = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(isolated_metadata)
    isolated_metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    try:
        with factory() as db:
            db.add_all([Nutrient(**row) for row in nutrient_seed_rows()])
            db.commit()
        yield factory
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _revision_log(factory) -> tuple:
    with factory() as db:
        user = User(id=uuid4(), email=f"phase3n-{uuid4()}@example.test")
        recipe = Recipe(
            id=uuid4(),
            user_id=user.id,
            name="Concurrent Recipe",
            serving_count_yield=Decimal("1"),
            final_cooked_weight_grams=Decimal("100"),
        )
        db.add(user)
        db.flush()
        db.add(recipe)
        db.flush()
        revision = build_revision(
            recipe_id=recipe.id,
            user_id=user.id,
            revision_number=1,
            creation_origin="normal_publication",
            provenance_confidence="complete",
            content=RecipePublicationContent(
                published_name=recipe.name,
                published_notes=None,
                amount_definitions=(
                    PublishedAmountContent(
                        display_order=0,
                        display_label="1 serving",
                        semantic_mode="serving",
                        display_quantity=Decimal("1"),
                        display_unit="serving",
                        gram_equivalent=Decimal("100"),
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
                    PublishedNutrientContent(
                        nutrient_id="calories",
                        amount=Decimal("100"),
                        unit="kcal",
                        basis="per_serving",
                        data_status="known",
                    ),
                    PublishedNutrientContent(
                        nutrient_id="calories",
                        amount=Decimal("100"),
                        unit="kcal",
                        basis="per_100g",
                        data_status="known",
                    ),
                ),
            ),
        )
        db.add(revision)
        db.flush()
        projection = FoodItem(id=uuid4(), user_id=user.id, name=recipe.name)
        apply_revision_to_projection(
            projection,
            revision,
            recipe_id=recipe.id,
            user_id=user.id,
            updated_at=recipe.created_at,
        )
        projection.recipe_publication_revision_id = revision.id
        db.add(projection)
        db.flush()
        recipe.active_publication_revision_id = revision.id
        recipe.published_food_item_id = projection.id
        db.commit()
        serving_id = next(row.id for row in projection.serving_definitions if row.is_default)
        log = LogService(db).create_log(
            user.id,
            DailyLogCreateRequest(
                food_item_id=projection.id,
                logged_date=date(2026, 7, 13),
                amount_quantity=Decimal("1"),
                amount_unit="serving",
                serving_definition_id=serving_id,
            ),
        )
        return user.id, log.id


def _manual_log(factory) -> tuple:
    with factory() as db:
        user = User(id=uuid4(), email=f"manual-phase3n-{uuid4()}@example.test")
        db.add(user)
        db.flush()
        serving = ServingDefinition(
            id=uuid4(),
            label="1 portion",
            quantity=Decimal("1"),
            unit="portion",
            gram_weight=Decimal("100"),
            is_default=True,
            source="manual",
            is_user_confirmed=True,
        )
        food = FoodItem(
            id=uuid4(),
            user_id=user.id,
            name="Concurrent Manual Food",
            source_type="manual",
            is_recipe=False,
            serving_definitions=[serving],
            nutrients=[
                FoodNutrient(
                    id=uuid4(),
                    nutrient_id="calories",
                    amount=Decimal("100"),
                    unit="kcal",
                    basis="per_serving",
                    data_status="known",
                    source="manual",
                    is_user_confirmed=True,
                )
            ],
        )
        db.add(food)
        db.commit()
        log = LogService(db).create_log(
            user.id,
            DailyLogCreateRequest(
                food_item_id=food.id,
                logged_date=date(2026, 7, 13),
                amount_quantity=Decimal("1"),
                amount_unit="serving",
                serving_definition_id=serving.id,
            ),
        )
        return user.id, log.id


def _manual_create_target(factory) -> tuple:
    with factory() as db:
        user = User(id=uuid4(), email=f"manual-create-{uuid4()}@example.test")
        db.add(user)
        db.flush()
        serving = ServingDefinition(
            id=uuid4(),
            label="1 portion",
            quantity=Decimal("1"),
            unit="portion",
            gram_weight=Decimal("100"),
            is_default=True,
            source="manual",
            is_user_confirmed=True,
        )
        food = FoodItem(
            id=uuid4(),
            user_id=user.id,
            name="Idempotent Concurrent Food",
            source_type="manual",
            is_recipe=False,
            serving_definitions=[serving],
            nutrients=[
                FoodNutrient(
                    id=uuid4(),
                    nutrient_id="calories",
                    amount=Decimal("100"),
                    unit="kcal",
                    basis="per_serving",
                    data_status="known",
                    source="manual",
                    is_user_confirmed=True,
                )
            ],
        )
        db.add(food)
        db.commit()
        return user.id, food.id, serving.id


def test_concurrent_create_with_same_request_id_commits_one_log_and_snapshot_set(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    user_id, food_id, serving_id = _manual_create_target(factory)
    request_id = uuid4()
    first_flushed, release = Event(), Event()
    first_result, second_result = [], []

    def create(result, *, hold=False):
        with factory() as db:
            service = LogService(db)
            if hold:
                def after_flush(_log):
                    first_flushed.set()
                    assert release.wait(5)

                service._after_snapshot_creation = after_flush
            try:
                log = service.create_log(
                    user_id,
                    DailyLogCreateRequest(
                        client_request_id=request_id,
                        food_item_id=food_id,
                        logged_date=date(2026, 7, 14),
                        amount_quantity=Decimal("1"),
                        amount_unit="serving",
                        serving_definition_id=serving_id,
                    ),
                )
                result.append(log.id)
            except Exception as exc:
                result.append(exc)

    first = Thread(target=create, args=(first_result,), kwargs={"hold": True})
    first.start()
    assert first_flushed.wait(5)
    second = Thread(target=create, args=(second_result,))
    second.start()
    Event().wait(0.2)
    assert not second_result
    release.set()
    first.join(5)
    second.join(5)

    assert len(first_result) == len(second_result) == 1
    assert first_result[0] == second_result[0]
    with factory() as db:
        logs = list(
            db.scalars(
                select(DailyLog).where(
                    DailyLog.user_id == user_id,
                    DailyLog.client_request_id == request_id,
                )
            )
        )
        assert len(logs) == 1
        assert len(logs[0].snapshots) == 1


def _ocr_confirmation_request(request_id):
    def field(key, value, *, nutrient_id=None, unit=None):
        return {
            "field_key": key,
            "nutrient_id": nutrient_id,
            "suggested_value": value,
            "confirmed_value": value,
            "unit": unit,
            "decision": "accepted",
            "parse_status": "parsed",
            "comparison": None,
            "confidence": "0.95",
            "source_text": key,
            "source_observation_ids": [f"obs-{key}"],
            "warning_codes": [],
            "resolution": None,
        }

    return OcrNutritionConfirmationRequest.model_validate(
        {
            "parser_version": "nutrition_label_v1",
            "image_source_type": "photo_library",
            "client_request_id": request_id,
            "food": {
                "name": "Concurrent Cereal",
                "brand": None,
                "notes": None,
                "serving_definitions": [
                    {
                        "label": "100 g",
                        "quantity": "100",
                        "unit": "g",
                        "gram_weight": "100",
                        "is_default": False,
                    },
                    {
                        "label": "1 cup (30g)",
                        "quantity": "1",
                        "unit": "cup",
                        "gram_weight": "30",
                        "is_default": True,
                    },
                ],
                "nutrients": [
                    {
                        "nutrient_id": "calories",
                        "amount": "120",
                        "unit": "kcal",
                        "basis": "per_serving",
                        "data_status": "known",
                    }
                ],
            },
            "field_decisions": [
                field("food.name", "Concurrent Cereal"),
                {**field("food.brand", None), "decision": "omitted"},
                {**field("food.notes", None), "decision": "omitted"},
                field("serving.display", "1 cup (30g)"),
                field("serving.quantity", "1"),
                field("serving.unit", "cup"),
                field("serving.gram_weight", "30", unit="g"),
                field(
                    "nutrient.calories",
                    "120",
                    nutrient_id="calories",
                    unit="kcal",
                ),
            ],
            "unknown_nutrients": [],
            "parser_warning_codes": [],
        }
    )


def test_concurrent_same_id_confirmation_commits_one_food_and_trace(
    postgres_sessions,
) -> None:
    factory = postgres_sessions
    with factory() as db:
        user = User(id=uuid4(), email=f"ocr-concurrency-{uuid4()}@example.test")
        db.add(user)
        db.commit()
        user_id = user.id

    payload = _ocr_confirmation_request(uuid4())
    first_flushed, release = Event(), Event()
    first_result, second_result = [], []

    def confirm(result, *, hold=False):
        with factory() as db:
            service = OcrConfirmationService(db)
            if hold:
                def after_trace(_trace):
                    first_flushed.set()
                    assert release.wait(5)

                service._after_trace_creation = after_trace
            try:
                food, trace = service.confirm(user_id, payload)
                result.append((food.id, trace.id))
            except Exception as exc:
                result.append(exc)

    first = Thread(target=confirm, args=(first_result,), kwargs={"hold": True})
    first.start()
    assert first_flushed.wait(5)
    second = Thread(target=confirm, args=(second_result,))
    second.start()
    Event().wait(0.2)
    assert not second_result
    release.set()
    first.join(5)
    second.join(5)

    assert len(first_result) == len(second_result) == 1
    assert first_result[0] == second_result[0]
    with factory() as db:
        traces = list(
            db.scalars(
                select(OcrNutritionConfirmationTrace).where(
                    OcrNutritionConfirmationTrace.user_id == user_id,
                    OcrNutritionConfirmationTrace.client_request_id
                    == payload.client_request_id,
                )
            )
        )
        assert len(traces) == 1
        assert db.scalar(
            select(func.count()).select_from(FoodItem).where(FoodItem.user_id == user_id)
        ) == 1


def test_postgres_idempotency_migration_upgrade_and_downgrade(postgres_sessions) -> None:
    engine = postgres_sessions.kw["bind"]
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            idempotency_migration.downgrade()
        columns = {column["name"] for column in inspect(connection).get_columns("daily_logs")}
        assert "client_request_id" not in columns

        with Operations.context(context):
            idempotency_migration.upgrade()
        columns = {column["name"] for column in inspect(connection).get_columns("daily_logs")}
        assert {"client_request_id", "client_request_fingerprint"} <= columns

        with Operations.context(context):
            idempotency_migration.downgrade()
        columns = {column["name"] for column in inspect(connection).get_columns("daily_logs")}
        assert "client_request_id" not in columns

        # Restore the isolated fixture schema for any later test using this factory.
        with Operations.context(context):
            idempotency_migration.upgrade()


def _run_update(factory, user_id, log_id, payload, *, locked=None, release=None, fail=False, result=None):
    with factory() as db:
        service = LogService(db)
        if locked is not None:
            def after_lock(_revision):
                locked.set()
                assert release.wait(5)
            service._after_edit_revision_lookup = after_lock
        if fail:
            def fail_after_replacement(_log):
                raise RuntimeError("forced rollback after replacement")
            service._after_edit_snapshot_regeneration = fail_after_replacement
        try:
            service.update_log(user_id, log_id, DailyLogUpdateRequest(**payload))
            if result is not None:
                result.append("committed")
        except Exception as exc:  # assertions inspect the expected failure in the caller.
            if result is not None:
                result.append(exc)


def _assert_coherent(
    factory,
    user_id,
    log_id,
    quantity: Decimal,
    notes: str | None = None,
    daily_total: Decimal | None = None,
    snapshot_amount: Decimal | None = None,
):
    with factory() as db:
        log = db.get(DailyLog, log_id)
        assert log.amount_quantity == quantity
        assert log.notes == notes
        assert len(log.snapshots) == 1
        snapshot = log.snapshots[0]
        assert snapshot.consumed_amount_quantity == quantity
        expected_snapshot = (
            snapshot_amount if snapshot_amount is not None else quantity * Decimal("100")
        )
        assert snapshot.amount == expected_snapshot
        summary = LogService(db).daily_summary(user_id, log.logged_date)
        calories = next(row for row in summary if row.nutrient_id == "calories")
        assert calories.amount_known == (daily_total if daily_total is not None else snapshot.amount)


def test_second_quantity_patch_waits_then_uses_latest_committed_state(postgres_sessions) -> None:
    factory = postgres_sessions
    user_id, log_id = _revision_log(factory)
    locked, release = Event(), Event()
    first_result, second_result = [], []
    first = Thread(
        target=_run_update,
        args=(factory, user_id, log_id, {"amount_quantity": Decimal("2")}),
        kwargs={"locked": locked, "release": release, "result": first_result},
    )
    first.start()
    assert locked.wait(5)
    second = Thread(
        target=_run_update,
        args=(factory, user_id, log_id, {"amount_quantity": Decimal("3")}),
        kwargs={"result": second_result},
    )
    second.start()
    Event().wait(0.2)
    assert not second_result
    release.set()
    first.join(5)
    second.join(5)
    assert first_result == second_result == ["committed"]
    _assert_coherent(factory, user_id, log_id, Decimal("3"))


def test_metadata_patch_waits_for_nutrition_and_preserves_latest_amount(postgres_sessions) -> None:
    factory = postgres_sessions
    user_id, log_id = _revision_log(factory)
    locked, release = Event(), Event()
    first = Thread(
        target=_run_update,
        args=(factory, user_id, log_id, {"amount_quantity": Decimal("2")}),
        kwargs={"locked": locked, "release": release},
    )
    first.start()
    assert locked.wait(5)
    second = Thread(
        target=_run_update,
        args=(factory, user_id, log_id, {"notes": "latest metadata"}),
    )
    second.start()
    release.set()
    first.join(5)
    second.join(5)
    _assert_coherent(factory, user_id, log_id, Decimal("2"), "latest metadata")


def test_waiter_proceeds_after_first_replacement_rolls_back(postgres_sessions) -> None:
    factory = postgres_sessions
    user_id, log_id = _revision_log(factory)
    locked, release = Event(), Event()
    first_result, second_result = [], []
    first = Thread(
        target=_run_update,
        args=(factory, user_id, log_id, {"amount_quantity": Decimal("2")}),
        kwargs={
            "locked": locked,
            "release": release,
            "fail": True,
            "result": first_result,
        },
    )
    first.start()
    assert locked.wait(5)
    second = Thread(
        target=_run_update,
        args=(factory, user_id, log_id, {"amount_quantity": Decimal("4")}),
        kwargs={"result": second_result},
    )
    second.start()
    release.set()
    first.join(5)
    second.join(5)
    assert isinstance(first_result[0], RuntimeError)
    assert second_result == ["committed"]
    _assert_coherent(factory, user_id, log_id, Decimal("4"))


def test_different_log_row_does_not_wait(postgres_sessions) -> None:
    factory = postgres_sessions
    user_id, first_log_id = _revision_log(factory)
    with factory() as db:
        first_log = db.get(DailyLog, first_log_id)
        second_log = LogService(db).create_log(
            user_id,
            DailyLogCreateRequest(
                food_item_id=first_log.food_item_id,
                logged_date=first_log.logged_date,
                amount_quantity=Decimal("1"),
                amount_unit="serving",
                serving_definition_id=first_log.serving_definition_id,
            ),
        )
        second_log_id = second_log.id
    locked, release, second_result = Event(), Event(), []
    first = Thread(
        target=_run_update,
        args=(factory, user_id, first_log_id, {"amount_quantity": Decimal("2")}),
        kwargs={"locked": locked, "release": release},
    )
    first.start()
    assert locked.wait(5)
    second = Thread(
        target=_run_update,
        args=(factory, user_id, second_log_id, {"amount_quantity": Decimal("5")}),
        kwargs={"result": second_result},
    )
    second.start()
    second.join(2)
    assert second_result == ["committed"]
    release.set()
    first.join(5)
    _assert_coherent(
        factory,
        user_id,
        second_log_id,
        Decimal("5"),
        daily_total=Decimal("700"),
    )


def test_concurrent_valid_amount_definition_change_is_coherent(postgres_sessions) -> None:
    factory = postgres_sessions
    user_id, log_id = _revision_log(factory)
    with factory() as db:
        log = db.get(DailyLog, log_id)
        revision = db.get(RecipePublicationRevision, log.recipe_publication_revision_id)
        gram_amount_id = next(
            row.id for row in revision.amount_definitions if row.semantic_mode == "g"
        )
    locked, release = Event(), Event()
    first = Thread(
        target=_run_update,
        args=(factory, user_id, log_id, {"amount_quantity": Decimal("2")}),
        kwargs={"locked": locked, "release": release},
    )
    first.start()
    assert locked.wait(5)
    second = Thread(
        target=_run_update,
        args=(
            factory,
            user_id,
            log_id,
            {
                "amount_quantity": Decimal("50"),
                "amount_unit": "g",
                "serving_definition_id": gram_amount_id,
            },
        ),
    )
    second.start()
    release.set()
    first.join(5)
    second.join(5)
    _assert_coherent(
        factory,
        user_id,
        log_id,
        Decimal("50"),
        snapshot_amount=Decimal("50"),
    )
    with factory() as db:
        log = db.get(DailyLog, log_id)
        assert log.amount_unit == "g"
        assert log.recipe_publication_amount_definition_id == gram_amount_id


def test_manual_food_updates_are_serialized(postgres_sessions) -> None:
    factory = postgres_sessions
    user_id, log_id = _manual_log(factory)
    locked, release = Event(), Event()
    first_result, second_result = [], []

    class LockHoldingManualService(LogService):
        pass

    def first_update():
        with factory() as db:
            service = LockHoldingManualService(db)
            original = service._update_compatibility_log

            def hold(user, log, payload):
                locked.set()
                assert release.wait(5)
                original(user, log, payload)

            service._update_compatibility_log = hold
            try:
                service.update_log(
                    user_id,
                    log_id,
                    DailyLogUpdateRequest(amount_quantity=Decimal("2")),
                )
                first_result.append("committed")
            except Exception as exc:
                first_result.append(exc)

    first = Thread(target=first_update)
    first.start()
    assert locked.wait(5)
    second = Thread(
        target=_run_update,
        args=(factory, user_id, log_id, {"amount_quantity": Decimal("3")}),
        kwargs={"result": second_result},
    )
    second.start()
    Event().wait(0.2)
    assert not second_result
    release.set()
    first.join(5)
    second.join(5)
    assert first_result == second_result == ["committed"]
    _assert_coherent(factory, user_id, log_id, Decimal("3"))


def test_deleted_projection_revision_log_updates_are_serialized(postgres_sessions) -> None:
    factory = postgres_sessions
    user_id, log_id = _revision_log(factory)
    with factory() as db:
        log = db.get(DailyLog, log_id)
        log.food_item.deleted_at = log.updated_at
        db.commit()
    locked, release = Event(), Event()
    first = Thread(
        target=_run_update,
        args=(factory, user_id, log_id, {"amount_quantity": Decimal("2")}),
        kwargs={"locked": locked, "release": release},
    )
    first.start()
    assert locked.wait(5)
    second = Thread(
        target=_run_update,
        args=(factory, user_id, log_id, {"amount_quantity": Decimal("6")}),
    )
    second.start()
    release.set()
    first.join(5)
    second.join(5)
    _assert_coherent(factory, user_id, log_id, Decimal("6"))
