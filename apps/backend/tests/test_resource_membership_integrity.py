from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    UniqueConstraint,
    delete,
    select,
    text,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.food import (
    FoodItem,
    FoodNutrient,
    OcrNutritionConfirmationTrace,
    ServingDefinition,
)
from app.models.log import DailyLog, DailyLogNutrientSnapshot
from app.models.recipe import Recipe, RecipeIngredient
from app.models.recipe_publication import (
    RecipePublicationAmountDefinition,
    RecipePublicationRevision,
)
from app.models.user import User
from app.operators.phase5c_contracts import canonical_digest
from app.operators.immutable_provenance_sqlite import (
    allow_sqlite_snapshot_replacement,
)
from app.operators.resource_membership_contracts import (
    CONSTRAINT_MANIFEST_VERSION,
    FOREIGN_KEY_CONTRACTS,
    PARENT_UNIQUE_CONSTRAINTS,
    PROJECTION_REVISION_UNIQUE_INDEX,
    PUBLICATION_LINK_CHECK,
    SUPPORTING_INDEXES,
    expected_constraint_manifest,
    expected_runtime_privilege_manifest,
)
from app.operators.resource_membership_qualification import (
    qualify_runtime_privileges,
)


def test_runtime_privilege_qualification_rejects_unknown_policy_state() -> None:
    with pytest.raises(ValueError, match="normal or maintenance"):
        qualify_runtime_privileges(object(), expected_state="partially_closed")


def _user(db: Session, label: str) -> UUID:
    user_id = uuid4()
    db.execute(
        User.__table__.insert().values(
            id=user_id,
            email=f"membership-{label}-{user_id}@example.test",
        )
    )
    return user_id


def _food(
    db: Session,
    user_id: UUID,
    label: str,
    *,
    revision_id: UUID | None = None,
    recipe_id: UUID | None = None,
) -> UUID:
    if revision_id is not None and recipe_id is None:
        raise AssertionError("revision-backed test Foods require their Recipe identity")
    food_id = uuid4()
    db.execute(
        FoodItem.__table__.insert().values(
            id=food_id,
            user_id=user_id,
            name=label,
            source_type="recipe" if revision_id is not None else "manual",
            source_id=str(recipe_id) if revision_id is not None else None,
            recipe_publication_revision_id=revision_id,
            is_recipe=revision_id is not None,
        )
    )
    return food_id


def _recipe(db: Session, user_id: UUID, label: str) -> UUID:
    recipe_id = uuid4()
    db.execute(
        Recipe.__table__.insert().values(
            id=recipe_id,
            user_id=user_id,
            name=label,
            needs_republish=False,
        )
    )
    return recipe_id


def _serving(db: Session, food_id: UUID, label: str = "1 portion") -> UUID:
    serving_id = uuid4()
    db.execute(
        ServingDefinition.__table__.insert().values(
            id=serving_id,
            food_item_id=food_id,
            label=label,
            quantity=Decimal("1"),
            unit="portion",
            gram_weight=Decimal("100"),
            is_default=True,
            source="manual",
            is_user_confirmed=True,
        )
    )
    return serving_id


def _food_nutrient(
    db: Session,
    food_id: UUID,
    nutrient_id: str = "calories",
) -> UUID:
    row_id = uuid4()
    db.execute(
        FoodNutrient.__table__.insert().values(
            id=row_id,
            food_item_id=food_id,
            nutrient_id=nutrient_id,
            amount=Decimal("100"),
            unit="kcal" if nutrient_id == "calories" else "g",
            basis="per_100g",
            data_status="known",
            source="manual",
            is_user_confirmed=True,
        )
    )
    return row_id


def _ingredient_values(
    *,
    recipe_id: UUID,
    food_id: UUID,
    user_id: UUID,
    serving_id: UUID | None = None,
) -> dict:
    return {
        "id": uuid4(),
        "user_id": user_id,
        "recipe_id": recipe_id,
        "food_item_id": food_id,
        "position": 0,
        "amount_quantity": Decimal("1"),
        "amount_unit": "serving" if serving_id is not None else "g",
        "serving_definition_id": serving_id,
        "resolved_gram_amount": Decimal("100"),
    }


