from __future__ import annotations

from datetime import date
from decimal import Decimal
from importlib import import_module
from uuid import UUID, uuid4

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Column, MetaData, Table, Text, create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.types import GUID
from app.dependencies.user import ensure_dev_user
from app.models.food import FoodItem
from app.models.log import DailyLog
from app.models.recipe import Recipe
from app.models.recipe_publication import (
    RecipePublicationAmountDefinition,
    RecipePublicationNutrient,
    RecipePublicationRevision,
)
from app.repositories.recipe_publication_repository import RecipePublicationRepository

publication_migration = import_module("app.migrations.versions.0008_recipe_publication_revisions")


def _recipe(db: Session, *, name: str = "Soup") -> Recipe:
    user = ensure_dev_user(db)
    recipe = Recipe(id=uuid4(), user_id=user.id, name=name)
    db.add(recipe)
    db.flush()
    return recipe


def _revision(
    recipe: Recipe,
    number: int,
    *,
    digest: str = "same-diagnostic-digest",
    origin: str = "normal_publication",
    confidence: str = "complete",
) -> RecipePublicationRevision:
    return RecipePublicationRevision(
        id=uuid4(),
        recipe_id=recipe.id,
        user_id=recipe.user_id,
        revision_number=number,
        creation_origin=origin,
        provenance_confidence=confidence,
        published_name=recipe.name,
        published_notes=recipe.notes,
        content_digest=digest,
    )


def _amount(
    revision: RecipePublicationRevision,
    *,
    order: int = 0,
    label: str = "1 serving",
    mode: str = "serving",
    quantity: Decimal | None = Decimal("1"),
    unit: str = "serving",
    grams: Decimal | None = Decimal("250"),
    is_default: bool = True,
) -> RecipePublicationAmountDefinition:
    return RecipePublicationAmountDefinition(
        id=uuid4(),
        revision_id=revision.id,
        display_order=order,
        display_label=label,
        semantic_mode=mode,
        display_quantity=quantity,
        display_unit=unit,
        gram_equivalent=grams,
        is_default=is_default,
    )


def _food(db: Session, *, name: str = "Projection") -> FoodItem:
    user = ensure_dev_user(db)
    food = FoodItem(id=uuid4(), user_id=user.id, name=name, source_type="manual", is_recipe=False)
    db.add(food)
    db.flush()
    return food


def _log(
    db: Session,
    food: FoodItem,
    *,
    revision_id: UUID | None = None,
    amount_id: UUID | None = None,
) -> DailyLog:
    log = DailyLog(
        id=uuid4(),
        user_id=food.user_id,
        food_item_id=food.id,
        logged_date=date(2026, 7, 13),
        amount_quantity=Decimal("1"),
        amount_unit="serving",
        recipe_publication_revision_id=revision_id,
        recipe_publication_amount_definition_id=amount_id,
    )
    db.add(log)
    return log


def test_repository_round_trips_append_only_revision_graph(db_session: Session) -> None:
    recipe = _recipe(db_session)
    revision = _revision(recipe, 1)
    revision.amount_definitions = [
        _amount(revision),
        _amount(
            revision,
            order=1,
            label="g",
            mode="g",
            quantity=None,
            unit="g",
            grams=None,
            is_default=False,
        ),
    ]
    revision.nutrients = [
        RecipePublicationNutrient(
            id=uuid4(),
            revision_id=revision.id,
            nutrient_id="calories",
            amount=Decimal("125"),
            unit="kcal",
            basis="per_serving",
            data_status="known",
        ),
        RecipePublicationNutrient(
            id=uuid4(),
            revision_id=revision.id,
            nutrient_id="vitamin_d",
            amount=None,
            unit="mcg",
            basis="per_serving",
            data_status="unknown",
        ),
    ]

    repository = RecipePublicationRepository(db_session)
    loaded = repository.add(revision)

    assert [amount.semantic_mode for amount in loaded.amount_definitions] == ["serving", "g"]
    assert loaded.amount_definitions[1].display_quantity is None
    assert loaded.amount_definitions[1].gram_equivalent is None
    assert [nutrient.data_status for nutrient in loaded.nutrients] == ["known", "unknown"]
    assert not hasattr(repository, "update")
    assert not hasattr(repository, "delete")


def test_revision_history_allows_identical_digests_and_recipe_local_numbers(
    db_session: Session,
) -> None:
    first_recipe = _recipe(db_session, name="Soup")
    second_recipe = _recipe(db_session, name="Stew")
    repository = RecipePublicationRepository(db_session)

    first = repository.add(_revision(first_recipe, 1))
    second = repository.add(_revision(first_recipe, 2))
    other = repository.add(_revision(second_recipe, 1))

    assert first.id != second.id
    assert first.content_digest == second.content_digest
    assert [
        revision.revision_number
        for revision in repository.list_for_recipe(first_recipe.id, first_recipe.user_id)
    ] == [
        1,
        2,
    ]
    assert other.revision_number == 1


