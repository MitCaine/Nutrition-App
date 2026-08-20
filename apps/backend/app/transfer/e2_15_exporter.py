"""Read-only PostgreSQL exporter for the one approved E2-15 handoff."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import secrets
from typing import Any, Mapping, Sequence
from uuid import NAMESPACE_DNS, UUID, uuid5

from pydantic import ValidationError
from sqlalchemy import Connection, create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.catalog.nutrients import nutrient_seed_rows
from app.core.database_identity import database_connect_args
from app.domain.nutrition import NutrientDataStatus, NutrientSnapshot
from app.nutrition.aggregation import aggregate_snapshots
from app.operators.immutable_provenance_qualification import (
    ImmutableProvenanceQualificationError,
    qualify_immutable_provenance_manifest,
)
from app.operators.current_runtime_authority import (
    CurrentRuntimeAuthorityError,
    qualify_current_runtime_authority,
)
from app.operators.phase5c_contracts import Phase5CAdmissionError
from app.operators.phase5c_isolation import load_clone_marker
from app.schemas.log import DailyLogResponse
from app.transfer.e2_15 import (
    CONTRACT,
    SCHEMA_CONTRACT_DIGEST,
    SECTION_CONTRACTS,
    SECTION_NAMES,
    SOURCE_SCHEMA,
    TransferPackageError,
    build_daily_totals_section,
    build_section,
    canonical_digest,
    canonical_transfer_json,
    canonicalize_transfer_scalar,
    sort_transfer_records,
    serialize_transfer_document,
    validate_transfer_package,
    validate_portable_receipt,
    with_overall_digest,
)


class TransferExportError(RuntimeError):
    """Fail closed without exposing owner data or connection details."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> TransferExportError:
    return TransferExportError(code, message)


REQUIRED_EXPORT_SELECT_TABLES = tuple(
    dict.fromkeys(
        (
            "alembic_version",
            "nutrients",
            *SECTION_NAMES,
            *CONTRACT["source"]["optional_public_tables"],
        )
    )
)
OPTIONAL_CLONE_MARKER_TABLE = "phase5c_conversion_clone_marker"
EXPECTED_CLONE_MARKER_PROTECTIONS = (
    (
        "phase5c_clone_marker_immutable_row",
        27,
        "O",
        "public",
        "phase5c_reject_immutable_row_mutation",
    ),
    (
        "phase5c_clone_marker_immutable_truncate",
        34,
        "O",
        "public",
        "phase5c_reject_immutable_truncate",
    ),
)
_POSTGRES_DIALECT = postgresql.dialect()
CURRENT_EXPORT_SOURCE_REVISION = "0033_complete_runtime_authority"


def canonical_owner_id(value: str) -> str:
    try:
        parsed = str(UUID(value))
    except (AttributeError, TypeError, ValueError):
        raise _fail("invalid_owner_id", "Owner ID must be a canonical UUID.") from None
    if parsed != value:
        raise _fail("invalid_owner_id", "Owner ID must be a canonical UUID.")
    return parsed


def validate_output_path(path: Path) -> Path:
    candidate = path.expanduser().resolve(strict=False)
    if candidate.suffixes[-2:] != [".nutrition-transfer", ".json"]:
        raise _fail("invalid_output_path", "Output must use .nutrition-transfer.json.")
    if not candidate.parent.is_dir() or candidate.exists():
        raise _fail("invalid_output_path", "Output directory must exist and output must not exist.")
    cloud_markers = {"mobile documents", "icloud drive", "dropbox", "onedrive", "google drive"}
    if any(part.casefold() in cloud_markers for part in candidate.parts):
        raise _fail("invalid_output_path", "Output must be on a non-cloud-synced local path.")
    return candidate


def validate_export_session_observation(observation: Mapping[str, Any]) -> None:
    expected = {
        "current_user": "nutrition_qualifier",
        "session_user": "nutrition_qualifier",
        "default_read_only": "on",
        "transaction_read_only": "on",
        "transaction_isolation": "serializable",
        "transaction_deferrable": "on",
        "postgres_major": "16",
        "role_superuser": False,
        "role_create_db": False,
        "role_create_role": False,
        "role_replication": False,
        "role_bypass_rls": False,
        "database_create": False,
        "database_temp": False,
        "schema_create": False,
        "missing_select_count": 0,
        "write_privilege_count": 0,
        "sequence_write_privilege_count": 0,
    }
    if dict(observation) != expected:
        raise _fail(
            "source_authority_invalid",
            "PostgreSQL export authority is not the fixed read-only qualifier role.",
        )


