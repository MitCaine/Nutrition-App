from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
import os
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models.food import FoodItem
from app.models.user import User
from app.schemas.food import FoodCreateRequest
from app.services.food_service import FoodService
from tests.postgres_test_support import isolated_postgres_session_factory


pytestmark = pytest.mark.postgres_concurrency

POSTGRES_URL = os.getenv(
    "NUTRITION_TEST_POSTGRES_URL",
    "postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app",
)

MIGRATION = import_module(
    "app.migrations.versions.0028_duplicate_food_source_identity"
)


@pytest.fixture()
def postgres_sessions():
    with isolated_postgres_session_factory(
        database_url=POSTGRES_URL,
        schema_prefix="test_food_duplicate_name",
    ) as factory:
        yield factory


def _active_source_index_predicate(connection) -> str:
    predicate = connection.scalar(
        text(
            """
            SELECT pg_catalog.pg_get_expr(
                index_metadata.indpred,
                index_metadata.indrelid
            )
            FROM pg_catalog.pg_index AS index_metadata
            JOIN pg_catalog.pg_class AS index_relation
              ON index_relation.oid = index_metadata.indexrelid
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = index_relation.relnamespace
            WHERE namespace.nspname = current_schema()
              AND index_relation.relname =
                  'ix_food_items_active_source_identity'
            """
        )
    )
    assert isinstance(predicate, str)
    return predicate


def test_0028_migration_relaxes_only_manual_duplicate_source_identity(
    postgres_sessions,
) -> None:
    with postgres_sessions() as db:
        connection = db.connection()

        # Reconstruct the exact pre-0028 index so this test exercises the
        # migration itself rather than merely Base.metadata.create_all().
        connection.execute(
            text(
                'DROP INDEX "ix_food_items_active_source_identity"'
            )
        )
        connection.execute(
            text(
                """
                CREATE UNIQUE INDEX "ix_food_items_active_source_identity"
                ON "food_items" ("user_id", "source_type", "source_id")
                WHERE "deleted_at" IS NULL
                  AND "source_id" IS NOT NULL
                """
            )
        )

        before = _active_source_index_predicate(connection).lower()
        assert "source_id is not null" in before
        assert "manual" not in before

        context = MigrationContext.configure(connection)
        with Operations.context(context):
            MIGRATION.upgrade()

        after = _active_source_index_predicate(connection).lower()
        assert "source_id is not null" in after
        assert "source_type" in after
        assert "manual" in after

        user_id = uuid4()
        db.add(
            User(
                id=user_id,
                email=f"duplicate-index-{uuid4()}@example.test",
            )
        )
        db.flush()

        shared_manual_source = str(uuid4())
        db.add_all(
            [
                FoodItem(
                    id=uuid4(),
                    user_id=user_id,
                    name="Manual Copy A",
                    source_type="manual",
                    source_id=shared_manual_source,
                    is_recipe=False,
                ),
                FoodItem(
                    id=uuid4(),
                    user_id=user_id,
                    name="Manual Copy B",
                    source_type="manual",
                    source_id=shared_manual_source,
                    is_recipe=False,
                ),
            ]
        )
        db.commit()

        # The exemption must be narrow. External source identities remain
        # unique for an active owner/source triple.
        external_source_id = f"fdc-{uuid4()}"
        with postgres_sessions() as external_db:
            external_db.add(
                FoodItem(
                    id=uuid4(),
                    user_id=user_id,
                    name="USDA Materialization A",
                    source_type="usda",
                    source_id=external_source_id,
                    is_recipe=False,
                )
            )
            external_db.commit()

        with postgres_sessions() as external_db:
            external_db.add(
                FoodItem(
                    id=uuid4(),
                    user_id=user_id,
                    name="USDA Materialization B",
                    source_type="usda",
                    source_id=external_source_id,
                    is_recipe=False,
                )
            )
            with pytest.raises(IntegrityError):
                external_db.commit()
            external_db.rollback()


def test_concurrent_duplicate_operations_allocate_distinct_names(
    postgres_sessions,
) -> None:
    with postgres_sessions() as db:
        user = User(
            id=uuid4(),
            email=f"duplicate-concurrency-{uuid4()}@example.test",
        )
        db.add(user)
        db.commit()

        source = FoodService(db).create_manual_food(
            user.id,
            FoodCreateRequest(
                name="Concurrent Oatmeal",
                serving_definitions=[
                    {
                        "label": "1 serving",
                        "quantity": "1",
                        "unit": "serving",
                        "gram_weight": "100",
                        "is_default": True,
                    }
                ],
                nutrients=[],
            ),
        )
        user_id = user.id
        source_id = source.id

    worker_count = 6
    start = Barrier(worker_count + 1)

    def duplicate_once():
        with postgres_sessions() as db:
            start.wait(timeout=10)
            return FoodService(db).duplicate_food(
                user_id,
                source_id,
                uuid4(),
            )

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = [
            pool.submit(duplicate_once)
            for _ in range(worker_count)
        ]
        start.wait(timeout=10)
        results = [
            future.result(timeout=20)
            for future in futures
        ]

    assert {result.name for result in results} == {
        "Concurrent Oatmeal Copy",
        "Concurrent Oatmeal Copy 2",
        "Concurrent Oatmeal Copy 3",
        "Concurrent Oatmeal Copy 4",
        "Concurrent Oatmeal Copy 5",
        "Concurrent Oatmeal Copy 6",
    }
    assert len({result.id for result in results}) == worker_count
    assert all(
        result.source_id == str(source_id)
        for result in results
    )
    assert all(
        result.source_kind == "duplicate"
        for result in results
    )

    with postgres_sessions() as db:
        stored_names = set(
            db.scalars(
                select(FoodItem.name).where(
                    FoodItem.user_id == user_id,
                    FoodItem.source_type == "manual",
                    FoodItem.source_id == str(source_id),
                    FoodItem.deleted_at.is_(None),
                )
            )
        )

    assert stored_names == {
        "Concurrent Oatmeal Copy",
        "Concurrent Oatmeal Copy 2",
        "Concurrent Oatmeal Copy 3",
        "Concurrent Oatmeal Copy 4",
        "Concurrent Oatmeal Copy 5",
        "Concurrent Oatmeal Copy 6",
    }
