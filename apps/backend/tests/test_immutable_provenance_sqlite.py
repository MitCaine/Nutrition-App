from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.food import (
    FoodItem,
    FoodNutrient,
    OcrNutritionConfirmationTrace,
    ServingDefinition,
)
from app.models.log import DailyLog, DailyLogNutrientSnapshot
from app.models.recipe import Recipe
from app.models.recipe_publication import (
    RecipePublicationAmountDefinition,
    RecipePublicationNutrient,
    RecipePublicationRevision,
)
from app.models.user import User
from app.operators.immutable_provenance_contracts import SQLITE_TRIGGER_NAMES
from app.operators.immutable_provenance_sqlite import (
    allow_sqlite_snapshot_replacement,
)
from app.repositories.log_repository import LogRepository


def _seed_historical_graph(db: Session) -> dict[str, UUID]:
    ids = {
        name: uuid4()
        for name in (
            "user",
            "food",
            "food_nutrient",
            "serving",
            "recipe",
            "revision",
            "revision_two",
            "amount",
            "amount_alt",
            "amount_two",
            "revision_nutrient",
            "trace",
            "log",
            "snapshot",
        )
    }
    db.execute(
        User.__table__.insert().values(
            id=ids["user"],
            email=f"immutable-sqlite-{ids['user']}@example.test",
        )
    )
    db.execute(
        FoodItem.__table__.insert().values(
            id=ids["food"],
            user_id=ids["user"],
            name="Historical source",
            source_type="manual",
            is_recipe=False,
        )
    )
    db.execute(
        FoodNutrient.__table__.insert().values(
            id=ids["food_nutrient"],
            food_item_id=ids["food"],
            nutrient_id="calories",
            amount=Decimal("125"),
            unit="kcal",
            basis="per_100g",
            data_status="known",
            source="manual",
            is_user_confirmed=True,
        )
    )
    db.execute(
        ServingDefinition.__table__.insert().values(
            id=ids["serving"],
            food_item_id=ids["food"],
            label="1 cup",
            quantity=Decimal("1"),
            unit="cup",
            gram_weight=Decimal("100"),
            is_default=True,
            source="manual",
            is_user_confirmed=True,
        )
    )
    db.execute(
        Recipe.__table__.insert().values(
            id=ids["recipe"],
            user_id=ids["user"],
            name="Historical recipe",
            needs_republish=False,
        )
    )
    db.execute(
        RecipePublicationRevision.__table__.insert().values(
            id=ids["revision"],
            recipe_id=ids["recipe"],
            user_id=ids["user"],
            revision_number=1,
            creation_origin="normal_publication",
            provenance_confidence="complete",
            published_name="Historical recipe",
            content_digest=f"immutable-{ids['revision']}",
        )
    )
    db.execute(
        RecipePublicationAmountDefinition.__table__.insert().values(
            id=ids["amount"],
            revision_id=ids["revision"],
            display_order=0,
            display_label="1 serving",
            semantic_mode="serving",
            display_quantity=Decimal("1"),
            display_unit="serving",
            gram_equivalent=Decimal("100"),
            is_default=True,
        )
    )
    db.execute(
        RecipePublicationAmountDefinition.__table__.insert().values(
            id=ids["amount_alt"],
            revision_id=ids["revision"],
            display_order=1,
            display_label="100 g",
            semantic_mode="g",
            display_unit="g",
            is_default=False,
        )
    )
    db.execute(
        RecipePublicationRevision.__table__.insert().values(
            id=ids["revision_two"],
            recipe_id=ids["recipe"],
            user_id=ids["user"],
            revision_number=2,
            creation_origin="explicit_republish",
            provenance_confidence="complete",
            published_name="Historical recipe v2",
            content_digest=f"immutable-{ids['revision_two']}",
        )
    )
    db.execute(
        RecipePublicationAmountDefinition.__table__.insert().values(
            id=ids["amount_two"],
            revision_id=ids["revision_two"],
            display_order=0,
            display_label="1 serving",
            semantic_mode="serving",
            display_quantity=Decimal("1"),
            display_unit="serving",
            gram_equivalent=Decimal("110"),
            is_default=True,
        )
    )
    db.execute(
        RecipePublicationNutrient.__table__.insert().values(
            id=ids["revision_nutrient"],
            revision_id=ids["revision"],
            nutrient_id="calories",
            amount=Decimal("125"),
            unit="kcal",
            basis="per_serving",
            data_status="known",
        )
    )
    db.execute(
        OcrNutritionConfirmationTrace.__table__.insert().values(
            id=ids["trace"],
            user_id=ids["user"],
            food_item_id=ids["food"],
            parser_version="test-v1",
            image_source_type="upload",
            schema_version="trace-v1",
            trace_snapshot={"status": "confirmed"},
            client_request_id=uuid4(),
            request_fingerprint="immutable-test",
        )
    )
    db.execute(
        DailyLog.__table__.insert().values(
            id=ids["log"],
            user_id=ids["user"],
            food_item_id=ids["food"],
            food_name_snapshot="Historical source",
            logged_date=date(2026, 7, 21),
            amount_quantity=Decimal("1"),
            amount_unit="serving",
            serving_definition_id=ids["serving"],
            recipe_publication_revision_id=ids["revision"],
            recipe_publication_amount_definition_id=ids["amount"],
            gram_amount=Decimal("100"),
        )
    )
    db.execute(
        DailyLogNutrientSnapshot.__table__.insert().values(
            id=ids["snapshot"],
            daily_log_id=ids["log"],
            source_food_item_id=ids["food"],
            source_food_nutrient_id=ids["food_nutrient"],
            serving_definition_id=ids["serving"],
            nutrient_id="calories",
            amount=Decimal("125"),
            unit="kcal",
            data_status="known",
            consumed_amount_quantity=Decimal("1"),
            consumed_amount_unit="serving",
            consumed_gram_amount=Decimal("100"),
        )
    )
    db.commit()
    return ids