def _log(
    db: Session,
    *,
    user_id: UUID,
    food_id: UUID,
    serving_id: UUID | None = None,
    revision_id: UUID | None = None,
    amount_id: UUID | None = None,
) -> UUID:
    log_id = uuid4()
    db.execute(
        DailyLog.__table__.insert().values(
            id=log_id,
            user_id=user_id,
            food_item_id=food_id,
            food_name_snapshot="Historical food",
            logged_date=date(2026, 7, 21),
            amount_quantity=Decimal("1"),
            amount_unit="serving" if serving_id is not None else "g",
            serving_definition_id=serving_id,
            recipe_publication_revision_id=revision_id,
            recipe_publication_amount_definition_id=amount_id,
            gram_amount=Decimal("100"),
        )
    )
    return log_id


def _snapshot_values(
    *,
    log_id: UUID,
    food_id: UUID,
    nutrient_id: str = "calories",
    food_nutrient_id: UUID | None = None,
    serving_id: UUID | None = None,
    amount: Decimal = Decimal("100"),
) -> dict:
    return {
        "id": uuid4(),
        "daily_log_id": log_id,
        "source_food_item_id": food_id,
        "source_food_nutrient_id": food_nutrient_id,
        "serving_definition_id": serving_id,
        "nutrient_id": nutrient_id,
        "amount": amount,
        "unit": "kcal" if nutrient_id == "calories" else "g",
        "data_status": "known",
        "consumed_amount_quantity": Decimal("1"),
        "consumed_amount_unit": "serving" if serving_id is not None else "g",
        "consumed_gram_amount": Decimal("100"),
    }


def _revision(db: Session, recipe_id: UUID, user_id: UUID, number: int) -> tuple[UUID, UUID]:
    revision_id = uuid4()
    amount_id = uuid4()
    db.execute(
        RecipePublicationRevision.__table__.insert().values(
            id=revision_id,
            recipe_id=recipe_id,
            user_id=user_id,
            revision_number=number,
            creation_origin="normal_publication" if number == 1 else "explicit_republish",
            provenance_confidence="complete",
            published_name=f"Published revision {number}",
            content_digest=f"revision-{revision_id}",
        )
    )
    db.execute(
        RecipePublicationAmountDefinition.__table__.insert().values(
            id=amount_id,
            revision_id=revision_id,
            display_order=0,
            display_label="1 serving",
            semantic_mode="serving",
            display_quantity=Decimal("1"),
            display_unit="serving",
            gram_equivalent=Decimal("100"),
            is_default=True,
        )
    )
    return revision_id, amount_id


def _assert_rejected(db: Session, statement) -> None:
    with pytest.raises(IntegrityError):
        db.execute(statement)
        if db.get_bind().dialect.name == "postgresql":
            # PostgreSQL does not check INITIALLY DEFERRED constraints when the
            # test session merely releases its savepoint inside the fixture's
            # rollback-only outer transaction.  Force the real commit-time
            # validation point without weakening production deferrability.
            db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        db.commit()
    db.rollback()


def _first_publication(db: Session) -> dict[str, UUID]:
    user_id = _user(db, "publication")
    recipe_id = _recipe(db, user_id, "Publication Recipe")
    revision_id, amount_id = _revision(db, recipe_id, user_id, 1)
    projection_id = _food(
        db,
        user_id,
        "Publication projection",
        revision_id=revision_id,
        recipe_id=recipe_id,
    )
    db.commit()
    db.execute(
        update(Recipe)
        .where(Recipe.id == recipe_id)
        .values(
            published_food_item_id=projection_id,
            active_publication_revision_id=revision_id,
        )
    )
    db.commit()
    return {
        "user_id": user_id,
        "recipe_id": recipe_id,
        "revision_id": revision_id,
        "amount_id": amount_id,
        "projection_id": projection_id,
    }