@pytest.mark.parametrize("number", [0, -1])
def test_revision_number_must_be_positive(db_session: Session, number: int) -> None:
    recipe = _recipe(db_session)
    db_session.add(_revision(recipe, number))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_revision_number_is_unique_within_recipe(db_session: Session) -> None:
    recipe = _recipe(db_session)
    db_session.add_all([_revision(recipe, 1, digest="a"), _revision(recipe, 1, digest="b")])
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    ("origin", "confidence"),
    [("not_an_origin", "complete"), ("normal_publication", "not_confidence")],
)
def test_invalid_origin_or_provenance_is_rejected(
    db_session: Session, origin: str, confidence: str
) -> None:
    recipe = _recipe(db_session)
    db_session.add(_revision(recipe, 1, origin=origin, confidence=confidence))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_creation_origin_and_provenance_confidence_are_independent(db_session: Session) -> None:
    recipe = _recipe(db_session)
    baseline = _revision(
        recipe,
        1,
        origin="legacy_projection_capture",
        confidence="transition_baseline",
    )
    ambiguous = _revision(
        recipe,
        2,
        origin="legacy_projection_capture",
        confidence="ambiguous",
    )
    db_session.add_all([baseline, ambiguous])
    db_session.flush()
    assert baseline.creation_origin == ambiguous.creation_origin
    assert baseline.provenance_confidence != ambiguous.provenance_confidence


