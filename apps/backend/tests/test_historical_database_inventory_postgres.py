from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, event, make_url, text

from app.operators.historical_database_inventory import (
    REPORT_SCHEMA_VERSION,
    inventory_database,
)


pytestmark = pytest.mark.postgres_concurrency

POSTGRES_URL = os.getenv(
    "NUTRITION_TEST_POSTGRES_URL",
    "postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app",
)
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _run_alembic(database_url: str, revision: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "NUTRITION_DEPLOYMENT_MODE": "test",
            "NUTRITION_DATABASE_URL": database_url,
        }
    )
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_inventory_cli(database_url: str, output_format: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["NUTRITION_DATABASE_URL"] = database_url
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.inventory_historical_database",
            "--format",
            output_format,
        ],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture()
def isolated_postgres_schema() -> tuple[Engine, str]:
    admin = create_engine(POSTGRES_URL, pool_pre_ping=True)
    try:
        with admin.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - depends on developer environment.
        admin.dispose()
        pytest.skip(f"PostgreSQL inventory database unavailable: {exc}")

    schema = f"test_historical_inventory_{uuid4().hex}"
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    database_url = (
        make_url(POSTGRES_URL)
        .update_query_dict({"options": f"-csearch_path={schema}"})
        .render_as_string(hide_password=False)
    )
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        yield engine, database_url
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _upgrade(database_url: str, revision: str = "head") -> None:
    result = _run_alembic(database_url, revision)
    assert result.returncode == 0, result.stderr


def _insert_user(connection, *, email: str = "inventory@example.test"):
    user_id = uuid4()
    connection.execute(
        text("INSERT INTO users (id, email, display_name) VALUES (:id, :email, :display_name)"),
        {"id": user_id, "email": email, "display_name": "Sensitive Operator Name"},
    )
    return user_id


def _insert_current_draft(connection, user_id, *, name: str = "Sensitive Recipe Name"):
    recipe_id = uuid4()
    connection.execute(
        text(
            """
            INSERT INTO recipes (id, user_id, name, notes)
            VALUES (:id, :user_id, :name, :notes)
            """
        ),
        {
            "id": recipe_id,
            "user_id": user_id,
            "name": name,
            "notes": "Sensitive Recipe Notes",
        },
    )
    return recipe_id


def _insert_revision(connection, user_id, recipe_id):
    revision_id = uuid4()
    connection.execute(
        text(
            """
            INSERT INTO recipe_publication_revisions
                (id, recipe_id, user_id, revision_number, creation_origin,
                 provenance_confidence, published_name, published_notes, content_digest)
            VALUES
                (:id, :recipe_id, :user_id, 1, 'normal_publication',
                 'complete', 'Sensitive Published Name', 'Sensitive Published Notes', :digest)
            """
        ),
        {
            "id": revision_id,
            "recipe_id": recipe_id,
            "user_id": user_id,
            "digest": "0" * 64,
        },
    )
    return revision_id


def test_empty_current_database_inventory_is_stable_and_aggregate_only(
    isolated_postgres_schema: tuple[Engine, str],
) -> None:
    engine, database_url = isolated_postgres_schema
    _upgrade(database_url)

    first = inventory_database(engine)
    second = inventory_database(engine)
    payload = first.to_dict()

    assert payload["schema_version"] == REPORT_SCHEMA_VERSION
    assert payload["read_only"] is True
    assert payload["classification"] == {
        "value": "empty_database",
        "reason": "no_application_or_historical_rows_detected",
    }
    assert payload["migration"]["current_alembic_revision"] == "0014_create_idempotency"
    assert payload["migration"]["already_beyond_migration_0004"] is True
    assert payload["legacy_recipes"]["recipe_count"] == 0
    assert payload["current_recipes"]["recipe_count"] == 0
    assert payload["revisions"]["ingredient_snapshot_table_present"] is False
    assert payload["revisions"]["ingredient_snapshot_count"] is None
    assert first.to_json() == second.to_json()
    assert json.loads(first.to_json()) == payload
    assert set(payload) == {
        "schema_version",
        "read_only",
        "classification",
        "migration",
        "legacy_recipes",
        "current_recipes",
        "revisions",
        "daily_logs",
        "ocr",
        "idempotency",
        "retention",
        "consistency",
        "limitations",
    }