@pytest.mark.parametrize("contract", FOREIGN_KEY_CONTRACTS, ids=lambda item: item.name)
def test_frozen_composite_foreign_key_metadata_is_exact(contract) -> None:
    table = Recipe.metadata.tables[contract.child_table]
    constraint = next(
        item
        for item in table.constraints
        if isinstance(item, ForeignKeyConstraint) and item.name == contract.name
    )

    assert tuple(column.name for column in constraint.columns) == contract.child_columns
    assert tuple(element.column.table.name for element in constraint.elements) == (
        contract.parent_table,
    ) * len(contract.parent_columns)
    assert tuple(element.column.name for element in constraint.elements) == contract.parent_columns
    assert constraint.onupdate == contract.on_update
    assert constraint.ondelete == contract.on_delete
    assert constraint.match == contract.match
    assert bool(constraint.deferrable) is contract.deferrable
    assert constraint.initially == contract.initially


@pytest.mark.parametrize(
    ("name", "table_name", "columns"),
    PARENT_UNIQUE_CONSTRAINTS,
    ids=[item[0] for item in PARENT_UNIQUE_CONSTRAINTS],
)
def test_frozen_parent_membership_unique_metadata_is_exact(
    name: str,
    table_name: str,
    columns: tuple[str, ...],
) -> None:
    table = Recipe.metadata.tables[table_name]
    constraint = next(
        item
        for item in table.constraints
        if isinstance(item, UniqueConstraint) and item.name == name
    )

    assert tuple(column.name for column in constraint.columns) == columns


@pytest.mark.parametrize(
    ("name", "table_name", "columns"),
    SUPPORTING_INDEXES,
    ids=[item[0] for item in SUPPORTING_INDEXES],
)
def test_frozen_supporting_index_metadata_is_exact(
    name: str,
    table_name: str,
    columns: tuple[str, ...],
) -> None:
    table = Recipe.metadata.tables[table_name]
    index = next(item for item in table.indexes if item.name == name)

    assert tuple(column.name for column in index.columns) == columns


def test_publication_pair_and_projection_revision_uniqueness_metadata_is_present() -> None:
    publication_check = next(
        item
        for item in Recipe.__table__.constraints
        if isinstance(item, CheckConstraint) and item.name == PUBLICATION_LINK_CHECK
    )
    projection_index = next(
        item
        for item in FoodItem.__table__.indexes
        if item.name == PROJECTION_REVISION_UNIQUE_INDEX
    )

    assert publication_check.sqltext is not None
    assert tuple(column.name for column in projection_index.columns) == (
        "recipe_publication_revision_id",
    )
    assert projection_index.unique is True


def test_0019_constraint_and_runtime_privilege_manifest_digests_are_frozen() -> None:
    assert canonical_digest(
        {
            "constraint_manifest_version": CONSTRAINT_MANIFEST_VERSION,
            "constraints": expected_constraint_manifest(),
        }
    ) == "d30e2543da3b2fecabf6b07ba1f0e719fd731b708f1fe51e5b68340626734f25"
    assert canonical_digest(expected_runtime_privilege_manifest()) == (
        "2cce47afce6f92c03c84b938c5230f9c56688676b594b6954d750756888d6423"
    )


def test_recipe_ingredient_rejects_recipe_owner_mismatch(db_session: Session) -> None:
    recipe_owner = _user(db_session, "ingredient-recipe-owner")
    other_owner = _user(db_session, "ingredient-other-owner")
    recipe_id = _recipe(db_session, recipe_owner, "Owned recipe")
    other_food_id = _food(db_session, other_owner, "Other food")
    db_session.commit()

    _assert_rejected(
        db_session,
        RecipeIngredient.__table__.insert().values(
            **_ingredient_values(
                recipe_id=recipe_id,
                food_id=other_food_id,
                user_id=other_owner,
            )
        ),
    )


def test_recipe_ingredient_rejects_food_owner_mismatch(db_session: Session) -> None:
    recipe_owner = _user(db_session, "ingredient-food-owner")
    other_owner = _user(db_session, "ingredient-food-other")
    recipe_id = _recipe(db_session, recipe_owner, "Owned recipe")
    other_food_id = _food(db_session, other_owner, "Other food")
    db_session.commit()

    _assert_rejected(
        db_session,
        RecipeIngredient.__table__.insert().values(
            **_ingredient_values(
                recipe_id=recipe_id,
                food_id=other_food_id,
                user_id=recipe_owner,
            )
        ),
    )


