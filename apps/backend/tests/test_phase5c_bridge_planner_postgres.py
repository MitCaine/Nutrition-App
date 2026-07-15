from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, inspect, make_url, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from app.operators import historical_recipe_bridge as bridge_module
from app.operators import historical_recipe_converter as converter_module
from app.operators import historical_recipe_qualification as qualification_module
from app.operators.historical_database_inventory import inventory_database
from app.operators.historical_recipe_bridge import (
    SCHEMA_SIGNATURE_DIGEST,
    bridge_legacy_recipes,
    establish_conversion_clone_marker,
    legacy_schema_structure,
)
from app.operators.historical_recipe_converter import (
    execute_historical_recipe_conversion,
)
from app.operators.historical_recipe_planner import plan_historical_recipe_conversion
from app.operators.historical_recipe_qualification import (
    Phase5CQualificationError,
    qualify_historical_recipe_conversion,
)
from app.operators.phase5c_contracts import (
    CONTROL_REVISION,
    CONVERSION_PLAN_VERSION,
    EXECUTION_REVISION,
    Phase5CAdmissionError,
    SUPPORTED_SCHEMA_SIGNATURE,
    canonical_digest,
    canonical_json,
)
from app.operators.phase5c_isolation import (
    build_operator_attestation,
    load_clone_marker,
    phase5c_maintenance_session,
    safe_database_identity,
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


@pytest.fixture()
def conversion_clone() -> tuple[Engine, str, str]:
    admin = create_engine(
        POSTGRES_URL,
        pool_pre_ping=True,
        isolation_level="AUTOCOMMIT",
    )
    try:
        with admin.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - depends on developer environment.
        admin.dispose()
        pytest.skip(f"PostgreSQL conversion database unavailable: {exc}")

    token = uuid4().hex
    database_name = f"test_phase5c_clone_{token}"
    archive_schema = f"test_phase5c_archive_{token}"
    assert len(database_name.encode("ascii")) <= 63
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    admin.dispose()
    database_url = make_url(POSTGRES_URL).set(database=database_name).render_as_string(
        hide_password=False
    )
    engine = create_engine(database_url, pool_pre_ping=True, poolclass=NullPool)
    try:
        yield engine, database_url, archive_schema
    finally:
        engine.dispose()
        cleanup = create_engine(
            POSTGRES_URL,
            pool_pre_ping=True,
            isolation_level="AUTOCOMMIT",
        )
        try:
            with cleanup.connect() as connection:
                connection.execute(text(f'DROP DATABASE "{database_name}" WITH (FORCE)'))
        finally:
            cleanup.dispose()


def _upgrade(database_url: str, revision: str) -> None:
    result = _run_alembic(database_url, revision)
    assert result.returncode == 0, result.stderr


def _seed_recipe(
    engine: Engine,
    *,
    recipe_id: UUID | None = None,
    instructions: str | None = None,
    foreign_ingredient_owner: bool = False,
    user_id: UUID | None = None,
    ingredient_food_item_id: UUID | None = None,
    ingredient_serving_id: UUID | None = None,
) -> dict[str, UUID]:
    if (ingredient_food_item_id is None) != (ingredient_serving_id is None):
        raise ValueError("Nested ingredient Food and serving must be supplied together")
    uses_existing_ingredient = ingredient_food_item_id is not None
    ids = {
        "user": user_id or uuid4(),
        "foreign_user": uuid4(),
        "recipe": recipe_id or uuid4(),
        "projection": uuid4(),
        "projection_serving": uuid4(),
        "projection_nutrient": uuid4(),
        "ingredient_food": ingredient_food_item_id or uuid4(),
        "ingredient_serving": ingredient_serving_id or uuid4(),
        "ingredient_nutrient": uuid4(),
        "ingredient": uuid4(),
    }
    with engine.begin() as connection:
        if user_id is None:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, display_name) VALUES "
                    "(:user_id, :user_email, 'Recipe Owner'), "
                    "(:foreign_id, :foreign_email, 'Foreign Owner')"
                ),
                {
                    "user_id": ids["user"],
                    "user_email": f"phase5c-{ids['user']}@example.test",
                    "foreign_id": ids["foreign_user"],
                    "foreign_email": f"phase5c-{ids['foreign_user']}@example.test",
                },
            )
        else:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, display_name) VALUES "
                    "(:foreign_id, :foreign_email, 'Foreign Owner')"
                ),
                {
                    "foreign_id": ids["foreign_user"],
                    "foreign_email": f"phase5c-{ids['foreign_user']}@example.test",
                },
            )
        connection.execute(
            text(
                """
                INSERT INTO food_items
                    (id, user_id, name, source_type, source_id, is_recipe)
                VALUES (:projection_id, :user_id, 'Historical Recipe Projection',
                        'recipe', :recipe_source_id, true)
                """
            ),
            {
                "projection_id": ids["projection"],
                "ingredient_id": ids["ingredient_food"],
                "user_id": ids["user"],
                "ingredient_owner": (
                    ids["foreign_user"] if foreign_ingredient_owner else ids["user"]
                ),
                "recipe_source_id": str(ids["recipe"]),
            },
        )
        if not uses_existing_ingredient:
            connection.execute(
                text(
                    """
                    INSERT INTO food_items
                        (id, user_id, name, source_type, source_id, is_recipe)
                    VALUES (:ingredient_id, :ingredient_owner,
                            'Historical Ingredient', 'manual', NULL, false)
                    """
                ),
                {
                    "ingredient_id": ids["ingredient_food"],
                    "ingredient_owner": (
                        ids["foreign_user"]
                        if foreign_ingredient_owner
                        else ids["user"]
                    ),
                },
            )
        connection.execute(
            text(
                """
                INSERT INTO serving_definitions
                    (id, food_item_id, label, quantity, unit, gram_weight,
                     is_default, source, is_user_confirmed)
                VALUES (:projection_serving, :projection, '1 serving', 1,
                        'serving', 250, true, 'recipe', true)
                """
            ),
            ids,
        )
        if not uses_existing_ingredient:
            connection.execute(
                text(
                    """
                    INSERT INTO serving_definitions
                        (id, food_item_id, label, quantity, unit, gram_weight,
                         is_default, source, is_user_confirmed)
                    VALUES (:ingredient_serving, :ingredient_food, '1 cup', 1,
                            'cup', 100, true, 'manual', true)
                    """
                ),
                ids,
            )
        connection.execute(
            text(
                """
                INSERT INTO food_nutrients
                    (id, food_item_id, nutrient_id, amount, unit, basis, data_status,
                     source, is_user_confirmed)
                VALUES (:projection_nutrient, :projection, 'calories', 200, 'kcal',
                        'per_serving', 'known', 'recipe', true)
                """
            ),
            ids,
        )
        if not uses_existing_ingredient:
            connection.execute(
                text(
                    """
                    INSERT INTO food_nutrients
                        (id, food_item_id, nutrient_id, amount, unit, basis,
                         data_status, source, is_user_confirmed)
                    VALUES (:ingredient_nutrient, :ingredient_food, 'calories',
                            100, 'kcal', 'per_serving', 'known', 'manual', true)
                    """
                ),
                ids,
            )
        connection.execute(
            text(
                """
                INSERT INTO recipes
                    (id, food_item_id, user_id, serving_count, final_yield_quantity,
                     final_yield_unit, instructions)
                VALUES (:recipe, :projection, :user, 2, 500, 'g', :instructions)
                """
            ),
            {**ids, "instructions": instructions},
        )
        connection.execute(
            text(
                """
                INSERT INTO recipe_ingredients
                    (id, recipe_id, ingredient_food_item_id, quantity, unit,
                     serving_definition_id, gram_amount, preparation_note, sort_order)
                VALUES (:ingredient, :recipe, :ingredient_food, 2, :ingredient_unit,
                        :ingredient_serving, :ingredient_grams, 'prepared', 0)
                """
            ),
            {
                **ids,
                "ingredient_unit": "serving" if uses_existing_ingredient else "cup",
                "ingredient_grams": 500 if uses_existing_ingredient else 200,
            },
        )
    return ids


def _seed_historical_log_and_ocr(engine: Engine, ids: dict[str, UUID]) -> None:
    daily_log_id = uuid4()
    scan_id = uuid4()
    parse_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO daily_logs
                    (id, user_id, food_item_id, logged_date, meal_type,
                     amount_quantity, amount_unit, serving_definition_id,
                     gram_amount, notes)
                VALUES (:id, :user_id, :food_id, DATE '2024-01-02', 'lunch',
                        2, 'cup', :serving_id, 200, 'historical log note')
                """
            ),
            {
                "id": daily_log_id,
                "user_id": ids["user"],
                "food_id": ids["ingredient_food"],
                "serving_id": ids["ingredient_serving"],
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO daily_log_nutrient_snapshots
                    (id, daily_log_id, source_food_item_id,
                     source_food_nutrient_id, serving_definition_id, nutrient_id,
                     amount, unit, data_status, consumed_amount_quantity,
                     consumed_amount_unit, consumed_gram_amount,
                     calculation_metadata)
                VALUES (:id, :log_id, :food_id, :nutrient_id, :serving_id,
                        'calories', 200, 'kcal', 'known', 2, 'cup', 200,
                        '{"historical":"snapshot"}'::jsonb)
                """
            ),
            {
                "id": uuid4(),
                "log_id": daily_log_id,
                "food_id": ids["ingredient_food"],
                "nutrient_id": ids["ingredient_nutrient"],
                "serving_id": ids["ingredient_serving"],
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO ocr_scans
                    (id, user_id, image_metadata, ocr_engine, raw_ocr_payload,
                     full_text)
                VALUES (:scan_id, :user_id, '{"source":"camera"}'::jsonb,
                        'historical-engine', '{"private":"ocr payload"}'::jsonb,
                        'historical OCR text')
                """
            ),
            {"scan_id": scan_id, "user_id": ids["user"]},
        )
        connection.execute(
            text(
                """
                INSERT INTO parse_results
                    (id, ocr_scan_id, parser_version, status, diagnostics,
                     parsed_payload, created_food_item_id)
                VALUES (:parse_id, :scan_id, 'legacy-parser', 'confirmed',
                        '{"diagnostic":"private"}'::jsonb,
                        '{"parsed":"private"}'::jsonb, :food_id)
                """
            ),
            {
                "parse_id": parse_id,
                "scan_id": scan_id,
                "food_id": ids["ingredient_food"],
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO parser_corrections
                    (id, user_id, ocr_scan_id, parse_result_id, parser_version,
                     field_name, parsed_value, confirmed_value,
                     confirmation_action)
                VALUES (:id, :user_id, :scan_id, :parse_id, 'legacy-parser',
                        'serving_size', '{"old":"private"}'::jsonb,
                        '{"new":"private"}'::jsonb, 'replace')
                """
            ),
            {
                "id": uuid4(),
                "user_id": ids["user"],
                "scan_id": scan_id,
                "parse_id": parse_id,
            },
        )


def _seed_qualification_preservation_rows(
    engine: Engine, archive_schema: str
) -> None:
    archive = engine.dialect.identifier_preparer.quote(archive_schema)
    with engine.connect() as connection:
        row = connection.execute(
            text(
                f"SELECT recipe.user_id, ingredient.ingredient_food_item_id, "
                f"ingredient.serving_definition_id FROM {archive}.recipes recipe "
                f"JOIN {archive}.recipe_ingredients ingredient "
                "ON ingredient.recipe_id = recipe.id ORDER BY recipe.id LIMIT 1"
            )
        ).mappings().one()
        nutrient_id = connection.scalar(
            text(
                "SELECT id FROM food_nutrients WHERE food_item_id = :food_id "
                "ORDER BY id LIMIT 1"
            ),
            {"food_id": row["ingredient_food_item_id"]},
        )
    _seed_historical_log_and_ocr(
        engine,
        {
            "user": row["user_id"],
            "ingredient_food": row["ingredient_food_item_id"],
            "ingredient_serving": row["serving_definition_id"],
            "ingredient_nutrient": nutrient_id,
        },
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO ocr_nutrition_confirmation_traces "
                "(id, user_id, food_item_id, parser_version, image_source_type, "
                "schema_version, trace_snapshot, client_request_id, "
                "request_fingerprint) VALUES "
                "(:id, :user_id, :food_id, 'legacy-parser', 'camera', 'v1', "
                "'{\"private\":\"trace payload\"}'::jsonb, :request_id, "
                "'qualification-fixture')"
            ),
            {
                "id": uuid4(),
                "user_id": row["user_id"],
                "food_id": row["ingredient_food_item_id"],
                "request_id": uuid4(),
            },
        )


def _inventory(engine: Engine) -> dict:
    report = inventory_database(engine).to_dict()
    assert report["classification"]["value"] == "legacy_conversion_required"
    return report


def _bridge(
    engine: Engine,
    archive_schema: str,
    inventory: dict,
    evidence: dict,
):
    return bridge_legacy_recipes(
        engine,
        inventory_payload=inventory,
        archive_schema=archive_schema,
        conversion_clone_id=evidence["conversion_clone_id"],
        clone_marker_identity=evidence["clone_marker_identity"],
        attestation_payload=evidence["attestation"],
    )


