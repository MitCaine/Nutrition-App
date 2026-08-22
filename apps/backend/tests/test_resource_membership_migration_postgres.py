from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from importlib import import_module
from types import SimpleNamespace

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.autogenerate.api import compare_metadata
from psycopg import sql
import pytest
from sqlalchemy import Connection, create_engine, make_url, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool
from uuid import uuid4

from app.operators import phase5c4_roles as roles
from app.core.config import DeploymentMode, ProcessMode, Settings
from app.core.database import Base
from app.main import _admit_canary_startup
from app.migrations.schema_authority import build_alembic_metadata
from app.operators.resource_membership_contracts import (
    CHECK_CONSTRAINT_CONTRACTS,
    CONSTRAINT_MANIFEST_VERSION,
    CURRENT_RUNTIME_SCHEMA_REVISION,
    HISTORICAL_PHASE5_SCHEMA_REVISION,
    LOCAL_ADMISSION_VERSION,
    MIGRATION_LOCK_TIMEOUT,
    MIGRATION_STATEMENT_TIMEOUT,
    MIGRATION_TABLE_LOCK_MODE,
    MIGRATION_TABLE_LOCK_ORDER,
    PREFLIGHT_CATEGORIES,
    PROJECTION_REVISION_UNIQUE_INDEX,
    RETAINED_FOREIGN_KEY_CONTRACTS,
    SUPPORTING_INDEXES,
)
from app.operators.resource_membership_qualification import (
    ResourceMembershipQualificationError,
    _validate_current_prerequisites,
    collect_resource_membership_qualification,
    qualify_constraint_manifest,
)
from app.operators.resource_membership_preflight import (
    ResourceMembershipPreflightBlockedError,
    assert_no_blocking_findings,
)
from tests import test_phase5c4_prerequisites_postgres as historical_support
from tests import test_resource_membership_integrity as direct_write_contracts


pytestmark = pytest.mark.postgres_concurrency


_POST_0019_METADATA_COLUMNS = frozenset(
    {
        ("serving_definitions", "reference_gram_weight"),
        ("serving_definitions", "reference_quantity"),
        ("serving_definitions", "reference_unit"),
        ("user_profiles", "authoritative_time_zone"),
        ("user_profiles", "calendar_revision"),
    }
)
_POST_0019_METADATA_TABLES = frozenset(
    {
        "daily_log_day_completions",
        "phase5c_activation_runtime_commands",
        "phase5c_activation_schema_evidence",
    }
)
_POST_0019_METADATA_UNIQUE_CONSTRAINTS = frozenset(
    {
        ("food_nutrients", "uq_food_nutrients_food_nutrient_basis"),
    }
)


def _include_0019_schema_object(
    object_: object,
    name: str | None,
    type_: str,
    reflected: bool,
    _compare_to: object | None,
) -> bool:
    """Project current metadata onto the exact historical 0019 boundary."""

    if type_ == "table":
        if reflected and name == "phase5c_conversion_clone_marker":
            return False
        if not reflected and name in _POST_0019_METADATA_TABLES:
            return False
    if type_ == "column" and not reflected:
        table = getattr(object_, "table", None)
        identity = (getattr(table, "name", None), name)
        if identity in _POST_0019_METADATA_COLUMNS:
            return False
    if type_ == "unique_constraint" and not reflected:
        table = getattr(object_, "table", None)
        identity = (getattr(table, "name", None), name)
        if identity in _POST_0019_METADATA_UNIQUE_CONSTRAINTS:
            return False
    return True


def _upgrade_0019(database_url: str) -> None:
    migration = import_module(
        "app.migrations.versions.0019_resource_membership_integrity"
    )
    engine = create_engine(database_url, poolclass=NullPool, hide_parameters=True)
    try:
        with engine.connect() as connection:
            connection.execute(text(f"SET SESSION AUTHORIZATION {roles.MIGRATOR_ROLE}"))
            roles.assume_migration_owner(connection)
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                migration.upgrade()
            connection.execute(
                text("UPDATE public.alembic_version SET version_num = :revision"),
                {"revision": CURRENT_RUNTIME_SCHEMA_REVISION},
            )
            connection.commit()
    finally:
        engine.dispose()


@contextmanager
def _clone_target(
    target: historical_support.TargetDatabase,
) -> Generator[historical_support.TargetDatabase, None, None]:
    root = make_url(target.admin_url)
    source_name = str(root.database)
    database_name = f"test_phase5c4_membership_{uuid4().hex}"
    control = create_engine(
        root.set(database="postgres").render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
        hide_parameters=True,
    )
    try:
        with control.connect() as connection:
            raw = connection.connection.driver_connection
            with raw.cursor() as cursor:
                cursor.execute(
                    sql.SQL("CREATE DATABASE {} WITH TEMPLATE {} OWNER {}").format(
                        sql.Identifier(database_name),
                        sql.Identifier(source_name),
                        sql.Identifier(roles.OWNER_ROLE),
                    )
                )
                cursor.execute(
                    sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(
                        sql.Identifier(database_name)
                    )
                )
                cursor.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                        sql.Identifier(database_name),
                        sql.SQL(", ").join(
                            sql.Identifier(role)
                            for role in (
                                roles.MIGRATOR_ROLE,
                                roles.CANARY_ROLE,
                                roles.QUALIFIER_ROLE,
                                roles.OPS_ROLE,
                            )
                        ),
                    )
                )
        cloned_admin_url = root.set(database=database_name).render_as_string(
            hide_password=False
        )
        clone_engine = create_engine(
            cloned_admin_url,
            poolclass=NullPool,
            hide_parameters=True,
        )
        try:
            with clone_engine.begin() as connection:
                connection.execute(
                    text(f"SET SESSION AUTHORIZATION {roles.MIGRATOR_ROLE}")
                )
                roles.assume_migration_owner(connection)
                roles.install_revision_maintenance_policy(
                    connection,
                    roles.PROMOTION_PREREQUISITES_REVISION,
                )
        finally:
            clone_engine.dispose()
        yield historical_support.TargetDatabase(
            admin_url=cloned_admin_url,
            archive_identity=target.archive_identity,
            clone_marker_digest=target.clone_marker_digest,
            conversion_clone_identity_digest=(
                target.conversion_clone_identity_digest
            ),
            conversion_run_id=target.conversion_run_id,
            canary_user_id=target.canary_user_id,
            canary_user_email=target.canary_user_email,
        )
    finally:
        with control.connect() as connection:
            raw = connection.connection.driver_connection
            with raw.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )
        control.dispose()


def _initialize_closed_fence(target: historical_support.TargetDatabase) -> None:
    engine = target.engine()
    try:
        with engine.connect() as connection:
            connection.execute(text(f"SET SESSION AUTHORIZATION {roles.MIGRATOR_ROLE}"))
            roles.assume_migration_owner(connection)
            connection.execute(
                text(
                    "UPDATE public.phase5c_conversion_runs "
                    "SET execution_state = 'completed', verification_state = 'verified'"
                )
            )
            connection.commit()
    finally:
        engine.dispose()
    with target.connect_as(roles.OPS_ROLE) as connection:
        connection.execute(
            text(
                "SELECT public.phase5c_initialize_promotion_target("
                "CAST(:command AS uuid), :archive, CAST(:run AS uuid), :marker, :clone)"
            ),
            {
                "command": uuid4(),
                "archive": target.archive_identity,
                "run": target.conversion_run_id,
                "marker": target.clone_marker_digest,
                "clone": target.conversion_clone_identity_digest,
            },
        )
        connection.commit()
    ops = historical_support._engine_as(
        target,
        roles.OPS_ROLE,
        read_only=False,
    )
    try:
        closed = roles.close_runtime_maintenance(
            ops,
            quiet_period_seconds=0,
            drain_timeout_seconds=5,
            poll_interval_seconds=0.01,
        )
        assert closed["state"] == "maintenance"
    finally:
        ops.dispose()


def _set_role_password_and_url(
    target: historical_support.TargetDatabase,
    role: str,
) -> str:
    password = f"resource-membership-{role}"
    engine = target.engine()
    try:
        with engine.begin() as connection:
            raw = connection.connection.driver_connection
            with raw.cursor() as cursor:
                cursor.execute(
                    sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                        sql.Identifier(role),
                        sql.Literal(password),
                    )
                )
    finally:
        engine.dispose()
    return make_url(target.admin_url).set(
        username=role,
        password=password,
    ).render_as_string(hide_password=False)


def _owner_execute(
    target: historical_support.TargetDatabase,
    statement: str,
) -> None:
    engine = target.engine()
    try:
        with engine.begin() as connection:
            connection.execute(text(f"SET SESSION AUTHORIZATION {roles.MIGRATOR_ROLE}"))
            roles.assume_migration_owner(connection)
            connection.execute(text(statement))
    finally:
        engine.dispose()