def qualify_export_session(connection: Connection) -> None:
    observation = dict(
        connection.execute(
            text(
                """
                SELECT current_user::text AS current_user,
                       session_user::text AS session_user,
                       current_setting('default_transaction_read_only') AS default_read_only,
                       current_setting('transaction_read_only') AS transaction_read_only,
                       current_setting('transaction_isolation') AS transaction_isolation,
                       current_setting('transaction_deferrable') AS transaction_deferrable,
                       current_setting('server_version_num')::integer / 10000 AS postgres_major,
                       role.rolsuper AS role_superuser,
                       role.rolcreatedb AS role_create_db,
                       role.rolcreaterole AS role_create_role,
                       role.rolreplication AS role_replication,
                       role.rolbypassrls AS role_bypass_rls,
                       pg_catalog.has_database_privilege(current_user, current_database(), 'CREATE') AS database_create,
                       pg_catalog.has_database_privilege(current_user, current_database(), 'TEMP') AS database_temp,
                       pg_catalog.has_schema_privilege(current_user, 'public', 'CREATE') AS schema_create,
                       (SELECT count(*)
                          FROM pg_catalog.pg_class relation
                          JOIN pg_catalog.pg_namespace namespace ON namespace.oid = relation.relnamespace
                         WHERE namespace.nspname = 'public'
                           AND relation.relkind IN ('r', 'p')
                           AND relation.relname = ANY(CAST(:tables AS text[]))
                           AND NOT pg_catalog.has_table_privilege(current_user, relation.oid, 'SELECT')) AS missing_select_count,
                       (SELECT count(*)
                          FROM pg_catalog.pg_class relation
                          JOIN pg_catalog.pg_namespace namespace ON namespace.oid = relation.relnamespace
                         WHERE namespace.nspname = 'public'
                           AND relation.relkind IN ('r', 'p')
                           AND relation.relname = ANY(CAST(:write_tables AS text[]))
                           AND (pg_catalog.has_table_privilege(current_user, relation.oid, 'INSERT')
                             OR pg_catalog.has_table_privilege(current_user, relation.oid, 'UPDATE')
                             OR pg_catalog.has_table_privilege(current_user, relation.oid, 'DELETE')
                             OR pg_catalog.has_table_privilege(current_user, relation.oid, 'TRUNCATE')
                             OR pg_catalog.has_table_privilege(current_user, relation.oid, 'REFERENCES')
                             OR pg_catalog.has_table_privilege(current_user, relation.oid, 'TRIGGER'))) AS write_privilege_count,
                       (SELECT count(*)
                          FROM pg_catalog.pg_class relation
                          JOIN pg_catalog.pg_namespace namespace ON namespace.oid = relation.relnamespace
                         WHERE namespace.nspname = 'public'
                           AND relation.relkind = 'S'
                           AND (pg_catalog.has_sequence_privilege(current_user, relation.oid, 'USAGE')
                             OR pg_catalog.has_sequence_privilege(current_user, relation.oid, 'UPDATE'))) AS sequence_write_privilege_count
                  FROM pg_catalog.pg_roles role
                 WHERE role.rolname = current_user
                """
            ),
            {
                "tables": list(REQUIRED_EXPORT_SELECT_TABLES),
                "write_tables": [
                    *CONTRACT["source"]["expected_public_tables"],
                    *CONTRACT["source"]["optional_public_tables"],
                ],
            },
        ).mappings().one()
    )
    observation["postgres_major"] = str(observation["postgres_major"])
    for key in ("missing_select_count", "write_privilege_count", "sequence_write_privilege_count"):
        observation[key] = int(observation[key])
    validate_export_session_observation(observation)


def _normalize_space(value: Any) -> str:
    return " ".join(str(value).strip().split())


def _type_text(value: Any) -> str:
    if hasattr(value, "compile"):
        value = value.compile(dialect=_POSTGRES_DIALECT)
    rendered = _normalize_space(value).lower().replace(", ", ",")
    return rendered.replace("varchar", "character varying", 1) if rendered.startswith("varchar") else rendered


def normalize_reflected_foreign_key_options(options: Mapping[str, Any]) -> dict[str, Any]:
    """Render PostgreSQL's omitted FK clauses as their exact default semantics."""

    return {
        "deferrable": bool(options.get("deferrable", False)),
        "initially": options.get("initially"),
        "match": options.get("match") or "SIMPLE",
        "ondelete": options.get("ondelete") or "NO ACTION",
        "onupdate": options.get("onupdate") or "NO ACTION",
    }


_TEXT_LITERAL_CAST = re.compile(r"^'((?:''|[^'])*)'::(?:text|character varying)$", re.I)
_INLINE_TEXT_LITERAL_CAST = re.compile(
    r"('(?:''|[^'])*')::(?:text|character varying)", re.I
)
_SIMPLE_PREDICATE_GROUP = re.compile(
    r"\(([^()]*(?:"
    r"\bIS\s+(?:NOT\s+)?NULL\b"
    r"|=\s*(?:true|false|'(?:''|[^'])*')"
    r"|<>\s*'(?:''|[^'])*'"
    r")[^()]*)\)",
    re.I,
)


