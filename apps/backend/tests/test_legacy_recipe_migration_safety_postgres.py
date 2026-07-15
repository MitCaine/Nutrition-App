from __future__ import annotations

from importlib import import_module
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType
from uuid import UUID, uuid4

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection, Engine, create_engine, inspect, make_url, text


pytestmark = pytest.mark.postgres_concurrency

POSTGRES_URL = os.getenv(
    "NUTRITION_TEST_POSTGRES_URL",
    "postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app",
)

initial_migration = import_module("app.migrations.versions.0001_initial_schema")
snapshot_migration = import_module("app.migrations.versions.0002_snapshot_provenance_on_delete")
usda_migration = import_module("app.migrations.versions.0003_usda_source_identity")
recipe_migration = import_module("app.migrations.versions.0004_recipe_domain_foundation")
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _run_migration(connection: Connection, migration: ModuleType, direction: str) -> None:
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        getattr(migration, direction)()


def _run_alembic(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "NUTRITION_DEPLOYMENT_MODE": "test",
            "NUTRITION_DATABASE_URL": database_url,
        }
    )
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture()
def legacy_0003_engine() -> Engine:
    admin = create_engine(POSTGRES_URL, pool_pre_ping=True)
    try:
        with admin.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - depends on developer environment.
        admin.dispose()
        pytest.skip(f"PostgreSQL migration database unavailable: {exc}")

    schema = f"test_legacy_recipe_migration_{uuid4().hex}"
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    engine = create_engine(
        POSTGRES_URL,
        connect_args={"options": f"-csearch_path={schema}"},
        pool_pre_ping=True,
    )
    try:
        with engine.begin() as connection:
            _run_migration(connection, initial_migration, "upgrade")
            _run_migration(connection, snapshot_migration, "upgrade")
            _run_migration(connection, usda_migration, "upgrade")
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture()
def empty_postgres_schema() -> tuple[Engine, str]:
    admin = create_engine(POSTGRES_URL, pool_pre_ping=True)
    try:
        with admin.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - depends on developer environment.
        admin.dispose()
        pytest.skip(f"PostgreSQL migration database unavailable: {exc}")

    schema = f"test_alembic_baseline_{uuid4().hex}"
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    migration_url = (
        make_url(POSTGRES_URL)
        .update_query_dict({"options": f"-csearch_path={schema}"})
        .render_as_string(hide_password=False)
    )
    engine = create_engine(migration_url, pool_pre_ping=True)
    try:
        yield engine, migration_url
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _seed_legacy_recipe(connection: Connection, *, include_ingredient: bool = True) -> dict[str, UUID]:
    ids = {
        "user": uuid4(),
        "recipe_food": uuid4(),
        "ingredient_food": uuid4(),
        "serving": uuid4(),
        "recipe": uuid4(),
        "ingredient": uuid4(),
    }
    connection.execute(
        text("INSERT INTO users (id, email, display_name) VALUES (:id, :email, :display_name)"),
        {
            "id": ids["user"],
            "email": f"legacy-recipe-{ids['user']}@example.test",
            "display_name": "Legacy Recipe Owner",
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO food_items (id, user_id, name, source_type, is_recipe)
            VALUES
                (:recipe_food_id, :user_id, 'Legacy Vegetable Soup', 'recipe', true),
                (:ingredient_food_id, :user_id, 'Legacy Diced Tomatoes', 'manual', false)
            """
        ),
        {
            "recipe_food_id": ids["recipe_food"],
            "ingredient_food_id": ids["ingredient_food"],
            "user_id": ids["user"],
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO serving_definitions
                (id, food_item_id, label, quantity, unit, gram_weight, is_default, source)
            VALUES
                (:id, :food_item_id, '1 cup diced', 1, 'cup', 180, true, 'manual')
            """
        ),
        {"id": ids["serving"], "food_item_id": ids["ingredient_food"]},
    )
    connection.execute(
        text(
            """
            INSERT INTO recipes
                (id, food_item_id, user_id, serving_count, final_yield_quantity,
                 final_yield_unit, instructions)
            VALUES
                (:id, :food_item_id, :user_id, 6, 6, 'serving',
                 'Combine ingredients and simmer for 30 minutes.')
            """
        ),
        {
            "id": ids["recipe"],
            "food_item_id": ids["recipe_food"],
            "user_id": ids["user"],
        },
    )
    if include_ingredient:
        connection.execute(
            text(
                """
                INSERT INTO recipe_ingredients
                    (id, recipe_id, ingredient_food_item_id, quantity, unit,
                     serving_definition_id, gram_amount, preparation_note, sort_order)
                VALUES
                    (:id, :recipe_id, :food_item_id, 2, 'cup', :serving_id,
                     360, 'drained', 0)
                """
            ),
            {
                "id": ids["ingredient"],
                "recipe_id": ids["recipe"],
                "food_item_id": ids["ingredient_food"],
                "serving_id": ids["serving"],
            },
        )
    return ids