def test_operator_cli_emits_human_and_machine_readable_reports_without_database_url(
    isolated_postgres_schema: tuple[Engine, str],
) -> None:
    _engine, database_url = isolated_postgres_schema
    _upgrade(database_url)

    json_result = _run_inventory_cli(database_url, "json")
    human_result = _run_inventory_cli(database_url, "human")

    assert json_result.returncode == 0, json_result.stderr
    assert human_result.returncode == 0, human_result.stderr
    assert json.loads(json_result.stdout)["classification"]["value"] == "empty_database"
    assert "Classification: empty_database" in human_result.stdout
    rendered = json_result.stdout + json_result.stderr + human_result.stdout + human_result.stderr
    assert database_url not in rendered
    password = make_url(database_url).password
    if password:
        assert password not in rendered


def test_inventory_uses_only_read_only_queries_and_changes_no_domain_rows(
    isolated_postgres_schema: tuple[Engine, str],
) -> None:
    engine, database_url = isolated_postgres_schema
    _upgrade(database_url)
    with engine.begin() as connection:
        user_id = _insert_user(connection)
        recipe_id = _insert_current_draft(connection, user_id)
        before = connection.execute(
            text("SELECT id, user_id, name, notes, updated_at FROM recipes")
        ).mappings().all()

    statements: list[str] = []

    def capture_statement(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.strip())

    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        report = inventory_database(engine)
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)

    with engine.connect() as connection:
        after = connection.execute(
            text("SELECT id, user_id, name, notes, updated_at FROM recipes")
        ).mappings().all()
    assert before == after
    assert before[0]["id"] == recipe_id
    assert report.to_dict()["classification"]["value"] == "clean_current_database"
    assert any(statement.upper() == "SET TRANSACTION READ ONLY" for statement in statements)
    forbidden = ("INSERT ", "UPDATE ", "DELETE ", "ALTER ", "CREATE ", "DROP ", "TRUNCATE ")
    assert not [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith(forbidden)
    ]


def test_current_published_recipe_revision_and_projection_are_counted_cleanly(
    isolated_postgres_schema: tuple[Engine, str],
) -> None:
    engine, database_url = isolated_postgres_schema
    _upgrade(database_url)
    with engine.begin() as connection:
        user_id = _insert_user(connection)
        recipe_id = _insert_current_draft(connection, user_id)
        revision_id = _insert_revision(connection, user_id, recipe_id)
        amount_id = uuid4()
        projection_id = uuid4()
        connection.execute(
            text(
                """
                INSERT INTO recipe_publication_amount_definitions
                    (id, revision_id, display_order, display_label, semantic_mode,
                     display_quantity, display_unit, gram_equivalent, is_default)
                VALUES
                    (:id, :revision_id, 0, '1 serving', 'serving', 1, 'serving', 100, true)
                """
            ),
            {"id": amount_id, "revision_id": revision_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO recipe_publication_nutrients
                    (id, revision_id, nutrient_id, amount, unit, basis, data_status)
                VALUES (:id, :revision_id, 'calories', 250, 'kcal', 'per_serving', 'known')
                """
            ),
            {"id": uuid4(), "revision_id": revision_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO food_items
                    (id, user_id, name, source_type, source_id,
                     recipe_publication_revision_id, is_recipe)
                VALUES
                    (:id, :user_id, 'Sensitive projection', 'recipe', :source_id,
                     :revision_id, true)
                """
            ),
            {
                "id": projection_id,
                "user_id": user_id,
                "source_id": str(recipe_id),
                "revision_id": revision_id,
            },
        )
        manual_food_id = uuid4()
        connection.execute(
            text(
                """
                INSERT INTO food_items (id, user_id, name, source_type, is_recipe)
                VALUES (:id, :user_id, 'Sensitive manual food', 'manual', false)
                """
            ),
            {"id": manual_food_id, "user_id": user_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO daily_logs
                    (id, user_id, food_item_id, logged_date, amount_quantity, amount_unit,
                     recipe_publication_revision_id,
                     recipe_publication_amount_definition_id)
                VALUES
                    (:id, :user_id, :food_id, DATE '2026-07-14', 1, 'serving',
                     :revision_id, :amount_id)
                """
            ),
            {
                "id": uuid4(),
                "user_id": user_id,
                "food_id": projection_id,
                "revision_id": revision_id,
                "amount_id": amount_id,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO daily_logs
                    (id, user_id, food_item_id, client_request_id,
                     client_request_fingerprint, logged_date, amount_quantity, amount_unit)
                VALUES
                    (:id, :user_id, :food_id, :request_id, :fingerprint,
                     DATE '2026-07-14', 100, 'g')
                """
            ),
            {
                "id": uuid4(),
                "user_id": user_id,
                "food_id": manual_food_id,
                "request_id": uuid4(),
                "fingerprint": "a" * 64,
            },
        )
        connection.execute(
            text(
                """
                UPDATE recipes
                SET active_publication_revision_id = :revision_id,
                    published_food_item_id = :projection_id
                WHERE id = :recipe_id
                """
            ),
            {
                "revision_id": revision_id,
                "projection_id": projection_id,
                "recipe_id": recipe_id,
            },
        )

    report = inventory_database(engine).to_dict()

    assert report["current_recipes"]["published_recipe_count"] == 1
    assert report["current_recipes"]["draft_recipe_count"] == 0
    assert report["current_recipes"]["projection_count"] == 1
    assert report["revisions"]["total_revision_count"] == 1
    assert report["revisions"]["active_revision_count"] == 1
    assert report["revisions"]["amount_definition_snapshot_count"] == 1
    assert report["revisions"]["nutrient_snapshot_count"] == 1
    assert report["daily_logs"]["mutable_food_log_count"] == 1
    assert report["daily_logs"]["immutable_recipe_revision_log_count"] == 1
    assert report["daily_logs"]["unknown_authority_count"] == 0
    assert report["idempotency"]["daily_log_request_identity_count"] == 1
    assert report["retention"]["superseded_revision_count"] == 0
    assert report["classification"]["value"] == "clean_current_database"