def _assert_immutable_rejection(db: Session, statement, message: str) -> None:
    with pytest.raises(IntegrityError, match=message):
        db.execute(statement)
    db.rollback()


def test_sqlite_installs_exact_frozen_trigger_set(db_session: Session) -> None:
    installed = tuple(
        db_session.scalars(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'trigger' AND name LIKE 'phase0020_%' ORDER BY name"
            )
        ).all()
    )

    assert installed == tuple(sorted(SQLITE_TRIGGER_NAMES))


def test_sqlite_allows_approved_historical_inserts(db_session: Session) -> None:
    ids = _seed_historical_graph(db_session)

    assert db_session.get(RecipePublicationRevision, ids["revision"]) is not None
    assert db_session.get(RecipePublicationNutrient, ids["revision_nutrient"]) is not None
    assert db_session.get(RecipePublicationAmountDefinition, ids["amount"]) is not None
    assert db_session.get(OcrNutritionConfirmationTrace, ids["trace"]) is not None
    assert db_session.get(DailyLogNutrientSnapshot, ids["snapshot"]) is not None


@pytest.mark.parametrize(
    ("table", "id_key", "changed_values"),
    (
        (RecipePublicationRevision, "revision", {"published_name": "Mutated"}),
        (RecipePublicationNutrient, "revision_nutrient", {"amount": Decimal("999")}),
        (
            RecipePublicationAmountDefinition,
            "amount",
            {"display_label": "Mutated"},
        ),
        (OcrNutritionConfirmationTrace, "trace", {"parser_version": "mutated"}),
    ),
)
def test_sqlite_core_rejects_append_only_updates(
    db_session: Session,
    table,
    id_key: str,
    changed_values: dict[str, object],
) -> None:
    ids = _seed_historical_graph(db_session)

    _assert_immutable_rejection(
        db_session,
        update(table).where(table.id == ids[id_key]).values(**changed_values),
        "phase0020_immutable_row_mutation",
    )


