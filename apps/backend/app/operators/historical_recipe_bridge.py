from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import re
from typing import Any, Iterator
from uuid import UUID

from sqlalchemy import (
    Connection,
    DateTime,
    Engine,
    Integer,
    Numeric,
    Text,
    Uuid,
    bindparam,
    inspect,
    text,
)

from app.core.database_identity import database_identity
from app.operators.historical_database_inventory import (
    HistoricalDatabaseInventory,
    REPORT_SCHEMA_VERSION,
)
from app.operators.phase5c_contracts import (
    CONTROL_REVISION,
    CONVERSION_RULES_VERSION,
    EXECUTION_REVISION,
    Phase5CAdmissionError,
    SUPPORTED_SCHEMA_SIGNATURE,
    SUPPORTED_SOURCE_REVISION,
    canonical_digest,
    canonical_json,
    validate_inventory_contract,
)
from app.operators.phase5c_isolation import (
    assert_database_session_isolation,
    conversion_clone_identity_digest,
    establish_clone_marker_on_connection,
    phase5c_maintenance_session,
    validate_operator_attestation,
    verify_clone_isolation_evidence,
)
from app.operators.phase5c_lookup_indexes import (
    ARCHIVE_RECIPE_INGREDIENT_LOOKUP_INDEX,
    archive_recipe_ingredient_lookup_index_state,
)


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CURRENT_ONLY_TABLES = {
    "recipe_publication_revisions",
    "recipe_publication_amount_definitions",
    "recipe_publication_nutrients",
}

_RECIPE_COLUMNS = (
    "id",
    "food_item_id",
    "user_id",
    "serving_count",
    "final_yield_quantity",
    "final_yield_unit",
    "instructions",
    "created_at",
    "updated_at",
)
_INGREDIENT_COLUMNS = (
    "id",
    "recipe_id",
    "ingredient_food_item_id",
    "quantity",
    "unit",
    "serving_definition_id",
    "gram_amount",
    "preparation_note",
    "sort_order",
)
_FOOD_COLUMNS = (
    "id",
    "user_id",
    "name",
    "brand",
    "source_type",
    "source_id",
    "is_recipe",
    "notes",
    "created_at",
    "updated_at",
    "deleted_at",
)
_SERVING_COLUMNS = (
    "id",
    "food_item_id",
    "label",
    "quantity",
    "unit",
    "gram_weight",
    "is_default",
    "source",
    "confidence",
    "is_user_confirmed",
)
_NUTRIENT_COLUMNS = (
    "id",
    "food_item_id",
    "nutrient_id",
    "amount",
    "unit",
    "basis",
    "data_status",
    "confidence",
    "source",
    "is_user_confirmed",
    "original_amount",
    "original_unit",
    "original_text",
    "created_at",
    "updated_at",
)
_SOURCE_COLUMNS = (
    "id",
    "food_item_id",
    "source_type",
    "external_id",
    "raw_payload",
    "metadata",
    "created_at",
)


def _column(name: str, kind: str, nullable: bool, default: str | None = None) -> dict[str, Any]:
    return {"name": name, "type": kind, "nullable": nullable, "default": default}


_EXPECTED_LEGACY_STRUCTURE = {
    "recipes": {
        "columns": [
            _column("id", "uuid", False, "gen_random_uuid"),
            _column("food_item_id", "uuid", False),
            _column("user_id", "uuid", False),
            _column("serving_count", "numeric(14,6)", True),
            _column("final_yield_quantity", "numeric(14,6)", True),
            _column("final_yield_unit", "text", True),
            _column("instructions", "text", True),
            _column("created_at", "timestamp_tz", False, "now"),
            _column("updated_at", "timestamp_tz", False, "now"),
        ],
        "primary_key": {"name": "recipes_pkey", "columns": ["id"]},
        "unique_constraints": [
            {"name": "recipes_food_item_id_key", "columns": ["food_item_id"]}
        ],
        "foreign_keys": [
            {
                "name": "recipes_food_item_id_fkey",
                "columns": ["food_item_id"],
                "referred_table": "food_items",
                "referred_columns": ["id"],
                "ondelete": None,
            },
            {
                "name": "recipes_user_id_fkey",
                "columns": ["user_id"],
                "referred_table": "users",
                "referred_columns": ["id"],
                "ondelete": None,
            },
        ],
        "check_constraints": [],
    },
    "recipe_ingredients": {
        "columns": [
            _column("id", "uuid", False, "gen_random_uuid"),
            _column("recipe_id", "uuid", False),
            _column("ingredient_food_item_id", "uuid", False),
            _column("quantity", "numeric(14,6)", False),
            _column("unit", "text", False),
            _column("serving_definition_id", "uuid", True),
            _column("gram_amount", "numeric(14,6)", True),
            _column("preparation_note", "text", True),
            _column("sort_order", "integer", False),
        ],
        "primary_key": {"name": "recipe_ingredients_pkey", "columns": ["id"]},
        "unique_constraints": [],
        "foreign_keys": [
            {
                "name": "recipe_ingredients_ingredient_food_item_id_fkey",
                "columns": ["ingredient_food_item_id"],
                "referred_table": "food_items",
                "referred_columns": ["id"],
                "ondelete": None,
            },
            {
                "name": "recipe_ingredients_recipe_id_fkey",
                "columns": ["recipe_id"],
                "referred_table": "recipes",
                "referred_columns": ["id"],
                "ondelete": None,
            },
            {
                "name": "recipe_ingredients_serving_definition_id_fkey",
                "columns": ["serving_definition_id"],
                "referred_table": "serving_definitions",
                "referred_columns": ["id"],
                "ondelete": None,
            },
        ],
        "check_constraints": [],
    },
}