def _user(connection: Connection, label: str):
    identifier = uuid4()
    connection.execute(
        text("INSERT INTO public.users (id, email) VALUES (:id, :email)"),
        {"id": identifier, "email": f"membership-{label}-{identifier}@example.test"},
    )
    return identifier


def _food(
    connection: Connection,
    user_id,
    label: str,
    *,
    revision_id=None,
    recipe_id=None,
    deleted: bool = False,
):
    identifier = uuid4()
    source_type = "recipe" if recipe_id is not None else "manual"
    connection.execute(
        text(
            "INSERT INTO public.food_items ("
            "id, user_id, name, source_type, source_id, "
            "recipe_publication_revision_id, is_recipe, deleted_at) VALUES ("
            ":id, :user_id, :name, :source_type, :source_id, :revision_id, "
            ":is_recipe, CASE WHEN :deleted THEN clock_timestamp() ELSE NULL END)"
        ),
        {
            "id": identifier,
            "user_id": user_id,
            "name": label,
            "source_type": source_type,
            "source_id": None if recipe_id is None else str(recipe_id),
            "revision_id": revision_id,
            "is_recipe": recipe_id is not None,
            "deleted": deleted,
        },
    )
    return identifier


def _recipe(connection: Connection, user_id, label: str):
    identifier = uuid4()
    connection.execute(
        text(
            "INSERT INTO public.recipes (id, user_id, name, needs_republish) "
            "VALUES (:id, :user_id, :name, false)"
        ),
        {"id": identifier, "user_id": user_id, "name": label},
    )
    return identifier


def _revision(connection: Connection, recipe_id, user_id, number: int = 1):
    identifier = uuid4()
    connection.execute(
        text(
            "INSERT INTO public.recipe_publication_revisions ("
            "id, recipe_id, user_id, revision_number, creation_origin, "
            "provenance_confidence, published_name, content_digest) VALUES ("
            ":id, :recipe_id, :user_id, :number, 'normal_publication', "
            "'complete', :name, :digest)"
        ),
        {
            "id": identifier,
            "recipe_id": recipe_id,
            "user_id": user_id,
            "number": number,
            "name": f"Revision {number}",
            "digest": f"revision-{identifier}",
        },
    )
    return identifier


def _amount(connection: Connection, revision_id):
    identifier = uuid4()
    connection.execute(
        text(
            "INSERT INTO public.recipe_publication_amount_definitions ("
            "id, revision_id, display_order, display_label, semantic_mode, "
            "display_quantity, display_unit, gram_equivalent, is_default) VALUES ("
            ":id, :revision_id, 0, '1 serving', 'serving', 1, 'serving', 100, true)"
        ),
        {"id": identifier, "revision_id": revision_id},
    )
    return identifier


def _serving(connection: Connection, food_id):
    identifier = uuid4()
    connection.execute(
        text(
            "INSERT INTO public.serving_definitions ("
            "id, food_item_id, label, quantity, unit, gram_weight, is_default, "
            "source, is_user_confirmed) VALUES ("
            ":id, :food_id, '1 portion', 1, 'portion', 100, true, 'manual', true)"
        ),
        {"id": identifier, "food_id": food_id},
    )
    return identifier


def _food_nutrient(connection: Connection, food_id, nutrient_id: str = "calories"):
    identifier = uuid4()
    connection.execute(
        text(
            "INSERT INTO public.food_nutrients ("
            "id, food_item_id, nutrient_id, amount, unit, basis, data_status, "
            "source, is_user_confirmed) VALUES ("
            ":id, :food_id, :nutrient_id, 100, :unit, 'per_100g', 'known', "
            "'manual', true)"
        ),
        {
            "id": identifier,
            "food_id": food_id,
            "nutrient_id": nutrient_id,
            "unit": "kcal" if nutrient_id == "calories" else "g",
        },
    )
    return identifier


def _log(
    connection: Connection,
    user_id,
    food_id,
    *,
    serving_id=None,
    revision_id=None,
    amount_id=None,
):
    identifier = uuid4()
    connection.execute(
        text(
            "INSERT INTO public.daily_logs ("
            "id, user_id, food_item_id, food_name_snapshot, logged_date, "
            "amount_quantity, amount_unit, serving_definition_id, "
            "recipe_publication_revision_id, "
            "recipe_publication_amount_definition_id, gram_amount) VALUES ("
            ":id, :user_id, :food_id, 'Historical', DATE '2026-07-21', 1, "
            ":unit, :serving_id, :revision_id, :amount_id, 100)"
        ),
        {
            "id": identifier,
            "user_id": user_id,
            "food_id": food_id,
            "unit": "serving" if serving_id is not None else "g",
            "serving_id": serving_id,
            "revision_id": revision_id,
            "amount_id": amount_id,
        },
    )
    return identifier


def _snapshot(
    connection: Connection,
    log_id,
    food_id,
    *,
    nutrient_id: str = "calories",
    food_nutrient_id=None,
    serving_id=None,
):
    identifier = uuid4()
    connection.execute(
        text(
            "INSERT INTO public.daily_log_nutrient_snapshots ("
            "id, daily_log_id, source_food_item_id, source_food_nutrient_id, "
            "serving_definition_id, nutrient_id, amount, unit, data_status, "
            "consumed_amount_quantity, consumed_amount_unit, consumed_gram_amount) "
            "VALUES (:id, :log_id, :food_id, :food_nutrient_id, :serving_id, "
            ":nutrient_id, 100, :unit, 'known', 1, 'g', 100)"
        ),
        {
            "id": identifier,
            "log_id": log_id,
            "food_id": food_id,
            "food_nutrient_id": food_nutrient_id,
            "serving_id": serving_id,
            "nutrient_id": nutrient_id,
            "unit": "kcal" if nutrient_id == "calories" else "g",
        },
    )
    return identifier


def _ingredient(connection: Connection, recipe_id, food_id, *, serving_id=None):
    identifier = uuid4()
    connection.execute(
        text(
            "INSERT INTO public.recipe_ingredients ("
            "id, recipe_id, food_item_id, position, amount_quantity, amount_unit, "
            "serving_definition_id, resolved_gram_amount) VALUES ("
            ":id, :recipe_id, :food_id, 0, 1, :unit, :serving_id, 100)"
        ),
        {
            "id": identifier,
            "recipe_id": recipe_id,
            "food_id": food_id,
            "unit": "serving" if serving_id is not None else "g",
            "serving_id": serving_id,
        },
    )
    return identifier


def _publication(connection: Connection, user_id, label: str):
    recipe_id = _recipe(connection, user_id, label)
    revision_id = _revision(connection, recipe_id, user_id)
    amount_id = _amount(connection, revision_id)
    projection_id = _food(
        connection,
        user_id,
        f"{label} projection",
        revision_id=revision_id,
        recipe_id=recipe_id,
    )
    connection.execute(
        text(
            "UPDATE public.recipes SET published_food_item_id = :food_id, "
            "active_publication_revision_id = :revision_id WHERE id = :recipe_id"
        ),
        {
            "food_id": projection_id,
            "revision_id": revision_id,
            "recipe_id": recipe_id,
        },
    )
    return recipe_id, revision_id, amount_id, projection_id