@pytest.mark.parametrize(
    ("table", "id_key"),
    (
        (RecipePublicationRevision, "revision"),
        (RecipePublicationNutrient, "revision_nutrient"),
        (RecipePublicationAmountDefinition, "amount"),
        (OcrNutritionConfirmationTrace, "trace"),
    ),
)
def test_sqlite_core_rejects_append_only_deletes(
    db_session: Session,
    table,
    id_key: str,
) -> None:
    ids = _seed_historical_graph(db_session)

    _assert_immutable_rejection(
        db_session,
        delete(table).where(table.id == ids[id_key]),
        "phase0020_immutable_row_mutation",
    )


def test_sqlite_orm_rejects_append_only_mutation(db_session: Session) -> None:
    ids = _seed_historical_graph(db_session)
    revision = db_session.get(RecipePublicationRevision, ids["revision"])
    assert revision is not None
    revision.published_name = "ORM mutation"

    with pytest.raises(IntegrityError, match="phase0020_immutable_row_mutation"):
        db_session.flush()
    db_session.rollback()


def test_sqlite_orm_rejects_append_only_delete(db_session: Session) -> None:
    ids = _seed_historical_graph(db_session)
    trace = db_session.get(OcrNutritionConfirmationTrace, ids["trace"])
    assert trace is not None
    db_session.delete(trace)

    with pytest.raises(IntegrityError, match="phase0020_immutable_row_mutation"):
        db_session.flush()
    db_session.rollback()


def test_sqlite_rejects_snapshot_core_and_orm_updates(db_session: Session) -> None:
    ids = _seed_historical_graph(db_session)
    _assert_immutable_rejection(
        db_session,
        update(DailyLogNutrientSnapshot)
        .where(DailyLogNutrientSnapshot.id == ids["snapshot"])
        .values(source_food_nutrient_id=None),
        "phase0020_snapshot_immutable_update",
    )

    snapshot = db_session.get(DailyLogNutrientSnapshot, ids["snapshot"])
    assert snapshot is not None
    snapshot.amount = Decimal("999")
    with pytest.raises(IntegrityError, match="phase0020_snapshot_immutable_update"):
        db_session.flush()
    db_session.rollback()


@pytest.mark.parametrize(
    "mutation",
    (
        "id",
        "user_id",
        "food_item_id",
        "food_name_snapshot",
        "client_identity",
        "revision_pin",
        "created_at",
    ),
)
def test_sqlite_rejects_permanently_frozen_daily_log_columns(
    db_session: Session,
    mutation: str,
) -> None:
    ids = _seed_historical_graph(db_session)
    changed_values: dict[str, object]
    if mutation == "id":
        changed_values = {"id": uuid4()}
    elif mutation == "user_id":
        changed_values = {"user_id": uuid4()}
    elif mutation == "food_item_id":
        changed_values = {"food_item_id": uuid4()}
    elif mutation == "food_name_snapshot":
        changed_values = {"food_name_snapshot": "Rewritten history"}
    elif mutation == "client_identity":
        changed_values = {
            "client_request_id": uuid4(),
            "client_request_fingerprint": "rewritten-request",
        }
    elif mutation == "revision_pin":
        changed_values = {
            "recipe_publication_revision_id": ids["revision_two"],
            "recipe_publication_amount_definition_id": ids["amount_two"],
        }
    else:
        changed_values = {"created_at": datetime(2030, 1, 1, tzinfo=timezone.utc)}

    _assert_immutable_rejection(
        db_session,
        update(DailyLog)
        .where(DailyLog.id == ids["log"])
        .values(**changed_values),
        "phase0020_daily_log_immutable_update",
    )


