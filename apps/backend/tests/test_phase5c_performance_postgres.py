from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, inspect, make_url, text
from sqlalchemy.pool import NullPool

from app.operators.historical_recipe_performance import (
    Phase5CPerformanceError,
    admit_disposable_benchmark_target,
    execute_performance_path,
)
from app.operators.historical_recipe_performance_fixtures import (
    INTERNAL_REDUCED_TIER,
    PerformanceFixtureError,
    build_performance_fixture_blueprint,
    calculate_performance_fixture_logical_digest,
    seed_performance_fixture,
)
from app.operators.phase5c_performance_instrumentation import (
    Phase5CPerformanceInstrumentation,
)
from app.operators.phase5c_performance_contracts import (
    load_performance_manifest_file,
)


pytestmark = pytest.mark.postgres_concurrency

POSTGRES_URL = os.getenv(
    "NUTRITION_TEST_POSTGRES_URL",
    "postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app",
)
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _upgrade(database_url: str, revision: str) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "NUTRITION_DEPLOYMENT_MODE": "test",
            "NUTRITION_DATABASE_URL": database_url,
        }
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture()
def benchmark_database() -> tuple[Engine, str, str]:
    admin = create_engine(
        POSTGRES_URL,
        pool_pre_ping=True,
        isolation_level="AUTOCOMMIT",
    )
    try:
        with admin.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - developer environment dependent.
        admin.dispose()
        pytest.skip(f"PostgreSQL performance database unavailable: {exc}")

    database_name = f"nutrition_phase5c_bench_{uuid4().hex}"
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    admin.dispose()
    database_url = make_url(POSTGRES_URL).set(database=database_name).render_as_string(
        hide_password=False
    )
    engine = create_engine(database_url, pool_pre_ping=True, poolclass=NullPool)
    try:
        yield engine, database_url, database_name
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


def test_reduced_bridge_to_qualification_flow_is_measured_without_runtime_state(
    benchmark_database: tuple[Engine, str, str],
) -> None:
    engine, database_url, database_name = benchmark_database
    assert admit_disposable_benchmark_target(
        engine, confirmed_database_name=database_name
    ) == database_name
    blueprint = build_performance_fixture_blueprint(
        INTERNAL_REDUCED_TIER,
        17,
        allow_internal=True,
    )
    recorder = Phase5CPerformanceInstrumentation(
        archive_schema="nutrition_phase5c_archive"
    )

    with recorder.install():
        result = execute_performance_path(
            engine,
            database_url=database_url,
            confirmed_database_name=database_name,
            blueprint=blueprint,
            recorder=recorder,
            migration_runner=_upgrade,
        )
        with recorder.ignore_queries():
            with engine.connect() as connection:
                recorder.record_database_size(
                    int(
                        connection.scalar(
                            text("SELECT pg_database_size(current_database())")
                        )
                    )
                )
                connection.rollback()

    measurements = recorder.snapshot()
    assert result.correctness == {
        "independent_qualification_passed": True,
        "restart_verification_passed": True,
        "qualification_receipt_digest": result.qualification_receipt[
            "receipt_digest"
        ],
        "failure_reason_code": None,
    }
    assert result.plan["summary"] == {
        "total": 4,
        "convert": 2,
        "quarantine": 1,
        "block": 1,
    }
    assert all(
        measurements["stages"][stage]["status"] == "completed"
        for stage in measurements["stages"]
    )
    assert measurements["subject_conversion_seconds"]["count"] == 2
    assert measurements["subject_query_distribution"]["count"] == 4
    assert measurements["scan_counts"]["per_subject_global_source_passes"] > 0
    assert measurements["scan_counts"]["per_subject_daily_log_relation_scans"] > 0
    assert measurements["scan_counts"]["per_subject_ocr_relation_scans"] > 0
    assert measurements["artifact_bytes"]["execution_receipt"] > 0
    assert measurements["artifact_bytes"]["qualification_receipt"] > 0
    assert measurements["database_size_bytes"] > 0

    with engine.connect() as connection:
        performance_tables = connection.scalars(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema() "
                "AND table_name LIKE '%performance%'"
            )
        ).all()
        assert performance_tables == []
        assert "phase5c_conversion_runs" in inspect(connection).get_table_names()