def test_recipe_ingredient_rejects_serving_from_another_food(db_session: Session) -> None:
    owner_id = _user(db_session, "ingredient-serving")
    recipe_id = _recipe(db_session, owner_id, "Owned recipe")
    food_id = _food(db_session, owner_id, "Ingredient food")
    other_food_id = _food(db_session, owner_id, "Serving owner")
    other_serving_id = _serving(db_session, other_food_id)
    db_session.commit()

    _assert_rejected(
        db_session,
        RecipeIngredient.__table__.insert().values(
            **_ingredient_values(
                recipe_id=recipe_id,
                food_id=food_id,
                user_id=owner_id,
                serving_id=other_serving_id,
            )
        ),
    )


def test_daily_log_rejects_food_owned_by_another_user(db_session: Session) -> None:
    log_owner = _user(db_session, "log-owner")
    food_owner = _user(db_session, "log-food-owner")
    food_id = _food(db_session, food_owner, "Foreign food")
    db_session.commit()

    statement = DailyLog.__table__.insert().values(
        id=uuid4(),
        user_id=log_owner,
        food_item_id=food_id,
        food_name_snapshot="Foreign",
        logged_date=date(2026, 7, 21),
        amount_quantity=Decimal("1"),
        amount_unit="g",
    )
    _assert_rejected(db_session, statement)


def test_daily_log_rejects_serving_from_another_food(db_session: Session) -> None:
    owner_id = _user(db_session, "log-serving")
    food_id = _food(db_session, owner_id, "Logged food")
    other_food_id = _food(db_session, owner_id, "Serving owner")
    other_serving_id = _serving(db_session, other_food_id)
    db_session.commit()

    statement = DailyLog.__table__.insert().values(
        id=uuid4(),
        user_id=owner_id,
        food_item_id=food_id,
        food_name_snapshot="Logged food",
        logged_date=date(2026, 7, 21),
        amount_quantity=Decimal("1"),
        amount_unit="serving",
        serving_definition_id=other_serving_id,
    )
    _assert_rejected(db_session, statement)


def test_recipe_rejects_projection_from_a_different_active_revision(
    db_session: Session,
) -> None:
    owner_id = _user(db_session, "projection-revision")
    recipe_id = _recipe(db_session, owner_id, "Projection Recipe")
    first_revision_id, _ = _revision(db_session, recipe_id, owner_id, 1)
    second_revision_id, _ = _revision(db_session, recipe_id, owner_id, 2)
    projection_id = _food(
        db_session,
        owner_id,
        "Second revision projection",
        revision_id=second_revision_id,
        recipe_id=recipe_id,
    )
    db_session.commit()

    _assert_rejected(
        db_session,
        update(Recipe)
        .where(Recipe.id == recipe_id)
        .values(
            published_food_item_id=projection_id,
            active_publication_revision_id=first_revision_id,
        ),
    )


def test_projection_food_rejects_revision_owned_by_another_user(
    db_session: Session,
) -> None:
    recipe_owner = _user(db_session, "projection-owner")
    projection_owner = _user(db_session, "projection-other-owner")
    recipe_id = _recipe(db_session, recipe_owner, "Projection Recipe")
    revision_id, _ = _revision(db_session, recipe_id, recipe_owner, 1)
    db_session.commit()

    _assert_rejected(
        db_session,
        FoodItem.__table__.insert().values(
            id=uuid4(),
            user_id=projection_owner,
            name="Foreign-owner projection",
            source_type="recipe",
            source_id=str(recipe_id),
            recipe_publication_revision_id=revision_id,
            is_recipe=True,
        ),
    )


def test_projection_food_requires_owner_when_revision_bound(
    db_session: Session,
) -> None:
    owner_id = _user(db_session, "projection-required-owner")
    recipe_id = _recipe(db_session, owner_id, "Projection Recipe")
    revision_id, _ = _revision(db_session, recipe_id, owner_id, 1)
    db_session.commit()

    _assert_rejected(
        db_session,
        FoodItem.__table__.insert().values(
            id=uuid4(),
            user_id=None,
            name="Ownerless projection",
            source_type="recipe",
            source_id=str(recipe_id),
            recipe_publication_revision_id=revision_id,
            is_recipe=True,
        ),
    )