def _seed_corruption(
    target: historical_support.TargetDatabase,
    category: str,
) -> None:
    engine = target.engine()
    try:
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            owner = _user(connection, f"{category}-owner")
            other = _user(connection, f"{category}-other")

            if category == "recipe_ingredient_owner_mismatch":
                _ingredient(
                    connection,
                    _recipe(connection, owner, "Owned recipe"),
                    _food(connection, other, "Foreign food"),
                )
            elif category == "recipe_ingredient_serving_food_mismatch":
                food = _food(connection, owner, "Ingredient food")
                other_food = _food(connection, owner, "Serving food")
                _ingredient(
                    connection,
                    _recipe(connection, owner, "Serving recipe"),
                    food,
                    serving_id=_serving(connection, other_food),
                )
            elif category == "daily_log_food_owner_mismatch":
                _log(connection, owner, _food(connection, other, "Foreign log food"))
            elif category == "daily_log_serving_food_mismatch":
                food = _food(connection, owner, "Log food")
                other_food = _food(connection, owner, "Other serving food")
                _log(
                    connection,
                    owner,
                    food,
                    serving_id=_serving(connection, other_food),
                )
            elif category == "daily_log_publication_links_unpaired":
                # 0018 already carries this check. This isolated drift fixture
                # removes it only to prove the preflight fails closed if an
                # externally corrupted exact-revision database is presented.
                connection.execute(
                    text(
                        "ALTER TABLE public.daily_logs DROP CONSTRAINT "
                        "ck_daily_logs_publication_links_paired"
                    )
                )
                _, revision, _, projection = _publication(
                    connection, owner, "Unpaired log"
                )
                _log(connection, owner, projection, revision_id=revision)
            elif category == "daily_log_revision_owner_mismatch":
                foreign_recipe = _recipe(connection, other, "Foreign revision recipe")
                revision = _revision(connection, foreign_recipe, other)
                amount = _amount(connection, revision)
                _log(
                    connection,
                    owner,
                    _food(connection, owner, "Owned mutable food"),
                    revision_id=revision,
                    amount_id=amount,
                )
            elif category == "daily_log_amount_revision_mismatch":
                recipe, revision, _, projection = _publication(
                    connection, owner, "Amount mismatch"
                )
                other_revision = _revision(connection, recipe, owner, 2)
                _log(
                    connection,
                    owner,
                    projection,
                    revision_id=revision,
                    amount_id=_amount(connection, other_revision),
                )
            elif category == "daily_log_revision_recipe_projection_mismatch":
                _, _, _, projection = _publication(
                    connection, owner, "Logged projection"
                )
                other_recipe = _recipe(connection, owner, "Other revision recipe")
                other_revision = _revision(connection, other_recipe, owner)
                _log(
                    connection,
                    owner,
                    projection,
                    revision_id=other_revision,
                    amount_id=_amount(connection, other_revision),
                )
            elif category == "recipe_projection_owner_mismatch":
                recipe = _recipe(connection, owner, "Cross-owner projection")
                revision = _revision(connection, recipe, owner)
                projection = _food(
                    connection,
                    other,
                    "Foreign projection",
                    revision_id=revision,
                    recipe_id=recipe,
                )
                connection.execute(
                    text(
                        "UPDATE public.recipes SET published_food_item_id = :food, "
                        "active_publication_revision_id = :revision WHERE id = :recipe"
                    ),
                    {"food": projection, "revision": revision, "recipe": recipe},
                )
            elif category == "recipe_projection_missing_active_revision":
                recipe = _recipe(connection, owner, "Missing active revision")
                projection = _food(
                    connection,
                    owner,
                    "Unlinked projection",
                    recipe_id=recipe,
                )
                connection.execute(
                    text(
                        "UPDATE public.recipes SET published_food_item_id = :food "
                        "WHERE id = :recipe"
                    ),
                    {"food": projection, "recipe": recipe},
                )
            elif category == "recipe_projection_active_revision_mismatch":
                recipe = _recipe(connection, owner, "Revision mismatch")
                first = _revision(connection, recipe, owner, 1)
                second = _revision(connection, recipe, owner, 2)
                projection = _food(
                    connection,
                    owner,
                    "Wrong revision projection",
                    revision_id=second,
                    recipe_id=recipe,
                )
                connection.execute(
                    text(
                        "UPDATE public.recipes SET published_food_item_id = :food, "
                        "active_publication_revision_id = :revision WHERE id = :recipe"
                    ),
                    {"food": projection, "revision": first, "recipe": recipe},
                )
            elif category == "recipe_projection_source_identity_mismatch":
                _, _, _, projection = _publication(
                    connection, owner, "Source mismatch"
                )
                connection.execute(
                    text(
                        "UPDATE public.food_items SET source_type = 'manual', "
                        "source_id = NULL, is_recipe = false WHERE id = :food"
                    ),
                    {"food": projection},
                )
            elif category == "projection_revision_duplicate":
                recipe, revision, _, _ = _publication(
                    connection, owner, "Duplicate revision"
                )
                _food(
                    connection,
                    owner,
                    "Duplicate projection",
                    revision_id=revision,
                    recipe_id=uuid4(),
                )
            elif category == "projection_revision_without_recipe_backlink":
                recipe = _recipe(connection, owner, "Orphan projection")
                revision = _revision(connection, recipe, owner)
                _food(
                    connection,
                    owner,
                    "Orphan projection food",
                    revision_id=revision,
                    recipe_id=recipe,
                )
            elif category == "ocr_trace_food_owner_mismatch":
                food = _food(connection, owner, "OCR food")
                connection.execute(
                    text(
                        "INSERT INTO public.ocr_nutrition_confirmation_traces ("
                        "id, user_id, food_item_id, parser_version, image_source_type, "
                        "schema_version, trace_snapshot, client_request_id, "
                        "request_fingerprint) VALUES ("
                        ":id, :user_id, :food_id, 'v1', 'upload', 'v1', "
                        "CAST('{}' AS json), :request_id, :fingerprint)"
                    ),
                    {
                        "id": uuid4(),
                        "user_id": other,
                        "food_id": food,
                        "request_id": uuid4(),
                        "fingerprint": "ocr-owner-mismatch",
                    },
                )
            elif category == "log_snapshot_source_food_mismatch":
                food = _food(connection, owner, "Logged food")
                source = _food(connection, owner, "Wrong source food")
                _snapshot(connection, _log(connection, owner, food), source)
            elif category == "log_snapshot_source_nutrient_food_mismatch":
                food = _food(connection, owner, "Snapshot food")
                other_food = _food(connection, owner, "Nutrient food")
                nutrient = _food_nutrient(connection, other_food)
                _snapshot(
                    connection,
                    _log(connection, owner, food),
                    food,
                    food_nutrient_id=nutrient,
                )
            elif category == "log_snapshot_source_nutrient_identity_mismatch":
                food = _food(connection, owner, "Identity food")
                nutrient = _food_nutrient(connection, food, "calories")
                _snapshot(
                    connection,
                    _log(connection, owner, food),
                    food,
                    nutrient_id="protein",
                    food_nutrient_id=nutrient,
                )
            elif category == "log_snapshot_serving_food_mismatch":
                food = _food(connection, owner, "Snapshot serving food")
                other_food = _food(connection, owner, "Other snapshot serving")
                _snapshot(
                    connection,
                    _log(connection, owner, food),
                    food,
                    serving_id=_serving(connection, other_food),
                )
            else:  # pragma: no cover - frozen contract assertion.
                raise AssertionError(category)
    finally:
        engine.dispose()


def _table_root(connection: Connection, table_name: str, *, omit_user_id: bool = False):
    document = "pg_catalog.to_jsonb(row_value)"
    if omit_user_id:
        document += " - 'user_id'"
    return tuple(
        connection.execute(
            text(
                f"SELECT count(*), pg_catalog.md5(COALESCE("
                f"pg_catalog.string_agg(({document})::text, E'\\n' "
                f"ORDER BY ({document})::text), '')) "
                f"FROM public.{table_name} AS row_value"
            )
        ).one()
    )


def _seed_valid_historical_graph(target: historical_support.TargetDatabase):
    engine = target.engine()
    try:
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            owner = _user(connection, "historical-owner")
            ingredient_food = _food(connection, owner, "Historical ingredient food")
            ingredient_serving = _serving(connection, ingredient_food)
            recipe_id, revision_id, amount_id, projection_id = _publication(
                connection,
                owner,
                "Historical publication",
            )
            ingredient_id = _ingredient(
                connection,
                recipe_id,
                ingredient_food,
                serving_id=ingredient_serving,
            )
            projection_serving = _serving(connection, projection_id)
            source_nutrient = _food_nutrient(connection, projection_id)
            connection.execute(
                text(
                    "INSERT INTO public.recipe_publication_nutrients ("
                    "id, revision_id, nutrient_id, amount, unit, basis, data_status) "
                    "VALUES (:id, :revision, 'calories', 100, 'kcal', "
                    "'per_serving', 'known')"
                ),
                {"id": uuid4(), "revision": revision_id},
            )
            log_id = _log(
                connection,
                owner,
                projection_id,
                serving_id=projection_serving,
                revision_id=revision_id,
                amount_id=amount_id,
            )
            _snapshot(
                connection,
                log_id,
                projection_id,
                food_nutrient_id=source_nutrient,
                serving_id=projection_serving,
            )
            connection.execute(
                text(
                    "INSERT INTO public.ocr_nutrition_confirmation_traces ("
                    "id, user_id, food_item_id, parser_version, image_source_type, "
                    "schema_version, trace_snapshot, client_request_id, "
                    "request_fingerprint) VALUES ("
                    ":id, :owner, :food, 'v1', 'upload', 'v1', "
                    "CAST('{}' AS json), :request, 'historical-trace')"
                ),
                {
                    "id": uuid4(),
                    "owner": owner,
                    "food": projection_id,
                    "request": uuid4(),
                },
            )
            unchanged_tables = (
                "daily_log_nutrient_snapshots",
                "daily_logs",
                "food_items",
                "food_nutrients",
                "ocr_nutrition_confirmation_traces",
                "recipe_publication_amount_definitions",
                "recipe_publication_nutrients",
                "recipe_publication_revisions",
                "recipes",
                "serving_definitions",
            )
            roots = {
                table_name: _table_root(connection, table_name)
                for table_name in unchanged_tables
            }
            roots["recipe_ingredients_without_new_owner"] = _table_root(
                connection,
                "recipe_ingredients",
                omit_user_id=True,
            )
        return owner, ingredient_id, roots
    finally:
        engine.dispose()