def test_duplicate_semantic_amount_and_second_gram_mode_are_rejected(db_session: Session) -> None:
    recipe = _recipe(db_session)
    revision = _revision(recipe, 1)
    db_session.add(revision)
    db_session.flush()
    db_session.add_all([_amount(revision), _amount(revision, order=1)])
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_canonical_gram_mode_rejects_fixed_entered_quantity(db_session: Session) -> None:
    recipe = _recipe(db_session)
    revision = _revision(recipe, 1)
    db_session.add(revision)
    db_session.flush()
    db_session.add(
        _amount(
            revision,
            label="50 g",
            mode="g",
            quantity=Decimal("50"),
            unit="g",
            grams=None,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_revision_allows_at_most_one_canonical_gram_mode(db_session: Session) -> None:
    recipe = _recipe(db_session)
    revision = _revision(recipe, 1)
    db_session.add(revision)
    db_session.flush()
    db_session.add_all(
        [
            _amount(
                revision,
                order=0,
                label="g",
                mode="g",
                quantity=None,
                unit="g",
                grams=None,
            ),
            _amount(
                revision,
                order=1,
                label="grams",
                mode="g",
                quantity=None,
                unit="g",
                grams=None,
                is_default=False,
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    ("status", "amount"),
    [("known", None), ("estimated", None), ("unknown", Decimal("1")), ("zero", Decimal("1"))],
)
def test_nutrient_status_amount_semantics_are_enforced(
    db_session: Session, status: str, amount: Decimal | None
) -> None:
    recipe = _recipe(db_session)
    revision = _revision(recipe, 1)
    db_session.add(revision)
    db_session.flush()
    db_session.add(
        RecipePublicationNutrient(
            id=uuid4(),
            revision_id=revision.id,
            nutrient_id="calories",
            amount=amount,
            unit="kcal",
            basis="per_serving",
            data_status=status,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_nutrient_identity_and_basis_are_unique_per_revision(db_session: Session) -> None:
    recipe = _recipe(db_session)
    revision = _revision(recipe, 1)
    db_session.add(revision)
    db_session.flush()
    rows = [
        RecipePublicationNutrient(
            id=uuid4(),
            revision_id=revision.id,
            nutrient_id="calories",
            amount=Decimal("100") + index,
            unit="kcal",
            basis="per_serving",
            data_status="known",
        )
        for index in range(2)
    ]
    db_session.add_all(rows)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_revisions_preserve_different_values_for_same_nutrient(db_session: Session) -> None:
    recipe = _recipe(db_session)
    first = _revision(recipe, 1)
    second = _revision(recipe, 2)
    first.nutrients = [
        RecipePublicationNutrient(
            id=uuid4(),
            revision_id=first.id,
            nutrient_id="calories",
            amount=Decimal("100"),
            unit="kcal",
            basis="per_serving",
            data_status="known",
        )
    ]
    second.nutrients = [
        RecipePublicationNutrient(
            id=uuid4(),
            revision_id=second.id,
            nutrient_id="calories",
            amount=Decimal("125"),
            unit="kcal",
            basis="per_serving",
            data_status="estimated",
        ),
        RecipePublicationNutrient(
            id=uuid4(),
            revision_id=second.id,
            nutrient_id="added_sugars",
            amount=Decimal("0"),
            unit="g",
            basis="per_serving",
            data_status="zero",
        ),
    ]
    db_session.add_all([first, second])
    db_session.flush()
    assert first.nutrients[0].amount == Decimal("100")
    assert second.nutrients[0].amount == Decimal("125")
    assert second.nutrients[1].data_status == "zero"


def test_active_revision_is_nullable_owned_and_repository_readable(db_session: Session) -> None:
    recipe = _recipe(db_session)
    revision = _revision(recipe, 1)
    repository = RecipePublicationRepository(db_session)
    repository.add(revision)
    assert recipe.active_publication_revision_id is None

    recipe.active_publication_revision_id = revision.id
    db_session.flush()
    assert repository.get_active_for_recipe(recipe.id, recipe.user_id).id == revision.id


def test_cross_recipe_active_revision_is_rejected(db_session: Session) -> None:
    owner = _recipe(db_session, name="Owner")
    other = _recipe(db_session, name="Other")
    revision = _revision(owner, 1)
    db_session.add(revision)
    db_session.flush()
    other.active_publication_revision_id = revision.id
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_projection_linkage_is_optional_and_owner_checked(db_session: Session) -> None:
    recipe = _recipe(db_session)
    revision = _revision(recipe, 1)
    db_session.add(revision)
    manual_food = _food(db_session, name="Manual")
    db_session.flush()
    assert manual_food.recipe_publication_revision_id is None

    projection = _food(db_session)
    projection.source_type = "recipe"
    projection.is_recipe = True
    projection.recipe_publication_revision_id = revision.id
    db_session.flush()
    assert projection.recipe_publication_revision_id == revision.id


def test_daily_log_revision_links_are_paired_and_amount_membership_is_enforced(
    db_session: Session,
) -> None:
    recipe = _recipe(db_session)
    first = _revision(recipe, 1)
    second = _revision(recipe, 2)
    first_amount = _amount(first)
    second_amount = _amount(second)
    db_session.add_all([first, second, first_amount, second_amount])
    food = _food(db_session)
    db_session.flush()

    legacy = _log(db_session, food)
    db_session.flush()
    assert legacy.recipe_publication_revision_id is None
    assert legacy.recipe_publication_amount_definition_id is None

    revision_aware = _log(db_session, food, revision_id=first.id, amount_id=first_amount.id)
    db_session.flush()
    assert revision_aware.recipe_publication_amount_definition_id == first_amount.id

    mismatched = _log(db_session, food, revision_id=first.id, amount_id=second_amount.id)
    db_session.add(mismatched)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_daily_log_rejects_only_one_revision_link(db_session: Session) -> None:
    recipe = _recipe(db_session)
    revision = _revision(recipe, 1)
    db_session.add(revision)
    food = _food(db_session)
    db_session.flush()
    _log(db_session, food, revision_id=revision.id)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_revision_with_historical_children_cannot_be_deleted(db_session: Session) -> None:
    recipe = _recipe(db_session)
    revision = _revision(recipe, 1)
    revision.amount_definitions = [_amount(revision)]
    db_session.add(revision)
    db_session.commit()

    db_session.delete(revision)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_migration_upgrades_and_downgrades_without_backfill() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    metadata = MetaData()
    Table("users", metadata, Column("id", GUID(), primary_key=True))
    Table("nutrients", metadata, Column("id", Text, primary_key=True))
    Table(
        "recipes",
        metadata,
        Column("id", GUID(), primary_key=True),
        Column("user_id", GUID(), nullable=False),
        Column("name", Text, nullable=False),
    )
    Table(
        "food_items",
        metadata,
        Column("id", GUID(), primary_key=True),
        Column("user_id", GUID(), nullable=True),
        Column("name", Text, nullable=False),
    )
    Table(
        "daily_logs",
        metadata,
        Column("id", GUID(), primary_key=True),
        Column("user_id", GUID(), nullable=False),
    )
    metadata.create_all(engine)
    user_id = uuid4()
    recipe_id = uuid4()
    with engine.begin() as connection:
        connection.execute(metadata.tables["users"].insert().values(id=user_id))
        connection.execute(
            metadata.tables["recipes"]
            .insert()
            .values(id=recipe_id, user_id=user_id, name="Existing")
        )
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            publication_migration.upgrade()

        inspector = inspect(connection)
        assert "recipe_publication_revisions" in inspector.get_table_names()
        assert "recipe_publication_amount_definitions" in inspector.get_table_names()
        assert "recipe_publication_nutrients" in inspector.get_table_names()
        assert "active_publication_revision_id" in {
            column["name"] for column in inspector.get_columns("recipes")
        }
        assert (
            connection.exec_driver_sql(
                "SELECT name FROM recipes WHERE id = ?", (str(recipe_id),)
            ).scalar_one()
            == "Existing"
        )
        assert (
            connection.exec_driver_sql(
                "SELECT COUNT(*) FROM recipe_publication_revisions"
            ).scalar_one()
            == 0
        )

        with Operations.context(context):
            publication_migration.downgrade()
        inspector = inspect(connection)
        assert "recipe_publication_revisions" not in inspector.get_table_names()
        assert "active_publication_revision_id" not in {
            column["name"] for column in inspector.get_columns("recipes")
        }