def test_legacy_recipe_tables_and_rows_are_counted_without_upgrading(
    isolated_postgres_schema: tuple[Engine, str],
) -> None:
    engine, database_url = isolated_postgres_schema
    _upgrade(database_url, "0003_usda_source_identity")
    with engine.begin() as connection:
        user_id = _insert_user(connection, email="legacy-sensitive@example.test")
        recipe_food_id = uuid4()
        ingredient_food_id = uuid4()
        serving_id = uuid4()
        recipe_id = uuid4()
        connection.execute(
            text(
                """
                INSERT INTO food_items (id, user_id, name, source_type, is_recipe)
                VALUES
                    (:recipe_food, :user_id, 'Legacy Secret Soup', 'recipe', true),
                    (:ingredient_food, :user_id, 'Legacy Secret Ingredient', 'manual', false)
                """
            ),
            {
                "recipe_food": recipe_food_id,
                "ingredient_food": ingredient_food_id,
                "user_id": user_id,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO serving_definitions
                    (id, food_item_id, label, quantity, unit, gram_weight, is_default, source)
                VALUES (:id, :food_id, 'secret portion', 1, 'portion', 100, true, 'manual')
                """
            ),
            {"id": serving_id, "food_id": ingredient_food_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO recipes
                    (id, food_item_id, user_id, serving_count, final_yield_quantity,
                     final_yield_unit, instructions)
                VALUES (:id, :food_id, :user_id, 4, 4, 'serving', 'Sensitive instructions')
                """
            ),
            {"id": recipe_id, "food_id": recipe_food_id, "user_id": user_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO recipe_ingredients
                    (id, recipe_id, ingredient_food_item_id, quantity, unit,
                     serving_definition_id, gram_amount, preparation_note, sort_order)
                VALUES
                    (:id, :recipe_id, :food_id, 2, 'portion', :serving_id,
                     200, 'Sensitive preparation', 0)
                """
            ),
            {
                "id": uuid4(),
                "recipe_id": recipe_id,
                "food_id": ingredient_food_id,
                "serving_id": serving_id,
            },
        )

    report = inventory_database(engine).to_dict()

    assert report["migration"]["migration_0004_pending"] is True
    assert report["migration"]["migration_0004_can_safely_proceed"] is False
    assert report["legacy_recipes"] == {
        "recipes_table_present": True,
        "recipe_ingredients_table_present": True,
        "recipe_count": 1,
        "recipe_ingredient_count": 1,
    }
    assert report["current_recipes"]["schema_present"] is False
    assert report["classification"]["value"] == "legacy_conversion_required"


def test_missing_projection_is_classified_as_historical_repair(
    isolated_postgres_schema: tuple[Engine, str],
) -> None:
    engine, database_url = isolated_postgres_schema
    _upgrade(database_url)
    with engine.begin() as connection:
        user_id = _insert_user(connection)
        recipe_id = _insert_current_draft(connection, user_id)
        revision_id = _insert_revision(connection, user_id, recipe_id)
        connection.execute(
            text(
                "UPDATE recipes SET active_publication_revision_id = :revision_id "
                "WHERE id = :recipe_id"
            ),
            {"revision_id": revision_id, "recipe_id": recipe_id},
        )

    report = inventory_database(engine).to_dict()

    assert report["current_recipes"]["recipes_lacking_compatibility_projections"] == 1
    assert report["consistency"]["missing_recipe_projections"] == 1
    assert report["classification"]["value"] == "historical_repair_required"


def test_projection_source_revision_and_inactive_mismatches_are_detected(
    isolated_postgres_schema: tuple[Engine, str],
) -> None:
    engine, database_url = isolated_postgres_schema
    _upgrade(database_url)
    with engine.begin() as connection:
        user_id = _insert_user(connection)
        recipe_id = _insert_current_draft(connection, user_id)
        revision_id = _insert_revision(connection, user_id, recipe_id)
        projection_id = uuid4()
        connection.execute(
            text(
                """
                INSERT INTO food_items
                    (id, user_id, name, source_type, source_id, is_recipe, deleted_at)
                VALUES
                    (:id, :user_id, 'Sensitive projection', 'manual', 'wrong-source',
                     false, now())
                """
            ),
            {"id": projection_id, "user_id": user_id},
        )
        connection.execute(
            text(
                """
                UPDATE recipes
                SET active_publication_revision_id = :revision_id,
                    published_food_item_id = :projection_id
                WHERE id = :recipe_id
                """
            ),
            {
                "revision_id": revision_id,
                "projection_id": projection_id,
                "recipe_id": recipe_id,
            },
        )

    report = inventory_database(engine).to_dict()

    assert report["consistency"]["projection_source_mismatches"] == 1
    assert report["consistency"]["projection_revision_mismatches"] == 1
    assert report["current_recipes"]["projections_referencing_inactive_objects"] == 1
    assert report["consistency"]["inactive_references"] == 1
    assert report["classification"]["value"] == "historical_repair_required"


def test_orphan_revision_is_detected_in_disposable_broken_schema(
    isolated_postgres_schema: tuple[Engine, str],
) -> None:
    engine, database_url = isolated_postgres_schema
    _upgrade(database_url)
    with engine.begin() as connection:
        user_id = _insert_user(connection)
        connection.execute(
            text(
                "ALTER TABLE recipe_publication_revisions "
                "DROP CONSTRAINT fk_recipe_publication_revision_recipe_owner"
            )
        )
        _insert_revision(connection, user_id, uuid4())

    report = inventory_database(engine).to_dict()

    assert report["revisions"]["orphan_revision_count"] == 1
    assert report["consistency"]["orphan_revisions"] == 1
    assert report["classification"]["value"] == "historical_repair_required"


def test_ocr_idempotency_and_sensitive_values_are_reported_only_as_counts(
    isolated_postgres_schema: tuple[Engine, str],
) -> None:
    engine, database_url = isolated_postgres_schema
    _upgrade(database_url)
    secrets = {
        "sensitive-email-token@example.test",
        "SENSITIVE_DISPLAY_NAME_TOKEN",
        "SENSITIVE_FOOD_NAME_TOKEN",
        "SENSITIVE_OCR_TEXT_TOKEN",
        "SENSITIVE_IMAGE_PATH_TOKEN",
        "SENSITIVE_REQUEST_PAYLOAD_TOKEN",
        "SENSITIVE_RESPONSE_SNAPSHOT_TOKEN",
    }
    with engine.begin() as connection:
        user_id = uuid4()
        food_id = uuid4()
        scan_id = uuid4()
        parse_id = uuid4()
        connection.execute(
            text(
                "INSERT INTO users (id, email, display_name) "
                "VALUES (:id, :email, :display_name)"
            ),
            {
                "id": user_id,
                "email": "sensitive-email-token@example.test",
                "display_name": "SENSITIVE_DISPLAY_NAME_TOKEN",
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO food_items (id, user_id, name, source_type, is_recipe, notes)
                VALUES (:id, :user_id, :name, 'manual', false, :notes)
                """
            ),
            {
                "id": food_id,
                "user_id": user_id,
                "name": "SENSITIVE_FOOD_NAME_TOKEN",
                "notes": "SENSITIVE_REQUEST_PAYLOAD_TOKEN",
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO ocr_scans
                    (id, user_id, image_metadata, ocr_engine, raw_ocr_payload, full_text)
                VALUES
                    (:id, :user_id, CAST(:image AS jsonb), 'test-engine',
                     CAST(:raw AS jsonb), :full_text)
                """
            ),
            {
                "id": scan_id,
                "user_id": user_id,
                "image": json.dumps({"path": "SENSITIVE_IMAGE_PATH_TOKEN"}),
                "raw": json.dumps({"payload": "SENSITIVE_REQUEST_PAYLOAD_TOKEN"}),
                "full_text": "SENSITIVE_OCR_TEXT_TOKEN",
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO parse_results
                    (id, ocr_scan_id, parser_version, status, diagnostics, parsed_payload)
                VALUES
                    (:id, :scan_id, 'test-parser', 'parsed', CAST('{}' AS jsonb),
                     CAST(:payload AS jsonb))
                """
            ),
            {
                "id": parse_id,
                "scan_id": scan_id,
                "payload": json.dumps({"text": "SENSITIVE_OCR_TEXT_TOKEN"}),
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO parser_corrections
                    (id, user_id, ocr_scan_id, parse_result_id, parser_version,
                     field_name, parsed_value, confirmed_value, confirmation_action)
                VALUES
                    (:id, :user_id, :scan_id, :parse_id, 'test-parser', 'serving',
                     CAST(:parsed AS jsonb), CAST(:confirmed AS jsonb), 'confirmed')
                """
            ),
            {
                "id": uuid4(),
                "user_id": user_id,
                "scan_id": scan_id,
                "parse_id": parse_id,
                "parsed": json.dumps({"value": "SENSITIVE_REQUEST_PAYLOAD_TOKEN"}),
                "confirmed": json.dumps({"value": "SENSITIVE_OCR_TEXT_TOKEN"}),
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO ocr_nutrition_confirmation_traces
                    (id, user_id, food_item_id, parser_version, image_source_type,
                     schema_version, trace_snapshot, client_request_id, request_fingerprint)
                VALUES
                    (:id, :user_id, :food_id, 'test-parser', 'camera', 'v1',
                     CAST(:trace AS json), :request_id, :fingerprint)
                """
            ),
            {
                "id": uuid4(),
                "user_id": user_id,
                "food_id": food_id,
                "trace": json.dumps({"text": "SENSITIVE_OCR_TEXT_TOKEN"}),
                "request_id": uuid4(),
                "fingerprint": "f" * 64,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO create_operation_idempotency
                    (id, user_id, operation, client_request_id, request_fingerprint,
                     resource_id, response_snapshot, completed_at)
                VALUES
                    (:id, :user_id, 'food_create', :request_id, :fingerprint,
                     :resource_id, CAST(:snapshot AS json), now())
                """
            ),
            {
                "id": uuid4(),
                "user_id": user_id,
                "request_id": uuid4(),
                "fingerprint": "e" * 64,
                "resource_id": food_id,
                "snapshot": json.dumps({"value": "SENSITIVE_RESPONSE_SNAPSHOT_TOKEN"}),
            },
        )

    report = inventory_database(engine)
    payload = report.to_dict()
    rendered = report.to_json() + report.to_human()

    assert payload["ocr"]["confirmation_trace_count"] == 1
    assert payload["ocr"]["legacy_tables"]["ocr_scans"]["row_count"] == 1
    assert payload["ocr"]["legacy_tables"]["parse_results"]["row_count"] == 1
    assert payload["ocr"]["legacy_tables"]["parser_corrections"]["row_count"] == 1
    assert payload["ocr"]["raw_ocr_payload_contains_data"] is True
    assert payload["idempotency"]["create_operation_receipt_count"] == 1
    for secret in secrets:
        assert secret not in rendered