def _current_prerequisites(target: historical_support.TargetDatabase):
    with target.connect_as(roles.QUALIFIER_ROLE) as connection:
        raw = connection.scalar(
            text("SELECT public.phase5c_read_qualifier_evidence_v2()")
        )
        connection.rollback()
    return _validate_current_prerequisites(raw)


def _local_integrity_valid(target: historical_support.TargetDatabase) -> bool:
    with target.connect_as(roles.CANARY_ROLE) as connection:
        return bool(
            connection.scalar(
                text(
                    "SELECT resource_membership_integrity_valid "
                    "FROM public.phase5c_local_admission_v2()"
                )
            )
        )


def _open_runtime_writes(target: historical_support.TargetDatabase) -> None:
    _restore_runtime_access(target)
    prerequisites = _current_prerequisites(target)
    with target.connect_as(roles.OPS_ROLE) as connection:
        connection.execute(
            text(
                "SELECT public.phase5c_transition_closed_write_fence("
                "CAST(:target AS uuid), CAST(:command AS uuid), :epoch, :mode, "
                ":last, 'closed_cutover')"
            ),
            {
                "target": prerequisites.identity["target_instance_id"],
                "command": uuid4(),
                "epoch": prerequisites.state["epoch"],
                "mode": prerequisites.state["mode"],
                "last": prerequisites.state["last_event_digest"],
            },
        )
        connection.commit()
    historical_support._force_owner_fence_event(
        target,
        _current_prerequisites(target),
        to_mode="open_production",
    )


def _restore_runtime_access(target: historical_support.TargetDatabase) -> None:
    ops = historical_support._engine_as(
        target,
        roles.OPS_ROLE,
        read_only=False,
    )
    try:
        restored = roles.restore_runtime_privileges(ops)
        assert restored["state"] == "normal"
    finally:
        ops.dispose()


def _open_historical_writes(target: historical_support.TargetDatabase) -> None:
    prerequisites = historical_support._read_qualifier_evidence(target)
    with target.connect_as(roles.OPS_ROLE) as connection:
        connection.execute(
            text(
                "SELECT public.phase5c_transition_closed_write_fence("
                "CAST(:target AS uuid), CAST(:command AS uuid), :epoch, :mode, "
                ":last, 'closed_cutover')"
            ),
            {
                "target": prerequisites.identity["target_instance_id"],
                "command": uuid4(),
                "epoch": prerequisites.state["epoch"],
                "mode": prerequisites.state["mode"],
                "last": prerequisites.state["last_event_digest"],
            },
        )
        connection.commit()
    historical_support._force_owner_fence_event(
        target,
        historical_support._read_qualifier_evidence(target),
        to_mode="open_production",
    )


@pytest.fixture(scope="module")
def phase5_baseline() -> Generator[historical_support.TargetDatabase, None, None]:
    baseline = historical_support.target_database.__wrapped__()
    target = next(baseline)
    try:
        _initialize_closed_fence(target)
        yield target
    finally:
        try:
            next(baseline)
        except StopIteration:
            pass


@pytest.fixture(scope="module")
def membership_database(
    phase5_baseline: historical_support.TargetDatabase,
) -> Generator[historical_support.TargetDatabase, None, None]:
    with _clone_target(phase5_baseline) as target:
        _upgrade_0019(target.admin_url)
        ops = historical_support._engine_as(
            target,
            roles.OPS_ROLE,
            read_only=False,
        )
        try:
            assert roles.restore_runtime_privileges(ops)["state"] == "normal"
        finally:
            ops.dispose()
        yield target


@pytest.fixture(scope="module")
def open_membership_database(
    phase5_baseline: historical_support.TargetDatabase,
) -> Generator[historical_support.TargetDatabase, None, None]:
    with _clone_target(phase5_baseline) as target:
        _upgrade_0019(target.admin_url)
        _open_runtime_writes(target)
        yield target


@pytest.fixture
def postgres_membership_session(
    open_membership_database: historical_support.TargetDatabase,
) -> Generator[Session, None, None]:
    engine = historical_support._engine_as(
        open_membership_database,
        roles.RUNTIME_ROLE,
        read_only=False,
    )
    try:
        with engine.connect() as connection:
            outer_transaction = connection.begin()
            try:
                with Session(
                    bind=connection,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    yield session
                    session.rollback()
            finally:
                outer_transaction.rollback()
        verification_engine = open_membership_database.engine()
        try:
            with verification_engine.connect() as verification:
                verification.execute(text("SET TRANSACTION READ ONLY"))
                report = assert_no_blocking_findings(
                    verification,
                    observed_schema_revision=CURRENT_RUNTIME_SCHEMA_REVISION,
                    read_only=True,
                )
                assert report.to_dict()["blocking_row_count"] == 0
                verification.rollback()
        finally:
            verification_engine.dispose()
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "category",
    [item.code for item in PREFLIGHT_CATEGORIES],
)
def test_each_blocking_preflight_category_aborts_without_partial_schema(
    phase5_baseline: historical_support.TargetDatabase,
    category: str,
) -> None:
    with _clone_target(phase5_baseline) as target:
        _seed_corruption(target, category)

        with pytest.raises(ResourceMembershipPreflightBlockedError) as rejected:
            _upgrade_0019(target.admin_url)

        category_row = next(
            item
            for item in rejected.value.report.to_dict()["category_counts"]
            if item["category"] == category
        )
        assert category_row["count"] > 0
        engine = target.engine()
        try:
            with engine.connect() as connection:
                assert connection.scalar(
                    text("SELECT version_num FROM public.alembic_version")
                ) == "0018_phase5c_promotion_prerequisites"
                assert connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_catalog.pg_attribute "
                        "WHERE attrelid = 'public.recipe_ingredients'::regclass "
                        "AND attname = 'user_id' AND NOT attisdropped"
                    )
                ) == 0
                assert connection.scalar(
                    text(
                        "SELECT pg_catalog.to_regclass("
                        "'public.uq_food_items_publication_revision_projection')"
                    )
                ) is None
                assert connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_catalog.pg_constraint "
                        "WHERE connamespace = 'public'::regnamespace "
                        "AND conname LIKE 'fk_log_snapshots_%_food%'"
                    )
                ) == 0
        finally:
            engine.dispose()


def test_migration_lock_contract_is_exact_and_bounded() -> None:
    assert MIGRATION_LOCK_TIMEOUT == "5s"
    assert MIGRATION_STATEMENT_TIMEOUT == "15min"
    assert MIGRATION_TABLE_LOCK_MODE == "SHARE ROW EXCLUSIVE"
    assert MIGRATION_TABLE_LOCK_ORDER == (
        "daily_logs",
        "food_items",
        "recipes",
        "recipe_publication_revisions",
        "recipe_publication_amount_definitions",
        "serving_definitions",
        "food_nutrients",
        "recipe_ingredients",
        "daily_log_nutrient_snapshots",
        "ocr_nutrition_confirmation_traces",
    )


def test_migration_rejects_open_write_fence_before_schema_mutation(
    phase5_baseline: historical_support.TargetDatabase,
) -> None:
    with _clone_target(phase5_baseline) as target:
        _open_historical_writes(target)

        with pytest.raises(
            RuntimeError,
            match="resource_membership_migration_requires_closed_write_fence",
        ):
            _upgrade_0019(target.admin_url)

        with target.engine().connect() as connection:
            assert connection.scalar(
                text("SELECT version_num FROM public.alembic_version")
            ) == HISTORICAL_PHASE5_SCHEMA_REVISION
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM pg_catalog.pg_attribute "
                    "WHERE attrelid = 'public.recipe_ingredients'::regclass "
                    "AND attname = 'user_id' AND NOT attisdropped"
                )
            ) == 0


def test_migration_rejects_undrained_runtime_before_schema_mutation(
    phase5_baseline: historical_support.TargetDatabase,
) -> None:
    with _clone_target(phase5_baseline) as target:
        runtime_url = _set_role_password_and_url(target, roles.RUNTIME_ROLE)
        database_name = str(make_url(target.admin_url).database)
        admin = target.engine()
        quoted_database = admin.dialect.identifier_preparer.quote(database_name)
        runtime_engine = create_engine(
            runtime_url,
            poolclass=NullPool,
            hide_parameters=True,
        )
        try:
            with admin.begin() as connection:
                connection.execute(
                    text(
                        f"GRANT CONNECT ON DATABASE {quoted_database} "
                        "TO nutrition_runtime"
                    )
                )
            with runtime_engine.connect() as runtime_connection:
                runtime_connection.execute(text("SELECT 1"))
                with admin.begin() as connection:
                    connection.execute(
                        text(
                            f"REVOKE CONNECT ON DATABASE {quoted_database} "
                            "FROM nutrition_runtime"
                        )
                    )
                with pytest.raises(
                    RuntimeError,
                    match="resource_membership_migration_requires_drained_runtime",
                ):
                    _upgrade_0019(target.admin_url)
        finally:
            runtime_engine.dispose()
            admin.dispose()

        with target.engine().connect() as connection:
            assert connection.scalar(
                text("SELECT version_num FROM public.alembic_version")
            ) == HISTORICAL_PHASE5_SCHEMA_REVISION
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM pg_catalog.pg_attribute "
                    "WHERE attrelid = 'public.recipe_ingredients'::regclass "
                    "AND attname = 'user_id' AND NOT attisdropped"
                )
            ) == 0