@pytest.mark.parametrize("include_ingredient", [False, True])
def test_populated_legacy_recipe_tables_fail_before_destructive_ddl_and_preserve_rows(
    legacy_0003_engine: Engine,
    include_ingredient: bool,
) -> None:
    with legacy_0003_engine.begin() as connection:
        ids = _seed_legacy_recipe(connection, include_ingredient=include_ingredient)

    migration_error: RuntimeError | None = None
    try:
        with legacy_0003_engine.begin() as connection:
            _run_migration(connection, recipe_migration, "upgrade")
    except RuntimeError as exc:
        migration_error = exc

    with legacy_0003_engine.connect() as connection:
        inspector = inspect(connection)
        table_names = set(inspector.get_table_names())
        recipe_columns = {column["name"] for column in inspector.get_columns("recipes")}
        ingredient_columns = {
            column["name"] for column in inspector.get_columns("recipe_ingredients")
        }
        recipe_rows = []
        if "food_item_id" in recipe_columns:
            recipe_rows = connection.execute(
                text(
                    """
                    SELECT id, food_item_id, user_id, serving_count, final_yield_quantity,
                           final_yield_unit, instructions
                    FROM recipes
                    """
                )
            ).mappings().all()
        ingredient_rows = []
        if "ingredient_food_item_id" in ingredient_columns:
            ingredient_rows = connection.execute(
                text(
                    """
                    SELECT id, recipe_id, ingredient_food_item_id, quantity, unit,
                           serving_definition_id, gram_amount, preparation_note, sort_order
                    FROM recipe_ingredients
                    """
                )
            ).mappings().all()

    assert migration_error is not None, (
        "0004 completed against populated legacy tables; "
        f"tables={sorted(table_names)}, recipe_rows={len(recipe_rows)}, "
        f"ingredient_rows={len(ingredient_rows)}, "
        f"legacy_recipe_columns_present={'food_item_id' in recipe_columns}, "
        f"legacy_ingredient_columns_present={'ingredient_food_item_id' in ingredient_columns}"
    )
    assert "historical Recipe conversion is required" in str(migration_error)
    assert {"recipes", "recipe_ingredients"} <= table_names
    assert "recipes_legacy" not in table_names
    assert "recipe_ingredients_legacy" not in table_names
    assert "food_item_id" in recipe_columns
    assert "ingredient_food_item_id" in ingredient_columns
    assert recipe_rows == [
        {
            "id": ids["recipe"],
            "food_item_id": ids["recipe_food"],
            "user_id": ids["user"],
            "serving_count": 6,
            "final_yield_quantity": 6,
            "final_yield_unit": "serving",
            "instructions": "Combine ingredients and simmer for 30 minutes.",
        }
    ]
    expected_ingredients = []
    if include_ingredient:
        expected_ingredients.append(
            {
                "id": ids["ingredient"],
                "recipe_id": ids["recipe"],
                "ingredient_food_item_id": ids["ingredient_food"],
                "quantity": 2,
                "unit": "cup",
                "serving_definition_id": ids["serving"],
                "gram_amount": 360,
                "preparation_note": "drained",
                "sort_order": 0,
            }
        )
    assert ingredient_rows == expected_ingredients