def _prepare_isolation_evidence(
    engine: Engine,
    archive_schema: str,
    inventory: dict,
    *,
    scope: str = "bridge_and_planning",
    establish_marker: bool = True,
    operator_attestation_identity: str = "phase5c-test-operator",
    clone_marker_identity: str = "phase5c-test-clone-marker",
    conversion_clone_id: str = "phase5c-test-conversion-clone",
    source_production_identity_digest: str | None = None,
) -> dict:
    with engine.connect() as connection:
        clone_identity = safe_database_identity(connection)
        if source_production_identity_digest is None:
            source_unsigned = {
                key: value
                for key, value in clone_identity.items()
                if key != "identity_digest"
            }
            source_unsigned["schema"] = "recorded_production_source"
            source_production_identity_digest = canonical_digest(source_unsigned)
        attestation = build_operator_attestation(
            connection,
            operator_attestation_identity=operator_attestation_identity,
            scope=scope,
            clone_marker_identity=clone_marker_identity,
            conversion_clone_id=conversion_clone_id,
            source_production_identity_digest=source_production_identity_digest,
            inventory_digest=canonical_digest(inventory),
            schema_signature=SUPPORTED_SCHEMA_SIGNATURE,
            schema_signature_digest=SCHEMA_SIGNATURE_DIGEST,
        )
    if establish_marker:
        establish_conversion_clone_marker(
            engine,
            inventory_payload=inventory,
            archive_schema=archive_schema,
            clone_marker_identity=clone_marker_identity,
            conversion_clone_id=conversion_clone_id,
            attestation_payload=attestation,
        )
    return {
        "clone_marker_identity": clone_marker_identity,
        "conversion_clone_id": conversion_clone_id,
        "attestation": attestation,
    }


def _archive_rows(engine: Engine, archive_schema: str, table: str) -> list[dict]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(f'SELECT * FROM "{archive_schema}"."{table}" ORDER BY id')
        ).mappings().all()
    return [dict(row) for row in rows]


def test_bridge_creates_verified_archive_placeholders_and_is_restart_safe(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    _upgrade(database_url, "0003_usda_source_identity")
    _seed_recipe(engine)
    inventory = _inventory(engine)
    evidence = _prepare_isolation_evidence(engine, archive_schema, inventory)
    with engine.connect() as connection:
        recipes_before = [dict(row) for row in connection.execute(
            text("SELECT * FROM recipes ORDER BY id")
        ).mappings().all()]
        ingredients_before = [dict(row) for row in connection.execute(
            text("SELECT * FROM recipe_ingredients ORDER BY id")
        ).mappings().all()]

    first = _bridge(engine, archive_schema, inventory, evidence)
    second = _bridge(engine, archive_schema, inventory, evidence)

    assert first.payload["archive_created"] is True
    assert second.payload["archive_created"] is False
    assert first.payload["archive_identity"] == second.payload["archive_identity"]
    assert first.payload["schema_signature"] == SUPPORTED_SCHEMA_SIGNATURE
    assert first.payload["schema_signature_digest"] == SCHEMA_SIGNATURE_DIGEST
    assert first.payload["semantic_conversion_performed"] is False
    assert evidence["conversion_clone_id"] not in (first.to_json() + first.to_human())
    assert _archive_rows(engine, archive_schema, "recipes") == recipes_before
    assert _archive_rows(engine, archive_schema, "recipe_ingredients") == ingredients_before
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM recipes")) == 0
        assert connection.scalar(text("SELECT count(*) FROM recipe_ingredients")) == 0
        assert legacy_schema_structure(connection, archive_schema) == legacy_schema_structure(
            connection, str(connection.scalar(text("SELECT current_schema()")))
        )
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0003_usda_source_identity"
        )
    with pytest.raises(Phase5CAdmissionError, match="command evidence"):
        bridge_legacy_recipes(
            engine,
            inventory_payload=inventory,
            archive_schema=archive_schema,
            conversion_clone_id="different-conversion-clone",
            clone_marker_identity=evidence["clone_marker_identity"],
            attestation_payload=evidence["attestation"],
        )
    changed_source = _prepare_isolation_evidence(
        engine,
        archive_schema,
        inventory,
        establish_marker=False,
        source_production_identity_digest="a" * 64,
    )
    with pytest.raises(Phase5CAdmissionError, match="marker and attestation differ"):
        _bridge(engine, archive_schema, inventory, changed_source)


def test_bridge_rejects_unsupported_revision_and_schema_signature(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    _upgrade(database_url, "0003_usda_source_identity")
    _seed_recipe(engine)
    inventory = _inventory(engine)
    evidence = _prepare_isolation_evidence(engine, archive_schema, inventory)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE alembic_version SET version_num = '0002_snapshot_fk'")
        )
    with pytest.raises(Phase5CAdmissionError, match="source revision"):
        _bridge(engine, archive_schema, inventory, evidence)

    with engine.begin() as connection:
        connection.execute(
            text("UPDATE alembic_version SET version_num = '0003_usda_source_identity'")
        )
        connection.execute(text("ALTER TABLE recipes ADD COLUMN unsupported_column text"))
    with pytest.raises(Phase5CAdmissionError, match="supported signature"):
        _bridge(engine, archive_schema, inventory, evidence)


def test_bridge_restart_detects_archived_row_tampering(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    _upgrade(database_url, "0003_usda_source_identity")
    _seed_recipe(engine)
    inventory = _inventory(engine)
    evidence = _prepare_isolation_evidence(engine, archive_schema, inventory)
    _bridge(engine, archive_schema, inventory, evidence)
    with engine.begin() as connection:
        connection.execute(
            text(f'UPDATE "{archive_schema}".recipes SET instructions = :value'),
            {"value": "tampered historical content"},
        )
    with pytest.raises(Phase5CAdmissionError, match="checksum verification failed"):
        _bridge(engine, archive_schema, inventory, evidence)


def test_clone_marker_preflight_is_required_and_changes_no_domain_or_revision_rows(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    _upgrade(database_url, "0003_usda_source_identity")
    ids = _seed_recipe(engine)
    inventory = _inventory(engine)
    evidence = _prepare_isolation_evidence(
        engine,
        archive_schema,
        inventory,
        establish_marker=False,
    )

    with pytest.raises(Phase5CAdmissionError, match="clone_marker_missing"):
        _bridge(engine, archive_schema, inventory, evidence)

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0003_usda_source_identity"
        )
        assert connection.scalar(
            text("SELECT count(*) FROM recipes WHERE id = :id"), {"id": ids["recipe"]}
        ) == 1
        assert connection.scalar(
            text("SELECT count(*) FROM recipe_ingredients WHERE id = :id"),
            {"id": ids["ingredient"]},
        ) == 1

    established = establish_conversion_clone_marker(
        engine,
        inventory_payload=inventory,
        archive_schema=archive_schema,
        clone_marker_identity=evidence["clone_marker_identity"],
        conversion_clone_id=evidence["conversion_clone_id"],
        attestation_payload=evidence["attestation"],
    )
    repeated = establish_conversion_clone_marker(
        engine,
        inventory_payload=inventory,
        archive_schema=archive_schema,
        clone_marker_identity=evidence["clone_marker_identity"],
        conversion_clone_id=evidence["conversion_clone_id"],
        attestation_payload=evidence["attestation"],
    )
    assert established == repeated
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0003_usda_source_identity"
        )
        assert connection.scalar(text("SELECT count(*) FROM recipes")) == 1
        assert connection.scalar(text("SELECT count(*) FROM recipe_ingredients")) == 1
        assert connection.scalar(
            text("SELECT count(*) FROM phase5c_conversion_clone_marker")
        ) == 1


def test_clone_admission_rejects_source_equality_and_mismatched_evidence(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    _upgrade(database_url, "0003_usda_source_identity")
    _seed_recipe(engine)
    inventory = _inventory(engine)
    with engine.connect() as connection:
        safe_identity = safe_database_identity(connection)
        clone_digest = safe_identity["identity_digest"]
    rendered_identity = canonical_json(safe_identity)
    parsed_url = make_url(database_url)
    assert parsed_url.username not in rendered_identity
    assert parsed_url.password not in rendered_identity
    assert "NUTRITION_DATABASE_URL" not in rendered_identity
    with pytest.raises(Phase5CAdmissionError, match="clone_matches_source"):
        _prepare_isolation_evidence(
            engine,
            archive_schema,
            inventory,
            source_production_identity_digest=clone_digest,
        )

    evidence = _prepare_isolation_evidence(engine, archive_schema, inventory)
    with pytest.raises(Phase5CAdmissionError, match="command evidence"):
        bridge_legacy_recipes(
            engine,
            inventory_payload=inventory,
            archive_schema=archive_schema,
            conversion_clone_id=evidence["conversion_clone_id"],
            clone_marker_identity="phase5c-different-marker",
            attestation_payload=evidence["attestation"],
        )

    different_attestation = _prepare_isolation_evidence(
        engine,
        archive_schema,
        inventory,
        establish_marker=False,
        operator_attestation_identity="phase5c-different-operator",
        source_production_identity_digest=evidence["attestation"][
            "source_production_identity_digest"
        ],
    )
    with pytest.raises(Phase5CAdmissionError, match="marker and attestation differ"):
        _bridge(engine, archive_schema, inventory, different_attestation)

    planning_only = _prepare_isolation_evidence(
        engine,
        archive_schema,
        inventory,
        establish_marker=False,
        scope="planning",
        source_production_identity_digest=evidence["attestation"][
            "source_production_identity_digest"
        ],
    )
    with pytest.raises(Phase5CAdmissionError, match="scope"):
        _bridge(engine, archive_schema, inventory, planning_only)


def test_clone_admission_rejects_unsupported_evidence_versions(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    _upgrade(database_url, "0003_usda_source_identity")
    _seed_recipe(engine)
    inventory = _inventory(engine)
    evidence = _prepare_isolation_evidence(engine, archive_schema, inventory)

    unsupported_attestation = deepcopy(evidence)
    unsupported_attestation["attestation"] = deepcopy(evidence["attestation"])
    unsupported_attestation["attestation"]["attestation_version"] = "unsupported"
    with pytest.raises(Phase5CAdmissionError, match="attestation version"):
        _bridge(engine, archive_schema, inventory, unsupported_attestation)

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE phase5c_conversion_clone_marker "
                "SET marker_format_version = 'unsupported'"
            )
        )
    with pytest.raises(Phase5CAdmissionError, match="marker version"):
        _bridge(engine, archive_schema, inventory, evidence)