_REQUIRED_SUPPORTING_COLUMNS = {
    "users": {"id"},
    "food_items": set(_FOOD_COLUMNS),
    "serving_definitions": set(_SERVING_COLUMNS),
    "food_nutrients": set(_NUTRIENT_COLUMNS),
    "food_sources": set(_SOURCE_COLUMNS),
}
_SCHEMA_SIGNATURE_CONTRACT = {
    "legacy_tables": _EXPECTED_LEGACY_STRUCTURE,
    "required_supporting_columns": {
        table: sorted(columns) for table, columns in _REQUIRED_SUPPORTING_COLUMNS.items()
    },
    "forbidden_current_recipe_tables": sorted(_CURRENT_ONLY_TABLES),
}

SCHEMA_SIGNATURE_DIGEST = canonical_digest(_SCHEMA_SIGNATURE_CONTRACT)


@dataclass(frozen=True)
class BridgeResult:
    payload: dict[str, Any]

    def to_json(self) -> str:
        return canonical_json(self.payload)

    def to_human(self) -> str:
        action = "created" if self.payload["archive_created"] else "verified"
        return "\n".join(
            (
                "Phase 5C historical bridge",
                f"Archive: {action}",
                f"Archive identity: {self.payload['archive_identity']}",
                f"Schema signature: {self.payload['schema_signature']}",
                f"Legacy Recipes: {self.payload['recipe_count']}",
                f"Legacy Recipe ingredients: {self.payload['ingredient_count']}",
                "Semantic conversion performed: no",
            )
        )


def _validate_identifier(value: str, label: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise Phase5CAdmissionError(f"{label} must be a simple PostgreSQL identifier")
    return value


def _qualified(connection: Connection, schema: str, table: str) -> str:
    quote = connection.dialect.identifier_preparer.quote
    return f"{quote(schema)}.{quote(table)}"


def _type_key(value: Any) -> str:
    if isinstance(value, Uuid):
        return "uuid"
    if isinstance(value, Numeric):
        return f"numeric({value.precision},{value.scale})"
    if isinstance(value, DateTime):
        return "timestamp_tz" if value.timezone else "timestamp"
    if isinstance(value, Integer):
        return "integer"
    if isinstance(value, Text):
        return "text"
    return str(value).lower()


def _default_key(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).lower().replace(" ", "")
    if "gen_random_uuid" in normalized:
        return "gen_random_uuid"
    if "now()" in normalized or "current_timestamp" in normalized:
        return "now"
    return normalized


def legacy_schema_structure(connection: Connection, schema: str) -> dict[str, Any]:
    inspector = inspect(connection)
    structure: dict[str, Any] = {}
    table_names = set(inspector.get_table_names(schema=schema))
    if not {"recipes", "recipe_ingredients"} <= table_names:
        raise Phase5CAdmissionError("Supported legacy Recipe tables are not both present")
    for table in ("recipes", "recipe_ingredients"):
        columns = [
            {
                "name": str(column["name"]),
                "type": _type_key(column["type"]),
                "nullable": bool(column["nullable"]),
                "default": _default_key(column.get("default")),
            }
            for column in inspector.get_columns(table, schema=schema)
        ]
        pk = inspector.get_pk_constraint(table, schema=schema)
        uniques = sorted(
            (
                {
                    "name": constraint.get("name"),
                    "columns": list(constraint.get("column_names") or ()),
                }
                for constraint in inspector.get_unique_constraints(table, schema=schema)
            ),
            key=lambda item: (str(item["name"]), item["columns"]),
        )
        foreign_keys = sorted(
            (
                {
                    "name": constraint.get("name"),
                    "columns": list(constraint.get("constrained_columns") or ()),
                    "referred_table": constraint.get("referred_table"),
                    "referred_columns": list(constraint.get("referred_columns") or ()),
                    "ondelete": (constraint.get("options") or {}).get("ondelete"),
                }
                for constraint in inspector.get_foreign_keys(table, schema=schema)
            ),
            key=lambda item: (str(item["name"]), item["columns"]),
        )
        checks = sorted(
            (
                {
                    "name": constraint.get("name"),
                    "sqltext": "".join(str(constraint.get("sqltext") or "").split()),
                }
                for constraint in inspector.get_check_constraints(table, schema=schema)
            ),
            key=lambda item: (str(item["name"]), item["sqltext"]),
        )
        structure[table] = {
            "columns": columns,
            "primary_key": {
                "name": pk.get("name"),
                "columns": list(pk.get("constrained_columns") or ()),
            },
            "unique_constraints": uniques,
            "foreign_keys": foreign_keys,
            "check_constraints": checks,
        }
    return structure


def require_supported_legacy_schema(connection: Connection, schema: str) -> None:
    actual = legacy_schema_structure(connection, schema)
    if actual != _EXPECTED_LEGACY_STRUCTURE:
        raise Phase5CAdmissionError(
            f"Schema does not match supported signature {SUPPORTED_SCHEMA_SIGNATURE}"
        )


def _require_supporting_schema(connection: Connection, schema: str) -> None:
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names(schema=schema))
    if _CURRENT_ONLY_TABLES & table_names:
        raise Phase5CAdmissionError("Unsupported current Recipe-domain state is present")
    for table, required in _REQUIRED_SUPPORTING_COLUMNS.items():
        if table not in table_names:
            raise Phase5CAdmissionError("Required supporting legacy table is absent")
        actual = {str(column["name"]) for column in inspector.get_columns(table, schema=schema)}
        if not required <= actual:
            raise Phase5CAdmissionError("Required supporting legacy columns are absent")
    recipe_columns = {
        str(column["name"]) for column in inspector.get_columns("recipes", schema=schema)
    }
    if {"name", "published_food_item_id", "deleted_at"} <= recipe_columns:
        raise Phase5CAdmissionError("Unsupported current Recipe schema is active")