def test_disposable_target_admission_refuses_mismatch_sessions_and_rows(
    benchmark_database: tuple[Engine, str, str],
) -> None:
    engine, _database_url, database_name = benchmark_database
    with pytest.raises(
        Phase5CPerformanceError,
        match="performance_target_confirmation_mismatch",
    ):
        admit_disposable_benchmark_target(
            engine,
            confirmed_database_name="nutrition_phase5c_benchmark_wrong_target",
        )

    blocker = engine.connect()
    try:
        with pytest.raises(
            Phase5CPerformanceError,
            match="performance_target_has_other_sessions",
        ):
            admit_disposable_benchmark_target(
                engine,
                confirmed_database_name=database_name,
            )
    finally:
        blocker.close()

    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE benchmark_nonempty_guard (id integer)"))
    with pytest.raises(
        Phase5CPerformanceError,
        match="performance_target_not_empty",
    ):
        admit_disposable_benchmark_target(
            engine,
            confirmed_database_name=database_name,
        )


def test_fixture_seeder_refuses_populated_nonfixture_legacy_tables(
    benchmark_database: tuple[Engine, str, str],
) -> None:
    engine, database_url, database_name = benchmark_database
    _upgrade(database_url, "0003_usda_source_identity")
    with engine.begin() as connection:
        nutrient_id = str(connection.scalar(text("SELECT id FROM nutrients LIMIT 1")))
        connection.execute(
            text(
                "INSERT INTO nutrient_reference_values "
                "(nutrient_id, reference_system, population_group, target_amount, "
                "unit, source_version) VALUES "
                "(:nutrient_id, 'fixture', 'fixture', 1, 'fixture-unit', 'fixture-v1')"
            ),
            {"nutrient_id": nutrient_id},
        )

    blueprint = build_performance_fixture_blueprint(
        INTERNAL_REDUCED_TIER,
        17,
        allow_internal=True,
    )
    with pytest.raises(PerformanceFixtureError, match="contains application rows"):
        seed_performance_fixture(
            engine,
            blueprint,
            confirmed_database_name=database_name,
        )


@pytest.mark.phase5c_performance_t0
@pytest.mark.skipif(
    os.getenv("NUTRITION_RUN_PHASE5C_T0") != "1",
    reason="full T0 performance qualification is explicitly operator-triggered",
)
def test_t0_full_path_uses_real_cli_migrations_and_deterministic_fixture(
    benchmark_database: tuple[Engine, str, str],
    tmp_path: Path,
) -> None:
    engine, database_url, database_name = benchmark_database
    admit_disposable_benchmark_target(
        engine,
        confirmed_database_name=database_name,
    )
    blueprint = build_performance_fixture_blueprint("T0", 20260714)
    output_path = tmp_path / "phase5c-performance-t0.json"
    environment = os.environ.copy()
    environment.update(
        {
            "NUTRITION_DEPLOYMENT_MODE": "test",
            "NUTRITION_DATABASE_URL": database_url,
        }
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.qualify_phase5c_performance",
            "--tier",
            "T0",
            "--fixture-seed",
            "20260714",
            "--storage-environment",
            "isolated PostgreSQL test storage",
            "--cache-mode",
            "warm",
            "--output",
            str(output_path),
            "--confirm-disposable-database",
            database_name,
        ],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode in {0, 1}, completed.stderr
    assert output_path.exists(), completed.stderr
    manifest = load_performance_manifest_file(output_path)
    assert manifest["correctness"]["independent_qualification_passed"] is True
    assert manifest["correctness"]["restart_verification_passed"] is True
    assert manifest["fixture_evidence"]["blueprint_digest"] == blueprint.blueprint_digest
    assert manifest["fixture_evidence"]["logical_digest"] == (
        calculate_performance_fixture_logical_digest(blueprint)
    )
    assert manifest["dimensions"]["recipes"] == 50
    assert manifest["dimensions"]["foods"] == 250
    assert manifest["dimensions"]["daily_logs"] == 5_000
    assert manifest["dimensions"]["ocr_records"] == 1_000
    assert all(
        measurement["status"] == "completed"
        for measurement in manifest["measurements"]["stages"].values()
    )
    password = make_url(database_url).password
    if password:
        assert password not in completed.stdout
        assert password not in completed.stderr