def test_bridge_rejects_nonmaintenance_session_and_accepts_marker_lock_holder(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    _upgrade(database_url, "0003_usda_source_identity")
    _seed_recipe(engine)
    inventory = _inventory(engine)
    evidence = _prepare_isolation_evidence(engine, archive_schema, inventory)
    blocker_engine = create_engine(database_url, pool_pre_ping=True)
    blocker = blocker_engine.connect()
    blocker.execute(text("SELECT 1"))
    blocker.commit()
    try:
        with pytest.raises(Phase5CAdmissionError, match="nonmaintenance_sessions"):
            _bridge(engine, archive_schema, inventory, evidence)
    finally:
        blocker.close()
        blocker_engine.dispose()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM recipes")) == 1
        assert archive_schema not in inspect(connection).get_schema_names()

    with engine.connect() as permitted:
        marker = load_clone_marker(permitted)
        permitted.rollback()
        with phase5c_maintenance_session(permitted, marker["clone_marker_digest"]):
            result = _bridge(engine, archive_schema, inventory, evidence)
    assert result.payload["archive_created"] is True


def test_bridge_rechecks_sessions_after_operation_lock_and_rolls_back(
    conversion_clone: tuple[Engine, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, database_url, archive_schema = conversion_clone
    _upgrade(database_url, "0003_usda_source_identity")
    _seed_recipe(engine)
    inventory = _inventory(engine)
    evidence = _prepare_isolation_evidence(engine, archive_schema, inventory)
    original = bridge_module.assert_database_session_isolation
    blocker_engine = create_engine(database_url, pool_pre_ping=True)
    blocker = None
    calls = 0

    def inject_session(connection, marker_digest):
        nonlocal blocker, calls
        original(connection, marker_digest)
        calls += 1
        if calls == 1:
            blocker = blocker_engine.connect()
            blocker.execute(text("SELECT 1"))
            blocker.commit()

    monkeypatch.setattr(
        bridge_module,
        "assert_database_session_isolation",
        inject_session,
    )
    try:
        with pytest.raises(Phase5CAdmissionError, match="nonmaintenance_sessions"):
            _bridge(engine, archive_schema, inventory, evidence)
    finally:
        if blocker is not None:
            blocker.close()
        blocker_engine.dispose()
    assert calls == 1
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM recipes")) == 1
        assert archive_schema not in inspect(connection).get_schema_names()


def test_concurrent_bridges_serialize_with_maintenance_admission(
    conversion_clone: tuple[Engine, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, database_url, archive_schema = conversion_clone
    _upgrade(database_url, "0003_usda_source_identity")
    _seed_recipe(engine)
    inventory = _inventory(engine)
    evidence = _prepare_isolation_evidence(engine, archive_schema, inventory)
    barrier = threading.Barrier(2)
    local = threading.local()
    original = bridge_module.assert_database_session_isolation

    def synchronize_first_check(connection, marker_digest):
        if not getattr(local, "entered", False):
            local.entered = True
            barrier.wait(timeout=10)
        original(connection, marker_digest)

    monkeypatch.setattr(
        bridge_module,
        "assert_database_session_isolation",
        synchronize_first_check,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(_bridge, engine, archive_schema, inventory, evidence)
            for _ in range(2)
        ]
        results = [future.result(timeout=20) for future in futures]
    assert sorted(result.payload["archive_created"] for result in results) == [False, True]
    with engine.connect() as connection:
        assert connection.scalar(
            text(f'SELECT count(*) FROM "{archive_schema}".bridge_metadata')
        ) == 1


def _prepare_planner_clone(
    engine: Engine,
    database_url: str,
    archive_schema: str,
    *,
    classified_fixture: bool = False,
    convert_count: int = 1,
) -> tuple[dict, dict]:
    _upgrade(database_url, "0003_usda_source_identity")
    if classified_fixture:
        _seed_recipe(
            engine,
            recipe_id=UUID("00000000-0000-0000-0000-000000000003"),
            foreign_ingredient_owner=True,
        )
        _seed_recipe(
            engine,
            recipe_id=UUID("00000000-0000-0000-0000-000000000002"),
            instructions="historical instructions have no lossless current field",
        )
        _seed_recipe(
            engine,
            recipe_id=UUID("00000000-0000-0000-0000-000000000001"),
        )
    else:
        for _ in range(convert_count):
            _seed_recipe(engine)
    inventory = _inventory(engine)
    evidence = _prepare_isolation_evidence(engine, archive_schema, inventory)
    _bridge(engine, archive_schema, inventory, evidence)
    _upgrade(database_url, CONTROL_REVISION)
    return inventory, evidence


def _prepare_execution_clone(
    engine: Engine,
    database_url: str,
    archive_schema: str,
    *,
    classified_fixture: bool = False,
    convert_count: int = 1,
) -> tuple[dict, dict, dict]:
    inventory, evidence = _prepare_planner_clone(
        engine,
        database_url,
        archive_schema,
        classified_fixture=classified_fixture,
        convert_count=convert_count,
    )
    plan = plan_historical_recipe_conversion(
        engine,
        inventory_payload=inventory,
        archive_schema=archive_schema,
        conversion_clone_id=evidence["conversion_clone_id"],
        clone_marker_identity=evidence["clone_marker_identity"],
        attestation_payload=evidence["attestation"],
    ).payload
    evidence["execution_attestation"] = _build_execution_attestation(
        engine, inventory, evidence, plan
    )
    _upgrade(database_url, EXECUTION_REVISION)
    return inventory, evidence, plan


def _build_execution_attestation(
    engine: Engine,
    inventory: dict,
    evidence: dict,
    plan: dict,
    *,
    scope: str = "execution",
    operator_attestation_identity: str = "phase5c-test-execution-operator",
) -> dict:
    with engine.connect() as connection:
        return build_operator_attestation(
            connection,
            operator_attestation_identity=operator_attestation_identity,
            scope=scope,
            clone_marker_identity=evidence["clone_marker_identity"],
            conversion_clone_id=evidence["conversion_clone_id"],
            source_production_identity_digest=evidence["attestation"][
                "source_production_identity_digest"
            ],
            inventory_digest=canonical_digest(inventory),
            schema_signature=SUPPORTED_SCHEMA_SIGNATURE,
            schema_signature_digest=SCHEMA_SIGNATURE_DIGEST,
            conversion_plan_payload=plan,
        )


def _execute_conversion(
    engine: Engine,
    archive_schema: str,
    inventory: dict,
    evidence: dict,
    plan: dict,
    **kwargs,
):
    attestation_payload = kwargs.pop(
        "attestation_payload",
        evidence.get("execution_attestation"),
    )
    if attestation_payload is None:
        attestation_payload = _build_execution_attestation(
            engine, inventory, evidence, plan
        )
    return execute_historical_recipe_conversion(
        engine,
        plan_payload=plan,
        inventory_payload=inventory,
        archive_schema=archive_schema,
        conversion_clone_id=evidence["conversion_clone_id"],
        clone_marker_identity=evidence["clone_marker_identity"],
        attestation_payload=attestation_payload,
        **kwargs,
    )


def _qualify_conversion(
    engine: Engine,
    archive_schema: str,
    inventory: dict,
    evidence: dict,
    plan: dict,
    execution_receipt: dict,
    **kwargs,
):
    return qualify_historical_recipe_conversion(
        engine,
        plan_payload=kwargs.pop("plan_payload", plan),
        inventory_payload=kwargs.pop("inventory_payload", inventory),
        execution_attestation_payload=kwargs.pop(
            "execution_attestation_payload", evidence["execution_attestation"]
        ),
        execution_receipt_payload=kwargs.pop(
            "execution_receipt_payload", execution_receipt
        ),
        archive_schema=kwargs.pop("archive_schema_override", archive_schema),
        conversion_clone_id=kwargs.pop(
            "conversion_clone_id", evidence["conversion_clone_id"]
        ),
        clone_marker_identity=kwargs.pop(
            "clone_marker_identity", evidence["clone_marker_identity"]
        ),
        **kwargs,
    )


def _redigest_attestation(attestation: dict, **changes) -> dict:
    changed = deepcopy(attestation)
    for key, value in changes.items():
        if key.startswith("schema_signature__"):
            changed["schema_signature"][key.removeprefix("schema_signature__")] = value
        else:
            changed[key] = value
    unsigned = {
        key: value for key, value in changed.items() if key != "attestation_digest"
    }
    changed["attestation_digest"] = canonical_digest(unsigned)
    return changed


def _redigest_plan(plan: dict, **changes) -> dict:
    changed = deepcopy(plan)
    for path, value in changes.items():
        target = changed
        keys = path.split("__")
        for key in keys[:-1]:
            target = target[int(key)] if isinstance(target, list) else target[key]
        if isinstance(target, list):
            target[int(keys[-1])] = value
        else:
            target[keys[-1]] = value
    unsigned = {key: value for key, value in changed.items() if key != "manifest_digest"}
    changed["manifest_digest"] = canonical_digest(unsigned)
    return changed


def _plan_authorization_evidence(plan: dict) -> dict:
    return {
        "contract_version": plan["manifest_version"],
        "digest": plan["manifest_digest"],
        "archive_identity": plan["source_identity"]["archive_identity"],
        "source_checksums": plan["source_checksums"],
    }


def _domain_fingerprints(engine: Engine, archive_schema: str) -> dict[str, str]:
    tables = (
        "food_items",
        "food_nutrients",
        "serving_definitions",
        "daily_logs",
        "daily_log_nutrient_snapshots",
        "ocr_scans",
        "parse_results",
        "parser_corrections",
        "recipes",
        "recipe_ingredients",
        "recipe_publication_revisions",
        "recipe_publication_amount_definitions",
        "recipe_publication_nutrients",
    )
    result: dict[str, str] = {}
    with engine.connect() as connection:
        for table in tables:
            result[table] = str(
                connection.scalar(
                    text(
                        f"SELECT md5(COALESCE(jsonb_agg(to_jsonb(row_value) "
                        f"ORDER BY row_value.id)::text, '[]')) FROM {table} row_value"
                    )
                )
            )
        for table in ("recipes", "recipe_ingredients"):
            result[f"archive.{table}"] = str(
                connection.scalar(
                    text(
                        f'SELECT md5(COALESCE(jsonb_agg(to_jsonb(row_value) '
                        f'ORDER BY row_value.id)::text, \'[]\')) '
                        f'FROM "{archive_schema}"."{table}" row_value'
                    )
                )
            )
    return result


def test_planner_is_deterministic_classifies_every_recipe_and_changes_no_domain_rows(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence = _prepare_planner_clone(
        engine,
        database_url,
        archive_schema,
        classified_fixture=True,
    )
    before = _domain_fingerprints(engine, archive_schema)

    first = plan_historical_recipe_conversion(
        engine,
        inventory_payload=inventory,
        archive_schema=archive_schema,
        conversion_clone_id=evidence["conversion_clone_id"],
        clone_marker_identity=evidence["clone_marker_identity"],
        attestation_payload=evidence["attestation"],
    )
    second = plan_historical_recipe_conversion(
        engine,
        inventory_payload=inventory,
        archive_schema=archive_schema,
        conversion_clone_id=evidence["conversion_clone_id"],
        clone_marker_identity=evidence["clone_marker_identity"],
        attestation_payload=evidence["attestation"],
    )
    after = _domain_fingerprints(engine, archive_schema)

    assert first.to_json() == second.to_json()
    assert before == after
    payload = first.payload
    assert payload["manifest_version"] == CONVERSION_PLAN_VERSION
    assert payload["summary"] == {
        "total": 3,
        "convert": 1,
        "quarantine": 1,
        "block": 1,
    }
    assert [decision["source_recipe_id"] for decision in payload["decisions"]] == [
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000003",
    ]
    assert [decision["intended_disposition"] for decision in payload["decisions"]] == [
        "convert",
        "quarantine",
        "block",
    ]
    assert [decision["reason_code"] for decision in payload["decisions"]] == [
        "eligible_lossless_mapping",
        "instructions_not_losslessly_representable",
        "ingredient_owner_mismatch",
    ]
    unsigned = {key: value for key, value in payload.items() if key != "manifest_digest"}
    assert payload["manifest_digest"] == canonical_digest(unsigned)
    assert len({decision["source_checksum"] for decision in payload["decisions"]}) == 3
    rendered = first.to_json() + first.to_human()
    assert "Historical Recipe Projection" not in rendered
    assert "Historical Ingredient" not in rendered
    assert "historical instructions have no lossless current field" not in rendered
    assert "prepared" not in rendered
    assert "timestamp" not in rendered.casefold()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM phase5c_conversion_metadata")) == 1
        assert connection.scalar(
            text("SELECT manifest_digest FROM phase5c_conversion_metadata")
        ) == payload["manifest_digest"]
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            CONTROL_REVISION
        )


def test_planner_rejects_unsupported_inventory_archive_schema_and_source_changes(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence = _prepare_planner_clone(engine, database_url, archive_schema)
    unsupported = deepcopy(inventory)
    unsupported["schema_version"] = "historical_database_inventory_v999"
    with pytest.raises(Phase5CAdmissionError, match="Unsupported historical inventory"):
        plan_historical_recipe_conversion(
            engine,
            inventory_payload=unsupported,
            archive_schema=archive_schema,
            conversion_clone_id=evidence["conversion_clone_id"],
            clone_marker_identity=evidence["clone_marker_identity"],
            attestation_payload=evidence["attestation"],
        )

    with engine.begin() as connection:
        connection.execute(
            text(
                f'UPDATE "{archive_schema}".bridge_metadata '
                "SET source_alembic_revision = '0002_snapshot_fk'"
            )
        )
    with pytest.raises(Phase5CAdmissionError, match="planner prerequisites"):
        plan_historical_recipe_conversion(
            engine,
            inventory_payload=inventory,
            archive_schema=archive_schema,
            conversion_clone_id=evidence["conversion_clone_id"],
            clone_marker_identity=evidence["clone_marker_identity"],
            attestation_payload=evidence["attestation"],
        )
    with engine.begin() as connection:
        connection.execute(
            text(
                f'UPDATE "{archive_schema}".bridge_metadata '
                "SET source_alembic_revision = '0003_usda_source_identity'"
            )
        )

    with engine.begin() as connection:
        connection.execute(
            text("UPDATE food_items SET name = 'changed after bridge' WHERE is_recipe = true")
        )
    with pytest.raises(Phase5CAdmissionError, match="checksums cannot be reproduced"):
        plan_historical_recipe_conversion(
            engine,
            inventory_payload=inventory,
            archive_schema=archive_schema,
            conversion_clone_id=evidence["conversion_clone_id"],
            clone_marker_identity=evidence["clone_marker_identity"],
            attestation_payload=evidence["attestation"],
        )

    with engine.begin() as connection:
        connection.execute(text(f'ALTER TABLE "{archive_schema}".recipes ADD COLUMN drift text'))
    with pytest.raises(Phase5CAdmissionError, match="supported signature"):
        plan_historical_recipe_conversion(
            engine,
            inventory_payload=inventory,
            archive_schema=archive_schema,
            conversion_clone_id=evidence["conversion_clone_id"],
            clone_marker_identity=evidence["clone_marker_identity"],
            attestation_payload=evidence["attestation"],
        )


def test_planner_requires_unchanged_marker_and_attested_command_evidence(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence = _prepare_planner_clone(engine, database_url, archive_schema)
    with pytest.raises(Phase5CAdmissionError, match="command evidence"):
        plan_historical_recipe_conversion(
            engine,
            inventory_payload=inventory,
            archive_schema=archive_schema,
            conversion_clone_id=evidence["conversion_clone_id"],
            clone_marker_identity="phase5c-changed-marker",
            attestation_payload=evidence["attestation"],
        )
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE phase5c_conversion_clone_marker"))
    with pytest.raises(Phase5CAdmissionError, match="clone_marker_missing"):
        plan_historical_recipe_conversion(
            engine,
            inventory_payload=inventory,
            archive_schema=archive_schema,
            conversion_clone_id=evidence["conversion_clone_id"],
            clone_marker_identity=evidence["clone_marker_identity"],
            attestation_payload=evidence["attestation"],
        )


def test_planner_rejects_nonmaintenance_database_session(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence = _prepare_planner_clone(engine, database_url, archive_schema)
    blocker_engine = create_engine(database_url, pool_pre_ping=True)
    blocker = blocker_engine.connect()
    blocker.execute(text("SELECT 1"))
    blocker.commit()
    try:
        with pytest.raises(Phase5CAdmissionError, match="nonmaintenance_sessions"):
            plan_historical_recipe_conversion(
                engine,
                inventory_payload=inventory,
                archive_schema=archive_schema,
                conversion_clone_id=evidence["conversion_clone_id"],
                clone_marker_identity=evidence["clone_marker_identity"],
                attestation_payload=evidence["attestation"],
            )
    finally:
        blocker.close()
        blocker_engine.dispose()
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT count(*) FROM phase5c_conversion_metadata")
        ) == 0


def test_converter_creates_transition_baseline_and_restart_verifies_exact_state(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence, plan = _prepare_execution_clone(
        engine, database_url, archive_schema
    )
    with engine.connect() as connection:
        projection_id = connection.scalar(
            text(f'SELECT food_item_id FROM "{archive_schema}".recipes')
        )
        projection_children_before = {
            "servings": canonical_digest(
                [
                    dict(row)
                    for row in connection.execute(
                        text(
                            "SELECT * FROM serving_definitions "
                            "WHERE food_item_id = :id ORDER BY id"
                        ),
                        {"id": projection_id},
                    ).mappings()
                ]
            ),
            "nutrients": canonical_digest(
                [
                    dict(row)
                    for row in connection.execute(
                        text(
                            "SELECT * FROM food_nutrients "
                            "WHERE food_item_id = :id ORDER BY id"
                        ),
                        {"id": projection_id},
                    ).mappings()
                ]
            ),
            "sources": canonical_digest(
                [
                    dict(row)
                    for row in connection.execute(
                        text(
                            "SELECT * FROM food_sources "
                            "WHERE food_item_id = :id ORDER BY id"
                        ),
                        {"id": projection_id},
                    ).mappings()
                ]
            ),
        }

    first = execute_historical_recipe_conversion(
        engine,
        plan_payload=plan,
        inventory_payload=inventory,
        archive_schema=archive_schema,
        conversion_clone_id=evidence["conversion_clone_id"],
        clone_marker_identity=evidence["clone_marker_identity"],
        attestation_payload=evidence["execution_attestation"],
    )
    second = execute_historical_recipe_conversion(
        engine,
        plan_payload=plan,
        inventory_payload=inventory,
        archive_schema=archive_schema,
        conversion_clone_id=evidence["conversion_clone_id"],
        clone_marker_identity=evidence["clone_marker_identity"],
        attestation_payload=evidence["execution_attestation"],
    )

    assert first.to_json() == second.to_json()
    assert first.payload["counts"] == {
        "converted": 1,
        "quarantined": 0,
        "blocked": 0,
        "failed": 0,
        "pending": 0,
    }, first.payload["subjects"]
    subject = first.payload["subjects"][0]
    assert subject["source_recipe_id"] == subject["target_recipe_id"]
    assert subject["projection_food_item_id"] == str(projection_id)
    with engine.connect() as connection:
        recipe = connection.execute(text("SELECT * FROM recipes")).mappings().one()
        archived_recipe = connection.execute(
            text(f'SELECT * FROM "{archive_schema}".recipes')
        ).mappings().one()
        revision = connection.execute(
            text("SELECT * FROM recipe_publication_revisions")
        ).mappings().one()
        assert recipe["id"] == archived_recipe["id"]
        assert recipe["user_id"] == archived_recipe["user_id"]
        assert recipe["published_food_item_id"] == archived_recipe["food_item_id"]
        assert recipe["serving_count_yield"] == archived_recipe["serving_count"]
        assert recipe["final_cooked_weight_grams"] == archived_recipe[
            "final_yield_quantity"
        ]
        assert revision["revision_number"] == 1
        assert revision["creation_origin"] == "legacy_projection_capture"
        assert revision["provenance_confidence"] == "transition_baseline"
        assert recipe["active_publication_revision_id"] == revision["id"]
        assert recipe["needs_republish"] is True
        assert connection.scalar(
            text(
                "SELECT recipe_publication_revision_id FROM food_items WHERE id = :id"
            ),
            {"id": projection_id},
        ) == revision["id"]
        ingredient = connection.execute(
            text("SELECT * FROM recipe_ingredients")
        ).mappings().one()
        archived_ingredient = connection.execute(
            text(f'SELECT * FROM "{archive_schema}".recipe_ingredients')
        ).mappings().one()
        assert ingredient["id"] == archived_ingredient["id"]
        assert ingredient["food_item_id"] == archived_ingredient[
            "ingredient_food_item_id"
        ]
        assert ingredient["amount_quantity"] == archived_ingredient["quantity"]
        assert ingredient["amount_unit"] == archived_ingredient["unit"]
        assert ingredient["serving_definition_id"] == archived_ingredient[
            "serving_definition_id"
        ]
        assert ingredient["resolved_gram_amount"] == archived_ingredient["gram_amount"]
        assert ingredient["preparation_note"] == archived_ingredient["preparation_note"]
        assert ingredient["position"] == archived_ingredient["sort_order"]
        projection_children_after = {
            "servings": canonical_digest(
                [
                    dict(row)
                    for row in connection.execute(
                        text(
                            "SELECT * FROM serving_definitions "
                            "WHERE food_item_id = :id ORDER BY id"
                        ),
                        {"id": projection_id},
                    ).mappings()
                ]
            ),
            "nutrients": canonical_digest(
                [
                    dict(row)
                    for row in connection.execute(
                        text(
                            "SELECT * FROM food_nutrients "
                            "WHERE food_item_id = :id ORDER BY id"
                        ),
                        {"id": projection_id},
                    ).mappings()
                ]
            ),
            "sources": canonical_digest(
                [
                    dict(row)
                    for row in connection.execute(
                        text(
                            "SELECT * FROM food_sources "
                            "WHERE food_item_id = :id ORDER BY id"
                        ),
                        {"id": projection_id},
                    ).mappings()
                ]
            ),
        }
    assert projection_children_after == projection_children_before
    rendered = first.to_json() + first.to_human()
    assert "Historical Recipe Projection" not in rendered
    assert "Historical Ingredient" not in rendered
    assert "prepared" not in rendered


def test_planning_only_attestation_can_plan_but_cannot_execute(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence = _prepare_planner_clone(
        engine, database_url, archive_schema
    )
    plan = plan_historical_recipe_conversion(
        engine,
        inventory_payload=inventory,
        archive_schema=archive_schema,
        conversion_clone_id=evidence["conversion_clone_id"],
        clone_marker_identity=evidence["clone_marker_identity"],
        attestation_payload=evidence["attestation"],
    ).payload
    execution_authorization = _build_execution_attestation(
        engine, inventory, evidence, plan
    )
    planning_only = _redigest_attestation(
        execution_authorization,
        scope="planning",
    )
    repeated = plan_historical_recipe_conversion(
        engine,
        inventory_payload=inventory,
        archive_schema=archive_schema,
        conversion_clone_id=evidence["conversion_clone_id"],
        clone_marker_identity=evidence["clone_marker_identity"],
        attestation_payload=planning_only,
    ).payload
    assert repeated == plan
    _upgrade(database_url, EXECUTION_REVISION)

    with pytest.raises(Phase5CAdmissionError, match="scope") as failure:
        _execute_conversion(
            engine,
            archive_schema,
            inventory,
            evidence,
            plan,
            attestation_payload=planning_only,
        )
    assert planning_only["attestation_digest"] not in str(failure.value)
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT count(*) FROM phase5c_conversion_runs")
        ) == 0
        assert connection.scalar(
            text("SELECT count(*) FROM phase5c_conversion_outcomes")
        ) == 0
        assert connection.scalar(text("SELECT count(*) FROM recipes")) == 0


def test_bridge_only_attestation_cannot_execute(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence, plan = _prepare_execution_clone(
        engine, database_url, archive_schema
    )
    bridge_only = _prepare_isolation_evidence(
        engine,
        archive_schema,
        inventory,
        scope="bridge",
        establish_marker=False,
        operator_attestation_identity="phase5c-test-bridge-only",
        source_production_identity_digest=evidence["attestation"][
            "source_production_identity_digest"
        ],
    )["attestation"]

    with pytest.raises(Phase5CAdmissionError, match="scope"):
        _execute_conversion(
            engine,
            archive_schema,
            inventory,
            evidence,
            plan,
            attestation_payload=bridge_only,
        )
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT count(*) FROM phase5c_conversion_runs")
        ) == 0
        assert connection.scalar(text("SELECT count(*) FROM recipes")) == 0


def test_execution_only_attestation_executes_but_cannot_bridge_or_plan(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence = _prepare_planner_clone(
        engine, database_url, archive_schema
    )
    plan = plan_historical_recipe_conversion(
        engine,
        inventory_payload=inventory,
        archive_schema=archive_schema,
        conversion_clone_id=evidence["conversion_clone_id"],
        clone_marker_identity=evidence["clone_marker_identity"],
        attestation_payload=evidence["attestation"],
    ).payload
    execution_only = _build_execution_attestation(
        engine, inventory, evidence, plan
    )

    with pytest.raises(Phase5CAdmissionError, match="scope"):
        bridge_legacy_recipes(
            engine,
            inventory_payload=inventory,
            archive_schema=archive_schema,
            conversion_clone_id=evidence["conversion_clone_id"],
            clone_marker_identity=evidence["clone_marker_identity"],
            attestation_payload=execution_only,
        )
    with pytest.raises(Phase5CAdmissionError, match="scope"):
        plan_historical_recipe_conversion(
            engine,
            inventory_payload=inventory,
            archive_schema=archive_schema,
            conversion_clone_id=evidence["conversion_clone_id"],
            clone_marker_identity=evidence["clone_marker_identity"],
            attestation_payload=execution_only,
        )
    _upgrade(database_url, EXECUTION_REVISION)

    report = _execute_conversion(
        engine,
        archive_schema,
        inventory,
        evidence,
        plan,
        attestation_payload=execution_only,
    ).payload
    assert report["counts"]["converted"] == 1


def test_combined_planning_execution_attestation_permits_both_operations(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence = _prepare_planner_clone(
        engine, database_url, archive_schema
    )
    plan = plan_historical_recipe_conversion(
        engine,
        inventory_payload=inventory,
        archive_schema=archive_schema,
        conversion_clone_id=evidence["conversion_clone_id"],
        clone_marker_identity=evidence["clone_marker_identity"],
        attestation_payload=evidence["attestation"],
    ).payload
    combined = _build_execution_attestation(
        engine,
        inventory,
        evidence,
        plan,
        scope="planning_and_execution",
        operator_attestation_identity="phase5c-test-plan-execute",
    )
    repeated = plan_historical_recipe_conversion(
        engine,
        inventory_payload=inventory,
        archive_schema=archive_schema,
        conversion_clone_id=evidence["conversion_clone_id"],
        clone_marker_identity=evidence["clone_marker_identity"],
        attestation_payload=combined,
    ).payload
    assert repeated == plan
    _upgrade(database_url, EXECUTION_REVISION)

    report = _execute_conversion(
        engine,
        archive_schema,
        inventory,
        evidence,
        plan,
        attestation_payload=combined,
    ).payload
    assert report["counts"]["converted"] == 1


def test_execution_attestation_must_match_every_clone_and_plan_evidence_field(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence, plan = _prepare_execution_clone(
        engine, database_url, archive_schema
    )
    authorization = evidence["execution_attestation"]
    altered_authorizations = (
        _redigest_attestation(
            authorization, clone_marker_identity="phase5c-other-marker"
        ),
        _redigest_attestation(
            authorization, conversion_clone_identity_digest="0" * 64
        ),
        _redigest_attestation(authorization, inventory_digest="1" * 64),
        _redigest_attestation(
            authorization, schema_signature__name="unsupported_signature"
        ),
        _redigest_attestation(
            authorization, schema_signature__digest="2" * 64
        ),
        _redigest_attestation(
            authorization, conversion_rules_version="unsupported_rules"
        ),
        _redigest_attestation(
            authorization, source_production_identity_digest="3" * 64
        ),
        _redigest_attestation(
            authorization, clone_database_identity_digest="4" * 64
        ),
        _redigest_attestation(authorization, clone_marker_digest="5" * 64),
    )

    failure_messages: list[str] = []
    for altered in altered_authorizations:
        with pytest.raises(Phase5CAdmissionError) as failure:
            _execute_conversion(
                engine,
                archive_schema,
                inventory,
                evidence,
                plan,
                attestation_payload=altered,
            )
        failure_messages.append(str(failure.value))
    arbitrary_payload = deepcopy(authorization)
    arbitrary_payload["operator_secret"] = "private-attestation-payload"
    with pytest.raises(Phase5CAdmissionError) as failure:
        _execute_conversion(
            engine,
            archive_schema,
            inventory,
            evidence,
            plan,
            attestation_payload=arbitrary_payload,
        )
    failure_messages.append(str(failure.value))
    safe_failures = "\n".join(failure_messages)
    assert authorization["operator_attestation_identity"] not in safe_failures
    assert authorization["attestation_digest"] not in safe_failures
    assert "private-attestation-payload" not in safe_failures
    assert "postgresql" not in safe_failures
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT count(*) FROM phase5c_conversion_runs")
        ) == 0
        assert connection.scalar(
            text("SELECT count(*) FROM phase5c_conversion_outcomes")
        ) == 0
        assert connection.scalar(text("SELECT count(*) FROM recipes")) == 0


def test_execution_attestation_authorizes_only_its_exact_plan_and_archive_evidence(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence, plan = _prepare_execution_clone(
        engine, database_url, archive_schema
    )
    authorization = evidence["execution_attestation"]
    invalid_digest = deepcopy(plan)
    invalid_digest["decisions"][0]["reason_code"] = "changed_decision_reason"
    with pytest.raises(Phase5CAdmissionError, match="digest verification"):
        _execute_conversion(
            engine,
            archive_schema,
            inventory,
            evidence,
            invalid_digest,
            attestation_payload=authorization,
        )

    other_plan = _redigest_plan(
        plan,
        decisions__0__reason_code="changed_decision_reason",
    )
    other_archive = _redigest_plan(
        plan,
        source_identity__archive_identity="6" * 64,
    )
    other_checksum = _redigest_plan(
        plan,
        source_checksums__archive="7" * 64,
    )
    for unauthorized_plan in (other_plan, other_archive, other_checksum):
        with pytest.raises(
            Phase5CAdmissionError,
            match="does not authorize this conversion plan",
        ):
            _execute_conversion(
                engine,
                archive_schema,
                inventory,
                evidence,
                unauthorized_plan,
                attestation_payload=authorization,
            )
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT count(*) FROM phase5c_conversion_runs")
        ) == 0
        assert connection.scalar(
            text("SELECT count(*) FROM phase5c_conversion_outcomes")
        ) == 0
        assert connection.scalar(text("SELECT count(*) FROM recipes")) == 0


def test_execution_attestation_creation_rejects_invalid_or_foreign_plan_evidence(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence = _prepare_planner_clone(
        engine, database_url, archive_schema
    )
    plan = plan_historical_recipe_conversion(
        engine,
        inventory_payload=inventory,
        archive_schema=archive_schema,
        conversion_clone_id=evidence["conversion_clone_id"],
        clone_marker_identity=evidence["clone_marker_identity"],
        attestation_payload=evidence["attestation"],
    ).payload
    invalid = deepcopy(plan)
    invalid["manifest_version"] = "unsupported_plan_version"
    foreign_marker = _redigest_plan(
        plan,
        isolation_evidence__clone_marker_digest="8" * 64,
    )
    with engine.connect() as connection:
        common = {
            "connection": connection,
            "operator_attestation_identity": "phase5c-test-plan-approval",
            "scope": "execution",
            "clone_marker_identity": evidence["clone_marker_identity"],
            "conversion_clone_id": evidence["conversion_clone_id"],
            "source_production_identity_digest": evidence["attestation"][
                "source_production_identity_digest"
            ],
            "inventory_digest": canonical_digest(inventory),
            "schema_signature": SUPPORTED_SCHEMA_SIGNATURE,
            "schema_signature_digest": SCHEMA_SIGNATURE_DIGEST,
        }
        with pytest.raises(Phase5CAdmissionError, match="Unsupported conversion plan"):
            build_operator_attestation(
                **common,
                conversion_plan_payload=invalid,
            )
        with pytest.raises(Phase5CAdmissionError, match="clone marker evidence"):
            build_operator_attestation(
                **common,
                conversion_plan_payload=foreign_marker,
            )
        with pytest.raises(Phase5CAdmissionError, match="does not match execution"):
            build_operator_attestation(
                **{
                    **common,
                    "inventory_digest": "9" * 64,
                },
                conversion_plan_payload=plan,
            )
        with pytest.raises(Phase5CAdmissionError, match="marker identity differs"):
            build_operator_attestation(
                **{
                    **common,
                    "clone_marker_identity": "phase5c-other-plan-marker",
                },
                conversion_plan_payload=plan,
            )
        with pytest.raises(Phase5CAdmissionError, match="source identity differs"):
            build_operator_attestation(
                **{
                    **common,
                    "source_production_identity_digest": "a" * 64,
                },
                conversion_plan_payload=plan,
            )

    authorization = _build_execution_attestation(
        engine, inventory, evidence, plan
    )
    rendered = canonical_json(authorization)
    assert set(authorization["conversion_plan_evidence"]) == {
        "contract_version",
        "digest",
        "archive_identity",
        "source_checksums",
    }
    for authored_value in (
        "Historical Recipe Projection",
        "Historical Ingredient",
        "prepared",
        "postgresql",
    ):
        assert authored_value not in rendered


def test_execution_authorization_is_rechecked_after_operation_lock(
    conversion_clone: tuple[Engine, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence, plan = _prepare_execution_clone(
        engine, database_url, archive_schema
    )
    original = converter_module.verify_clone_isolation_evidence
    calls = 0

    def reject_second_execution_check(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            kwargs["conversion_plan_payload"] = _redigest_plan(
                plan,
                decisions__0__reason_code="post_lock_changed_decision",
            )
        return original(*args, **kwargs)

    monkeypatch.setattr(
        converter_module,
        "verify_clone_isolation_evidence",
        reject_second_execution_check,
    )

    with pytest.raises(
        Phase5CAdmissionError,
        match="does not authorize this conversion plan",
    ):
        _execute_conversion(engine, archive_schema, inventory, evidence, plan)
    assert calls == 2
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT count(*) FROM phase5c_conversion_runs")
        ) == 0
        assert connection.scalar(text("SELECT count(*) FROM recipes")) == 0


def test_restart_requires_exact_same_execution_authorization(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence, plan = _prepare_execution_clone(
        engine, database_url, archive_schema
    )
    _execute_conversion(engine, archive_schema, inventory, evidence, plan)
    replacement = _build_execution_attestation(
        engine,
        inventory,
        evidence,
        plan,
        operator_attestation_identity="phase5c-test-replacement-executor",
    )
    other_plan = _redigest_plan(
        plan,
        decisions__0__reason_code="replacement_plan_decision",
    )
    other_plan_authorization = deepcopy(evidence["execution_attestation"])
    other_plan_authorization["conversion_plan_evidence"] = (
        _plan_authorization_evidence(other_plan)
    )
    other_plan_authorization = _redigest_attestation(other_plan_authorization)

    with pytest.raises(
        Phase5CAdmissionError,
        match="does not authorize this conversion plan",
    ):
        _execute_conversion(
            engine,
            archive_schema,
            inventory,
            evidence,
            plan,
            attestation_payload=other_plan_authorization,
        )

    with pytest.raises(
        Phase5CAdmissionError,
        match="execution authorization evidence differs",
    ):
        _execute_conversion(
            engine,
            archive_schema,
            inventory,
            evidence,
            plan,
            attestation_payload=replacement,
        )
    with engine.connect() as connection:
        run = connection.execute(
            text(
                "SELECT execution_attestation_version, "
                "execution_isolation_contract_version, "
                "execution_attestation_identity, execution_attestation_scope, "
                "execution_attestation_digest FROM phase5c_conversion_runs"
            )
        ).mappings().one()
    assert run["execution_attestation_identity"] == evidence[
        "execution_attestation"
    ]["operator_attestation_identity"]
    assert run["execution_attestation_scope"] == "execution"
    assert run["execution_attestation_digest"] == evidence[
        "execution_attestation"
    ]["attestation_digest"]


def test_converter_marks_exact_authored_projection_equivalence_current(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    _upgrade(database_url, "0003_usda_source_identity")
    ids = _seed_recipe(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE recipes SET serving_count = 1, final_yield_quantity = NULL, "
                "final_yield_unit = NULL WHERE id = :recipe_id"
            ),
            {"recipe_id": ids["recipe"]},
        )
        connection.execute(
            text(
                "UPDATE serving_definitions SET gram_weight = NULL "
                "WHERE id = :serving_id"
            ),
            {"serving_id": ids["projection_serving"]},
        )
    inventory = _inventory(engine)
    evidence = _prepare_isolation_evidence(engine, archive_schema, inventory)
    _bridge(engine, archive_schema, inventory, evidence)
    _upgrade(database_url, CONTROL_REVISION)
    plan = plan_historical_recipe_conversion(
        engine,
        inventory_payload=inventory,
        archive_schema=archive_schema,
        conversion_clone_id=evidence["conversion_clone_id"],
        clone_marker_identity=evidence["clone_marker_identity"],
        attestation_payload=evidence["attestation"],
    ).payload
    _upgrade(database_url, EXECUTION_REVISION)

    report = _execute_conversion(
        engine, archive_schema, inventory, evidence, plan
    ).payload

    assert report["counts"]["converted"] == 1
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT needs_republish FROM recipes")) is False


def test_converter_persists_quarantine_and_block_without_domain_mutation(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence, plan = _prepare_execution_clone(
        engine,
        database_url,
        archive_schema,
        classified_fixture=True,
    )

    report = _execute_conversion(
        engine, archive_schema, inventory, evidence, plan
    ).payload

    assert report["counts"] == {
        "converted": 1,
        "quarantined": 1,
        "blocked": 1,
        "failed": 0,
        "pending": 0,
    }
    by_source = {row["source_recipe_id"]: row for row in report["subjects"]}
    assert by_source["00000000-0000-0000-0000-000000000002"] == {
        "source_recipe_id": "00000000-0000-0000-0000-000000000002",
        "disposition": "quarantined",
        "reason_code": "instructions_not_losslessly_representable",
    }
    assert by_source["00000000-0000-0000-0000-000000000003"] == {
        "source_recipe_id": "00000000-0000-0000-0000-000000000003",
        "disposition": "blocked",
        "reason_code": "ingredient_owner_mismatch",
    }
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM recipes")) == 1
        assert connection.scalar(
            text("SELECT count(*) FROM recipe_publication_revisions")
        ) == 1
        assert connection.scalar(
            text(
                "SELECT count(*) FROM phase5c_conversion_outcomes "
                "WHERE execution_disposition IN ('quarantined', 'blocked') "
                "AND target_recipe_id IS NULL AND created_revision_id IS NULL"
            )
        ) == 2


def test_converter_converts_multiple_independent_recipes(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence, plan = _prepare_execution_clone(
        engine,
        database_url,
        archive_schema,
        convert_count=2,
    )

    report = _execute_conversion(
        engine, archive_schema, inventory, evidence, plan
    ).payload

    assert report["counts"]["converted"] == 2
    assert report["verification_result"] == "verified"
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM recipes")) == 2
        assert connection.scalar(
            text("SELECT count(*) FROM recipe_publication_revisions")
        ) == 2
        assert connection.scalar(
            text(
                "SELECT count(*) FROM recipes recipe "
                "JOIN recipe_publication_revisions revision "
                "ON revision.id = recipe.active_publication_revision_id "
                "WHERE revision.recipe_id = recipe.id AND revision.revision_number = 1"
            )
        ) == 2


def test_converter_processes_nested_recipes_in_dependency_order(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    _upgrade(database_url, "0003_usda_source_identity")
    child = _seed_recipe(engine)
    parent = _seed_recipe(
        engine,
        user_id=child["user"],
        ingredient_food_item_id=child["projection"],
        ingredient_serving_id=child["projection_serving"],
    )
    inventory = _inventory(engine)
    evidence = _prepare_isolation_evidence(engine, archive_schema, inventory)
    _bridge(engine, archive_schema, inventory, evidence)
    _upgrade(database_url, CONTROL_REVISION)
    plan = plan_historical_recipe_conversion(
        engine,
        inventory_payload=inventory,
        archive_schema=archive_schema,
        conversion_clone_id=evidence["conversion_clone_id"],
        clone_marker_identity=evidence["clone_marker_identity"],
        attestation_payload=evidence["attestation"],
    ).payload
    assert plan["summary"]["convert"] == 2
    _upgrade(database_url, EXECUTION_REVISION)
    execution_order: list[UUID] = []

    def record_order(stage: str, recipe_id: UUID) -> None:
        if stage == "before_domain_writes":
            execution_order.append(recipe_id)

    report = _execute_conversion(
        engine,
        archive_schema,
        inventory,
        evidence,
        plan,
        failure_hook=record_order,
    ).payload

    assert report["counts"]["converted"] == 2
    assert execution_order == [child["recipe"], parent["recipe"]]
    with engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT count(*) FROM recipes parent "
                "JOIN recipe_ingredients ingredient ON ingredient.recipe_id = parent.id "
                "JOIN recipes child ON child.published_food_item_id = ingredient.food_item_id "
                "WHERE parent.id = :parent_id AND child.id = :child_id"
            ),
            {"parent_id": parent["recipe"], "child_id": child["recipe"]},
        ) == 1


def test_converter_does_not_convert_parent_after_child_execution_failure(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    _upgrade(database_url, "0003_usda_source_identity")
    child = _seed_recipe(engine)
    parent = _seed_recipe(
        engine,
        user_id=child["user"],
        ingredient_food_item_id=child["projection"],
        ingredient_serving_id=child["projection_serving"],
    )
    inventory = _inventory(engine)
    evidence = _prepare_isolation_evidence(engine, archive_schema, inventory)
    _bridge(engine, archive_schema, inventory, evidence)
    _upgrade(database_url, CONTROL_REVISION)
    plan = plan_historical_recipe_conversion(
        engine,
        inventory_payload=inventory,
        archive_schema=archive_schema,
        conversion_clone_id=evidence["conversion_clone_id"],
        clone_marker_identity=evidence["clone_marker_identity"],
        attestation_payload=evidence["attestation"],
    ).payload
    _upgrade(database_url, EXECUTION_REVISION)

    def fail_child(stage: str, recipe_id: UUID) -> None:
        if stage == "after_recipe_insert" and recipe_id == child["recipe"]:
            raise RuntimeError("injected child failure")

    report = _execute_conversion(
        engine,
        archive_schema,
        inventory,
        evidence,
        plan,
        failure_hook=fail_child,
    ).payload

    reasons = {
        row["source_recipe_id"]: row["reason_code"] for row in report["subjects"]
    }
    assert reasons[str(child["recipe"])] == "subject_execution_failure"
    assert reasons[str(parent["recipe"])] == "dependency_execution_incomplete"
    assert report["counts"]["failed"] == 2
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM recipes")) == 0
        assert connection.scalar(
            text("SELECT count(*) FROM recipe_publication_revisions")
        ) == 0


def test_source_graph_cycle_is_planned_and_persisted_as_blocked(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    _upgrade(database_url, "0003_usda_source_identity")
    first = _seed_recipe(engine)
    second = _seed_recipe(
        engine,
        user_id=first["user"],
        ingredient_food_item_id=first["projection"],
        ingredient_serving_id=first["projection_serving"],
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE recipe_ingredients SET ingredient_food_item_id = :food_id, "
                "serving_definition_id = :serving_id, quantity = 2, unit = 'serving', "
                "gram_amount = 500 WHERE recipe_id = :recipe_id"
            ),
            {
                "food_id": second["projection"],
                "serving_id": second["projection_serving"],
                "recipe_id": first["recipe"],
            },
        )
    inventory = _inventory(engine)
    evidence = _prepare_isolation_evidence(engine, archive_schema, inventory)
    _bridge(engine, archive_schema, inventory, evidence)
    _upgrade(database_url, CONTROL_REVISION)
    plan = plan_historical_recipe_conversion(
        engine,
        inventory_payload=inventory,
        archive_schema=archive_schema,
        conversion_clone_id=evidence["conversion_clone_id"],
        clone_marker_identity=evidence["clone_marker_identity"],
        attestation_payload=evidence["attestation"],
    ).payload
    assert plan["summary"] == {
        "total": 2,
        "convert": 0,
        "quarantine": 0,
        "block": 2,
    }
    assert {row["reason_code"] for row in plan["decisions"]} == {
        "nested_recipe_cycle"
    }
    _upgrade(database_url, EXECUTION_REVISION)

    report = _execute_conversion(
        engine, archive_schema, inventory, evidence, plan
    ).payload

    assert report["counts"]["blocked"] == 2
    assert report["counts"]["converted"] == 0
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM recipes")) == 0
        assert connection.scalar(
            text("SELECT count(*) FROM recipe_publication_revisions")
        ) == 0


def test_converter_leaves_nonempty_daily_log_and_ocr_history_unchanged(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    _upgrade(database_url, "0003_usda_source_identity")
    ids = _seed_recipe(engine)
    _seed_historical_log_and_ocr(engine, ids)
    inventory = _inventory(engine)
    evidence = _prepare_isolation_evidence(engine, archive_schema, inventory)
    _bridge(engine, archive_schema, inventory, evidence)
    _upgrade(database_url, CONTROL_REVISION)
    plan = plan_historical_recipe_conversion(
        engine,
        inventory_payload=inventory,
        archive_schema=archive_schema,
        conversion_clone_id=evidence["conversion_clone_id"],
        clone_marker_identity=evidence["clone_marker_identity"],
        attestation_payload=evidence["attestation"],
    ).payload
    _upgrade(database_url, EXECUTION_REVISION)
    protected_tables = {
        "daily_logs",
        "daily_log_nutrient_snapshots",
        "ocr_scans",
        "parse_results",
        "parser_corrections",
    }
    before = {
        table: digest
        for table, digest in _domain_fingerprints(engine, archive_schema).items()
        if table in protected_tables
    }

    report = _execute_conversion(
        engine, archive_schema, inventory, evidence, plan
    )
    after = {
        table: digest
        for table, digest in _domain_fingerprints(engine, archive_schema).items()
        if table in protected_tables
    }

    assert after == before
    rendered = report.to_json() + report.to_human()
    for private_value in (
        "historical log note",
        "historical OCR text",
        "ocr payload",
        "legacy-parser",
    ):
        assert private_value not in rendered


@pytest.mark.parametrize(
    "stage",
    (
        "before_domain_writes",
        "after_recipe_insert",
        "after_ingredient_insert",
        "after_revision_children",
        "after_projection_link",
    ),
)
def test_converter_subject_failure_rolls_back_every_domain_stage(
    conversion_clone: tuple[Engine, str, str],
    stage: str,
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence, plan = _prepare_execution_clone(
        engine, database_url, archive_schema
    )

    def fail_at_stage(current_stage: str, _recipe_id: UUID) -> None:
        if current_stage == stage:
            raise RuntimeError("injected authored secret must remain private")

    report = _execute_conversion(
        engine,
        archive_schema,
        inventory,
        evidence,
        plan,
        failure_hook=fail_at_stage,
    ).payload

    assert report["counts"]["failed"] == 1
    assert report["subjects"][0]["reason_code"] == "subject_execution_failure"
    rendered = canonical_json(report)
    assert "injected authored secret" not in rendered
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM recipes")) == 0
        assert connection.scalar(text("SELECT count(*) FROM recipe_ingredients")) == 0
        assert connection.scalar(
            text("SELECT count(*) FROM recipe_publication_revisions")
        ) == 0
        assert connection.scalar(
            text(
                "SELECT count(*) FROM food_items "
                "WHERE recipe_publication_revision_id IS NOT NULL"
            )
        ) == 0
        assert connection.scalar(
            text(f'SELECT count(*) FROM "{archive_schema}".recipes')
        ) == 1


def test_converter_rejects_source_mutation_before_creating_run(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence, plan = _prepare_execution_clone(
        engine, database_url, archive_schema
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                f'UPDATE "{archive_schema}".recipe_ingredients '
                "SET quantity = quantity + 1"
            )
        )

    with pytest.raises(Phase5CAdmissionError, match="source checksums changed"):
        _execute_conversion(engine, archive_schema, inventory, evidence, plan)
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT count(*) FROM phase5c_conversion_runs")
        ) == 0
        assert connection.scalar(text("SELECT count(*) FROM recipes")) == 0


def test_converter_rejects_supporting_nutrition_mutation_before_creating_run(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence, plan = _prepare_execution_clone(
        engine, database_url, archive_schema
    )
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE food_nutrients SET amount = amount + 1 WHERE source = 'manual'")
        )

    with pytest.raises(Phase5CAdmissionError, match="source checksums changed"):
        _execute_conversion(engine, archive_schema, inventory, evidence, plan)
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT count(*) FROM phase5c_conversion_runs")
        ) == 0


def test_converter_rejects_preexisting_current_recipe_collision(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence, plan = _prepare_execution_clone(
        engine, database_url, archive_schema
    )
    with engine.begin() as connection:
        owner_id = connection.scalar(text("SELECT user_id FROM food_items LIMIT 1"))
        connection.execute(
            text(
                "INSERT INTO recipes (id, user_id, name, needs_republish) "
                "VALUES (:id, :owner_id, 'unexpected current Recipe', false)"
            ),
            {"id": uuid4(), "owner_id": owner_id},
        )

    with pytest.raises(Phase5CAdmissionError, match="before the first conversion run"):
        _execute_conversion(engine, archive_schema, inventory, evidence, plan)
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT count(*) FROM phase5c_conversion_runs")
        ) == 0


def test_converter_rejects_unknown_plan_fields_and_a_different_plan_digest(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence, plan = _prepare_execution_clone(
        engine, database_url, archive_schema
    )
    unknown = deepcopy(plan)
    unknown["unsupported_execution_hint"] = True
    with pytest.raises(Phase5CAdmissionError, match="unsupported v2 shape"):
        _execute_conversion(engine, archive_schema, inventory, evidence, unknown)

    changed = deepcopy(plan)
    changed["decisions"][0]["source_checksum"] = "0" * 64
    unsigned = {key: value for key, value in changed.items() if key != "manifest_digest"}
    changed["manifest_digest"] = canonical_digest(unsigned)
    with pytest.raises(
        Phase5CAdmissionError,
        match="does not authorize this conversion plan",
    ):
        _execute_conversion(engine, archive_schema, inventory, evidence, changed)
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT count(*) FROM phase5c_conversion_runs")
        ) == 0


def test_converter_restart_rejects_tampered_completed_domain_state(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence, plan = _prepare_execution_clone(
        engine, database_url, archive_schema
    )
    _execute_conversion(engine, archive_schema, inventory, evidence, plan)
    with engine.begin() as connection:
        connection.execute(text("UPDATE recipes SET name = 'tampered current state'"))

    with pytest.raises(
        Phase5CAdmissionError,
        match="Completed conversion checkpoint verification failed",
    ):
        _execute_conversion(engine, archive_schema, inventory, evidence, plan)


def test_post_commit_verification_failure_preserves_immutable_domain_and_marks_run(
    conversion_clone: tuple[Engine, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence, plan = _prepare_execution_clone(
        engine, database_url, archive_schema
    )

    def fail_verification(*args, **kwargs):
        raise converter_module.Phase5CSubjectError("private_verification_detail")

    monkeypatch.setattr(
        converter_module,
        "_verify_converted_outcome",
        fail_verification,
    )
    report = _execute_conversion(
        engine, archive_schema, inventory, evidence, plan
    ).payload

    assert report["counts"]["failed"] == 1
    assert report["subjects"][0]["reason_code"] == (
        "post_commit_verification_failed"
    )
    assert "private_verification_detail" not in canonical_json(report)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM recipes")) == 1
        assert connection.scalar(
            text("SELECT count(*) FROM recipe_publication_revisions")
        ) == 1
        assert connection.scalar(
            text(
                "SELECT count(*) FROM phase5c_conversion_outcomes "
                "WHERE checkpoint_state = 'failed' "
                "AND execution_disposition = 'converted' "
                "AND created_revision_id IS NOT NULL"
            )
        ) == 1


def test_converter_rejects_nonmaintenance_database_session(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence, plan = _prepare_execution_clone(
        engine, database_url, archive_schema
    )
    blocker_engine = create_engine(database_url, pool_pre_ping=True)
    blocker = blocker_engine.connect()
    blocker.execute(text("SELECT 1"))
    blocker.commit()
    try:
        with pytest.raises(Phase5CAdmissionError, match="nonmaintenance_sessions"):
            _execute_conversion(engine, archive_schema, inventory, evidence, plan)
    finally:
        blocker.close()
        blocker_engine.dispose()
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT count(*) FROM phase5c_conversion_runs")
        ) == 0


def test_concurrent_converters_serialize_and_return_one_verified_receipt(
    conversion_clone: tuple[Engine, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence, plan = _prepare_execution_clone(
        engine, database_url, archive_schema
    )
    barrier = threading.Barrier(2)
    local = threading.local()
    original = converter_module.assert_database_session_isolation

    def synchronize_first_check(connection, marker_digest):
        if not getattr(local, "entered", False):
            local.entered = True
            barrier.wait(timeout=10)
        original(connection, marker_digest)

    monkeypatch.setattr(
        converter_module,
        "assert_database_session_isolation",
        synchronize_first_check,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                _execute_conversion,
                engine,
                archive_schema,
                inventory,
                evidence,
                plan,
            )
            for _ in range(2)
        ]
        reports = [future.result(timeout=30) for future in futures]

    assert reports[0].to_json() == reports[1].to_json()
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT count(*) FROM phase5c_conversion_runs")
        ) == 1
        assert connection.scalar(text("SELECT count(*) FROM recipes")) == 1
        assert connection.scalar(
            text("SELECT count(*) FROM recipe_publication_revisions")
        ) == 1


def test_converter_retries_only_bounded_retryable_database_failures(
    conversion_clone: tuple[Engine, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence, plan = _prepare_execution_clone(
        engine, database_url, archive_schema
    )
    original = converter_module._convert_subject
    attempts = 0

    class RetryableDatabaseError(RuntimeError):
        sqlstate = "40001"

    def flaky_convert(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise DBAPIError(None, None, RetryableDatabaseError())
        return original(*args, **kwargs)

    monkeypatch.setattr(converter_module, "_convert_subject", flaky_convert)

    report = _execute_conversion(
        engine, archive_schema, inventory, evidence, plan
    ).payload

    assert attempts == 3
    assert report["counts"]["converted"] == 1


@pytest.mark.parametrize(
    ("sqlstate", "expected_attempts", "reason_code"),
    (
        ("40001", 3, "subject_retry_exhausted"),
        ("23505", 1, "subject_database_failure"),
    ),
)
def test_converter_bounds_retry_exhaustion_and_does_not_retry_other_failures(
    conversion_clone: tuple[Engine, str, str],
    monkeypatch: pytest.MonkeyPatch,
    sqlstate: str,
    expected_attempts: int,
    reason_code: str,
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence, plan = _prepare_execution_clone(
        engine, database_url, archive_schema
    )
    attempts = 0

    class DatabaseError(RuntimeError):
        pass

    def always_fail(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        original = DatabaseError()
        original.sqlstate = sqlstate
        raise DBAPIError(None, None, original)

    monkeypatch.setattr(converter_module, "_convert_subject", always_fail)
    report = _execute_conversion(
        engine, archive_schema, inventory, evidence, plan
    ).payload

    assert attempts == expected_attempts
    assert report["subjects"][0]["reason_code"] == reason_code
    assert report["counts"]["failed"] == 1


def test_independent_qualification_is_deterministic_private_and_read_only(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence, plan = _prepare_execution_clone(
        engine, database_url, archive_schema
    )
    execution_receipt = _execute_conversion(
        engine, archive_schema, inventory, evidence, plan
    ).payload
    with engine.connect() as connection:
        before = canonical_digest(
            {
                "run": [
                    dict(row)
                    for row in connection.execute(
                        text("SELECT * FROM phase5c_conversion_runs")
                    ).mappings()
                ],
                "outcomes": [
                    dict(row)
                    for row in connection.execute(
                        text(
                            "SELECT * FROM phase5c_conversion_outcomes "
                            "ORDER BY source_recipe_id"
                        )
                    ).mappings()
                ],
                "recipes": [
                    dict(row)
                    for row in connection.execute(
                        text("SELECT * FROM recipes ORDER BY id")
                    ).mappings()
                ],
            }
        )

    first = _qualify_conversion(
        engine, archive_schema, inventory, evidence, plan, execution_receipt
    )
    second = _qualify_conversion(
        engine, archive_schema, inventory, evidence, plan, execution_receipt
    )

    assert first.payload == second.payload
    assert first.payload["verification_result"] == "qualified"
    assert first.payload["observed_counts"]["converted"] == 1
    rendered = first.to_json() + first.to_human()
    for private_value in (
        "Historical Recipe Projection",
        "Historical Ingredient",
        "prepared",
        "postgresql",
    ):
        assert private_value not in rendered
    with engine.connect() as connection:
        after = canonical_digest(
            {
                "run": [
                    dict(row)
                    for row in connection.execute(
                        text("SELECT * FROM phase5c_conversion_runs")
                    ).mappings()
                ],
                "outcomes": [
                    dict(row)
                    for row in connection.execute(
                        text(
                            "SELECT * FROM phase5c_conversion_outcomes "
                            "ORDER BY source_recipe_id"
                        )
                    ).mappings()
                ],
                "recipes": [
                    dict(row)
                    for row in connection.execute(
                        text("SELECT * FROM recipes ORDER BY id")
                    ).mappings()
                ],
            }
        )
    assert before == after


@pytest.fixture()
def completed_qualification_clone(
    conversion_clone: tuple[Engine, str, str],
) -> tuple[Engine, str, str, dict, dict, dict, dict]:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence, plan = _prepare_execution_clone(
        engine, database_url, archive_schema
    )
    execution_receipt = _execute_conversion(
        engine, archive_schema, inventory, evidence, plan
    ).payload
    return (
        engine,
        database_url,
        archive_schema,
        inventory,
        evidence,
        plan,
        execution_receipt,
    )


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    (
        (
            "UPDATE {archive}.recipes SET instructions = 'changed archive'",
            "qualification_archive_checksum_changed",
        ),
        (
            "UPDATE {archive}.recipe_ingredients "
            "SET preparation_note = 'changed archive ingredient'",
            "qualification_archive_checksum_changed",
        ),
        (
            "UPDATE food_items SET name = 'changed supporting Food' "
            "WHERE id = (SELECT published_food_item_id FROM recipes LIMIT 1)",
            "qualification_archive_checksum_changed",
        ),
        (
            "UPDATE serving_definitions SET label = 'changed serving' "
            "WHERE food_item_id = (SELECT published_food_item_id FROM recipes LIMIT 1)",
            "qualification_archive_checksum_changed",
        ),
        (
            "UPDATE food_nutrients SET amount = amount + 1 "
            "WHERE food_item_id = (SELECT published_food_item_id FROM recipes LIMIT 1)",
            "qualification_archive_checksum_changed",
        ),
        (
            "INSERT INTO food_sources (id, food_item_id, source_type) "
            "SELECT gen_random_uuid(), published_food_item_id, 'changed-source' "
            "FROM recipes LIMIT 1",
            "qualification_archive_checksum_changed",
        ),
        (
            "UPDATE recipes SET serving_count_yield = serving_count_yield + 1",
            "qualification_converted_mapping_invalid",
        ),
        (
            "UPDATE recipe_ingredients SET preparation_note = 'changed authored row'",
            "qualification_converted_mapping_invalid",
        ),
        (
            "UPDATE food_items SET recipe_publication_revision_id = NULL "
            "WHERE id = (SELECT published_food_item_id FROM recipes LIMIT 1)",
            "qualification_projection_snapshot_invalid",
        ),
        (
            "UPDATE recipe_publication_revisions SET content_digest = repeat('0', 64)",
            "qualification_revision_digest_invalid",
        ),
        (
            "DELETE FROM recipe_publication_amount_definitions",
            "qualification_revision_digest_invalid",
        ),
        (
            "UPDATE recipes SET active_publication_revision_id = NULL",
            "qualification_projection_snapshot_invalid",
        ),
        (
            "UPDATE recipes SET needs_republish = NOT needs_republish",
            "qualification_staleness_invalid",
        ),
    ),
)
def test_independent_qualification_detects_archive_and_domain_corruption(
    completed_qualification_clone: tuple[Engine, str, str, dict, dict, dict, dict],
    mutation: str,
    reason_code: str,
) -> None:
    (
        engine,
        _database_url,
        archive_schema,
        inventory,
        evidence,
        plan,
        execution_receipt,
    ) = completed_qualification_clone
    quoted_archive = engine.dialect.identifier_preparer.quote(archive_schema)
    with engine.begin() as connection:
        connection.execute(text(mutation.format(archive=quoted_archive)))

    with pytest.raises(Phase5CQualificationError, match=reason_code):
        _qualify_conversion(
            engine,
            archive_schema,
            inventory,
            evidence,
            plan,
            execution_receipt,
        )


@pytest.mark.parametrize("missing", (True, False))
def test_independent_qualification_rejects_missing_or_extra_outcomes(
    completed_qualification_clone: tuple[Engine, str, str, dict, dict, dict, dict],
    missing: bool,
) -> None:
    (
        engine,
        _database_url,
        archive_schema,
        inventory,
        evidence,
        plan,
        execution_receipt,
    ) = completed_qualification_clone
    with engine.begin() as connection:
        run_id = connection.scalar(text("SELECT id FROM phase5c_conversion_runs"))
        if missing:
            connection.execute(text("DELETE FROM phase5c_conversion_outcomes"))
        else:
            connection.execute(
                text(
                    "INSERT INTO phase5c_conversion_outcomes "
                    "(run_id, source_recipe_id, planned_disposition, "
                    "planned_reason_code, source_checksum, execution_disposition, "
                    "checkpoint_state, verification_state) VALUES "
                    "(:run_id, :source_id, 'block', 'unexpected_subject', :checksum, "
                    "'blocked', 'completed', 'verified')"
                ),
                {
                    "run_id": run_id,
                    "source_id": uuid4(),
                    "checksum": "a" * 64,
                },
            )

    with pytest.raises(
        Phase5CQualificationError,
        match="qualification_outcome_cardinality_invalid",
    ):
        _qualify_conversion(
            engine,
            archive_schema,
            inventory,
            evidence,
            plan,
            execution_receipt,
        )


@pytest.mark.parametrize("state", ("pending", "failed"))
def test_independent_qualification_rejects_incomplete_runs(
    completed_qualification_clone: tuple[Engine, str, str, dict, dict, dict, dict],
    state: str,
) -> None:
    (
        engine,
        _database_url,
        archive_schema,
        inventory,
        evidence,
        plan,
        execution_receipt,
    ) = completed_qualification_clone
    with engine.begin() as connection:
        if state == "pending":
            connection.execute(
                text(
                    "UPDATE phase5c_conversion_runs SET execution_state = 'running', "
                    "verification_state = 'pending'"
                )
            )
        else:
            connection.execute(
                text(
                    "UPDATE phase5c_conversion_runs SET execution_state = 'failed', "
                    "verification_state = 'failed', "
                    "failure_reason_code = 'subject_failure'"
                )
            )

    with pytest.raises(
        Phase5CQualificationError, match="qualification_run_incomplete"
    ):
        _qualify_conversion(
            engine,
            archive_schema,
            inventory,
            evidence,
            plan,
            execution_receipt,
        )


def test_independent_qualification_reconciles_execution_receipt_subjects(
    completed_qualification_clone: tuple[Engine, str, str, dict, dict, dict, dict],
) -> None:
    (
        engine,
        _database_url,
        archive_schema,
        inventory,
        evidence,
        plan,
        execution_receipt,
    ) = completed_qualification_clone
    changed = deepcopy(execution_receipt)
    changed["subjects"][0]["reason_code"] = "changed_receipt_reason"
    unsigned = {key: value for key, value in changed.items() if key != "report_digest"}
    changed["report_digest"] = canonical_digest(unsigned)

    with pytest.raises(
        Phase5CQualificationError,
        match="qualification_execution_receipt_mismatch",
    ):
        _qualify_conversion(
            engine,
            archive_schema,
            inventory,
            evidence,
            plan,
            execution_receipt,
            execution_receipt_payload=changed,
        )


def test_independent_qualification_rechecks_evidence_after_operation_lock(
    completed_qualification_clone: tuple[Engine, str, str, dict, dict, dict, dict],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        engine,
        _database_url,
        archive_schema,
        inventory,
        evidence,
        plan,
        execution_receipt,
    ) = completed_qualification_clone
    original = qualification_module._verify_isolation
    calls = 0

    def reject_second_check(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise Phase5CQualificationError("qualification_evidence_mismatch")
        return original(*args, **kwargs)

    monkeypatch.setattr(
        qualification_module, "_verify_isolation", reject_second_check
    )
    with pytest.raises(
        Phase5CQualificationError, match="qualification_evidence_mismatch"
    ):
        _qualify_conversion(
            engine,
            archive_schema,
            inventory,
            evidence,
            plan,
            execution_receipt,
        )
    assert calls == 2


def test_independent_qualification_refuses_nonmaintenance_session(
    completed_qualification_clone: tuple[Engine, str, str, dict, dict, dict, dict],
) -> None:
    (
        engine,
        _database_url,
        archive_schema,
        inventory,
        evidence,
        plan,
        execution_receipt,
    ) = completed_qualification_clone
    with engine.connect() as unrelated:
        unrelated.execute(text("SELECT 1"))
        with pytest.raises(
            Phase5CQualificationError, match="qualification_evidence_mismatch"
        ):
            _qualify_conversion(
                engine,
                archive_schema,
                inventory,
                evidence,
                plan,
                execution_receipt,
            )


def test_independent_qualification_accepts_multiple_converted_recipes(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence, plan = _prepare_execution_clone(
        engine, database_url, archive_schema, convert_count=2
    )
    execution_receipt = _execute_conversion(
        engine, archive_schema, inventory, evidence, plan
    ).payload

    receipt = _qualify_conversion(
        engine, archive_schema, inventory, evidence, plan, execution_receipt
    ).payload

    assert receipt["observed_counts"]["converted"] == 2
    assert receipt["verification_result"] == "qualified"


def test_independent_qualification_accepts_nested_converted_recipes(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    _upgrade(database_url, "0003_usda_source_identity")
    child = _seed_recipe(engine)
    _seed_recipe(
        engine,
        user_id=child["user"],
        ingredient_food_item_id=child["projection"],
        ingredient_serving_id=child["projection_serving"],
    )
    inventory = _inventory(engine)
    evidence = _prepare_isolation_evidence(engine, archive_schema, inventory)
    _bridge(engine, archive_schema, inventory, evidence)
    _upgrade(database_url, CONTROL_REVISION)
    plan = plan_historical_recipe_conversion(
        engine,
        inventory_payload=inventory,
        archive_schema=archive_schema,
        conversion_clone_id=evidence["conversion_clone_id"],
        clone_marker_identity=evidence["clone_marker_identity"],
        attestation_payload=evidence["attestation"],
    ).payload
    evidence["execution_attestation"] = _build_execution_attestation(
        engine, inventory, evidence, plan
    )
    _upgrade(database_url, EXECUTION_REVISION)
    execution_receipt = _execute_conversion(
        engine, archive_schema, inventory, evidence, plan
    ).payload

    receipt = _qualify_conversion(
        engine, archive_schema, inventory, evidence, plan, execution_receipt
    ).payload

    assert receipt["observed_counts"]["converted"] == 2
    assert receipt["verification_result"] == "qualified"


def test_independent_qualification_accepts_mixed_convert_and_quarantine(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    _upgrade(database_url, "0003_usda_source_identity")
    _seed_recipe(engine)
    _seed_recipe(
        engine,
        instructions="historical instructions have no lossless current field",
    )
    inventory = _inventory(engine)
    evidence = _prepare_isolation_evidence(engine, archive_schema, inventory)
    _bridge(engine, archive_schema, inventory, evidence)
    _upgrade(database_url, CONTROL_REVISION)
    plan = plan_historical_recipe_conversion(
        engine,
        inventory_payload=inventory,
        archive_schema=archive_schema,
        conversion_clone_id=evidence["conversion_clone_id"],
        clone_marker_identity=evidence["clone_marker_identity"],
        attestation_payload=evidence["attestation"],
    ).payload
    evidence["execution_attestation"] = _build_execution_attestation(
        engine, inventory, evidence, plan
    )
    _upgrade(database_url, EXECUTION_REVISION)
    execution_receipt = _execute_conversion(
        engine, archive_schema, inventory, evidence, plan
    ).payload

    receipt = _qualify_conversion(
        engine, archive_schema, inventory, evidence, plan, execution_receipt
    ).payload

    assert receipt["observed_counts"] == {
        "converted": 1,
        "quarantined": 1,
        "blocked": 0,
        "failed": 0,
        "pending": 0,
    }
    assert receipt["verification_result"] == "qualified"


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    (
        (
            "UPDATE daily_logs SET notes = 'changed historical log'",
            "qualification_daily_log_state_changed",
        ),
        (
            "UPDATE daily_log_nutrient_snapshots SET amount = amount + 1",
            "qualification_daily_log_state_changed",
        ),
        (
            "UPDATE ocr_scans SET full_text = 'changed private OCR text'",
            "qualification_ocr_state_changed",
        ),
        (
            "UPDATE parse_results SET parsed_payload = "
            "'{\"changed\":\"private\"}'::jsonb",
            "qualification_ocr_state_changed",
        ),
        (
            "UPDATE ocr_nutrition_confirmation_traces SET trace_snapshot = "
            "'{\"changed\":\"private\"}'::jsonb",
            "qualification_ocr_state_changed",
        ),
    ),
)
def test_independent_qualification_detects_daily_log_and_ocr_mutation(
    conversion_clone: tuple[Engine, str, str],
    mutation: str,
    reason_code: str,
) -> None:
    engine, database_url, archive_schema = conversion_clone
    inventory, evidence, plan = _prepare_execution_clone(
        engine, database_url, archive_schema
    )
    _seed_qualification_preservation_rows(engine, archive_schema)
    execution_receipt = _execute_conversion(
        engine, archive_schema, inventory, evidence, plan
    ).payload
    with engine.begin() as connection:
        connection.execute(text(mutation))

    with pytest.raises(Phase5CQualificationError, match=reason_code):
        _qualify_conversion(
            engine,
            archive_schema,
            inventory,
            evidence,
            plan,
            execution_receipt,
        )


def test_independent_qualification_detects_current_dependency_cycle(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    _upgrade(database_url, "0003_usda_source_identity")
    child = _seed_recipe(engine)
    parent = _seed_recipe(
        engine,
        user_id=child["user"],
        ingredient_food_item_id=child["projection"],
        ingredient_serving_id=child["projection_serving"],
    )
    inventory = _inventory(engine)
    evidence = _prepare_isolation_evidence(engine, archive_schema, inventory)
    _bridge(engine, archive_schema, inventory, evidence)
    _upgrade(database_url, CONTROL_REVISION)
    plan = plan_historical_recipe_conversion(
        engine,
        inventory_payload=inventory,
        archive_schema=archive_schema,
        conversion_clone_id=evidence["conversion_clone_id"],
        clone_marker_identity=evidence["clone_marker_identity"],
        attestation_payload=evidence["attestation"],
    ).payload
    evidence["execution_attestation"] = _build_execution_attestation(
        engine, inventory, evidence, plan
    )
    _upgrade(database_url, EXECUTION_REVISION)
    execution_receipt = _execute_conversion(
        engine, archive_schema, inventory, evidence, plan
    ).payload
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE recipe_ingredients SET food_item_id = :parent_projection, "
                "serving_definition_id = :parent_serving, amount_unit = 'serving' "
                "WHERE recipe_id = :child_id"
            ),
            {
                "parent_projection": parent["projection"],
                "parent_serving": parent["projection_serving"],
                "child_id": child["recipe"],
            },
        )

    with pytest.raises(
        Phase5CQualificationError, match="qualification_dependency_cycle"
    ):
        _qualify_conversion(
            engine,
            archive_schema,
            inventory,
            evidence,
            plan,
            execution_receipt,
        )


def test_independent_qualification_rejects_dependency_on_quarantined_subject(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    _upgrade(database_url, "0003_usda_source_identity")
    converted = _seed_recipe(engine)
    quarantined = _seed_recipe(
        engine,
        user_id=converted["user"],
        instructions="historical instructions have no lossless current field",
    )
    inventory = _inventory(engine)
    evidence = _prepare_isolation_evidence(engine, archive_schema, inventory)
    _bridge(engine, archive_schema, inventory, evidence)
    _upgrade(database_url, CONTROL_REVISION)
    plan = plan_historical_recipe_conversion(
        engine,
        inventory_payload=inventory,
        archive_schema=archive_schema,
        conversion_clone_id=evidence["conversion_clone_id"],
        clone_marker_identity=evidence["clone_marker_identity"],
        attestation_payload=evidence["attestation"],
    ).payload
    evidence["execution_attestation"] = _build_execution_attestation(
        engine, inventory, evidence, plan
    )
    _upgrade(database_url, EXECUTION_REVISION)
    execution_receipt = _execute_conversion(
        engine, archive_schema, inventory, evidence, plan
    ).payload
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE recipe_ingredients SET food_item_id = :projection, "
                "serving_definition_id = :serving, amount_unit = 'serving' "
                "WHERE recipe_id = :recipe_id"
            ),
            {
                "projection": quarantined["projection"],
                "serving": quarantined["projection_serving"],
                "recipe_id": converted["recipe"],
            },
        )

    with pytest.raises(
        Phase5CQualificationError, match="qualification_dependency_invalid"
    ):
        _qualify_conversion(
            engine,
            archive_schema,
            inventory,
            evidence,
            plan,
            execution_receipt,
        )


def test_independent_qualification_detects_unexplained_current_recipe(
    completed_qualification_clone: tuple[Engine, str, str, dict, dict, dict, dict],
) -> None:
    (
        engine,
        _database_url,
        archive_schema,
        inventory,
        evidence,
        plan,
        execution_receipt,
    ) = completed_qualification_clone
    with engine.begin() as connection:
        owner_id = connection.scalar(text("SELECT user_id FROM recipes LIMIT 1"))
        connection.execute(
            text(
                "INSERT INTO recipes (id, user_id, name, needs_republish) "
                "VALUES (:id, :owner_id, 'unexplained private Recipe', false)"
            ),
            {"id": uuid4(), "owner_id": owner_id},
        )

    with pytest.raises(
        Phase5CQualificationError,
        match="qualification_unexplained_current_domain_row",
    ):
        _qualify_conversion(
            engine,
            archive_schema,
            inventory,
            evidence,
            plan,
            execution_receipt,
        )


def test_independent_qualification_detects_unexpected_revision(
    completed_qualification_clone: tuple[Engine, str, str, dict, dict, dict, dict],
) -> None:
    (
        engine,
        _database_url,
        archive_schema,
        inventory,
        evidence,
        plan,
        execution_receipt,
    ) = completed_qualification_clone
    with engine.begin() as connection:
        recipe = connection.execute(
            text("SELECT id, user_id FROM recipes LIMIT 1")
        ).mappings().one()
        connection.execute(
            text(
                "INSERT INTO recipe_publication_revisions "
                "(id, recipe_id, user_id, revision_number, creation_origin, "
                "provenance_confidence, published_name, content_digest) VALUES "
                "(:id, :recipe_id, :user_id, 2, 'normal_publication', 'complete', "
                "'unexpected private revision', :digest)"
            ),
            {
                "id": uuid4(),
                "recipe_id": recipe["id"],
                "user_id": recipe["user_id"],
                "digest": "a" * 64,
            },
        )

    with pytest.raises(
        Phase5CQualificationError,
        match="qualification_converted_mapping_invalid",
    ):
        _qualify_conversion(
            engine,
            archive_schema,
            inventory,
            evidence,
            plan,
            execution_receipt,
        )


def test_independent_qualification_rejects_current_domain_for_quarantine(
    conversion_clone: tuple[Engine, str, str],
) -> None:
    engine, database_url, archive_schema = conversion_clone
    _upgrade(database_url, "0003_usda_source_identity")
    _seed_recipe(engine)
    _seed_recipe(
        engine,
        instructions="historical instructions have no lossless current field",
    )
    inventory = _inventory(engine)
    evidence = _prepare_isolation_evidence(engine, archive_schema, inventory)
    _bridge(engine, archive_schema, inventory, evidence)
    _upgrade(database_url, CONTROL_REVISION)
    plan = plan_historical_recipe_conversion(
        engine,
        inventory_payload=inventory,
        archive_schema=archive_schema,
        conversion_clone_id=evidence["conversion_clone_id"],
        clone_marker_identity=evidence["clone_marker_identity"],
        attestation_payload=evidence["attestation"],
    ).payload
    evidence["execution_attestation"] = _build_execution_attestation(
        engine, inventory, evidence, plan
    )
    _upgrade(database_url, EXECUTION_REVISION)
    execution_receipt = _execute_conversion(
        engine, archive_schema, inventory, evidence, plan
    ).payload
    quarantined_id = UUID(
        next(
            row["source_recipe_id"]
            for row in plan["decisions"]
            if row["intended_disposition"] == "quarantine"
        )
    )
    archive = engine.dialect.identifier_preparer.quote(archive_schema)
    with engine.begin() as connection:
        source = connection.execute(
            text(
                f"SELECT recipe.user_id, recipe.food_item_id, food.name "
                f"FROM {archive}.recipes recipe JOIN food_items food "
                "ON food.id = recipe.food_item_id WHERE recipe.id = :recipe_id"
            ),
            {"recipe_id": quarantined_id},
        ).mappings().one()
        connection.execute(
            text(
                "INSERT INTO recipes "
                "(id, user_id, published_food_item_id, name, needs_republish) "
                "VALUES (:id, :user_id, :projection_id, :name, false)"
            ),
            {
                "id": quarantined_id,
                "user_id": source["user_id"],
                "projection_id": source["food_item_id"],
                "name": source["name"],
            },
        )

    with pytest.raises(
        Phase5CQualificationError,
        match="qualification_nonconvert_domain_row_exists",
    ):
        _qualify_conversion(
            engine,
            archive_schema,
            inventory,
            evidence,
            plan,
            execution_receipt,
        )


def test_independent_qualification_rejects_other_plan_attestation_run_and_clone(
    completed_qualification_clone: tuple[Engine, str, str, dict, dict, dict, dict],
) -> None:
    (
        engine,
        _database_url,
        archive_schema,
        inventory,
        evidence,
        plan,
        execution_receipt,
    ) = completed_qualification_clone
    other_plan = _redigest_plan(
        plan, decisions__0__reason_code="another_approved_decision"
    )
    other_attestation = _redigest_attestation(
        evidence["execution_attestation"],
        clone_marker_identity="phase5c-other-qualification-marker",
    )
    other_receipt = deepcopy(execution_receipt)
    other_receipt["run_id"] = str(uuid4())
    unsigned = {
        key: value for key, value in other_receipt.items() if key != "report_digest"
    }
    other_receipt["report_digest"] = canonical_digest(unsigned)
    cases = (
        {"plan_payload": other_plan},
        {"execution_attestation_payload": other_attestation},
        {"execution_receipt_payload": other_receipt},
        {"clone_marker_identity": "phase5c-other-qualification-marker"},
        {"conversion_clone_id": "phase5c-other-qualification-clone"},
        {"archive_schema_override": "phase5c_other_archive"},
    )
    for changes in cases:
        with pytest.raises(
            Phase5CQualificationError,
            match="qualification_evidence_mismatch",
        ):
            _qualify_conversion(
                engine,
                archive_schema,
                inventory,
                evidence,
                plan,
                execution_receipt,
                **changes,
            )


def test_independent_qualification_cli_emits_canonical_receipt(
    completed_qualification_clone: tuple[Engine, str, str, dict, dict, dict, dict],
    tmp_path: Path,
) -> None:
    (
        _engine,
        database_url,
        archive_schema,
        inventory,
        evidence,
        plan,
        execution_receipt,
    ) = completed_qualification_clone
    artifacts = {
        "plan": plan,
        "inventory": inventory,
        "attestation": evidence["execution_attestation"],
        "execution-receipt": execution_receipt,
    }
    paths: dict[str, Path] = {}
    for name, payload in artifacts.items():
        path = tmp_path / f"{name}.json"
        path.write_text(canonical_json(payload), encoding="utf-8")
        paths[name] = path
    environment = os.environ.copy()
    environment["NUTRITION_DATABASE_URL"] = database_url
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.verify_historical_recipe_conversion",
            "--plan",
            str(paths["plan"]),
            "--inventory",
            str(paths["inventory"]),
            "--attestation",
            str(paths["attestation"]),
            "--execution-receipt",
            str(paths["execution-receipt"]),
            "--clone-marker-id",
            evidence["clone_marker_identity"],
            "--conversion-clone-id",
            evidence["conversion_clone_id"],
            "--archive-schema",
            archive_schema,
            "--format",
            "json",
        ],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["verification_result"] == "qualified"
    assert canonical_json(receipt) + "\n" == result.stdout
    assert "postgresql" not in result.stdout