def test_ocr_trace_rejects_food_owned_by_another_user(db_session: Session) -> None:
    trace_owner = _user(db_session, "trace-owner")
    food_owner = _user(db_session, "trace-food-owner")
    food_id = _food(db_session, food_owner, "Foreign OCR food")
    db_session.commit()

    statement = OcrNutritionConfirmationTrace.__table__.insert().values(
        id=uuid4(),
        user_id=trace_owner,
        food_item_id=food_id,
        parser_version="test-parser",
        image_source_type="upload",
        schema_version="test-schema",
        trace_snapshot={},
        client_request_id=uuid4(),
        request_fingerprint="fingerprint",
    )
    _assert_rejected(db_session, statement)


def test_snapshot_rejects_source_food_different_from_daily_log(db_session: Session) -> None:
    owner_id = _user(db_session, "snapshot-log-food")
    logged_food_id = _food(db_session, owner_id, "Logged food")
    other_food_id = _food(db_session, owner_id, "Other snapshot food")
    log_id = _log(db_session, user_id=owner_id, food_id=logged_food_id)
    db_session.commit()

    _assert_rejected(
        db_session,
        DailyLogNutrientSnapshot.__table__.insert().values(
            **_snapshot_values(log_id=log_id, food_id=other_food_id)
        ),
    )


@pytest.mark.parametrize("mismatch", ["food", "nutrient"])
def test_snapshot_rejects_source_nutrient_membership_mismatch(
    db_session: Session,
    mismatch: str,
) -> None:
    owner_id = _user(db_session, f"snapshot-nutrient-{mismatch}")
    food_id = _food(db_session, owner_id, "Logged food")
    other_food_id = _food(db_session, owner_id, "Other nutrient food")
    nutrient_food_id = other_food_id if mismatch == "food" else food_id
    food_nutrient_id = _food_nutrient(db_session, nutrient_food_id, "calories")
    log_id = _log(db_session, user_id=owner_id, food_id=food_id)
    db_session.commit()

    _assert_rejected(
        db_session,
        DailyLogNutrientSnapshot.__table__.insert().values(
            **_snapshot_values(
                log_id=log_id,
                food_id=food_id,
                nutrient_id="protein" if mismatch == "nutrient" else "calories",
                food_nutrient_id=food_nutrient_id,
            )
        ),
    )


def test_snapshot_rejects_serving_from_another_food(db_session: Session) -> None:
    owner_id = _user(db_session, "snapshot-serving")
    food_id = _food(db_session, owner_id, "Logged food")
    other_food_id = _food(db_session, owner_id, "Serving owner")
    other_serving_id = _serving(db_session, other_food_id)
    log_id = _log(db_session, user_id=owner_id, food_id=food_id)
    db_session.commit()

    _assert_rejected(
        db_session,
        DailyLogNutrientSnapshot.__table__.insert().values(
            **_snapshot_values(
                log_id=log_id,
                food_id=food_id,
                serving_id=other_serving_id,
            )
        ),
    )


@pytest.mark.parametrize("link", ["projection", "revision"])
def test_recipe_publication_links_must_be_paired(
    db_session: Session,
    link: str,
) -> None:
    owner_id = _user(db_session, f"unpaired-{link}")
    recipe_id = _recipe(db_session, owner_id, "Unpaired Recipe")
    revision_id, _ = _revision(db_session, recipe_id, owner_id, 1)
    projection_id = _food(
        db_session,
        owner_id,
        "Unpaired projection",
        revision_id=revision_id,
        recipe_id=recipe_id,
    )
    db_session.commit()

    values = (
        {"published_food_item_id": projection_id}
        if link == "projection"
        else {"active_publication_revision_id": revision_id}
    )
    _assert_rejected(
        db_session,
        update(Recipe).where(Recipe.id == recipe_id).values(**values),
    )


def test_one_revision_cannot_back_multiple_projections(db_session: Session) -> None:
    owner_id = _user(db_session, "duplicate-projection")
    recipe_id = _recipe(db_session, owner_id, "Projection Recipe")
    revision_id, _ = _revision(db_session, recipe_id, owner_id, 1)
    _food(
        db_session,
        owner_id,
        "First projection",
        revision_id=revision_id,
        recipe_id=recipe_id,
    )
    db_session.commit()

    _assert_rejected(
        db_session,
        FoodItem.__table__.insert().values(
            id=uuid4(),
            user_id=owner_id,
            name="Duplicate projection",
            source_type="recipe",
            source_id=str(recipe_id),
            recipe_publication_revision_id=revision_id,
            is_recipe=True,
        ),
    )