@pytest.mark.parametrize(
    ("column", "value_key", "literal_value"),
    (
        ("amount_quantity", None, Decimal("2")),
        ("amount_unit", None, "g"),
        ("serving_definition_id", None, None),
        ("recipe_publication_amount_definition_id", "amount_alt", None),
        ("gram_amount", None, Decimal("200")),
        ("package_fraction", None, Decimal("0.5")),
    ),
)
def test_sqlite_rejects_daily_log_nutrition_changes_outside_replacement_scope(
    db_session: Session,
    column: str,
    value_key: str | None,
    literal_value: object,
) -> None:
    ids = _seed_historical_graph(db_session)
    value = ids[value_key] if value_key is not None else literal_value

    _assert_immutable_rejection(
        db_session,
        update(DailyLog)
        .where(DailyLog.id == ids["log"])
        .values(**{column: value}),
        "phase0020_daily_log_immutable_update",
    )


def test_sqlite_allows_daily_log_metadata_only_update(db_session: Session) -> None:
    ids = _seed_historical_graph(db_session)
    replacement_time = datetime(2026, 7, 22, tzinfo=timezone.utc)

    db_session.execute(
        update(DailyLog)
        .where(DailyLog.id == ids["log"])
        .values(
            logged_date=date(2026, 7, 22),
            meal_type="dinner",
            notes="metadata only",
            updated_at=replacement_time,
        )
    )
    db_session.commit()

    stored = db_session.execute(
        select(
            DailyLog.logged_date,
            DailyLog.meal_type,
            DailyLog.notes,
            DailyLog.amount_quantity,
            DailyLog.recipe_publication_revision_id,
        ).where(DailyLog.id == ids["log"])
    ).one()
    assert stored == (
        date(2026, 7, 22),
        "dinner",
        "metadata only",
        Decimal("1.000000"),
        ids["revision"],
    )


def test_sqlite_rejects_orm_daily_log_nutrition_mutation(
    db_session: Session,
) -> None:
    ids = _seed_historical_graph(db_session)
    log = db_session.get(DailyLog, ids["log"])
    assert log is not None
    log.amount_quantity = Decimal("99")

    with pytest.raises(IntegrityError, match="phase0020_daily_log_immutable_update"):
        db_session.flush()
    db_session.rollback()


def test_sqlite_rejects_independent_snapshot_delete(db_session: Session) -> None:
    ids = _seed_historical_graph(db_session)

    _assert_immutable_rejection(
        db_session,
        delete(DailyLogNutrientSnapshot).where(
            DailyLogNutrientSnapshot.id == ids["snapshot"]
        ),
        "phase0020_snapshot_immutable_delete",
    )


def test_sqlite_rejects_orm_snapshot_delete(db_session: Session) -> None:
    ids = _seed_historical_graph(db_session)
    snapshot = db_session.get(DailyLogNutrientSnapshot, ids["snapshot"])
    assert snapshot is not None
    db_session.delete(snapshot)

    with pytest.raises(IntegrityError, match="phase0020_snapshot_immutable_delete"):
        db_session.flush()
    db_session.rollback()


def test_sqlite_allows_fk_driven_nullable_provenance_only(db_session: Session) -> None:
    ids = _seed_historical_graph(db_session)

    db_session.execute(
        delete(FoodNutrient).where(FoodNutrient.id == ids["food_nutrient"])
    )
    db_session.execute(
        delete(ServingDefinition).where(ServingDefinition.id == ids["serving"])
    )
    db_session.commit()

    stored = db_session.execute(
        select(
            DailyLogNutrientSnapshot.source_food_nutrient_id,
            DailyLogNutrientSnapshot.serving_definition_id,
            DailyLogNutrientSnapshot.amount,
            DailyLogNutrientSnapshot.consumed_gram_amount,
        ).where(DailyLogNutrientSnapshot.id == ids["snapshot"])
    ).one()
    assert stored == (None, None, Decimal("125.000000"), Decimal("100.000000"))
    assert db_session.scalar(
        select(DailyLog.serving_definition_id).where(DailyLog.id == ids["log"])
    ) is None


