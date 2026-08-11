from __future__ import annotations

from decimal import Decimal
import os
from pathlib import Path
import re
import secrets
from types import SimpleNamespace
from uuid import UUID

import pytest
from psycopg import sql
from sqlalchemy import create_engine, event, make_url, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from app.operators import phase5c4_roles as roles
from app.models.recipe_publication import (
    RecipePublicationAmountDefinition,
    RecipePublicationRevision,
)
from app.publication.recipe_revision import revision_content_digest
from app.transfer.e2_15 import CONTRACT, validate_transfer_package
from app.transfer.e2_15_exporter import (
    export_personal_transfer,
    qualify_export_session,
    qualify_source_nutrients,
    qualify_source_schema,
)
pytestmark = pytest.mark.postgres_concurrency
E2_15_POSTGRES_URL = os.getenv("NUTRITION_E2_15_TEST_POSTGRES_URL")
E2_15_E2E_OUTPUT_PATH = os.getenv("NUTRITION_E2_15_E2E_OUTPUT_PATH")


@pytest.fixture(scope="module")
def qualified_database():
    if not E2_15_POSTGRES_URL:
        pytest.skip(
            "set NUTRITION_E2_15_TEST_POSTGRES_URL to an operator-prepared "
            "disposable pg-0025 database"
        )
    yield SimpleNamespace(admin_url=E2_15_POSTGRES_URL)


def _qualifier_url(database) -> str:
    password = secrets.token_urlsafe(24)
    engine = create_engine(database.admin_url, poolclass=NullPool, hide_parameters=True)
    try:
        with engine.begin() as connection:
            raw = connection.connection.driver_connection
            with raw.cursor() as cursor:
                cursor.execute(
                    sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                        sql.Identifier(roles.QUALIFIER_ROLE),
                        sql.Literal(password),
                    )
                )
    finally:
        engine.dispose()
    return make_url(database.admin_url).set(
        username=roles.QUALIFIER_ROLE,
        password=password,
    ).render_as_string(hide_password=False)


def _source_fingerprint(database_url: str) -> tuple[tuple[str, int, str], ...]:
    engine = create_engine(database_url, poolclass=NullPool, hide_parameters=True)
    try:
        with engine.connect() as connection:
            result = []
            tables = list(CONTRACT["source"]["expected_public_tables"])
            for optional in CONTRACT["source"]["optional_public_tables"]:
                if connection.scalar(
                    text("SELECT pg_catalog.to_regclass(:relation) IS NOT NULL"),
                    {"relation": f"public.{optional}"},
                ):
                    tables.append(optional)
            for table in tables:
                count, digest = connection.execute(
                    text(
                        f'SELECT COUNT(*)::bigint, '
                        f"COALESCE(md5(string_agg(row_to_json(e2_15_row)::text, E'\\n' "
                        f'ORDER BY row_to_json(e2_15_row)::text)), md5(\'\')) '
                        f'FROM public."{table}" AS e2_15_row'
                    )
                ).one()
                result.append((table, int(count), str(digest)))
            return tuple(result)
    finally:
        engine.dispose()


def _is_allowed_export_sql(statement: str) -> bool:
    normalized = " ".join(statement.strip().split()).upper()
    sequence_mutator = re.compile(
        r'(?<![A-Z0-9_$])(?:(?:"?PG_CATALOG"?)\s*\.\s*)?"?(?:NEXTVAL|SETVAL)"?\s*\(',
        re.IGNORECASE,
    )
    public_routine = re.compile(
        r'(?<![A-Z0-9_$])"?PUBLIC"?\s*\.\s*"?([A-Z_][A-Z0-9_$]*)"?\s*\(',
        re.IGNORECASE,
    )
    if sequence_mutator.search(statement):
        return False
    public_calls = {match.casefold() for match in public_routine.findall(statement)}
    if public_calls - {"phase0020_immutable_provenance_integrity_valid"}:
        return False
    if normalized.startswith(("SELECT ", "SHOW ")):
        return True
    if normalized.startswith("SET LOCAL "):
        return True
    return normalized in {
        "BEGIN ISOLATION LEVEL SERIALIZABLE READ ONLY DEFERRABLE",
        "BEGIN",
        "COMMIT",
        "ROLLBACK",
    }


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO public.users VALUES ('x')",
        "UPDATE public.users SET display_name = 'x'",
        "DELETE FROM public.users",
        "TRUNCATE public.users",
        "CREATE TABLE public.forbidden (id integer)",
        "ALTER TABLE public.users ADD COLUMN forbidden integer",
        "DROP TABLE public.users",
        "CALL public.forbidden()",
        "WITH changed AS (DELETE FROM public.users RETURNING *) SELECT * FROM changed",
    ],
)
def test_export_sql_surface_classifier_rejects_mutating_statements(statement: str) -> None:
    assert _is_allowed_export_sql(statement) is False


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT public.some_mutating_function()",
        'SELECT public."some_mutating_function"()',
        "SELECT nextval('public.some_sequence')",
        "SELECT pg_catalog.setval('public.some_sequence', 1)",
    ],
)
def test_export_sql_surface_classifier_rejects_mutating_select_functions(
    statement: str,
) -> None:
    assert _is_allowed_export_sql(statement) is False


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT public.phase0020_immutable_provenance_integrity_valid()",
        "SELECT pg_catalog.current_setting('transaction_read_only')",
        "SELECT source.id FROM public.users AS source",
    ],
)
def test_export_sql_surface_classifier_allows_approved_reads(statement: str) -> None:
    assert _is_allowed_export_sql(statement) is True


