from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys
import threading
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, inspect, make_url, text
from sqlalchemy.pool import NullPool

from app.operators import historical_recipe_bridge as bridge_module
from app.operators.historical_database_inventory import inventory_database
from app.operators.historical_recipe_bridge import (
    SCHEMA_SIGNATURE_DIGEST,
    bridge_legacy_recipes,
    establish_conversion_clone_marker,
    legacy_schema_structure,
)
from app.operators.historical_recipe_planner import plan_historical_recipe_conversion
from app.operators.phase5c_contracts import (
    CONTROL_REVISION,
    CONVERSION_PLAN_VERSION,
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
) -> dict[str, UUID]:
    ids = {
        "user": uuid4(),
        "foreign_user": uuid4(),
        "recipe": recipe_id or uuid4(),
        "projection": uuid4(),
        "projection_serving": uuid4(),
        "projection_nutrient": uuid4(),
        "ingredient_food": uuid4(),
        "ingredient_serving": uuid4(),
        "ingredient_nutrient": uuid4(),
        "ingredient": uuid4(),
    }
    with engine.begin() as connection:
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
        connection.execute(
            text(
                """
                INSERT INTO food_items
                    (id, user_id, name, source_type, source_id, is_recipe)
                VALUES
                    (:projection_id, :user_id, 'Historical Recipe Projection',
                     'recipe', :recipe_source_id, true),
                    (:ingredient_id, :ingredient_owner, 'Historical Ingredient',
                     'manual', NULL, false)
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
        connection.execute(
            text(
                """
                INSERT INTO serving_definitions
                    (id, food_item_id, label, quantity, unit, gram_weight,
                     is_default, source, is_user_confirmed)
                VALUES
                    (:projection_serving, :projection, '1 serving', 1, 'serving', 250,
                     true, 'recipe', true),
                    (:ingredient_serving, :ingredient_food, '1 cup', 1, 'cup', 100,
                     true, 'manual', true)
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
                VALUES
                    (:projection_nutrient, :projection, 'calories', 200, 'kcal',
                     'per_serving', 'known', 'recipe', true),
                    (:ingredient_nutrient, :ingredient_food, 'calories', 100, 'kcal',
                     'per_serving', 'known', 'manual', true)
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
                VALUES
                    (:ingredient, :recipe, :ingredient_food, 2, 'cup',
                     :ingredient_serving, 200, 'prepared', 0)
                """
            ),
            ids,
        )
    return ids


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
        _seed_recipe(engine)
    inventory = _inventory(engine)
    evidence = _prepare_isolation_evidence(engine, archive_schema, inventory)
    _bridge(engine, archive_schema, inventory, evidence)
    _upgrade(database_url, "head")
    return inventory, evidence


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
