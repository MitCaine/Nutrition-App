"""SQLite behavioral guards for immutable historical provenance rows.

PostgreSQL roles and protection objects remain the production security
boundary.  These SQLite triggers are deliberately narrower: they catch
accidental application and test mutations while retaining SQLite's foreign-key
actions and the existing whole-set Daily Log snapshot replacement operation.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any
from uuid import UUID

from sqlalchemy import DDL, event
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.operators.immutable_provenance_contracts import (
    APPEND_ONLY_TABLES,
    DAILY_LOG_TABLE,
    SNAPSHOT_TABLE,
)


_SNAPSHOT_REPLACEMENT_UDF = "phase0020_snapshot_replacement_allowed"
_snapshot_replacement_scopes: ContextVar[tuple[tuple[str, str], ...]] = ContextVar(
    "phase0020_sqlite_snapshot_replacement_scopes",
    default=(),
)


def _replacement_is_allowed(user_id: object, log_id: object) -> int:
    requested_scope = (str(user_id), str(log_id))
    return int(requested_scope in _snapshot_replacement_scopes.get())


def _register_sqlite_functions(
    dbapi_connection: Any,
    _connection_record: Any,
) -> None:
    if isinstance(dbapi_connection, sqlite3.Connection):
        dbapi_connection.create_function(
            _SNAPSHOT_REPLACEMENT_UDF,
            2,
            _replacement_is_allowed,
            deterministic=False,
        )


def _dialect_name(bind: Session | Connection | Engine) -> str:
    resolved: Connection | Engine
    if isinstance(bind, Session):
        resolved = bind.get_bind()
    else:
        resolved = bind
    return resolved.dialect.name


@contextmanager
def allow_sqlite_snapshot_replacement(
    bind: Session | Connection | Engine,
    user_id: UUID,
    log_id: UUID,
) -> Iterator[None]:
    """Permit one owner/log-scoped snapshot-set replacement on SQLite.

    The context is a no-op for non-SQLite binds so the repository can use one
    transaction shape across both supported databases.  It is intentionally a
    Python regression guard, not an authorization boundary.
    """

    if _dialect_name(bind) != "sqlite":
        yield
        return

    scope = (str(user_id), str(log_id))
    token = _snapshot_replacement_scopes.set(
        (*_snapshot_replacement_scopes.get(), scope)
    )
    try:
        yield
    finally:
        _snapshot_replacement_scopes.reset(token)


def _abort_trigger(name: str, table: str, operation: str, reason: str) -> DDL:
    return DDL(
        f'''CREATE TRIGGER "{name}"
        BEFORE {operation} ON "{table}"
        BEGIN
            SELECT RAISE(ABORT, '{reason}');
        END'''
    ).execute_if(dialect="sqlite")


def _install_append_only_triggers() -> None:
    for protected in APPEND_ONLY_TABLES:
        table = Base.metadata.tables[protected.table]
        for operation in ("UPDATE", "DELETE"):
            trigger_name = (
                f"{protected.trigger_prefix}_immutable_{operation.lower()}"
            )
            event.listen(
                table,
                "after_create",
                _abort_trigger(
                    trigger_name,
                    protected.table,
                    operation,
                    "phase0020_immutable_row_mutation",
                ),
            )


def _install_snapshot_triggers() -> None:
    table = Base.metadata.tables[SNAPSHOT_TABLE.table]
    ordinary_columns = tuple(
        column.name
        for column in table.columns
        if column.name not in {"source_food_nutrient_id", "serving_definition_id"}
    )
    ordinary_columns_unchanged = "\n                AND ".join(
        f'OLD."{column}" IS NEW."{column}"' for column in ordinary_columns
    )
    source_nutrient_is_unchanged_or_fk_nulled = """
        NEW."source_food_nutrient_id" IS OLD."source_food_nutrient_id"
        OR (
            OLD."source_food_nutrient_id" IS NOT NULL
            AND NEW."source_food_nutrient_id" IS NULL
            AND NOT EXISTS (
                SELECT 1 FROM "food_nutrients"
                WHERE "id" = OLD."source_food_nutrient_id"
            )
        )
    """
    serving_is_unchanged_or_fk_nulled = """
        NEW."serving_definition_id" IS OLD."serving_definition_id"
        OR (
            OLD."serving_definition_id" IS NOT NULL
            AND NEW."serving_definition_id" IS NULL
            AND NOT EXISTS (
                SELECT 1 FROM "serving_definitions"
                WHERE "id" = OLD."serving_definition_id"
            )
        )
    """
    provenance_changed = """
        NEW."source_food_nutrient_id" IS NOT OLD."source_food_nutrient_id"
        OR NEW."serving_definition_id" IS NOT OLD."serving_definition_id"
    """
    update_trigger = DDL(
        f'''CREATE TRIGGER
        "{SNAPSHOT_TABLE.trigger_prefix}_immutable_update"
        BEFORE UPDATE ON "{SNAPSHOT_TABLE.table}"
        WHEN NOT (
            {ordinary_columns_unchanged}
            AND ({source_nutrient_is_unchanged_or_fk_nulled})
            AND ({serving_is_unchanged_or_fk_nulled})
            AND ({provenance_changed})
        )
        BEGIN
            SELECT RAISE(ABORT, 'phase0020_snapshot_immutable_update');
        END'''
    ).execute_if(dialect="sqlite")
    delete_trigger = DDL(
        f'''CREATE TRIGGER
        "{SNAPSHOT_TABLE.trigger_prefix}_immutable_delete"
        BEFORE DELETE ON "{SNAPSHOT_TABLE.table}"
        WHEN EXISTS (
            SELECT 1 FROM "daily_logs" WHERE "id" = OLD."daily_log_id"
        ) AND {_SNAPSHOT_REPLACEMENT_UDF}(
            (
                SELECT "user_id" FROM "daily_logs"
                WHERE "id" = OLD."daily_log_id"
            ),
            OLD."daily_log_id"
        ) <> 1
        BEGIN
            SELECT RAISE(ABORT, 'phase0020_snapshot_immutable_delete');
        END'''
    ).execute_if(dialect="sqlite")
    event.listen(table, "after_create", update_trigger)
    event.listen(table, "after_create", delete_trigger)


def _install_daily_log_trigger() -> None:
    table = Base.metadata.tables[DAILY_LOG_TABLE.table]
    permanently_frozen_columns = (
        "id",
        "user_id",
        "food_item_id",
        "food_name_snapshot",
        "client_request_id",
        "client_request_fingerprint",
        "created_at",
    )
    replacement_columns = (
        "amount_quantity",
        "amount_unit",
        "serving_definition_id",
        "recipe_publication_amount_definition_id",
        "gram_amount",
        "package_fraction",
    )

    permanently_frozen = "\n                AND ".join(
        f'OLD."{column}" IS NEW."{column}"'
        for column in permanently_frozen_columns
    )
    revision_unchanged = (
        'OLD."recipe_publication_revision_id" IS '
        'NEW."recipe_publication_revision_id"'
    )
    replacement_columns_unchanged = "\n                    AND ".join(
        f'OLD."{column}" IS NEW."{column}"' for column in replacement_columns
    )
    all_except_serving_unchanged = "\n                    AND ".join(
        f'OLD."{column.name}" IS NEW."{column.name}"'
        for column in table.columns
        if column.name != "serving_definition_id"
    )
    trigger = DDL(
        f'''CREATE TRIGGER
        "{DAILY_LOG_TABLE.trigger_prefix}_immutable_update"
        BEFORE UPDATE ON "{DAILY_LOG_TABLE.table}"
        WHEN NOT (
            {permanently_frozen}
            AND (
                (
                    {revision_unchanged}
                    AND
                    {replacement_columns_unchanged}
                )
                OR {_SNAPSHOT_REPLACEMENT_UDF}(
                    OLD."user_id",
                    OLD."id"
                ) = 1
                OR (
                    OLD."serving_definition_id" IS NOT NULL
                    AND NEW."serving_definition_id" IS NULL
                    AND NOT EXISTS (
                        SELECT 1 FROM "serving_definitions"
                        WHERE "id" = OLD."serving_definition_id"
                    )
                    AND {all_except_serving_unchanged}
                )
            )
        )
        BEGIN
            SELECT RAISE(ABORT, 'phase0020_daily_log_immutable_update');
        END'''
    ).execute_if(dialect="sqlite")
    event.listen(table, "after_create", trigger)


event.listen(Engine, "connect", _register_sqlite_functions)
_install_append_only_triggers()
_install_snapshot_triggers()
_install_daily_log_trigger()
