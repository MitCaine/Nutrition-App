from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
import os
from pathlib import Path
import re
import secrets
from uuid import UUID

import pytest
from psycopg import sql
from sqlalchemy import create_engine, event, make_url, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from app.operators import phase5c4_roles as roles
from app.operators.phase5c_contracts import canonical_digest as phase5c_digest
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
from tests.test_issue_146_complete_runtime_authority_postgres import (
    MIGRATIONS,
    _apply_migration,
    _open_runtime,
)
from tests import test_phase5c4_recovery_postgres as recovery_support
from tests import test_resource_membership_migration_postgres as membership_support
from tests.test_phase5c4_target_activation_postgres import (
    _BINDINGS,
    _upgrade_0021,
)
pytestmark = pytest.mark.postgres_concurrency
pytest_plugins = ("tests.test_phase5c4_prerequisites_postgres",)
E2_15_E2E_OUTPUT_PATH = os.getenv("NUTRITION_E2_15_E2E_OUTPUT_PATH")


@pytest.fixture(scope="module")
def qualified_database(target_database):
    target = target_database
    admin = target.engine()
    try:
        with admin.connect() as connection:
            connection.execute(
                text(f"SET SESSION AUTHORIZATION {roles.MIGRATOR_ROLE}")
            )
            roles.assume_migration_owner(connection)
            marker = dict(
                connection.execute(
                    text("SELECT * FROM public.phase5c_conversion_clone_marker")
                )
                .mappings()
                .one()
            )
            marker["isolation_evidence_contract_version"] = (
                "phase5c_isolation_evidence_v1"
            )
            marker["conversion_rules_version"] = "phase5c_conversion_rules_v1"
            marker["operator_attestation_version"] = (
                "phase5c_operator_attestation_v1"
            )
            marker["operator_attestation_scope"] = "bridge_and_planning"
            marker_digest = phase5c_digest(
                {
                    key: value
                    for key, value in marker.items()
                    if key != "clone_marker_digest"
                }
            )
            archive_schema = str(
                connection.scalar(
                    text(
                        "SELECT archive_schema "
                        "FROM public.phase5c_conversion_metadata"
                    )
                )
            )
            quoted_archive = connection.dialect.identifier_preparer.quote(
                archive_schema
            )
            connection.execute(
                text(
                    "ALTER TABLE public.phase5c_conversion_clone_marker "
                    "DISABLE TRIGGER USER"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE public.phase5c_conversion_metadata "
                    "DISABLE TRIGGER USER"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE public.phase5c_conversion_runs "
                    "DISABLE TRIGGER USER"
                )
            )
            connection.execute(
                text(
                    f"ALTER TABLE {quoted_archive}.bridge_metadata "
                    "DISABLE TRIGGER USER"
                )
            )
            connection.execute(
                text(
                    "UPDATE public.phase5c_conversion_clone_marker "
                    "SET isolation_evidence_contract_version = :isolation_version, "
                    "conversion_rules_version = :rules_version, "
                    "operator_attestation_version = :attestation_version, "
                    "operator_attestation_scope = :scope, "
                    "clone_marker_digest = :digest"
                ),
                {
                    "isolation_version": marker[
                        "isolation_evidence_contract_version"
                    ],
                    "rules_version": marker["conversion_rules_version"],
                    "attestation_version": marker[
                        "operator_attestation_version"
                    ],
                    "scope": marker["operator_attestation_scope"],
                    "digest": marker_digest,
                },
            )
            connection.execute(
                text(
                    "UPDATE public.phase5c_conversion_metadata "
                    "SET clone_marker_digest = :digest"
                ),
                {"digest": marker_digest},
            )
            connection.execute(
                text(
                    "UPDATE public.phase5c_conversion_runs "
                    "SET clone_marker_digest = :digest"
                ),
                {"digest": marker_digest},
            )
            connection.execute(
                text(
                    f"UPDATE {quoted_archive}.bridge_metadata "
                    "SET clone_marker_digest = :digest"
                ),
                {"digest": marker_digest},
            )
            connection.execute(
                text(
                    "ALTER TABLE public.phase5c_conversion_clone_marker "
                    "ENABLE TRIGGER USER"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE public.phase5c_conversion_metadata "
                    "ENABLE TRIGGER USER"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE public.phase5c_conversion_runs "
                    "ENABLE TRIGGER USER"
                )
            )
            connection.execute(
                text(
                    f"ALTER TABLE {quoted_archive}.bridge_metadata "
                    "ENABLE TRIGGER USER"
                )
            )
            connection.commit()
    finally:
        admin.dispose()
    target = replace(target, clone_marker_digest=marker_digest)
    membership_support._initialize_closed_fence(target)
    membership_support._upgrade_0019(target.admin_url)
    recovery_support._upgrade_0020(target.admin_url)

    ops = membership_support.historical_support._engine_as(
        target,
        roles.OPS_ROLE,
        read_only=False,
    )
    try:
        assert roles.restore_runtime_privileges(ops)["state"] == "normal"
        closed = roles.close_runtime_maintenance(
            ops,
            quiet_period_seconds=0,
            drain_timeout_seconds=1,
            poll_interval_seconds=0.01,
        )
        assert closed["state"] == "maintenance"
        admin = target.engine()
        try:
            with admin.connect() as connection:
                fence = (
                    connection.execute(
                        text(
                            "SELECT target_instance_id, epoch, mode, "
                            "last_event_digest "
                            "FROM public.phase5c_write_fence_state"
                        )
                    )
                    .mappings()
                    .one()
                )
        finally:
            admin.dispose()
        with ops.begin() as connection:
            transitioned = connection.scalar(
                text(
                    "SELECT public.phase5c_transition_closed_write_fence("
                    "CAST(:target_id AS uuid), CAST(:command_id AS uuid), "
                    ":epoch, :mode, :last_event_digest, 'closed_cutover', "
                    "NULL, NULL, NULL)"
                ),
                {
                    "target_id": str(fence["target_instance_id"]),
                    "command_id": "00000000-0000-4000-8000-000000128100",
                    "epoch": int(fence["epoch"]),
                    "mode": fence["mode"],
                    "last_event_digest": fence["last_event_digest"],
                },
            )
            assert transitioned["state"]["mode"] == "closed_cutover"
    finally:
        ops.dispose()

    admin = target.engine()
    try:
        with admin.connect() as connection:
            identity = (
                connection.execute(
                    text(
                        "SELECT target.target_instance_id::text, "
                        "target.identity_digest "
                        "FROM public.phase5c_promotion_target_identity target"
                    )
                )
                .mappings()
                .one()
            )
    finally:
        admin.dispose()
    bindings = {
        **_BINDINGS,
        "NUTRITION_PHASE5C4_TARGET_DATABASE_INSTANCE_ID": identity[
            "target_instance_id"
        ],
        "NUTRITION_PHASE5C4_TARGET_IDENTITY_DIGEST": identity["identity_digest"],
    }
    _upgrade_0021(target, bindings)
    for module_name in MIGRATIONS:
        _apply_migration(target, module_name)
    _open_runtime(target, suffix="15")
    yield target


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
    if normalized.startswith("WITH "):
        data_changing_cte = re.compile(
            r"\b(?:INSERT\s+INTO|DELETE\s+FROM|UPDATE\s+(?:ONLY\s+)?[A-Z_\"]|"
            r"MERGE\s+INTO)\b"
        )
        return data_changing_cte.search(normalized) is None
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
        "WITH managed AS (SELECT oid FROM pg_catalog.pg_roles) SELECT * FROM managed",
    ],
)
def test_export_sql_surface_classifier_allows_approved_reads(statement: str) -> None:
    assert _is_allowed_export_sql(statement) is True