def normalize_reflected_default(value: Any, expected: str | None) -> str:
    """Accept only known PostgreSQL textual rendering of an equal default."""

    rendered = _normalize_space(value)
    literal = _TEXT_LITERAL_CAST.fullmatch(rendered)
    if literal is not None and expected == literal.group(1).replace("''", "'"):
        return expected
    return rendered


def _predicate_comparison_form(value: str) -> str:
    rendered = _INLINE_TEXT_LITERAL_CAST.sub(r"\1", _normalize_space(value))
    previous = None
    while rendered != previous:
        previous = rendered
        rendered = _SIMPLE_PREDICATE_GROUP.sub(lambda match: match.group(1).strip(), rendered)
    return rendered.casefold()


def normalize_reflected_predicate(value: Any, expected: str | None) -> str | None:
    """Collapse only inspector-added grouping/casts when the frozen SQL is equal."""

    if value is None:
        return None
    rendered = _normalize_space(value)
    if expected is not None and _predicate_comparison_form(rendered) == _predicate_comparison_form(expected):
        return expected
    return rendered


def observe_source_schema(connection: Connection) -> dict[str, Any]:
    """Project pg_catalog through SQLAlchemy's PostgreSQL inspector."""

    inspector = inspect(connection)
    table_names = sorted(inspector.get_table_names(schema="public"))
    tables: dict[str, Any] = {}
    for name in table_names:
        expected = SOURCE_SCHEMA["tables"].get(name, {})
        expected_foreign_keys = expected.get("foreign_keys", [])
        expected_uniques = expected.get("unique_constraints", [])
        expected_columns = {item["name"]: item for item in expected.get("columns", [])}
        columns = [
            {
                "default": None if item.get("default") is None else normalize_reflected_default(
                    item["default"], expected_columns.get(item["name"], {}).get("default")
                ),
                "name": item["name"],
                "nullable": bool(item["nullable"]),
                "type": _type_text(item["type"]),
            }
            for item in inspector.get_columns(name, schema="public")
        ]
        foreign_keys = []
        for item in inspector.get_foreign_keys(name, schema="public"):
            signature = (list(item["constrained_columns"]), item["referred_table"], list(item["referred_columns"]))
            matched = next((candidate for candidate in expected_foreign_keys if (candidate["columns"], candidate["target_table"], candidate["target_columns"]) == signature), None)
            options = normalize_reflected_foreign_key_options(item.get("options") or {})
            foreign_keys.append({
                "columns": signature[0],
                "deferrable": options["deferrable"],
                "initially": options["initially"],
                "match": options["match"],
                "name": matched["name"] if matched is not None else item.get("name"),
                "ondelete": options["ondelete"],
                "onupdate": options["onupdate"],
                "target_columns": signature[2],
                "target_table": signature[1],
            })
        unique_constraints = []
        for item in inspector.get_unique_constraints(name, schema="public"):
            columns_value = list(item["column_names"])
            matched = next((candidate for candidate in expected_uniques if candidate["columns"] == columns_value), None)
            unique_constraints.append({"columns": columns_value, "name": matched["name"] if matched is not None else item.get("name")})
        checks = [
            {"expression": _normalize_space(item["sqltext"]), "name": item.get("name")}
            for item in inspector.get_check_constraints(name, schema="public")
        ]
        expected_indexes = {item["name"]: item for item in expected.get("indexes", [])}
        indexes = []
        for item in inspector.get_indexes(name, schema="public"):
            if item.get("duplicates_constraint"):
                continue
            index_name = item.get("name")
            predicate = (item.get("dialect_options") or {}).get("postgresql_where")
            indexes.append({
                "columns": list(item["column_names"]),
                "name": index_name,
                "predicate": normalize_reflected_predicate(
                    predicate, expected_indexes.get(index_name, {}).get("predicate")
                ),
                "unique": bool(item["unique"]),
            })
        tables[name] = {
            "checks": sorted(checks, key=lambda item: (item["name"] or "", item["expression"])),
            "columns": columns,
            "foreign_keys": sorted(foreign_keys, key=lambda item: (item["name"] or "", item["columns"])),
            "indexes": sorted(indexes, key=lambda item: item["name"] or ""),
            "primary_key": list(inspector.get_pk_constraint(name, schema="public")["constrained_columns"]),
            "unique_constraints": sorted(unique_constraints, key=lambda item: (item["name"] or "", item["columns"])),
        }
    return {**SOURCE_SCHEMA, "tables": tables}