def test_sqlite_allows_explicit_whole_set_snapshot_replacement(
    db_session: Session,
) -> None:
    ids = _seed_historical_graph(db_session)
    replacement_id = uuid4()

    with allow_sqlite_snapshot_replacement(
        db_session,
        ids["user"],
        ids["log"],
    ):
        db_session.execute(
            delete(DailyLogNutrientSnapshot).where(
                DailyLogNutrientSnapshot.daily_log_id == ids["log"]
            )
        )
        db_session.execute(
            update(DailyLog)
            .where(DailyLog.id == ids["log"])
            .values(
                amount_quantity=Decimal("1.2"),
                amount_unit="g",
                serving_definition_id=None,
                recipe_publication_amount_definition_id=ids["amount_alt"],
                gram_amount=Decimal("120"),
                package_fraction=Decimal("0.5"),
            )
        )
    db_session.execute(
        DailyLogNutrientSnapshot.__table__.insert().values(
            id=replacement_id,
            daily_log_id=ids["log"],
            source_food_item_id=ids["food"],
            source_food_nutrient_id=ids["food_nutrient"],
            serving_definition_id=None,
            nutrient_id="calories",
            amount=Decimal("150"),
            unit="kcal",
            data_status="known",
            consumed_amount_quantity=Decimal("1.2"),
            consumed_amount_unit="serving",
            consumed_gram_amount=Decimal("120"),
        )
    )
    db_session.commit()

    assert db_session.scalar(
        select(DailyLogNutrientSnapshot.id).where(
            DailyLogNutrientSnapshot.daily_log_id == ids["log"]
        )
    ) == replacement_id
    stored_log = db_session.execute(
        select(
            DailyLog.amount_quantity,
            DailyLog.amount_unit,
            DailyLog.serving_definition_id,
            DailyLog.recipe_publication_amount_definition_id,
            DailyLog.gram_amount,
            DailyLog.package_fraction,
        ).where(DailyLog.id == ids["log"])
    ).one()
    assert stored_log == (
        Decimal("1.200000"),
        "g",
        None,
        ids["amount_alt"],
        Decimal("120.000000"),
        Decimal("0.500000"),
    )
    _assert_immutable_rejection(
        db_session,
        delete(DailyLogNutrientSnapshot).where(
            DailyLogNutrientSnapshot.id == replacement_id
        ),
        "phase0020_snapshot_immutable_delete",
    )


def test_sqlite_allows_approved_owned_log_delete(db_session: Session) -> None:
    ids = _seed_historical_graph(db_session)
    log = db_session.get(DailyLog, ids["log"])
    assert log is not None

    LogRepository(db_session).delete(log, ids["user"])
    db_session.commit()

    assert db_session.get(DailyLog, ids["log"]) is None
    assert db_session.get(DailyLogNutrientSnapshot, ids["snapshot"]) is None


@pytest.mark.parametrize("incorrect_scope", ("user", "log"))
def test_sqlite_replacement_context_is_owner_and_log_scoped(
    db_session: Session,
    incorrect_scope: str,
) -> None:
    ids = _seed_historical_graph(db_session)
    user_id = uuid4() if incorrect_scope == "user" else ids["user"]
    log_id = uuid4() if incorrect_scope == "log" else ids["log"]

    with allow_sqlite_snapshot_replacement(db_session, user_id, log_id):
        _assert_immutable_rejection(
            db_session,
            delete(DailyLogNutrientSnapshot).where(
                DailyLogNutrientSnapshot.id == ids["snapshot"]
            ),
            "phase0020_snapshot_immutable_delete",
        )
        _assert_immutable_rejection(
            db_session,
            update(DailyLog)
            .where(DailyLog.id == ids["log"])
            .values(amount_quantity=Decimal("2")),
            "phase0020_daily_log_immutable_update",
        )