def test_empty_legacy_recipe_tables_upgrade_successfully(legacy_0003_engine: Engine) -> None:
    with legacy_0003_engine.begin() as connection:
        _run_migration(connection, recipe_migration, "upgrade")

    with legacy_0003_engine.connect() as connection:
        table_names = set(inspect(connection).get_table_names())
        recipe_columns = {column["name"] for column in inspect(connection).get_columns("recipes")}

    assert {"recipes", "recipe_ingredients"} <= table_names
    assert "recipes_legacy" not in table_names
    assert "recipe_ingredients_legacy" not in table_names
    assert {"name", "published_food_item_id", "serving_count_yield"} <= recipe_columns
    assert "food_item_id" not in recipe_columns


def test_empty_0004_downgrade_and_reupgrade_remain_valid(legacy_0003_engine: Engine) -> None:
    with legacy_0003_engine.begin() as connection:
        _run_migration(connection, recipe_migration, "upgrade")
        _run_migration(connection, recipe_migration, "downgrade")

        legacy_columns = {column["name"] for column in inspect(connection).get_columns("recipes")}
        assert {"food_item_id", "serving_count", "final_yield_quantity"} <= legacy_columns
        assert connection.scalar(text("SELECT count(*) FROM recipes")) == 0
        assert connection.scalar(text("SELECT count(*) FROM recipe_ingredients")) == 0

        _run_migration(connection, recipe_migration, "upgrade")
        current_columns = {column["name"] for column in inspect(connection).get_columns("recipes")}

    assert {"name", "published_food_item_id", "serving_count_yield"} <= current_columns
    assert "food_item_id" not in current_columns


def test_empty_baseline_upgrades_to_head_and_latest_revision_round_trips(
    empty_postgres_schema: tuple[Engine, str],
) -> None:
    engine, migration_url = empty_postgres_schema

    result = _run_alembic(migration_url, "upgrade", "head")

    assert result.returncode == 0, result.stderr
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0014_create_idempotency"
        )
        table_names = set(inspect(connection).get_table_names())
    assert {"recipes", "recipe_ingredients", "recipe_publication_revisions"} <= table_names

    downgrade = _run_alembic(migration_url, "downgrade", "-1")
    assert downgrade.returncode == 0, downgrade.stderr
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0013_food_recipe_integrity"
        )

    reupgrade = _run_alembic(migration_url, "upgrade", "head")
    assert reupgrade.returncode == 0, reupgrade.stderr
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0014_create_idempotency"
        )


def test_alembic_populated_0003_to_0004_failure_keeps_revision_and_rows(
    empty_postgres_schema: tuple[Engine, str],
) -> None:
    engine, migration_url = empty_postgres_schema
    upgrade_to_0003 = _run_alembic(migration_url, "upgrade", "0003_usda_source_identity")
    assert upgrade_to_0003.returncode == 0, upgrade_to_0003.stderr

    with engine.begin() as connection:
        ids = _seed_legacy_recipe(connection)

    blocked_upgrade = _run_alembic(migration_url, "upgrade", "0004_recipe_domain_foundation")

    assert blocked_upgrade.returncode != 0
    output = blocked_upgrade.stdout + blocked_upgrade.stderr
    assert "historical Recipe conversion is required" in output
    password = make_url(migration_url).password
    if password:
        assert password not in output

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0003_usda_source_identity"
        )
        assert connection.scalar(text("SELECT count(*) FROM recipes")) == 1
        assert connection.scalar(text("SELECT count(*) FROM recipe_ingredients")) == 1
        assert connection.scalar(text("SELECT id FROM recipes")) == ids["recipe"]
        assert connection.scalar(text("SELECT id FROM recipe_ingredients")) == ids["ingredient"]
        recipe_columns = {column["name"] for column in inspect(connection).get_columns("recipes")}
        ingredient_columns = {
            column["name"] for column in inspect(connection).get_columns("recipe_ingredients")
        }
    assert "food_item_id" in recipe_columns
    assert "ingredient_food_item_id" in ingredient_columns