def test_snapshot_allows_nullable_mutable_source_provenance(db_session: Session) -> None:
    owner_id = _user(db_session, "nullable-provenance")
    food_id = _food(db_session, owner_id, "Historical source")
    log_id = _log(db_session, user_id=owner_id, food_id=food_id)
    snapshot_id = uuid4()
    values = _snapshot_values(log_id=log_id, food_id=food_id)
    values["id"] = snapshot_id
    db_session.execute(DailyLogNutrientSnapshot.__table__.insert().values(**values))

    db_session.commit()

    row = db_session.execute(
        select(
            DailyLogNutrientSnapshot.source_food_nutrient_id,
            DailyLogNutrientSnapshot.serving_definition_id,
        ).where(DailyLogNutrientSnapshot.id == snapshot_id)
    ).one()
    assert row == (None, None)


def test_soft_deleted_food_remains_a_valid_historical_membership_parent(
    db_session: Session,
) -> None:
    owner_id = _user(db_session, "soft-deleted-parent")
    food_id = _food(db_session, owner_id, "Soft-deleted source")
    recipe_id = _recipe(db_session, owner_id, "Historical consumer")
    db_session.execute(
        update(FoodItem)
        .where(FoodItem.id == food_id)
        .values(deleted_at=datetime.now(timezone.utc))
    )
    db_session.execute(
        RecipeIngredient.__table__.insert().values(
            **_ingredient_values(
                recipe_id=recipe_id,
                food_id=food_id,
                user_id=owner_id,
            )
        )
    )
    log_id = _log(db_session, user_id=owner_id, food_id=food_id)
    db_session.execute(
        OcrNutritionConfirmationTrace.__table__.insert().values(
            id=uuid4(),
            user_id=owner_id,
            food_item_id=food_id,
            parser_version="historical-parser",
            image_source_type="upload",
            schema_version="historical-schema",
            trace_snapshot={},
            client_request_id=uuid4(),
            request_fingerprint="historical-soft-delete",
        )
    )
    db_session.commit()

    assert db_session.scalar(
        select(DailyLog.food_item_id).where(DailyLog.id == log_id)
    ) == food_id


def test_deleting_mutable_provenance_sets_nullable_links_to_null(
    db_session: Session,
) -> None:
    owner_id = _user(db_session, "set-null")
    recipe_id = _recipe(db_session, owner_id, "Serving consumer")
    food_id = _food(db_session, owner_id, "Mutable source")
    serving_id = _serving(db_session, food_id)
    food_nutrient_id = _food_nutrient(db_session, food_id)
    ingredient_values = _ingredient_values(
        recipe_id=recipe_id,
        food_id=food_id,
        user_id=owner_id,
        serving_id=serving_id,
    )
    ingredient_id = ingredient_values["id"]
    db_session.execute(RecipeIngredient.__table__.insert().values(**ingredient_values))
    log_id = _log(
        db_session,
        user_id=owner_id,
        food_id=food_id,
        serving_id=serving_id,
    )
    snapshot_id = uuid4()
    snapshot_values = _snapshot_values(
        log_id=log_id,
        food_id=food_id,
        food_nutrient_id=food_nutrient_id,
        serving_id=serving_id,
    )
    snapshot_values["id"] = snapshot_id
    db_session.execute(DailyLogNutrientSnapshot.__table__.insert().values(**snapshot_values))
    db_session.commit()

    db_session.execute(delete(ServingDefinition).where(ServingDefinition.id == serving_id))
    db_session.execute(delete(FoodNutrient).where(FoodNutrient.id == food_nutrient_id))
    db_session.commit()

    assert db_session.scalar(
        select(RecipeIngredient.serving_definition_id).where(
            RecipeIngredient.id == ingredient_id
        )
    ) is None
    assert db_session.scalar(
        select(DailyLog.serving_definition_id).where(DailyLog.id == log_id)
    ) is None
    snapshot = db_session.execute(
        select(
            DailyLogNutrientSnapshot.source_food_item_id,
            DailyLogNutrientSnapshot.source_food_nutrient_id,
            DailyLogNutrientSnapshot.serving_definition_id,
            DailyLogNutrientSnapshot.amount,
        ).where(DailyLogNutrientSnapshot.id == snapshot_id)
    ).one()
    assert snapshot == (food_id, None, None, Decimal("100.000000"))