def test_migration_lock_timeout_rolls_back_without_partial_schema(
    phase5_baseline: historical_support.TargetDatabase,
) -> None:
    with _clone_target(phase5_baseline) as target:
        blocker = target.engine()
        try:
            with blocker.connect() as blocking_connection:
                blocking_connection.execute(
                    text("LOCK TABLE public.daily_logs IN ACCESS EXCLUSIVE MODE")
                )
                with pytest.raises(DBAPIError) as rejected:
                    _upgrade_0019(target.admin_url)
                assert getattr(rejected.value.orig, "sqlstate", None) == "55P03"
                blocking_connection.rollback()
        finally:
            blocker.dispose()

        with target.engine().connect() as connection:
            assert connection.scalar(
                text("SELECT version_num FROM public.alembic_version")
            ) == HISTORICAL_PHASE5_SCHEMA_REVISION
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM pg_catalog.pg_attribute "
                    "WHERE attrelid = 'public.recipe_ingredients'::regclass "
                    "AND attname = 'user_id' AND NOT attisdropped"
                )
            ) == 0


def test_backfill_trigger_disable_is_rolled_back_if_failure_precedes_reenable(
    phase5_baseline: historical_support.TargetDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _clone_target(phase5_baseline) as target:
        with target.engine().connect() as connection:
            trigger_before = connection.execute(
                text(
                    "SELECT trigger_value.tgenabled, "
                    "pg_catalog.pg_get_triggerdef(trigger_value.oid, true) "
                    "FROM pg_catalog.pg_trigger AS trigger_value "
                    "WHERE trigger_value.tgrelid = "
                    "'public.recipe_ingredients'::regclass "
                    "AND trigger_value.tgname = 'phase5c_write_fence_gate'"
                )
            ).one()

        migration = import_module(
            "app.migrations.versions.0019_resource_membership_integrity"
        )
        original_execute = migration.op.execute

        def fail_after_backfill(statement, *args, **kwargs):
            result = original_execute(statement, *args, **kwargs)
            if isinstance(statement, str) and (
                "UPDATE public.recipe_ingredients AS ingredient" in statement
            ):
                raise RuntimeError("injected_after_owner_backfill")
            return result

        monkeypatch.setattr(migration.op, "execute", fail_after_backfill)
        with pytest.raises(RuntimeError, match="injected_after_owner_backfill"):
            _upgrade_0019(target.admin_url)

        with target.engine().connect() as connection:
            trigger_after = connection.execute(
                text(
                    "SELECT trigger_value.tgenabled, "
                    "pg_catalog.pg_get_triggerdef(trigger_value.oid, true) "
                    "FROM pg_catalog.pg_trigger AS trigger_value "
                    "WHERE trigger_value.tgrelid = "
                    "'public.recipe_ingredients'::regclass "
                    "AND trigger_value.tgname = 'phase5c_write_fence_gate'"
                )
            ).one()
            assert connection.scalar(
                text("SELECT version_num FROM public.alembic_version")
            ) == HISTORICAL_PHASE5_SCHEMA_REVISION
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM pg_catalog.pg_attribute "
                    "WHERE attrelid = 'public.recipe_ingredients'::regclass "
                    "AND attname = 'user_id' AND NOT attisdropped"
                )
            ) == 0

        assert trigger_before[0] == "O"
        assert trigger_after == trigger_before


_RETAINED_SCHEMA_DRIFT_CASES = (
    *(
        (contract.name, contract.child_table)
        for contract in RETAINED_FOREIGN_KEY_CONTRACTS
    ),
    *(
        (contract.name, contract.table)
        for contract in CHECK_CONSTRAINT_CONTRACTS
        if not contract.introduced_by_0019
    ),
)


@pytest.mark.parametrize(
    ("constraint_name", "table_name"),
    _RETAINED_SCHEMA_DRIFT_CASES,
    ids=[case[0] for case in _RETAINED_SCHEMA_DRIFT_CASES],
)
def test_retained_schema_drift_blocks_migration_before_ddl(
    phase5_baseline: historical_support.TargetDatabase,
    constraint_name: str,
    table_name: str,
) -> None:
    with _clone_target(phase5_baseline) as target:
        _owner_execute(
            target,
            f"ALTER TABLE public.{table_name} DROP CONSTRAINT {constraint_name}",
        )

        with pytest.raises(
            ResourceMembershipQualificationError,
            match="resource_membership_retained_schema_invalid",
        ):
            _upgrade_0019(target.admin_url)

        with target.engine().connect() as connection:
            assert connection.scalar(
                text("SELECT version_num FROM public.alembic_version")
            ) == HISTORICAL_PHASE5_SCHEMA_REVISION
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM pg_catalog.pg_attribute "
                    "WHERE attrelid = 'public.recipe_ingredients'::regclass "
                    "AND attname = 'user_id' AND NOT attisdropped"
                )
            ) == 0


@pytest.mark.parametrize(
    "legacy_case",
    ("paired_null_log", "soft_deleted_food", "nulled_provenance"),
)
def test_legacy_compatible_relationships_permit_migration(
    phase5_baseline: historical_support.TargetDatabase,
    legacy_case: str,
) -> None:
    with _clone_target(phase5_baseline) as target:
        engine = target.engine()
        try:
            with engine.begin() as connection:
                connection.execute(text("SET LOCAL session_replication_role = replica"))
                owner = _user(connection, legacy_case)
                food = _food(
                    connection,
                    owner,
                    legacy_case,
                    deleted=legacy_case == "soft_deleted_food",
                )
                log = _log(connection, owner, food)
                if legacy_case == "nulled_provenance":
                    _snapshot(
                        connection,
                        log,
                        food,
                        food_nutrient_id=None,
                        serving_id=None,
                    )
        finally:
            engine.dispose()

        _upgrade_0019(target.admin_url)
        with target.engine().connect() as connection:
            assert connection.scalar(
                text("SELECT version_num FROM public.alembic_version")
            ) == CURRENT_RUNTIME_SCHEMA_REVISION


def test_mixed_blocking_and_legacy_compatible_rows_abort(
    phase5_baseline: historical_support.TargetDatabase,
) -> None:
    with _clone_target(phase5_baseline) as target:
        _seed_corruption(target, "daily_log_food_owner_mismatch")
        engine = target.engine()
        try:
            with engine.begin() as connection:
                connection.execute(text("SET LOCAL session_replication_role = replica"))
                owner = _user(connection, "mixed-null-provenance")
                food = _food(connection, owner, "Mixed valid food")
                _snapshot(connection, _log(connection, owner, food), food)
        finally:
            engine.dispose()

        with pytest.raises(ResourceMembershipPreflightBlockedError) as rejected:
            _upgrade_0019(target.admin_url)

        assert rejected.value.report.to_dict()["blocking_row_count"] > 0


def test_successful_migration_preserves_history_and_backfills_only_owner(
    phase5_baseline: historical_support.TargetDatabase,
) -> None:
    with _clone_target(phase5_baseline) as target:
        owner, ingredient_id, roots_before = _seed_valid_historical_graph(target)

        _upgrade_0019(target.admin_url)

        engine = target.engine()
        try:
            with engine.connect() as connection:
                roots_after = {
                    table_name: _table_root(connection, table_name)
                    for table_name in roots_before
                    if table_name != "recipe_ingredients_without_new_owner"
                }
                roots_after["recipe_ingredients_without_new_owner"] = _table_root(
                    connection,
                    "recipe_ingredients",
                    omit_user_id=True,
                )
                ingredient_owner = connection.scalar(
                    text(
                        "SELECT user_id FROM public.recipe_ingredients WHERE id = :id"
                    ),
                    {"id": ingredient_id},
                )
        finally:
            engine.dispose()

        assert roots_after == roots_before
        assert ingredient_owner == owner