def _rows(
    connection: Connection,
    schema: str,
    table: str,
    columns: tuple[str, ...],
    *,
    where_column: str | None = None,
    values: set[Any] | None = None,
) -> list[dict[str, Any]]:
    qualified = _qualified(connection, schema, table)
    selected = ", ".join(connection.dialect.identifier_preparer.quote(value) for value in columns)
    statement = f"SELECT {selected} FROM {qualified}"
    parameters: dict[str, Any] = {}
    query = text(statement)
    if where_column is not None:
        if not values:
            return []
        quoted_column = connection.dialect.identifier_preparer.quote(where_column)
        query = text(f"{statement} WHERE {quoted_column} IN :values").bindparams(
            bindparam("values", expanding=True)
        )
        parameters["values"] = sorted(values, key=str)
    result = connection.execute(query, parameters).mappings().all()
    return sorted((dict(row) for row in result), key=lambda row: str(row["id"]))


def _recipe_marker_food_rows(
    connection: Connection,
    schema: str,
) -> list[dict[str, Any]]:
    qualified = _qualified(connection, schema, "food_items")
    selected = ", ".join(
        connection.dialect.identifier_preparer.quote(value) for value in _FOOD_COLUMNS
    )
    rows = connection.execute(
        text(
            f"SELECT {selected} FROM {qualified} "
            "WHERE is_recipe = true OR source_type = 'recipe'"
        )
    ).mappings().all()
    return sorted((dict(row) for row in rows), key=lambda row: str(row["id"]))


def planning_source_payload(
    connection: Connection,
    *,
    recipe_schema: str,
    supporting_schema: str,
) -> dict[str, list[dict[str, Any]]]:
    recipes = _rows(connection, recipe_schema, "recipes", _RECIPE_COLUMNS)
    ingredients = _rows(
        connection,
        recipe_schema,
        "recipe_ingredients",
        _INGREDIENT_COLUMNS,
    )
    return _planning_source_payload_for_rows(
        connection,
        supporting_schema=supporting_schema,
        recipes=recipes,
        ingredients=ingredients,
        marker_foods=_recipe_marker_food_rows(connection, supporting_schema),
    )


def planning_subject_source_payload(
    connection: Connection,
    *,
    recipe_schema: str,
    supporting_schema: str,
    recipe_id: UUID,
) -> dict[str, list[dict[str, Any]]]:
    """Load exactly the canonical planning inputs capable of affecting one Recipe."""

    recipes = _rows(
        connection,
        recipe_schema,
        "recipes",
        _RECIPE_COLUMNS,
        where_column="id",
        values={recipe_id},
    )
    ingredients = _rows(
        connection,
        recipe_schema,
        "recipe_ingredients",
        _INGREDIENT_COLUMNS,
        where_column="recipe_id",
        values={recipe_id},
    )
    marker_foods: list[dict[str, Any]] = []
    if recipes:
        marker_foods = _recipe_marker_food_rows_for_subject(
            connection,
            supporting_schema,
            recipe_id=recipe_id,
            owner_id=recipes[0]["user_id"],
        )
    return _planning_source_payload_for_rows(
        connection,
        supporting_schema=supporting_schema,
        recipes=recipes,
        ingredients=ingredients,
        marker_foods=marker_foods,
    )