def project_current_source_tables_to_frozen_contract(
    actual: Mapping[str, Any],
) -> dict[str, Any]:
    """Qualify the current 0033 source schema.

    The function name is retained for the established test seam. E2-15 v3
    qualifies the current source directly: source-identity semantics, the
    current nutrient catalog, and explicit Daily Log Complete state remain
    visible rather than being projected back to an older contract.
    """

    validate_source_schema_tables(actual)
    return {name: dict(table) for name, table in actual.items()}


def validate_source_schema_tables(actual: Mapping[str, Any]) -> bool:
    required = SOURCE_SCHEMA["tables"]
    optional = SOURCE_SCHEMA["optional_tables"]
    actual_names = set(actual)
    required_names = set(required)
    extra_names = actual_names - required_names
    if (
        required_names - actual_names
        or extra_names not in (set(), {OPTIONAL_CLONE_MARKER_TABLE})
        or {name: actual[name] for name in required_names} != required
    ):
        raise _fail(
            "source_schema_invalid",
            "PostgreSQL source schema differs from pg-0033.",
        )
    marker_present = OPTIONAL_CLONE_MARKER_TABLE in extra_names
    if marker_present and actual[OPTIONAL_CLONE_MARKER_TABLE] != optional[
        OPTIONAL_CLONE_MARKER_TABLE
    ]:
        raise _fail(
            "source_schema_invalid",
            "PostgreSQL optional clone-marker schema differs from pg-0033.",
        )
    return marker_present


def observe_clone_marker_protections(
    connection: Connection,
) -> tuple[tuple[str, int, str, str, str], ...]:
    rows = connection.execute(
        text(
            """
            SELECT trigger.tgname::text AS trigger_name,
                   trigger.tgtype::integer AS trigger_type,
                   trigger.tgenabled::text AS trigger_enabled,
                   routine_schema.nspname::text AS routine_schema,
                   routine.proname::text AS routine_name
              FROM pg_catalog.pg_trigger trigger
              JOIN pg_catalog.pg_class relation ON relation.oid = trigger.tgrelid
              JOIN pg_catalog.pg_namespace relation_schema
                ON relation_schema.oid = relation.relnamespace
              JOIN pg_catalog.pg_proc routine ON routine.oid = trigger.tgfoid
              JOIN pg_catalog.pg_namespace routine_schema
                ON routine_schema.oid = routine.pronamespace
             WHERE relation_schema.nspname = 'public'
               AND relation.relname = 'phase5c_conversion_clone_marker'
               AND NOT trigger.tgisinternal
             ORDER BY trigger.tgname
            """
        )
    ).mappings()
    return tuple(
        (
            str(row["trigger_name"]),
            int(row["trigger_type"]),
            str(row["trigger_enabled"]),
            str(row["routine_schema"]),
            str(row["routine_name"]),
        )
        for row in rows
    )


def qualify_optional_clone_marker(connection: Connection) -> dict[str, Any]:
    try:
        marker = load_clone_marker(connection)
    except Phase5CAdmissionError:
        raise _fail(
            "source_marker_invalid",
            "PostgreSQL conversion-clone marker is invalid.",
        ) from None
    try:
        protections = observe_clone_marker_protections(connection)
    except SQLAlchemyError:
        raise _fail(
            "source_immutability_invalid",
            "PostgreSQL conversion-clone marker protection is invalid.",
        ) from None
    if protections != EXPECTED_CLONE_MARKER_PROTECTIONS:
        raise _fail(
            "source_immutability_invalid",
            "PostgreSQL conversion-clone marker protection is invalid.",
        )
    return marker


def qualify_source_schema(connection: Connection) -> None:
    revisions = list(connection.scalars(text("SELECT version_num::text FROM public.alembic_version ORDER BY version_num")))
    if revisions != [CURRENT_EXPORT_SOURCE_REVISION]:
        raise _fail(
            "source_schema_invalid",
            "PostgreSQL migration head is unsupported.",
        )
    observed = observe_source_schema(connection)
    if canonical_digest(SOURCE_SCHEMA) != SCHEMA_CONTRACT_DIGEST:
        raise _fail(
            "source_schema_invalid",
            "Installed pg-0033 schema contract is invalid.",
        )
    projected_tables = project_current_source_tables_to_frozen_contract(
        observed["tables"]
    )
    marker_present = validate_source_schema_tables(projected_tables)
    if marker_present:
        qualify_optional_clone_marker(connection)
    try:
        qualify_immutable_provenance_manifest(connection)
        qualify_current_validator_inputs(connection)
    except (ImmutableProvenanceQualificationError, SQLAlchemyError):
        raise _fail("source_immutability_invalid", "PostgreSQL immutable provenance protection is invalid.") from None


def qualify_current_validator_inputs(connection: Connection) -> None:
    try:
        qualify_current_runtime_authority(connection, expected_state="normal")
    except CurrentRuntimeAuthorityError:
        raise ImmutableProvenanceQualificationError(
            "immutable_provenance_current_runtime_authority_invalid"
        ) from None