def test_clean_0018_to_0019_runs_through_real_alembic_entrypoint(
    phase5_baseline: historical_support.TargetDatabase,
) -> None:
    with _clone_target(phase5_baseline) as target:
        migrator_url = _set_role_password_and_url(target, roles.MIGRATOR_ROLE)
        with target.engine().connect() as connection:
            trigger_before = connection.execute(
                text(
                    "SELECT trigger_value.tgenabled, "
                    "pg_catalog.pg_get_triggerdef(trigger_value.oid, true) "
                    "FROM pg_catalog.pg_trigger AS trigger_value "
                    "WHERE trigger_value.tgrelid = "
                    "'public.recipe_ingredients'::regclass "
                    "AND trigger_value.tgname = 'phase5c_write_fence_gate'"
                )
            ).one()

        migrated = historical_support._run_alembic(
            migrator_url,
            "upgrade",
            CURRENT_RUNTIME_SCHEMA_REVISION,
        )

        assert migrated.returncode == 0, migrated.stdout + migrated.stderr
        with target.engine().connect() as connection:
            assert connection.scalar(
                text("SELECT version_num FROM public.alembic_version")
            ) == CURRENT_RUNTIME_SCHEMA_REVISION
            trigger_after = connection.execute(
                text(
                    "SELECT trigger_value.tgenabled, "
                    "pg_catalog.pg_get_triggerdef(trigger_value.oid, true) "
                    "FROM pg_catalog.pg_trigger AS trigger_value "
                    "WHERE trigger_value.tgrelid = "
                    "'public.recipe_ingredients'::regclass "
                    "AND trigger_value.tgname = 'phase5c_write_fence_gate'"
                )
            ).one()
        assert trigger_before[0] == "O"
        assert trigger_after == trigger_before

        downgraded = historical_support._run_alembic(
            migrator_url,
            "downgrade",
            HISTORICAL_PHASE5_SCHEMA_REVISION,
        )
        assert downgraded.returncode != 0
        assert "restore or fix forward" in downgraded.stderr
        with target.engine().connect() as connection:
            assert connection.scalar(
                text("SELECT version_num FROM public.alembic_version")
            ) == CURRENT_RUNTIME_SCHEMA_REVISION


def test_0019_metadata_projection_is_explicit_and_typed() -> None:
    assert _POST_0019_METADATA_TABLES == {
        "daily_log_day_completions",
        "phase5c_activation_runtime_commands",
        "phase5c_activation_schema_evidence",
    }
    assert _POST_0019_METADATA_COLUMNS == {
        ("serving_definitions", "reference_gram_weight"),
        ("serving_definitions", "reference_quantity"),
        ("serving_definitions", "reference_unit"),
        ("user_profiles", "authoritative_time_zone"),
        ("user_profiles", "calendar_revision"),
    }
    assert _POST_0019_METADATA_UNIQUE_CONSTRAINTS == {
        ("food_nutrients", "uq_food_nutrients_food_nutrient_basis"),
    }

    table_object = SimpleNamespace()

    assert not _include_0019_schema_object(
        table_object,
        "daily_log_day_completions",
        "table",
        False,
        None,
    )
    assert not _include_0019_schema_object(
        table_object,
        "phase5c_activation_runtime_commands",
        "table",
        False,
        None,
    )
    assert _include_0019_schema_object(
        table_object,
        "unlisted_current_table",
        "table",
        False,
        None,
    )
    assert not _include_0019_schema_object(
        table_object,
        "phase5c_conversion_clone_marker",
        "table",
        True,
        None,
    )
    assert _include_0019_schema_object(
        table_object,
        "daily_log_day_completions",
        "table",
        True,
        None,
    )

    serving_column = SimpleNamespace(
        table=SimpleNamespace(name="serving_definitions")
    )
    user_profile_column = SimpleNamespace(
        table=SimpleNamespace(name="user_profiles")
    )

    for column_name in (
        "reference_quantity",
        "reference_unit",
        "reference_gram_weight",
    ):
        assert not _include_0019_schema_object(
            serving_column,
            column_name,
            "column",
            False,
            None,
        )

    assert not _include_0019_schema_object(
        user_profile_column,
        "authoritative_time_zone",
        "column",
        False,
        None,
    )
    assert _include_0019_schema_object(
        serving_column,
        "unlisted_current_column",
        "column",
        False,
        None,
    )
    assert _include_0019_schema_object(
        serving_column,
        "reference_quantity",
        "column",
        True,
        None,
    )

    food_nutrient_constraint = SimpleNamespace(
        table=SimpleNamespace(name="food_nutrients")
    )
    other_constraint = SimpleNamespace(
        table=SimpleNamespace(name="recipes")
    )

    assert not _include_0019_schema_object(
        food_nutrient_constraint,
        "uq_food_nutrients_food_nutrient_basis",
        "unique_constraint",
        False,
        None,
    )
    assert _include_0019_schema_object(
        food_nutrient_constraint,
        "unlisted_current_unique_constraint",
        "unique_constraint",
        False,
        None,
    )
    assert _include_0019_schema_object(
        other_constraint,
        "uq_food_nutrients_food_nutrient_basis",
        "unique_constraint",
        False,
        None,
    )
    assert _include_0019_schema_object(
        food_nutrient_constraint,
        "uq_food_nutrients_food_nutrient_basis",
        "unique_constraint",
        True,
        None,
    )

    assert _include_0019_schema_object(
        table_object,
        "unlisted_current_index",
        "index",
        False,
        None,
    )


def test_0019_sqlalchemy_metadata_has_no_domain_drift(
    membership_database: historical_support.TargetDatabase,
) -> None:
    engine = membership_database.engine()
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={
                    "compare_type": True,
                    "include_object": _include_0019_schema_object,
                },
            )
            differences = compare_metadata(
                context,
                build_alembic_metadata(Base.metadata),
            )
    finally:
        engine.dispose()

    assert differences == []


def test_clean_0018_to_0019_installs_current_local_admission(
    membership_database: historical_support.TargetDatabase,
) -> None:
    with membership_database.connect_as(roles.CANARY_ROLE) as connection:
        row = (
            connection.execute(text("SELECT * FROM public.phase5c_local_admission_v2()"))
            .mappings()
            .one()
        )

    assert row["admission_contract_version"] == LOCAL_ADMISSION_VERSION
    assert row["schema_revision"] == CURRENT_RUNTIME_SCHEMA_REVISION
    engine = membership_database.engine()
    try:
        with engine.connect() as connection:
            assert qualify_constraint_manifest(connection)
    finally:
        engine.dispose()
    assert row["resource_membership_integrity_valid"] is True

    canary_config = Settings(
        deployment_mode=DeploymentMode.PRIVATE_SINGLE_USER,
        process_mode=ProcessMode.CANARY,
        database_url=membership_database.admin_url,
        private_auth_secret="c" * 32,
        private_user_id=membership_database.canary_user_id,
        private_user_email=membership_database.canary_user_email,
        private_user_create_if_missing=False,
    )
    canary_engine = historical_support._engine_as(
        membership_database,
        roles.CANARY_ROLE,
        read_only=True,
    )
    try:
        # Runtime startup follows the current 0020 admission revision. The
        # frozen 0019 reader remains independently testable above, but must not
        # be accepted by a newer runtime binary.
        with pytest.raises(RuntimeError, match="canary_startup_admission_failed"):
            _admit_canary_startup(canary_config, canary_engine)
    finally:
        canary_engine.dispose()


def test_independent_0019_qualification_is_exact_and_read_only(
    membership_database: historical_support.TargetDatabase,
) -> None:
    qualifier_url = _set_role_password_and_url(
        membership_database,
        roles.QUALIFIER_ROLE,
    )

    qualification = collect_resource_membership_qualification(qualifier_url)
    payload = qualification.to_dict()

    assert payload["schema_revision"] == CURRENT_RUNTIME_SCHEMA_REVISION
    assert payload["constraint_manifest_version"] == CONSTRAINT_MANIFEST_VERSION
    assert payload["blocking_category_count"] == 0
    assert payload["blocking_row_count"] == 0


def test_current_qualification_detects_corrupt_denormalized_ingredient_owner(
    phase5_baseline: historical_support.TargetDatabase,
) -> None:
    with _clone_target(phase5_baseline) as target:
        _upgrade_0019(target.admin_url)
        _restore_runtime_access(target)
        engine = target.engine()
        try:
            with engine.begin() as connection:
                connection.execute(text("SET LOCAL session_replication_role = replica"))
                owner = _user(connection, "current-ingredient-owner")
                other = _user(connection, "current-ingredient-other")
                recipe = _recipe(connection, owner, "Current ingredient recipe")
                food = _food(connection, owner, "Current ingredient food")
                connection.execute(
                    text(
                        "INSERT INTO public.recipe_ingredients ("
                        "id, user_id, recipe_id, food_item_id, position, "
                        "amount_quantity, amount_unit, resolved_gram_amount) "
                        "VALUES (:id, :user_id, :recipe_id, :food_id, 0, 1, 'g', 1)"
                    ),
                    {
                        "id": uuid4(),
                        "user_id": other,
                        "recipe_id": recipe,
                        "food_id": food,
                    },
                )
            with engine.connect() as connection:
                connection.execute(text("SET TRANSACTION READ ONLY"))
                with pytest.raises(ResourceMembershipPreflightBlockedError) as blocked:
                    assert_no_blocking_findings(
                        connection,
                        observed_schema_revision=CURRENT_RUNTIME_SCHEMA_REVISION,
                        read_only=True,
                    )
                owner_count = next(
                    row["count"]
                    for row in blocked.value.report.to_dict()["category_counts"]
                    if row["category"] == "recipe_ingredient_owner_mismatch"
                )
                assert owner_count == 1
        finally:
            engine.dispose()

        qualifier_url = _set_role_password_and_url(target, roles.QUALIFIER_ROLE)
        with pytest.raises(
            ResourceMembershipQualificationError,
            match="resource_membership_qualification_preflight_invalid",
        ):
            collect_resource_membership_qualification(qualifier_url)