def test_first_publication_accepts_paired_revision_projection_links(
    db_session: Session,
) -> None:
    graph = _first_publication(db_session)

    stored = db_session.execute(
        select(
            Recipe.published_food_item_id,
            Recipe.active_publication_revision_id,
        ).where(Recipe.id == graph["recipe_id"])
    ).one()
    assert stored == (graph["projection_id"], graph["revision_id"])


def test_republish_allows_old_revision_log_to_remain_historical(
    db_session: Session,
) -> None:
    graph = _first_publication(db_session)
    old_log_id = _log(
        db_session,
        user_id=graph["user_id"],
        food_id=graph["projection_id"],
        revision_id=graph["revision_id"],
        amount_id=graph["amount_id"],
    )
    old_snapshot = _snapshot_values(
        log_id=old_log_id,
        food_id=graph["projection_id"],
        amount=Decimal("100"),
    )
    old_snapshot_id = old_snapshot["id"]
    db_session.execute(DailyLogNutrientSnapshot.__table__.insert().values(**old_snapshot))
    second_revision_id, _ = _revision(
        db_session,
        graph["recipe_id"],
        graph["user_id"],
        2,
    )
    db_session.commit()

    db_session.execute(
        update(FoodItem)
        .where(FoodItem.id == graph["projection_id"])
        .values(recipe_publication_revision_id=second_revision_id)
    )
    db_session.execute(
        update(Recipe)
        .where(Recipe.id == graph["recipe_id"])
        .values(active_publication_revision_id=second_revision_id)
    )
    db_session.commit()

    stored_log = db_session.execute(
        select(
            DailyLog.recipe_publication_revision_id,
            DailyLog.recipe_publication_amount_definition_id,
        ).where(DailyLog.id == old_log_id)
    ).one()
    assert stored_log == (graph["revision_id"], graph["amount_id"])
    assert db_session.scalar(
        select(FoodItem.recipe_publication_revision_id).where(
            FoodItem.id == graph["projection_id"]
        )
    ) == second_revision_id
    assert db_session.scalar(
        select(DailyLogNutrientSnapshot.amount).where(
            DailyLogNutrientSnapshot.id == old_snapshot_id
        )
    ) == Decimal("100.000000")


def test_valid_snapshot_replacement_preserves_log_membership(db_session: Session) -> None:
    owner_id = _user(db_session, "snapshot-replacement")
    food_id = _food(db_session, owner_id, "Mutable source")
    food_nutrient_id = _food_nutrient(db_session, food_id)
    log_id = _log(db_session, user_id=owner_id, food_id=food_id)
    original = _snapshot_values(
        log_id=log_id,
        food_id=food_id,
        food_nutrient_id=food_nutrient_id,
        amount=Decimal("100"),
    )
    original_id = original["id"]
    db_session.execute(DailyLogNutrientSnapshot.__table__.insert().values(**original))
    db_session.commit()

    replacement = _snapshot_values(
        log_id=log_id,
        food_id=food_id,
        food_nutrient_id=food_nutrient_id,
        amount=Decimal("125"),
    )
    replacement_id = replacement["id"]
    with allow_sqlite_snapshot_replacement(db_session, owner_id, log_id):
        db_session.execute(
            delete(DailyLogNutrientSnapshot).where(
                DailyLogNutrientSnapshot.id == original_id
            )
        )
    db_session.execute(DailyLogNutrientSnapshot.__table__.insert().values(**replacement))
    db_session.commit()

    stored = db_session.execute(
        select(
            DailyLogNutrientSnapshot.id,
            DailyLogNutrientSnapshot.daily_log_id,
            DailyLogNutrientSnapshot.source_food_item_id,
            DailyLogNutrientSnapshot.amount,
        ).where(DailyLogNutrientSnapshot.daily_log_id == log_id)
    ).one()
    assert stored == (
        replacement_id,
        log_id,
        food_id,
        Decimal("125.000000"),
    )