def qualify_source_nutrients(connection: Connection) -> None:
    columns = (
        "id", "display_name", "default_unit", "nutrient_kind",
        "parent_nutrient_id", "display_order",
    )
    rows = [
        {column: row[column] for column in columns}
        for row in connection.execute(
            text(
                'SELECT "id", "display_name", "default_unit", "nutrient_kind", '
                '"parent_nutrient_id", "display_order" FROM public."nutrients" '
                'ORDER BY "display_order", "id"'
            )
        ).mappings()
    ]
    expected = nutrient_seed_rows()
    preimage = {"count": len(rows), "name": "nutrients", "records": rows}
    if rows != expected or canonical_digest(preimage) != CONTRACT["nutrient_catalog_digest"]:
        raise _fail("source_nutrients_invalid", "PostgreSQL nutrient catalog is unsupported.")


_OWNER_DIRECT = {
    "users": '"id" = :owner_id',
    "user_profiles": '"user_id" = :owner_id',
    "food_items": '"user_id" = :owner_id',
    "food_favorites": '"user_id" = :owner_id',
    "recipes": '"user_id" = :owner_id',
    "recipe_ingredients": '"user_id" = :owner_id',
    "recipe_publication_revisions": '"user_id" = :owner_id',
    "daily_logs": '"user_id" = :owner_id',
    "daily_log_day_completions": '"user_id" = :owner_id',
    "ocr_nutrition_confirmation_traces": '"user_id" = :owner_id',
    "nutrition_targets": '"user_id" = :owner_id',
}
_CHILD_FILTERS = {
    "food_sources": 'EXISTS (SELECT 1 FROM public.food_items parent WHERE parent.id = source."food_item_id" AND parent.user_id = :owner_id)',
    "food_nutrients": 'EXISTS (SELECT 1 FROM public.food_items parent WHERE parent.id = source."food_item_id" AND parent.user_id = :owner_id)',
    "serving_definitions": 'EXISTS (SELECT 1 FROM public.food_items parent WHERE parent.id = source."food_item_id" AND parent.user_id = :owner_id)',
    "recipe_publication_amount_definitions": 'EXISTS (SELECT 1 FROM public.recipe_publication_revisions parent WHERE parent.id = source."revision_id" AND parent.user_id = :owner_id)',
    "recipe_publication_nutrients": 'EXISTS (SELECT 1 FROM public.recipe_publication_revisions parent WHERE parent.id = source."revision_id" AND parent.user_id = :owner_id)',
    "daily_log_nutrient_snapshots": 'EXISTS (SELECT 1 FROM public.daily_logs parent WHERE parent.id = source."daily_log_id" AND parent.user_id = :owner_id)',
}


def _canonical_row(section_name: str, row: Mapping[str, Any]) -> dict[str, Any]:
    contract = SECTION_CONTRACTS[section_name]
    return {
        column: canonicalize_transfer_scalar(kind, row[column])
        for column, kind in contract["columns"]
    }


def source_select_expression(column: str, kind: str) -> str:
    """Preserve SQL NULL separately from a JSON/JSONB literal null."""

    scalar_kind = kind.removeprefix("nullable_")
    if scalar_kind == "json_document":
        return f'CAST(source."{column}" AS text) AS "{column}"'
    return f'source."{column}"'


def _read_section(connection: Connection, name: str, owner_id: str) -> list[dict[str, Any]]:
    contract = SECTION_CONTRACTS[name]
    columns = ", ".join(
        source_select_expression(column, kind)
        for column, kind in contract["columns"]
    )
    predicate = _OWNER_DIRECT.get(name) or _CHILD_FILTERS[name]
    rows = connection.execute(
        text(f'SELECT {columns} FROM public."{name}" AS source WHERE {predicate}'),
        {"owner_id": owner_id},
    ).mappings()
    return sort_transfer_records(
        [_canonical_row(name, row) for row in rows],
        contract["primary_key"],
    )