def test_orphan_projection_revision_owner_corruption_is_impossible_and_blocking(
    phase5_baseline: historical_support.TargetDatabase,
) -> None:
    with _clone_target(phase5_baseline) as target:
        _upgrade_0019(target.admin_url)
        engine = target.engine()
        try:
            with engine.begin() as connection:
                connection.execute(text("SET LOCAL session_replication_role = replica"))
                owner = _user(connection, "orphan-projection-owner")
                other = _user(connection, "orphan-projection-other")
                recipe = _recipe(connection, owner, "Orphan projection recipe")
                revision = _revision(connection, recipe, owner)
                _food(
                    connection,
                    other,
                    "Cross-owner orphan projection",
                    revision_id=revision,
                    recipe_id=recipe,
                )
            with engine.connect() as connection:
                connection.execute(text("SET TRANSACTION READ ONLY"))
                with pytest.raises(ResourceMembershipPreflightBlockedError) as blocked:
                    assert_no_blocking_findings(
                        connection,
                        observed_schema_revision=CURRENT_RUNTIME_SCHEMA_REVISION,
                        read_only=True,
                    )
                counts = {
                    row["category"]: row["count"]
                    for row in blocked.value.report.to_dict()["category_counts"]
                }
                assert counts["recipe_projection_owner_mismatch"] == 1
                assert counts["projection_revision_without_recipe_backlink"] == 1
        finally:
            engine.dispose()


def test_wrong_active_revision_without_projection_is_impossible_and_blocking(
    phase5_baseline: historical_support.TargetDatabase,
) -> None:
    with _clone_target(phase5_baseline) as target:
        engine = target.engine()
        try:
            with engine.begin() as connection:
                connection.execute(text("SET LOCAL session_replication_role = replica"))
                owner = _user(connection, "wrong-active-owner")
                other = _user(connection, "wrong-active-other")
                recipe = _recipe(connection, owner, "Wrong active recipe")
                foreign_recipe = _recipe(connection, other, "Foreign active recipe")
                foreign_revision = _revision(connection, foreign_recipe, other)
                connection.execute(
                    text(
                        "UPDATE public.recipes "
                        "SET active_publication_revision_id = :revision "
                        "WHERE id = :recipe"
                    ),
                    {"revision": foreign_revision, "recipe": recipe},
                )
        finally:
            engine.dispose()

        with pytest.raises(ResourceMembershipPreflightBlockedError) as blocked:
            _upgrade_0019(target.admin_url)

        counts = {
            row["category"]: row["count"]
            for row in blocked.value.report.to_dict()["category_counts"]
        }
        assert counts["recipe_projection_missing_active_revision"] == 1
        assert counts["recipe_projection_active_revision_mismatch"] == 1


def test_postmigration_retained_constraint_drift_fails_local_and_independent_admission(
    phase5_baseline: historical_support.TargetDatabase,
) -> None:
    with _clone_target(phase5_baseline) as target:
        _upgrade_0019(target.admin_url)
        _restore_runtime_access(target)
        contract = RETAINED_FOREIGN_KEY_CONTRACTS[0]
        _owner_execute(
            target,
            f"ALTER TABLE public.{contract.child_table} "
            f"DROP CONSTRAINT {contract.name}",
        )

        assert _local_integrity_valid(target) is False
        qualifier_url = _set_role_password_and_url(target, roles.QUALIFIER_ROLE)
        with pytest.raises(ResourceMembershipQualificationError):
            collect_resource_membership_qualification(qualifier_url)


def test_owner_column_default_drift_fails_local_and_independent_admission(
    phase5_baseline: historical_support.TargetDatabase,
) -> None:
    with _clone_target(phase5_baseline) as target:
        _upgrade_0019(target.admin_url)
        _restore_runtime_access(target)
        _owner_execute(
            target,
            "ALTER TABLE public.recipe_ingredients "
            "ALTER COLUMN user_id SET DEFAULT "
            "'00000000-0000-0000-0000-000000000000'::uuid",
        )

        assert _local_integrity_valid(target) is False
        qualifier_url = _set_role_password_and_url(target, roles.QUALIFIER_ROLE)
        with pytest.raises(ResourceMembershipQualificationError):
            collect_resource_membership_qualification(qualifier_url)


def test_partial_projection_index_decoy_cannot_satisfy_local_admission(
    phase5_baseline: historical_support.TargetDatabase,
) -> None:
    with _clone_target(phase5_baseline) as target:
        _upgrade_0019(target.admin_url)
        _restore_runtime_access(target)
        engine = target.engine()
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(f"SET SESSION AUTHORIZATION {roles.MIGRATOR_ROLE}")
                )
                roles.assume_migration_owner(connection)
                target_attnum = int(
                    connection.scalar(
                        text(
                            "SELECT attnum FROM pg_catalog.pg_attribute "
                            "WHERE attrelid = 'public.food_items'::regclass "
                            "AND attname = 'recipe_publication_revision_id'"
                        )
                    )
                )
                padding = ", ".join(
                    f"padding_{position} integer"
                    for position in range(1, target_attnum)
                )
                connection.execute(
                    text(f"DROP INDEX public.{PROJECTION_REVISION_UNIQUE_INDEX}")
                )
                connection.execute(
                    text(
                        "CREATE TABLE public.resource_membership_index_decoy ("
                        f"{padding}, recipe_publication_revision_id uuid)"
                    )
                )
                connection.execute(
                    text(
                        f"CREATE UNIQUE INDEX {PROJECTION_REVISION_UNIQUE_INDEX} "
                        "ON public.resource_membership_index_decoy "
                        "(recipe_publication_revision_id) "
                        "WHERE recipe_publication_revision_id IS NOT NULL"
                    )
                )
        finally:
            engine.dispose()

        assert _local_integrity_valid(target) is False
        qualifier_url = _set_role_password_and_url(target, roles.QUALIFIER_ROLE)
        with pytest.raises(ResourceMembershipQualificationError):
            collect_resource_membership_qualification(qualifier_url)


def test_non_btree_supporting_index_cannot_satisfy_admission(
    phase5_baseline: historical_support.TargetDatabase,
) -> None:
    with _clone_target(phase5_baseline) as target:
        _upgrade_0019(target.admin_url)
        _restore_runtime_access(target)
        name, table_name, columns = SUPPORTING_INDEXES[0]
        _owner_execute(target, f"DROP INDEX public.{name}")
        _owner_execute(
            target,
            f"CREATE INDEX {name} ON public.{table_name} USING brin "
            f"({', '.join(columns)})",
        )

        assert _local_integrity_valid(target) is False
        qualifier_url = _set_role_password_and_url(target, roles.QUALIFIER_ROLE)
        with pytest.raises(ResourceMembershipQualificationError):
            collect_resource_membership_qualification(qualifier_url)


def test_unexpected_runtime_routine_grant_fails_local_and_independent_admission(
    phase5_baseline: historical_support.TargetDatabase,
) -> None:
    with _clone_target(phase5_baseline) as target:
        _upgrade_0019(target.admin_url)
        _restore_runtime_access(target)
        _owner_execute(
            target,
            "CREATE FUNCTION public.resource_membership_unexpected() "
            "RETURNS integer LANGUAGE sql IMMUTABLE AS 'SELECT 1'",
        )
        _owner_execute(
            target,
            "REVOKE ALL ON FUNCTION public.resource_membership_unexpected() FROM PUBLIC",
        )
        _owner_execute(
            target,
            "GRANT EXECUTE ON FUNCTION public.resource_membership_unexpected() "
            "TO nutrition_runtime",
        )

        assert _local_integrity_valid(target) is False
        qualifier_url = _set_role_password_and_url(target, roles.QUALIFIER_ROLE)
        with pytest.raises(ResourceMembershipQualificationError):
            collect_resource_membership_qualification(qualifier_url)