def test_pg_0033_data_bearing_transfer_is_owner_scoped_read_only_and_non_mutating(
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
    selected_food_id = "00000000-0000-4000-8000-000000000020"
    other_food_id = "00000000-0000-4000-8000-000000000021"
    complete_log_id = "00000000-0000-4000-8000-000000000022"
    unconfirmed_log_id = "00000000-0000-4000-8000-000000000023"
    other_log_id = "00000000-0000-4000-8000-000000000024"
    complete_snapshot_id = "00000000-0000-4000-8000-000000000025"
    unconfirmed_snapshot_id = "00000000-0000-4000-8000-000000000026"
    other_snapshot_id = "00000000-0000-4000-8000-000000000027"
    complete_date = date(2026, 8, 18)
    unconfirmed_date = date(2026, 8, 19)
    completed_at = datetime(2026, 8, 20, 12, 34, 56, 123456, tzinfo=timezone.utc)
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
                    "INSERT INTO public.food_items "
                    "(id, user_id, name, source_type, is_recipe) VALUES "
                    "(:selected_food_id, :owner_id, 'Selected transfer food', 'manual', false), "
                    "(:other_food_id, :other_id, 'Excluded transfer food', 'manual', false)"
                ),
                {
                    "selected_food_id": selected_food_id,
                    "other_food_id": other_food_id,
                    "owner_id": owner_id,
                    "other_id": other_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO public.daily_logs "
                    "(id, user_id, food_item_id, logged_date, meal_type, "
                    "amount_quantity, amount_unit, gram_amount, food_name_snapshot) VALUES "
                    "(:complete_log_id, :owner_id, :selected_food_id, :complete_date, "
                    "'breakfast', 1.000000, 'g', 1.000000, 'Selected transfer food'), "
                    "(:unconfirmed_log_id, :owner_id, :selected_food_id, :unconfirmed_date, "
                    "'lunch', 2.000000, 'g', 2.000000, 'Selected transfer food'), "
                    "(:other_log_id, :other_id, :other_food_id, :complete_date, "
                    "'dinner', 3.000000, 'g', 3.000000, 'Excluded transfer food')"
                ),
                {
                    "complete_log_id": complete_log_id,
                    "unconfirmed_log_id": unconfirmed_log_id,
                    "other_log_id": other_log_id,
                    "owner_id": owner_id,
                    "other_id": other_id,
                    "selected_food_id": selected_food_id,
                    "other_food_id": other_food_id,
                    "complete_date": complete_date,
                    "unconfirmed_date": unconfirmed_date,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO public.daily_log_nutrient_snapshots "
                    "(id, daily_log_id, source_food_item_id, nutrient_id, amount, unit, "
                    "data_status, consumed_amount_quantity, consumed_amount_unit, "
                    "consumed_gram_amount, calculation_metadata) VALUES "
                    "(:complete_snapshot_id, :complete_log_id, :selected_food_id, "
                    "'calories', 111.123456, 'kcal', 'known', 1.000000, 'g', 1.000000, "
                    "CAST('{\"fixture\":\"selected-complete\"}' AS jsonb)), "
                    "(:unconfirmed_snapshot_id, :unconfirmed_log_id, :selected_food_id, "
                    "'calories', 222.654321, 'kcal', 'known', 2.000000, 'g', 2.000000, "
                    "CAST('{\"fixture\":\"selected-unconfirmed\"}' AS jsonb)), "
                    "(:other_snapshot_id, :other_log_id, :other_food_id, "
                    "'calories', 333.000001, 'kcal', 'known', 3.000000, 'g', 3.000000, "
                    "CAST('{\"fixture\":\"other-complete\"}' AS jsonb))"
                ),
                {
                    "complete_snapshot_id": complete_snapshot_id,
                    "unconfirmed_snapshot_id": unconfirmed_snapshot_id,
                    "other_snapshot_id": other_snapshot_id,
                    "complete_log_id": complete_log_id,
                    "unconfirmed_log_id": unconfirmed_log_id,
                    "other_log_id": other_log_id,
                    "selected_food_id": selected_food_id,
                    "other_food_id": other_food_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO public.daily_log_day_completions "
                    "(user_id, logged_date, completed_at) VALUES "
                    "(:owner_id, :complete_date, :completed_at), "
                    "(:other_id, :complete_date, :completed_at)"
                ),
                {
                    "owner_id": owner_id,
                    "other_id": other_id,
                    "complete_date": complete_date,
                    "completed_at": completed_at,
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

    package = validate_transfer_package(output.read_bytes())
    records = {
        section["name"]: section["records"]
        for section in package["sections"]
    }
    assert result.overall_digest == package["overall_digest"]
    assert package["format_version"] == "3"
    assert package["source"] == {
        "postgres_major": "16",
        "alembic_revision": "0033_complete_runtime_authority",
        "schema_contract": "e2-15.pg-0033.v3",
        "schema_contract_digest": CONTRACT["source"]["schema_descriptor_digest"],
    }
    assert [row["id"] for row in records["users"]] == [owner_id]
    assert [row["user_id"] for row in records["user_profiles"]] == [owner_id]
    assert [row["id"] for row in records["daily_logs"]] == [
        complete_log_id,
        unconfirmed_log_id,
    ]
    assert records["daily_log_day_completions"] == [
        {
            "user_id": owner_id,
            "logged_date": complete_date.isoformat(),
            "completed_at": "2026-08-20T12:34:56.123456Z",
        }
    ]
    assert unconfirmed_date.isoformat() not in {
        row["logged_date"] for row in records["daily_log_day_completions"]
    }
    assert records["daily_log_nutrient_snapshots"] == [
        {
            "id": complete_snapshot_id,
            "daily_log_id": complete_log_id,
            "source_food_item_id": selected_food_id,
            "source_food_nutrient_id": None,
            "serving_definition_id": None,
            "nutrient_id": "calories",
            "amount": "111.123456",
            "unit": "kcal",
            "data_status": "known",
            "consumed_amount_quantity": "1.000000",
            "consumed_amount_unit": "g",
            "consumed_gram_amount": "1.000000",
            "consumed_package_fraction": None,
            "calculation_metadata": '{"fixture":"selected-complete"}',
        },
        {
            "id": unconfirmed_snapshot_id,
            "daily_log_id": unconfirmed_log_id,
            "source_food_item_id": selected_food_id,
            "source_food_nutrient_id": None,
            "serving_definition_id": None,
            "nutrient_id": "calories",
            "amount": "222.654321",
            "unit": "kcal",
            "data_status": "known",
            "consumed_amount_quantity": "2.000000",
            "consumed_amount_unit": "g",
            "consumed_gram_amount": "2.000000",
            "consumed_package_fraction": None,
            "calculation_metadata": '{"fixture":"selected-unconfirmed"}',
        },
    ]
    assert other_id not in output.read_text(encoding="utf-8")
    assert other_log_id not in output.read_text(encoding="utf-8")
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