def _planning_source_payload_for_rows(
    connection: Connection,
    *,
    supporting_schema: str,
    recipes: list[dict[str, Any]],
    ingredients: list[dict[str, Any]],
    marker_foods: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    food_ids = {row["food_item_id"] for row in recipes}
    food_ids.update(row["ingredient_food_item_id"] for row in ingredients)
    serving_ids = {
        row["serving_definition_id"]
        for row in ingredients
        if row["serving_definition_id"] is not None
    }
    user_ids = {row["user_id"] for row in recipes}
    referenced_foods = _rows(
        connection,
        supporting_schema,
        "food_items",
        _FOOD_COLUMNS,
        where_column="id",
        values=food_ids,
    )
    foods_by_id = {row["id"]: row for row in referenced_foods}
    foods_by_id.update({row["id"]: row for row in marker_foods})
    foods = sorted(foods_by_id.values(), key=lambda row: str(row["id"]))
    food_ids.update(foods_by_id)
    servings = _rows(
        connection,
        supporting_schema,
        "serving_definitions",
        _SERVING_COLUMNS,
        where_column="food_item_id",
        values=food_ids,
    )
    selected_servings = _rows(
        connection,
        supporting_schema,
        "serving_definitions",
        _SERVING_COLUMNS,
        where_column="id",
        values=serving_ids,
    )
    servings_by_id = {row["id"]: row for row in servings}
    servings_by_id.update({row["id"]: row for row in selected_servings})
    return {
        "recipes": recipes,
        "recipe_ingredients": ingredients,
        "users": _rows(
            connection,
            supporting_schema,
            "users",
            ("id",),
            where_column="id",
            values=user_ids,
        ),
        "food_items": foods,
        "serving_definitions": sorted(
            servings_by_id.values(), key=lambda row: str(row["id"])
        ),
        "food_nutrients": _rows(
            connection,
            supporting_schema,
            "food_nutrients",
            _NUTRIENT_COLUMNS,
            where_column="food_item_id",
            values=food_ids,
        ),
        "food_sources": _rows(
            connection,
            supporting_schema,
            "food_sources",
            _SOURCE_COLUMNS,
            where_column="food_item_id",
            values=food_ids,
        ),
    }


def _recipe_marker_food_rows_for_subject(
    connection: Connection,
    schema: str,
    *,
    recipe_id: UUID,
    owner_id: UUID,
) -> list[dict[str, Any]]:
    qualified = _qualified(connection, schema, "food_items")
    selected = ", ".join(
        connection.dialect.identifier_preparer.quote(value) for value in _FOOD_COLUMNS
    )
    rows = connection.execute(
        text(
            f"SELECT {selected} FROM {qualified} "
            "WHERE user_id = :owner_id AND source_type = 'recipe' "
            "AND source_id = :source_id"
        ),
        {"owner_id": owner_id, "source_id": str(recipe_id)},
    ).mappings().all()
    return sorted((dict(row) for row in rows), key=lambda row: str(row["id"]))


def _archive_checksums(payload: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    recipe_checksum = canonical_digest(payload["recipes"])
    ingredient_checksum = canonical_digest(payload["recipe_ingredients"])
    return {
        "recipe_count": len(payload["recipes"]),
        "ingredient_count": len(payload["recipe_ingredients"]),
        "recipes_checksum": recipe_checksum,
        "ingredients_checksum": ingredient_checksum,
        "archive_checksum": canonical_digest(
            {
                "recipes": recipe_checksum,
                "recipe_ingredients": ingredient_checksum,
            }
        ),
        "planning_source_checksum": canonical_digest(payload),
    }


def _current_revision(connection: Connection, schema: str) -> str | None:
    table_names = set(inspect(connection).get_table_names(schema=schema))
    if "alembic_version" not in table_names:
        return None
    rows = connection.scalars(
        text(f"SELECT version_num FROM {_qualified(connection, schema, 'alembic_version')}")
    ).all()
    return str(rows[0]) if len(rows) == 1 else None


def _lock_key(connection: Connection, source_schema: str) -> int:
    identity = database_identity(connection.engine.url)
    value = f"nutrition-phase5c:{identity.database}:{source_schema}".encode()
    return int.from_bytes(hashlib.sha256(value).digest()[:8], "big", signed=True)


@contextmanager
def phase5c_advisory_lock(connection: Connection, source_schema: str) -> Iterator[None]:
    key = _lock_key(connection, source_schema)
    connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": key})
    connection.commit()
    try:
        yield
    finally:
        connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
        connection.commit()


def _source_identity(
    connection: Connection,
    *,
    source_schema: str,
    archive_schema: str,
    isolation_evidence: dict[str, Any],
) -> dict[str, Any]:
    identity = database_identity(connection.engine.url)
    return {
        "driver_family": identity.driver_family,
        "host": identity.host,
        "port": identity.port,
        "database": identity.database,
        "source_schema": source_schema,
        "archive_schema": archive_schema,
        "conversion_clone_identity_digest": isolation_evidence[
            "conversion_clone_identity_digest"
        ],
    }


def _isolation_metadata(isolation_evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "marker_format_version": isolation_evidence["marker_format_version"],
        "isolation_evidence_contract_version": isolation_evidence[
            "isolation_evidence_contract_version"
        ],
        "clone_marker_identity": isolation_evidence["clone_marker_identity"],
        "clone_marker_digest": isolation_evidence["clone_marker_digest"],
        "clone_database_identity_digest": isolation_evidence[
            "clone_database_identity_digest"
        ],
        "source_production_identity_digest": isolation_evidence[
            "source_production_identity_digest"
        ],
        "operator_attestation_version": isolation_evidence[
            "operator_attestation_version"
        ],
        "operator_attestation_identity": isolation_evidence[
            "operator_attestation_identity"
        ],
        "operator_attestation_scope": isolation_evidence[
            "operator_attestation_scope"
        ],
        "operator_attestation_digest": isolation_evidence[
            "operator_attestation_digest"
        ],
    }


def _metadata_table(connection: Connection, archive_schema: str) -> str:
    return _qualified(connection, archive_schema, "bridge_metadata")


def _create_metadata_table(connection: Connection, archive_schema: str) -> None:
    connection.execute(
        text(
            f"""
            CREATE TABLE {_metadata_table(connection, archive_schema)} (
                archive_identity text PRIMARY KEY,
                source_driver_family text NOT NULL,
                source_host text NULL,
                source_port integer NULL,
                source_database text NOT NULL,
                source_schema text NOT NULL,
                archive_schema text NOT NULL UNIQUE,
                conversion_clone_identity_digest text NOT NULL,
                marker_format_version text NOT NULL,
                isolation_evidence_contract_version text NOT NULL,
                clone_marker_identity text NOT NULL,
                clone_marker_digest text NOT NULL,
                clone_database_identity_digest text NOT NULL,
                source_production_identity_digest text NOT NULL,
                operator_attestation_version text NOT NULL,
                operator_attestation_identity text NOT NULL,
                operator_attestation_scope text NOT NULL,
                operator_attestation_digest text NOT NULL,
                source_alembic_revision text NOT NULL,
                inventory_contract_version text NOT NULL,
                inventory_digest text NOT NULL,
                schema_signature text NOT NULL,
                schema_signature_digest text NOT NULL,
                recipe_count bigint NOT NULL,
                ingredient_count bigint NOT NULL,
                recipes_checksum text NOT NULL,
                ingredients_checksum text NOT NULL,
                archive_checksum text NOT NULL,
                planning_source_checksum text NOT NULL,
                conversion_rules_version text NOT NULL
            )
            """
        )
    )


def _insert_metadata(
    connection: Connection,
    archive_schema: str,
    metadata: dict[str, Any],
) -> None:
    columns = tuple(metadata)
    statement = text(
        f"INSERT INTO {_metadata_table(connection, archive_schema)} "
        f"({', '.join(columns)}) VALUES "
        f"({', '.join(':' + column for column in columns)})"
    )
    connection.execute(statement, metadata)


def load_bridge_metadata(connection: Connection, archive_schema: str) -> dict[str, Any]:
    inspector = inspect(connection)
    if "bridge_metadata" not in inspector.get_table_names(schema=archive_schema):
        raise Phase5CAdmissionError("Archive metadata is missing")
    rows = connection.execute(
        text(f"SELECT * FROM {_metadata_table(connection, archive_schema)}")
    ).mappings().all()
    if len(rows) != 1:
        raise Phase5CAdmissionError("Archive metadata must contain exactly one identity")
    return dict(rows[0])


def _create_placeholders(connection: Connection, source_schema: str) -> None:
    recipes = _qualified(connection, source_schema, "recipes")
    ingredients = _qualified(connection, source_schema, "recipe_ingredients")
    users = _qualified(connection, source_schema, "users")
    foods = _qualified(connection, source_schema, "food_items")
    servings = _qualified(connection, source_schema, "serving_definitions")
    connection.execute(
        text(
            f"""
            CREATE TABLE {recipes} (
                id uuid DEFAULT gen_random_uuid() NOT NULL,
                food_item_id uuid NOT NULL,
                user_id uuid NOT NULL,
                serving_count numeric(14, 6) NULL,
                final_yield_quantity numeric(14, 6) NULL,
                final_yield_unit text NULL,
                instructions text NULL,
                created_at timestamp with time zone DEFAULT now() NOT NULL,
                updated_at timestamp with time zone DEFAULT now() NOT NULL,
                CONSTRAINT recipes_pkey PRIMARY KEY (id),
                CONSTRAINT recipes_food_item_id_key UNIQUE (food_item_id),
                CONSTRAINT recipes_food_item_id_fkey FOREIGN KEY (food_item_id)
                    REFERENCES {foods} (id),
                CONSTRAINT recipes_user_id_fkey FOREIGN KEY (user_id) REFERENCES {users} (id)
            )
            """
        )
    )
    connection.execute(
        text(
            f"""
            CREATE TABLE {ingredients} (
                id uuid DEFAULT gen_random_uuid() NOT NULL,
                recipe_id uuid NOT NULL,
                ingredient_food_item_id uuid NOT NULL,
                quantity numeric(14, 6) NOT NULL,
                unit text NOT NULL,
                serving_definition_id uuid NULL,
                gram_amount numeric(14, 6) NULL,
                preparation_note text NULL,
                sort_order integer NOT NULL,
                CONSTRAINT recipe_ingredients_pkey PRIMARY KEY (id),
                CONSTRAINT recipe_ingredients_ingredient_food_item_id_fkey
                    FOREIGN KEY (ingredient_food_item_id) REFERENCES {foods} (id),
                CONSTRAINT recipe_ingredients_recipe_id_fkey
                    FOREIGN KEY (recipe_id) REFERENCES {recipes} (id),
                CONSTRAINT recipe_ingredients_serving_definition_id_fkey
                    FOREIGN KEY (serving_definition_id) REFERENCES {servings} (id)
            )
            """
        )
    )


def _ensure_archive_recipe_ingredient_lookup_index(
    connection: Connection,
    archive_schema: str,
    *,
    required: bool,
) -> None:
    state = archive_recipe_ingredient_lookup_index_state(connection, archive_schema)
    if state == "incompatible":
        raise Phase5CAdmissionError(
            "Archive Recipe ingredient lookup index definition differs"
        )
    if state == "valid" or not required:
        return

    name, table, columns = ARCHIVE_RECIPE_INGREDIENT_LOOKUP_INDEX
    quote = connection.dialect.identifier_preparer.quote
    qualified_table = _qualified(connection, archive_schema, table)
    rendered_columns = ", ".join(quote(column) for column in columns)
    connection.execute(
        text(f"CREATE INDEX {quote(name)} ON {qualified_table} ({rendered_columns})")
    )
    if archive_recipe_ingredient_lookup_index_state(connection, archive_schema) != "valid":
        raise Phase5CAdmissionError(
            "Archive Recipe ingredient lookup index verification failed"
        )


def _metadata_payload(
    *,
    source_identity: dict[str, Any],
    isolation_evidence: dict[str, Any],
    inventory_digest: str,
    checksums: dict[str, Any],
) -> dict[str, Any]:
    archive_identity = canonical_digest(
        {
            "source_identity": source_identity,
            "isolation_evidence": _isolation_metadata(isolation_evidence),
            "source_revision": SUPPORTED_SOURCE_REVISION,
            "inventory_digest": inventory_digest,
            "schema_signature": SUPPORTED_SCHEMA_SIGNATURE,
        }
    )
    return {
        "archive_identity": archive_identity,
        "source_driver_family": source_identity["driver_family"],
        "source_host": source_identity["host"],
        "source_port": source_identity["port"],
        "source_database": source_identity["database"],
        "source_schema": source_identity["source_schema"],
        "archive_schema": source_identity["archive_schema"],
        "conversion_clone_identity_digest": source_identity[
            "conversion_clone_identity_digest"
        ],
        **_isolation_metadata(isolation_evidence),
        "source_alembic_revision": SUPPORTED_SOURCE_REVISION,
        "inventory_contract_version": REPORT_SCHEMA_VERSION,
        "inventory_digest": inventory_digest,
        "schema_signature": SUPPORTED_SCHEMA_SIGNATURE,
        "schema_signature_digest": SCHEMA_SIGNATURE_DIGEST,
        **checksums,
        "conversion_rules_version": CONVERSION_RULES_VERSION,
    }


def _result(metadata: dict[str, Any], *, archive_created: bool) -> BridgeResult:
    return BridgeResult(
        {
            "archive_created": archive_created,
            "archive_identity": metadata["archive_identity"],
            "schema_signature": metadata["schema_signature"],
            "schema_signature_digest": metadata["schema_signature_digest"],
            "inventory_contract_version": metadata["inventory_contract_version"],
            "inventory_digest": metadata["inventory_digest"],
            "recipe_count": metadata["recipe_count"],
            "ingredient_count": metadata["ingredient_count"],
            "archive_checksum": metadata["archive_checksum"],
            "planning_source_checksum": metadata["planning_source_checksum"],
            "conversion_rules_version": metadata["conversion_rules_version"],
            "semantic_conversion_performed": False,
        }
    )


def _verify_existing_archive(
    connection: Connection,
    *,
    source_schema: str,
    archive_schema: str,
    inventory_digest: str,
    isolation_evidence: dict[str, Any],
) -> BridgeResult:
    metadata = load_bridge_metadata(connection, archive_schema)
    identity = _source_identity(
        connection,
        source_schema=source_schema,
        archive_schema=archive_schema,
        isolation_evidence=isolation_evidence,
    )
    expected_archive_identity = canonical_digest(
        {
            "source_identity": identity,
            "isolation_evidence": _isolation_metadata(isolation_evidence),
            "source_revision": SUPPORTED_SOURCE_REVISION,
            "inventory_digest": inventory_digest,
            "schema_signature": SUPPORTED_SCHEMA_SIGNATURE,
        }
    )
    required = {
        "archive_identity": expected_archive_identity,
        "source_driver_family": identity["driver_family"],
        "source_host": identity["host"],
        "source_port": identity["port"],
        "source_database": identity["database"],
        "conversion_clone_identity_digest": identity[
            "conversion_clone_identity_digest"
        ],
        **_isolation_metadata(isolation_evidence),
        "source_alembic_revision": SUPPORTED_SOURCE_REVISION,
        "inventory_contract_version": REPORT_SCHEMA_VERSION,
        "inventory_digest": inventory_digest,
        "schema_signature": SUPPORTED_SCHEMA_SIGNATURE,
        "schema_signature_digest": SCHEMA_SIGNATURE_DIGEST,
        "source_schema": source_schema,
        "archive_schema": archive_schema,
        "conversion_rules_version": CONVERSION_RULES_VERSION,
    }
    if any(metadata.get(key) != value for key, value in required.items()):
        raise Phase5CAdmissionError("Existing archive metadata does not match this bridge request")
    require_supported_legacy_schema(connection, archive_schema)
    payload = planning_source_payload(
        connection,
        recipe_schema=archive_schema,
        supporting_schema=source_schema,
    )
    checksums = _archive_checksums(payload)
    if any(metadata.get(key) != value for key, value in checksums.items()):
        raise Phase5CAdmissionError("Existing archive checksum verification failed")
    revision = _current_revision(connection, source_schema)
    if revision == SUPPORTED_SOURCE_REVISION:
        require_supported_legacy_schema(connection, source_schema)
        if connection.scalar(
            text(f"SELECT count(*) FROM {_qualified(connection, source_schema, 'recipes')}")
        ):
            raise Phase5CAdmissionError("Legacy placeholder recipes table is not empty")
        if connection.scalar(
            text(
                f"SELECT count(*) FROM "
                f"{_qualified(connection, source_schema, 'recipe_ingredients')}"
            )
        ):
            raise Phase5CAdmissionError("Legacy placeholder ingredients table is not empty")
    elif revision not in {
        "0004_recipe_domain_foundation",
        "0005_recipe_display_units",
        "0006_recipe_needs_republish",
        "0007_log_food_name_snapshot",
        "0008_recipe_pub_revisions",
        "0009_log_creation_idempotency",
        "0010_ocr_confirmation_trace",
        "0011_nutrition_target_foundation",
        "0012_food_favorites",
        "0013_food_recipe_integrity",
        "0014_create_idempotency",
        CONTROL_REVISION,
        "0016_phase5c_execution",
        EXECUTION_REVISION,
    }:
        raise Phase5CAdmissionError("Existing archive is paired with an unsupported migration state")
    _ensure_archive_recipe_ingredient_lookup_index(
        connection,
        archive_schema,
        required=revision == EXECUTION_REVISION,
    )
    return _result(metadata, archive_created=False)


def _validate_locked_legacy_source(
    connection: Connection,
    *,
    source_schema: str,
    inventory_digest: str,
) -> None:
    revision = _current_revision(connection, source_schema)
    if revision != SUPPORTED_SOURCE_REVISION:
        raise Phase5CAdmissionError(
            f"Bridge source revision must be {SUPPORTED_SOURCE_REVISION}"
        )
    live_inventory = HistoricalDatabaseInventory(connection).inspect().to_dict()
    if canonical_digest(live_inventory) != inventory_digest:
        raise Phase5CAdmissionError(
            "Inventory document does not match the locked conversion-clone state"
        )
    classification = live_inventory.get("classification", {}).get("value")
    if classification != "legacy_conversion_required":
        raise Phase5CAdmissionError(
            "Inventory classification must be legacy_conversion_required"
        )
    if live_inventory.get("limitations"):
        raise Phase5CAdmissionError("Inventory contains unsupported limitations")
    require_supported_legacy_schema(connection, source_schema)
    _require_supporting_schema(connection, source_schema)


def establish_conversion_clone_marker(
    engine: Engine,
    *,
    inventory_payload: dict[str, Any],
    archive_schema: str,
    clone_marker_identity: str,
    conversion_clone_id: str,
    attestation_payload: dict[str, Any],
) -> dict[str, Any]:
    """Record non-destructive evidence on an exact, unbridged PostgreSQL clone."""
    inventory_payload = validate_inventory_contract(inventory_payload)
    archive_schema = _validate_identifier(archive_schema, "archive schema")
    attestation = validate_operator_attestation(attestation_payload)
    inventory_digest = canonical_digest(inventory_payload)
    expected_evidence = {
        "clone_marker_identity": clone_marker_identity,
        "conversion_clone_identity_digest": conversion_clone_identity_digest(
            conversion_clone_id
        ),
        "inventory_digest": inventory_digest,
        "schema_signature": {
            "name": SUPPORTED_SCHEMA_SIGNATURE,
            "digest": SCHEMA_SIGNATURE_DIGEST,
        },
        "conversion_rules_version": CONVERSION_RULES_VERSION,
    }
    if any(attestation.get(key) != value for key, value in expected_evidence.items()):
        raise Phase5CAdmissionError(
            "Operator attestation does not match marker-preflight evidence"
        )
    if engine.dialect.name != "postgresql":
        raise Phase5CAdmissionError("Conversion-clone markers support PostgreSQL only")

    with engine.connect().execution_options(isolation_level="SERIALIZABLE") as connection:
        source_schema = _validate_identifier(
            str(connection.scalar(text("SELECT current_schema()"))), "source schema"
        )
        if source_schema == archive_schema:
            raise Phase5CAdmissionError("Archive schema must differ from the source schema")
        connection.commit()
        with phase5c_advisory_lock(connection, source_schema):
            with connection.begin():
                if archive_schema in inspect(connection).get_schema_names():
                    raise Phase5CAdmissionError(
                        "Conversion-clone marker requires an unbridged source"
                    )
                recipes = _qualified(connection, source_schema, "recipes")
                ingredients = _qualified(connection, source_schema, "recipe_ingredients")
                connection.execute(text(f"LOCK TABLE {recipes}, {ingredients} IN SHARE MODE"))
                _validate_locked_legacy_source(
                    connection,
                    source_schema=source_schema,
                    inventory_digest=inventory_digest,
                )
                return establish_clone_marker_on_connection(
                    connection,
                    attestation_payload=attestation,
                    clone_marker_identity=clone_marker_identity,
                    conversion_clone_id=conversion_clone_id,
                )


def bridge_legacy_recipes(
    engine: Engine,
    *,
    inventory_payload: dict[str, Any],
    archive_schema: str,
    conversion_clone_id: str,
    clone_marker_identity: str,
    attestation_payload: dict[str, Any],
) -> BridgeResult:
    """Archive canonical pre-0004 Recipe rows without performing semantic conversion."""
    inventory_payload = validate_inventory_contract(inventory_payload)
    archive_schema = _validate_identifier(archive_schema, "archive schema")
    if engine.dialect.name != "postgresql":
        raise Phase5CAdmissionError("The Phase 5C bridge supports PostgreSQL only")

    provided_inventory_digest = canonical_digest(inventory_payload)
    with engine.connect().execution_options(isolation_level="SERIALIZABLE") as connection:
        source_schema = _validate_identifier(
            str(connection.scalar(text("SELECT current_schema()"))), "source schema"
        )
        if source_schema == archive_schema:
            raise Phase5CAdmissionError("Archive schema must differ from the source schema")
        isolation_evidence = verify_clone_isolation_evidence(
            connection,
            attestation_payload=attestation_payload,
            clone_marker_identity=clone_marker_identity,
            conversion_clone_id=conversion_clone_id,
            inventory_digest=provided_inventory_digest,
            schema_signature=SUPPORTED_SCHEMA_SIGNATURE,
            schema_signature_digest=SCHEMA_SIGNATURE_DIGEST,
            operation="bridge",
        )
        with phase5c_maintenance_session(
            connection, isolation_evidence["clone_marker_digest"]
        ):
            assert_database_session_isolation(
                connection, isolation_evidence["clone_marker_digest"]
            )
            connection.commit()
            with phase5c_advisory_lock(connection, source_schema):
                isolation_evidence = verify_clone_isolation_evidence(
                    connection,
                    attestation_payload=attestation_payload,
                    clone_marker_identity=clone_marker_identity,
                    conversion_clone_id=conversion_clone_id,
                    inventory_digest=provided_inventory_digest,
                    schema_signature=SUPPORTED_SCHEMA_SIGNATURE,
                    schema_signature_digest=SCHEMA_SIGNATURE_DIGEST,
                    operation="bridge",
                )
                assert_database_session_isolation(
                    connection, isolation_evidence["clone_marker_digest"]
                )
                connection.commit()
                with connection.begin():
                    archive_exists = archive_schema in inspect(connection).get_schema_names()
                    if archive_exists:
                        return _verify_existing_archive(
                            connection,
                            source_schema=source_schema,
                            archive_schema=archive_schema,
                            inventory_digest=provided_inventory_digest,
                            isolation_evidence=isolation_evidence,
                        )

                    recipes = _qualified(connection, source_schema, "recipes")
                    ingredients = _qualified(connection, source_schema, "recipe_ingredients")
                    connection.execute(
                        text(f"LOCK TABLE {recipes}, {ingredients} IN ACCESS EXCLUSIVE MODE")
                    )
                    _validate_locked_legacy_source(
                        connection,
                        source_schema=source_schema,
                        inventory_digest=provided_inventory_digest,
                    )
                    source_payload = planning_source_payload(
                        connection,
                        recipe_schema=source_schema,
                        supporting_schema=source_schema,
                    )
                    checksums = _archive_checksums(source_payload)
                    source_identity = _source_identity(
                        connection,
                        source_schema=source_schema,
                        archive_schema=archive_schema,
                        isolation_evidence=isolation_evidence,
                    )
                    metadata = _metadata_payload(
                        source_identity=source_identity,
                        isolation_evidence=isolation_evidence,
                        inventory_digest=provided_inventory_digest,
                        checksums=checksums,
                    )

                    archive = connection.dialect.identifier_preparer.quote(archive_schema)
                    connection.execute(text(f"CREATE SCHEMA {archive}"))
                    connection.execute(
                        text(f"ALTER TABLE {ingredients} SET SCHEMA {archive}")
                    )
                    connection.execute(text(f"ALTER TABLE {recipes} SET SCHEMA {archive}"))
                    _ensure_archive_recipe_ingredient_lookup_index(
                        connection,
                        archive_schema,
                        required=True,
                    )
                    _create_placeholders(connection, source_schema)
                    require_supported_legacy_schema(connection, source_schema)
                    require_supported_legacy_schema(connection, archive_schema)
                    _create_metadata_table(connection, archive_schema)
                    _insert_metadata(connection, archive_schema, metadata)

                    archived_payload = planning_source_payload(
                        connection,
                        recipe_schema=archive_schema,
                        supporting_schema=source_schema,
                    )
                    if _archive_checksums(archived_payload) != checksums:
                        raise Phase5CAdmissionError(
                            "Archive verification failed before commit"
                        )
                    return _result(metadata, archive_created=True)