def test_unexpected_local_admission_grantee_fails_local_and_independent_admission(
    phase5_baseline: historical_support.TargetDatabase,
) -> None:
    with _clone_target(phase5_baseline) as target:
        _upgrade_0019(target.admin_url)
        _restore_runtime_access(target)
        _owner_execute(
            target,
            "GRANT EXECUTE ON FUNCTION public.phase5c_local_admission_v2() "
            "TO nutrition_ops",
        )

        assert _local_integrity_valid(target) is False
        qualifier_url = _set_role_password_and_url(target, roles.QUALIFIER_ROLE)
        with pytest.raises(ResourceMembershipQualificationError):
            collect_resource_membership_qualification(qualifier_url)


def test_local_admission_routine_definition_drift_fails_independent_qualification(
    phase5_baseline: historical_support.TargetDatabase,
) -> None:
    with _clone_target(phase5_baseline) as target:
        _upgrade_0019(target.admin_url)
        _restore_runtime_access(target)
        _owner_execute(
            target,
            "ALTER FUNCTION public.phase5c_local_admission_v2() VOLATILE",
        )

        qualifier_url = _set_role_password_and_url(target, roles.QUALIFIER_ROLE)
        with pytest.raises(
            ResourceMembershipQualificationError,
            match="resource_membership_local_admission_routine_invalid",
        ):
            collect_resource_membership_qualification(qualifier_url)


def test_incident_fence_is_not_deployable_qualification_or_canary_state(
    phase5_baseline: historical_support.TargetDatabase,
) -> None:
    with _clone_target(phase5_baseline) as target:
        _upgrade_0019(target.admin_url)
        _restore_runtime_access(target)
        historical_support._force_owner_fence_event(
            target,
            _current_prerequisites(target),
            to_mode="closed_incident",
        )

        qualifier_url = _set_role_password_and_url(target, roles.QUALIFIER_ROLE)
        with pytest.raises(ResourceMembershipQualificationError):
            collect_resource_membership_qualification(qualifier_url)

        canary_config = Settings(
            deployment_mode=DeploymentMode.PRIVATE_SINGLE_USER,
            process_mode=ProcessMode.CANARY,
            database_url=target.admin_url,
            private_auth_secret="c" * 32,
            private_user_id=target.canary_user_id,
            private_user_email=target.canary_user_email,
            private_user_create_if_missing=False,
        )
        canary_engine = historical_support._engine_as(
            target,
            roles.CANARY_ROLE,
            read_only=True,
        )
        try:
            with pytest.raises(RuntimeError, match="canary_startup_admission_failed"):
                _admit_canary_startup(canary_config, canary_engine)
        finally:
            canary_engine.dispose()


def test_runtime_can_write_valid_owner_graph_but_cannot_bypass_constraints(
    phase5_baseline: historical_support.TargetDatabase,
) -> None:
    with _clone_target(phase5_baseline) as target:
        _upgrade_0019(target.admin_url)
        _open_runtime_writes(target)

        user_id = uuid4()
        food_id = uuid4()
        recipe_id = uuid4()
        ingredient_id = uuid4()
        with target.connect_as(roles.RUNTIME_ROLE) as connection:
            admission = connection.execute(
                text("SELECT * FROM public.phase5c_local_admission_v2()")
            ).mappings().one()
            assert admission["schema_revision"] == CURRENT_RUNTIME_SCHEMA_REVISION
            assert admission["resource_membership_integrity_valid"] is True
            connection.execute(
                text("INSERT INTO public.users (id, email) VALUES (:id, :email)"),
                {"id": user_id, "email": f"runtime-{user_id}@example.test"},
            )
            connection.execute(
                text(
                    "INSERT INTO public.food_items ("
                    "id, user_id, name, source_type, is_recipe) "
                    "VALUES (:id, :owner, 'Runtime food', 'manual', false)"
                ),
                {"id": food_id, "owner": user_id},
            )
            connection.execute(
                text(
                    "INSERT INTO public.recipes ("
                    "id, user_id, name, needs_republish) "
                    "VALUES (:id, :owner, 'Runtime recipe', false)"
                ),
                {"id": recipe_id, "owner": user_id},
            )
            connection.execute(
                text(
                    "INSERT INTO public.recipe_ingredients ("
                    "id, user_id, recipe_id, food_item_id, position, "
                    "amount_quantity, amount_unit, resolved_gram_amount) "
                    "VALUES (:id, :owner, :recipe, :food, 0, 1, 'g', 100)"
                ),
                {
                    "id": ingredient_id,
                    "owner": user_id,
                    "recipe": recipe_id,
                    "food": food_id,
                },
            )
            connection.commit()

        denied_statements = (
            "ALTER TABLE public.recipe_ingredients DROP CONSTRAINT "
            "fk_recipe_ingredients_food_owner",
            "ALTER TABLE public.recipe_ingredients DISABLE TRIGGER ALL",
            "SET session_replication_role = replica",
        )
        for statement in denied_statements:
            with target.connect_as(roles.RUNTIME_ROLE) as connection:
                with pytest.raises(DBAPIError) as denied:
                    connection.execute(text(statement))
                assert getattr(denied.value.orig, "sqlstate", None) == "42501"
                connection.rollback()


_POSTGRES_DIRECT_WRITE_CASES = (
    (
        "ingredient_recipe_owner",
        direct_write_contracts.test_recipe_ingredient_rejects_recipe_owner_mismatch,
        (),
    ),
    (
        "ingredient_food_owner",
        direct_write_contracts.test_recipe_ingredient_rejects_food_owner_mismatch,
        (),
    ),
    (
        "ingredient_serving_membership",
        direct_write_contracts.test_recipe_ingredient_rejects_serving_from_another_food,
        (),
    ),
    (
        "daily_log_food_owner",
        direct_write_contracts.test_daily_log_rejects_food_owned_by_another_user,
        (),
    ),
    (
        "daily_log_serving_membership",
        direct_write_contracts.test_daily_log_rejects_serving_from_another_food,
        (),
    ),
    (
        "recipe_projection_revision",
        direct_write_contracts.test_recipe_rejects_projection_from_a_different_active_revision,
        (),
    ),
    (
        "recipe_projection_owner",
        direct_write_contracts.test_projection_food_rejects_revision_owned_by_another_user,
        (),
    ),
    (
        "recipe_projection_owner_required",
        direct_write_contracts.test_projection_food_requires_owner_when_revision_bound,
        (),
    ),
    (
        "ocr_trace_food_owner",
        direct_write_contracts.test_ocr_trace_rejects_food_owned_by_another_user,
        (),
    ),
    (
        "snapshot_daily_log_food",
        direct_write_contracts.test_snapshot_rejects_source_food_different_from_daily_log,
        (),
    ),
    (
        "snapshot_nutrient_food",
        direct_write_contracts.test_snapshot_rejects_source_nutrient_membership_mismatch,
        ("food",),
    ),
    (
        "snapshot_nutrient_identity",
        direct_write_contracts.test_snapshot_rejects_source_nutrient_membership_mismatch,
        ("nutrient",),
    ),
    (
        "snapshot_serving_membership",
        direct_write_contracts.test_snapshot_rejects_serving_from_another_food,
        (),
    ),
    (
        "recipe_publication_projection_link_pair",
        direct_write_contracts.test_recipe_publication_links_must_be_paired,
        ("projection",),
    ),
    (
        "recipe_publication_revision_link_pair",
        direct_write_contracts.test_recipe_publication_links_must_be_paired,
        ("revision",),
    ),
    (
        "projection_revision_unique",
        direct_write_contracts.test_one_revision_cannot_back_multiple_projections,
        (),
    ),
    (
        "nullable_provenance",
        direct_write_contracts.test_snapshot_allows_nullable_mutable_source_provenance,
        (),
    ),
    (
        "soft_deleted_food_parent",
        direct_write_contracts.test_soft_deleted_food_remains_a_valid_historical_membership_parent,
        (),
    ),
    (
        "provenance_set_null",
        direct_write_contracts.test_deleting_mutable_provenance_sets_nullable_links_to_null,
        (),
    ),
    (
        "first_publication",
        direct_write_contracts.test_first_publication_accepts_paired_revision_projection_links,
        (),
    ),
    (
        "republish_historical_log",
        direct_write_contracts.test_republish_allows_old_revision_log_to_remain_historical,
        (),
    ),
    (
        "snapshot_replacement",
        direct_write_contracts.test_valid_snapshot_replacement_preserves_log_membership,
        (),
    ),
)


@pytest.mark.parametrize(
    ("_case_name", "test_case", "arguments"),
    _POSTGRES_DIRECT_WRITE_CASES,
    ids=[case[0] for case in _POSTGRES_DIRECT_WRITE_CASES],
)
def test_postgresql_direct_write_contracts_match_sqlite(
    postgres_membership_session: Session,
    _case_name: str,
    test_case,
    arguments: tuple[str, ...],
) -> None:
    test_case(postgres_membership_session, *arguments)