def translate_update_receipt(row: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = row["response_snapshot"]
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except json.JSONDecodeError:
            raise _fail("source_idempotency_invalid", "Completed update receipt is malformed.") from None
    if not isinstance(snapshot, Mapping):
        raise _fail("source_idempotency_invalid", "Completed update receipt is malformed.")
    result = dict(snapshot)
    try:
        source_date = result.pop("_source_logged_date")
        destination_date = result.pop("_destination_logged_date")
    except KeyError:
        raise _fail("source_idempotency_invalid", "Completed update receipt is malformed.") from None
    try:
        remote_result = DailyLogResponse.model_validate(result).model_dump(mode="json")
    except ValidationError:
        raise _fail("source_idempotency_invalid", "Completed update receipt is malformed.") from None
    if remote_result != result:
        raise _fail("source_idempotency_invalid", "Completed update receipt is malformed.")
    local_result = {
        key: remote_result[key]
        for key in (
            "id",
            "food_item_id",
            "food_name_snapshot",
            "is_editable",
            "source_food_available",
            "edit_block_reason",
            "logged_date",
            "meal_type",
            "amount_quantity",
            "amount_unit",
            "serving_definition_id",
            "gram_amount",
            "notes",
            "created_at",
            "updated_at",
        )
    }
    local = {
        "kind": "log.update",
        "source_logged_date": canonicalize_transfer_scalar("date", source_date),
        "destination_logged_date": canonicalize_transfer_scalar("date", destination_date),
        "result": local_result,
    }
    translated = dict(row)
    translated["response_snapshot"] = local
    return translated


def _canonical_source_receipt(
    row: Mapping[str, Any],
    *,
    allow_excluded_delete: bool = False,
) -> dict[str, Any]:
    try:
        return {
            column: (
                "log.delete"
                if column == "operation"
                and allow_excluded_delete
                and row[column] == "log.delete"
                else canonicalize_transfer_scalar(kind, row[column])
            )
            for column, kind in SECTION_CONTRACTS[
                "create_operation_idempotency"
            ]["columns"]
        }
    except (KeyError, TransferPackageError, ValueError):
        raise _fail("source_idempotency_invalid", "Source receipt contains an invalid scalar.") from None


def validate_excluded_log_delete_receipt(
    row: Mapping[str, Any],
    owner_id: str,
) -> None:
    canonical = _canonical_source_receipt(row, allow_excluded_delete=True)
    try:
        snapshot = json.loads(canonical["response_snapshot"])
    except (TypeError, json.JSONDecodeError):
        raise _fail("source_idempotency_invalid", "Delete receipt snapshot is malformed.") from None
    if (
        canonical["user_id"] != owner_id
        or canonical["operation"] != "log.delete"
        or not isinstance(snapshot, dict)
        or set(snapshot) != {"deleted", "log_id"}
        or snapshot["deleted"] is not True
        or snapshot["log_id"] != canonical["resource_id"]
    ):
        raise _fail("source_idempotency_invalid", "Delete receipt snapshot is malformed.")


def local_log_response(
    log: Mapping[str, Any],
    food: Mapping[str, Any],
    recipes_by_id: Mapping[str, Mapping[str, Any]],
    revisions_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    food_available = food["deleted_at"] is None
    revision_backed = log["recipe_publication_revision_id"] is not None
    if food["is_recipe"] or food["source_type"] == "recipe":
        recipe = recipes_by_id.get(food["source_id"] or "")
        active_revision_id = recipe["active_publication_revision_id"] if recipe else None
        food_available = bool(
            food_available
            and food["is_recipe"]
            and food["source_type"] == "recipe"
            and recipe is not None
            and recipe["deleted_at"] is None
            and recipe["published_food_item_id"] == food["id"]
            and active_revision_id is not None
            and food["recipe_publication_revision_id"] == active_revision_id
            and active_revision_id in revisions_by_id
        )
    return {
        "id": log["id"],
        "food_item_id": log["food_item_id"],
        "food_name_snapshot": log["food_name_snapshot"],
        "is_editable": bool(revision_backed or food_available),
        "source_food_available": food_available,
        "edit_block_reason": None if revision_backed or food_available else "source_food_deleted",
        "logged_date": log["logged_date"],
        "meal_type": log["meal_type"],
        "amount_quantity": log["amount_quantity"],
        "amount_unit": log["amount_unit"],
        "serving_definition_id": log["serving_definition_id"],
        "gram_amount": log["gram_amount"],
        "notes": log["notes"],
        "created_at": log["created_at"],
        "updated_at": log["updated_at"],
    }


def target_ready_idempotency(
    source_rows: Sequence[Mapping[str, Any]],
    logs: Sequence[Mapping[str, Any]],
    foods: Sequence[Mapping[str, Any]],
    recipes: Sequence[Mapping[str, Any]],
    revisions: Sequence[Mapping[str, Any]],
    servings: Sequence[Mapping[str, Any]] = (),
    *,
    owner_id: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    copied = set(CONTRACT["idempotency"]["copied_operations"])
    supported = copied | {"log.update", "log.delete"}
    output: list[dict[str, Any]] = []
    excluded_delete = 0
    for raw in source_rows:
        is_delete = raw.get("operation") == "log.delete"
        canonical = _canonical_source_receipt(
            raw,
            allow_excluded_delete=is_delete,
        )
        if canonical["user_id"] != owner_id:
            raise _fail("source_idempotency_invalid", "Source receipt owner is invalid.")
        operation = canonical["operation"]
        if operation == "log.create" or operation not in supported:
            raise _fail("source_idempotency_invalid", "Source contains an unsupported receipt operation.")
        if raw["response_snapshot"] is None or raw["completed_at"] is None:
            raise _fail("source_idempotency_invalid", "Source contains an incomplete receipt.")
        if operation == "log.delete":
            validate_excluded_log_delete_receipt(raw, owner_id)
            excluded_delete += 1
            continue
        transformed = translate_update_receipt(raw) if operation == "log.update" else canonical
        output.append(
            _canonical_source_receipt(transformed)
            if operation == "log.update"
            else canonical
        )

    foods_by_id = {row["id"]: row for row in foods}
    recipes_by_id = {row["id"]: row for row in recipes}
    revisions_by_id = {row["id"]: row for row in revisions}
    reconstructed = 0
    for log in logs:
        if log["user_id"] != owner_id:
            raise _fail("source_idempotency_invalid", "Daily Log receipt owner is invalid.")
        request_id = log["client_request_id"]
        fingerprint = log["client_request_fingerprint"]
        if (request_id is None) != (fingerprint is None):
            raise _fail("source_idempotency_invalid", "Daily Log request identity is incomplete.")
        if request_id is None:
            continue
        food = foods_by_id.get(log["food_item_id"])
        if food is None:
            raise _fail("source_owner_graph_invalid", "Daily Log Food is missing.")
        receipt = {
            "id": str(uuid5(NAMESPACE_DNS, f"nutrition-app:e2-15:log.create:{log['user_id']}:{request_id}")),
            "user_id": log["user_id"],
            "operation": "log.create",
            "client_request_id": request_id,
            "request_fingerprint": fingerprint,
            "resource_id": log["id"],
            "response_snapshot": local_log_response(log, food, recipes_by_id, revisions_by_id),
            "completed_at": log["created_at"],
            "created_at": log["created_at"],
        }
        output.append(_canonical_row("create_operation_idempotency", receipt))
        reconstructed += 1
    sorted_output = sort_transfer_records(output, SECTION_CONTRACTS["create_operation_idempotency"]["primary_key"])
    if len({row["id"] for row in sorted_output}) != len(sorted_output):
        raise _fail("source_idempotency_invalid", "Target receipt identity collides.")
    portable_records = {
        "food_items": foods,
        "serving_definitions": servings,
        "recipes": recipes,
        "recipe_publication_revisions": revisions,
    }
    try:
        for receipt in sorted_output:
            if receipt["operation"] in copied:
                validate_portable_receipt(
                    receipt,
                    json.loads(receipt["response_snapshot"]),
                    portable_records,
                    owner_id,
                )
    except (TransferPackageError, ValueError):
        raise _fail("source_idempotency_invalid", "Source contains an invalid portable receipt.") from None
    return sorted_output, {
        "copied_portable_count": sum(row["operation"] in copied for row in sorted_output),
        "translated_log_update_count": sum(row["operation"] == "log.update" for row in sorted_output),
        "reconstructed_log_create_count": reconstructed,
        "excluded_log_delete_count": excluded_delete,
    }


def daily_totals(records: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    logs_by_id = {row["id"]: row for row in records["daily_logs"]}
    grouped: dict[str, list[NutrientSnapshot]] = defaultdict(list)
    for row in records["daily_log_nutrient_snapshots"]:
        grouped[logs_by_id[row["daily_log_id"]]["logged_date"]].append(
            NutrientSnapshot(
                nutrient_id=row["nutrient_id"],
                amount=None if row["amount"] is None else Decimal(row["amount"]),
                unit=row["unit"],
                data_status=NutrientDataStatus(row["data_status"]),
            )
        )
    output = []
    for logged_date, snapshots in grouped.items():
        for total in aggregate_snapshots(snapshots):
            output.append({
                "logged_date": logged_date,
                "nutrient_id": total.nutrient_id,
                "amount_known": canonicalize_transfer_scalar("response_decimal", total.amount_known),
                "amount_estimated": canonicalize_transfer_scalar("response_decimal", total.amount_estimated),
                "unit": total.unit,
                "has_unknown_contributors": total.has_unknown_contributors,
                "unknown_contributor_count": total.unknown_contributor_count,
            })
    return sort_transfer_records(output, CONTRACT["qualification"]["daily_totals_primary_key"])


def build_owner_transfer_package(
    connection: Connection,
    owner_id: str,
    exported_at: datetime,
) -> dict[str, Any]:
    records = {
        name: _read_section(connection, name, owner_id)
        for name in SECTION_NAMES
        if name != "create_operation_idempotency"
    }
    if len(records["users"]) != 1 or len(records["user_profiles"]) != 1:
        raise _fail("source_owner_invalid", "Exactly one owner User and profile are required.")
    receipt_contract = SECTION_CONTRACTS["create_operation_idempotency"]
    receipt_columns = ", ".join(
        source_select_expression(column, kind)
        for column, kind in receipt_contract["columns"]
    )
    raw_receipts = list(connection.execute(
        text(
            f'SELECT {receipt_columns} FROM public."create_operation_idempotency" AS source '
            'WHERE source."user_id" = :owner_id'
        ),
        {"owner_id": owner_id},
    ).mappings())
    receipts, policy_counts = target_ready_idempotency(
        raw_receipts,
        records["daily_logs"],
        records["food_items"],
        records["recipes"],
        records["recipe_publication_revisions"],
        records["serving_definitions"],
        owner_id=owner_id,
    )
    records["create_operation_idempotency"] = receipts
    package = {
        "format": CONTRACT["format"],
        "format_version": CONTRACT["format_version"],
        "codec_version": CONTRACT["codec_version"],
        "source": {
            "postgres_major": CONTRACT["source"]["postgres_major"],
            "alembic_revision": CONTRACT["source"]["alembic_revision"],
            "schema_contract": CONTRACT["source"]["schema_contract"],
            "schema_contract_digest": SCHEMA_CONTRACT_DIGEST,
        },
        "target": CONTRACT["target"],
        "exported_at": canonicalize_transfer_scalar("instant", exported_at),
        "owner_id": owner_id,
        "nutrient_catalog_digest": CONTRACT["nutrient_catalog_digest"],
        "idempotency_policy": {"version": CONTRACT["idempotency"]["policy_version"], **policy_counts},
        "sections": [build_section(name, records[name]) for name in SECTION_NAMES],
        "qualification": {"daily_totals": build_daily_totals_section(daily_totals(records))},
    }
    completed = with_overall_digest(package)
    validate_transfer_package(canonical_transfer_json(completed).encode("utf-8"))
    return completed


@dataclass(frozen=True)
class TransferExportResult:
    byte_count: int
    overall_digest: str
    section_counts: Mapping[str, int]
    output_path: Path


def write_transfer_file(document: Mapping[str, Any], output_path: Path) -> TransferExportResult:
    destination = validate_output_path(output_path)
    payload = serialize_transfer_document(document)
    temporary = destination.with_name(f".{destination.name}.{secrets.token_hex(8)}.tmp")
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = None
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination)
        os.unlink(temporary)
        directory = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except FileExistsError:
        raise _fail("output_exists", "Transfer output already exists.") from None
    except OSError as error:
        raise _fail("output_write_failed", "Transfer output could not be published.") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    completed = with_overall_digest(document)
    return TransferExportResult(
        byte_count=len(payload),
        overall_digest=str(completed["overall_digest"]),
        section_counts={str(section["name"]): int(section["count"]) for section in completed["sections"]},
        output_path=destination,
    )


def export_personal_transfer(
    database_url: str,
    owner_id: str,
    output_path: Path,
    *,
    frozen_writes_acknowledged: bool,
) -> TransferExportResult:
    owner = canonical_owner_id(owner_id)
    destination = validate_output_path(output_path)
    if not frozen_writes_acknowledged:
        raise _fail("frozen_writes_required", "Explicit frozen-writes acknowledgment is required.")
    try:
        url = make_url(database_url)
    except (ArgumentError, TypeError, ValueError):
        raise _fail("source_database_invalid", "Source database URL is invalid.") from None
    if url.get_backend_name() != "postgresql":
        raise _fail("source_database_invalid", "E2-15 export requires PostgreSQL.")
    engine = create_engine(
        database_url,
        poolclass=NullPool,
        hide_parameters=True,
        isolation_level="AUTOCOMMIT",
        connect_args=database_connect_args(database_url),
    )
    package: dict[str, Any] | None = None
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("BEGIN ISOLATION LEVEL SERIALIZABLE READ ONLY DEFERRABLE")
            try:
                qualify_export_session(connection)
                qualify_source_schema(connection)
                qualify_source_nutrients(connection)
                exported_at = connection.scalar(text("SELECT transaction_timestamp()"))
                if not isinstance(exported_at, datetime):
                    raise _fail("source_timestamp_invalid", "PostgreSQL export timestamp is invalid.")
                package = build_owner_transfer_package(connection, owner, exported_at)
            finally:
                connection.exec_driver_sql("ROLLBACK")
    except TransferExportError:
        raise
    except (SQLAlchemyError, TransferPackageError) as error:
        raise _fail("source_export_failed", "PostgreSQL transfer qualification failed.") from error
    finally:
        engine.dispose()
    if package is None:  # pragma: no cover - defensive transaction boundary
        raise _fail("source_export_failed", "PostgreSQL transfer qualification failed.")
    return write_transfer_file(package, destination)