def test_pg_0025_qualifier_is_exact_read_only_serializable_deferrable_and_non_mutating(
    qualified_database,
    tmp_path: Path,
) -> None:
    owner_id = "00000000-0000-4000-8000-000000000001"
    other_id = "00000000-0000-4000-8000-000000000002"
    recipe_id = "00000000-0000-4000-8000-000000000010"
    revision_id = "00000000-0000-4000-8000-000000000011"
    amount_sql_null_id = "00000000-0000-4000-8000-000000000012"
    amount_json_null_id = "00000000-0000-4000-8000-000000000013"
    target_sql_null_id = "00000000-0000-4000-8000-000000000014"
    target_json_null_id = "00000000-0000-4000-8000-000000000015"
    fixture_revision = RecipePublicationRevision(
        id=UUID(revision_id),
        recipe_id=UUID(recipe_id),
        user_id=UUID(owner_id),
        revision_number=1,
        creation_origin="normal_publication",
        provenance_confidence="complete",
        published_name="JSON transfer fixture",
        published_notes=None,
    )
    fixture_revision.amount_definitions = [
        RecipePublicationAmountDefinition(
            id=UUID(amount_sql_null_id),
            revision_id=UUID(revision_id),
            display_order=0,
            display_label="grams",
            semantic_mode="g",
            display_quantity=None,
            display_unit="g",
            gram_equivalent=None,
            is_default=False,
            conversion_metadata=None,
        ),
        RecipePublicationAmountDefinition(
            id=UUID(amount_json_null_id),
            revision_id=UUID(revision_id),
            display_order=1,
            display_label="1 serving",
            semantic_mode="serving",
            display_quantity=Decimal("1.000000"),
            display_unit="serving",
            gram_equivalent=Decimal("100.000000"),
            is_default=True,
            conversion_metadata=None,
        ),
    ]
    fixture_revision.nutrients = []
    fixture_content_digest = revision_content_digest(fixture_revision)
    admin = create_engine(qualified_database.admin_url, poolclass=NullPool, hide_parameters=True)
    try:
        with admin.begin() as connection:
            for identifier, email in (
                (owner_id, "selected@example.invalid"),
                (other_id, "excluded@example.invalid"),
            ):
                connection.execute(
                    text(
                        "INSERT INTO public.users (id, email, display_name) "
                        "VALUES (:id, :email, 'Synthetic owner')"
                    ),
                    {"id": identifier, "email": email},
                )
                connection.execute(
                    text(
                        "INSERT INTO public.user_profiles "
                        "(user_id, authoritative_time_zone) "
                        "VALUES (:id, 'America/Los_Angeles')"
                    ),
                    {"id": identifier},
                )
            connection.execute(
                text(
                    "INSERT INTO public.recipes "
                    "(id, user_id, name, needs_republish) "
                    "VALUES (:recipe_id, :owner_id, 'JSON transfer fixture', false)"
                ),
                {"recipe_id": recipe_id, "owner_id": owner_id},
            )
            connection.execute(
                text(
                    "INSERT INTO public.recipe_publication_revisions "
                    "(id, recipe_id, user_id, revision_number, creation_origin, "
                    "provenance_confidence, published_name, content_digest) "
                    "VALUES (:revision_id, :recipe_id, :owner_id, 1, "
                    "'normal_publication', 'complete', 'JSON transfer fixture', :digest)"
                ),
                {
                    "revision_id": revision_id,
                    "recipe_id": recipe_id,
                    "owner_id": owner_id,
                    "digest": fixture_content_digest,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO public.recipe_publication_amount_definitions "
                    "(id, revision_id, display_order, display_label, semantic_mode, "
                    "display_quantity, display_unit, gram_equivalent, is_default, "
                    "conversion_metadata) VALUES "
                    "(:sql_null_id, :revision_id, 0, 'grams', 'g', NULL, 'g', NULL, false, NULL), "
                    "(:json_null_id, :revision_id, 1, '1 serving', 'serving', "
                    "1.000000, 'serving', 100.000000, true, CAST('null' AS json))"
                ),
                {
                    "sql_null_id": amount_sql_null_id,
                    "json_null_id": amount_json_null_id,
                    "revision_id": revision_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO public.nutrition_targets "
                    "(id, user_id, target_type, nutrient_id, target_amount, unit, "
                    "basis, source, metadata) VALUES "
                    "(:sql_null_id, :owner_id, 'manual_override', 'calories', "
                    "2000.000000, 'kcal', 'per_day', 'user', NULL), "
                    "(:json_null_id, :owner_id, 'manual_override', 'protein', "
                    "90.000000, 'g', 'per_day', 'user', CAST('null' AS jsonb))"
                ),
                {
                    "sql_null_id": target_sql_null_id,
                    "json_null_id": target_json_null_id,
                    "owner_id": owner_id,
                },
            )
    finally:
        admin.dispose()

    before = _source_fingerprint(qualified_database.admin_url)
    qualifier_url = _qualifier_url(qualified_database)
    qualifier = create_engine(
        qualifier_url,
        poolclass=NullPool,
        hide_parameters=True,
        isolation_level="AUTOCOMMIT",
    )
    observed_sql: list[str] = []

    def observe_sql(
        _connection,
        _cursor,
        statement: str,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        observed_sql.append(statement)

    event.listen(Engine, "before_cursor_execute", observe_sql)
    try:
        with qualifier.connect() as connection:
            connection.exec_driver_sql(
                "BEGIN ISOLATION LEVEL SERIALIZABLE READ ONLY DEFERRABLE"
            )
            try:
                qualify_export_session(connection)
                qualify_source_schema(connection)
                qualify_source_nutrients(connection)
            finally:
                connection.exec_driver_sql("ROLLBACK")
        output = (
            Path(E2_15_E2E_OUTPUT_PATH)
            if E2_15_E2E_OUTPUT_PATH
            else tmp_path / "selected-owner.nutrition-transfer.json"
        )
        if E2_15_E2E_OUTPUT_PATH:
            assert output.parent.is_dir()
            assert not output.exists()
        result = export_personal_transfer(
            qualifier_url,
            owner_id,
            output,
            frozen_writes_acknowledged=True,
        )
    finally:
        event.remove(Engine, "before_cursor_execute", observe_sql)
        qualifier.dispose()

    disallowed_sql = [statement for statement in observed_sql if not _is_allowed_export_sql(statement)]
    assert disallowed_sql == []
    assert not any(
        "SELECT public.phase0020_immutable_provenance_integrity_valid()" in sql
        for sql in observed_sql
    )
    assert any("has_function_privilege" in sql for sql in observed_sql)
    assert any('FROM public."users"' in sql for sql in observed_sql)
    assert any("phase5c_conversion_clone_marker" in sql for sql in observed_sql)

    package = validate_transfer_package(output.read_bytes())
    records = {
        section["name"]: section["records"]
        for section in package["sections"]
    }
    assert result.overall_digest == package["overall_digest"]
    assert [row["id"] for row in records["users"]] == [owner_id]
    assert [row["user_id"] for row in records["user_profiles"]] == [owner_id]
    amount_metadata = {
        row["id"]: row["conversion_metadata"]
        for row in records["recipe_publication_amount_definitions"]
    }
    assert amount_metadata[amount_sql_null_id] is None
    assert amount_metadata[amount_json_null_id] == "null"
    target_metadata = {
        row["id"]: row["metadata"] for row in records["nutrition_targets"]
    }
    assert target_metadata[target_sql_null_id] is None
    assert target_metadata[target_json_null_id] == "null"

    forbidden = (
        "INSERT INTO public.users (id, email) VALUES "
        "('00000000-0000-4000-8000-000000000003', 'forbidden@example.invalid')",
        "UPDATE public.users SET display_name = 'forbidden' WHERE id = "
        "'00000000-0000-4000-8000-000000000001'",
        "DELETE FROM public.user_profiles WHERE user_id = "
        "'00000000-0000-4000-8000-000000000001'",
        "TRUNCATE public.user_profiles",
        "CREATE TABLE public.e2_15_forbidden (id integer)",
        "UPDATE public.phase5c_conversion_clone_marker "
        "SET clone_marker_digest = clone_marker_digest",
        "DELETE FROM public.phase5c_conversion_clone_marker",
        "TRUNCATE public.phase5c_conversion_clone_marker",
    )
    for statement in forbidden:
        with qualifier.connect() as connection:
            connection.exec_driver_sql(
                "BEGIN ISOLATION LEVEL SERIALIZABLE READ ONLY DEFERRABLE"
            )
            try:
                with pytest.raises(DBAPIError):
                    connection.exec_driver_sql(statement)
            finally:
                connection.exec_driver_sql("ROLLBACK")

    assert _source_fingerprint(qualified_database.admin_url) == before
