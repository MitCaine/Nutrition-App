from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import platform
import re
from typing import Any, Callable

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, make_url, text
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

from app.core.database_identity import database_connect_args
from app.operators.historical_database_inventory import inventory_database
from app.operators.historical_recipe_bridge import (
    SCHEMA_SIGNATURE_DIGEST,
    bridge_legacy_recipes,
    establish_conversion_clone_marker,
)
from app.operators.historical_recipe_converter import execute_historical_recipe_conversion
from app.operators.historical_recipe_performance_fixtures import (
    PerformanceFixtureBlueprint,
    PerformanceFixtureSeedResult,
    build_performance_fixture_blueprint,
    seed_performance_fixture,
)
from app.operators.historical_recipe_planner import plan_historical_recipe_conversion
from app.operators.historical_recipe_qualification import (
    Phase5CQualificationError,
    QualificationReceipt,
    qualify_historical_recipe_conversion,
)
from app.operators.phase5c_contracts import (
    CONTROL_REVISION,
    DEFAULT_ARCHIVE_SCHEMA,
    EXECUTION_REVISION,
    Phase5CAdmissionError,
    SUPPORTED_SCHEMA_SIGNATURE,
    SUPPORTED_SOURCE_REVISION,
    canonical_digest,
)
from app.operators.phase5c_isolation import (
    build_operator_attestation,
    safe_database_identity,
)
from app.operators.phase5c_performance_contracts import (
    PERFORMANCE_TIERS,
    PerformanceQualificationManifest,
    build_performance_manifest,
    validate_environment_description,
)
from app.operators.phase5c_performance_instrumentation import (
    Phase5CPerformanceInstrumentation,
)


BENCHMARK_DATABASE_PREFIX = "nutrition_phase5c_benchmark_"
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_DATABASE_NAME = re.compile(r"^nutrition_phase5c_(?:benchmark|bench)_[a-z0-9_]{3,48}$")
_POSTGRES_IDENTIFIER_MAX_BYTES = 63
_SAFE_REASON_CODES = {
    "performance_target_not_postgresql",
    "performance_target_confirmation_mismatch",
    "performance_target_name_invalid",
    "performance_target_not_empty",
    "performance_target_has_other_sessions",
    "performance_deployment_mode_invalid",
    "performance_large_tier_opt_in_required",
    "performance_database_setting_mismatch",
    "performance_fixture_classification_mismatch",
    "performance_conversion_verification_failed",
    "performance_independent_qualification_failed",
    "performance_restart_verification_failed",
    "performance_database_operation_failed",
}


class Phase5CPerformanceError(RuntimeError):
    """Bounded failure for the disposable offline performance harness."""

    def __init__(self, reason_code: str):
        if reason_code not in _SAFE_REASON_CODES:
            reason_code = "performance_database_operation_failed"
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class PerformancePathResult:
    fixture: PerformanceFixtureSeedResult
    inventory: dict[str, Any]
    plan: dict[str, Any]
    execution_receipt: dict[str, Any]
    qualification_receipt: dict[str, Any] | None
    independent_qualification_passed: bool
    restart_verification_passed: bool
    failure_reason_code: str | None

    @property
    def correctness(self) -> dict[str, Any]:
        return {
            "independent_qualification_passed": (
                self.independent_qualification_passed
            ),
            "restart_verification_passed": self.restart_verification_passed,
            "qualification_receipt_digest": (
                self.qualification_receipt["receipt_digest"]
                if self.qualification_receipt is not None
                else None
            ),
            "failure_reason_code": self.failure_reason_code,
        }


MigrationRunner = Callable[[str, str], None]


def admit_disposable_benchmark_target(
    engine: Engine,
    *,
    confirmed_database_name: str,
) -> str:
    """Prove that a specifically named, operator-created PostgreSQL database is empty."""

    if engine.dialect.name != "postgresql":
        raise Phase5CPerformanceError("performance_target_not_postgresql")
    database_name = str(engine.url.database or "")
    if confirmed_database_name != database_name:
        raise Phase5CPerformanceError("performance_target_confirmation_mismatch")
    if (
            not _DATABASE_NAME.fullmatch(database_name)
            or len(database_name.encode("ascii")) > _POSTGRES_IDENTIFIER_MAX_BYTES
    ):
        raise Phase5CPerformanceError("performance_target_name_invalid")

    with engine.connect() as connection:
        current_database = str(connection.scalar(text("SELECT current_database()")))
        current_schema = str(connection.scalar(text("SELECT current_schema()")))
        other_sessions = int(
            connection.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND pid <> pg_backend_pid()"
                )
            )
            or 0
        )
        schemas = set(
            connection.scalars(
                text(
                    "SELECT schema_name FROM information_schema.schemata "
                    "WHERE schema_name NOT LIKE 'pg_%' "
                    "AND schema_name <> 'information_schema'"
                )
            ).all()
        )
        tables = set(inspect(connection).get_table_names(schema="public"))
        connection.rollback()
    if current_database != database_name:
        raise Phase5CPerformanceError("performance_target_confirmation_mismatch")
    if other_sessions:
        raise Phase5CPerformanceError("performance_target_has_other_sessions")
    if current_schema != "public" or schemas != {"public"} or tables:
        raise Phase5CPerformanceError("performance_target_not_empty")
    return database_name


def capture_performance_environment(
    engine: Engine,
    *,
    storage_environment: str,
    cache_mode: str,
    available_memory_bytes: int | None = None,
) -> dict[str, Any]:
    validate_environment_description(storage_environment)
    if cache_mode not in {"cold", "warm"}:
        raise Phase5CPerformanceError("performance_database_operation_failed")
    memory_source = "operator_supplied"
    if available_memory_bytes is None:
        available_memory_bytes = _available_memory_bytes()
        memory_source = (
            "os_reported" if available_memory_bytes is not None else "unavailable"
        )
    elif (
        isinstance(available_memory_bytes, bool)
        or not isinstance(available_memory_bytes, int)
        or available_memory_bytes <= 0
    ):
        raise Phase5CPerformanceError("performance_database_operation_failed")

    setting_names = (
        "checkpoint_completion_target",
        "effective_cache_size",
        "jit",
        "maintenance_work_mem",
        "max_connections",
        "random_page_cost",
        "shared_buffers",
        "work_mem",
    )
    with engine.connect() as connection:
        postgresql_version = str(connection.scalar(text("SHOW server_version")))
        database_configuration = {
            name: str(connection.scalar(text(f"SHOW {name}")))
            for name in setting_names
        }
        connection.rollback()
    return {
        "postgresql_version": postgresql_version,
        "python_version": platform.python_version(),
        "platform": {
            "system": platform.system() or "unknown",
            "release": platform.release() or "unknown",
            "machine": platform.machine() or "unknown",
        },
        "cpu_count": os.cpu_count() or 1,
        "available_memory_bytes": available_memory_bytes,
        "available_memory_source": memory_source,
        "storage_environment": storage_environment,
        "database_configuration": database_configuration,
        "cache_mode": cache_mode,
    }


def execute_performance_path(
    engine: Engine,
    *,
    database_url: str,
    confirmed_database_name: str,
    blueprint: PerformanceFixtureBlueprint,
    recorder: Phase5CPerformanceInstrumentation,
    archive_schema: str = DEFAULT_ARCHIVE_SCHEMA,
    migration_runner: MigrationRunner | None = None,
) -> PerformancePathResult:
    """Execute the existing Phase 5C path without changing any correctness artifact."""

    migrate = migration_runner or run_alembic_upgrade
    with recorder.stage("fixture_creation"):
        _assert_no_other_database_sessions(engine)
        migrate(database_url, SUPPORTED_SOURCE_REVISION)
        fixture = seed_performance_fixture(
            engine,
            blueprint,
            confirmed_database_name=confirmed_database_name,
        )
        _assert_no_other_database_sessions(engine)

    with recorder.stage("inventory"):
        inventory = inventory_database(engine).to_dict()
    if inventory.get("classification", {}).get("value") != "legacy_conversion_required":
        raise Phase5CPerformanceError("performance_fixture_classification_mismatch")

    labels = _benchmark_labels(blueprint)
    with recorder.stage("marker_creation"):
        source_identity_digest, planning_attestation = _planning_attestation(
            engine,
            inventory=inventory,
            labels=labels,
        )
        establish_conversion_clone_marker(
            engine,
            inventory_payload=inventory,
            archive_schema=archive_schema,
            clone_marker_identity=labels["clone_marker_identity"],
            conversion_clone_id=labels["conversion_clone_id"],
            attestation_payload=planning_attestation,
        )

    with recorder.stage("bridge"):
        bridge_legacy_recipes(
            engine,
            inventory_payload=inventory,
            archive_schema=archive_schema,
            conversion_clone_id=labels["conversion_clone_id"],
            clone_marker_identity=labels["clone_marker_identity"],
            attestation_payload=planning_attestation,
        )

    with recorder.stage("migration_to_planning_head"):
        migrate(database_url, CONTROL_REVISION)

    with recorder.stage("planning"):
        plan = plan_historical_recipe_conversion(
            engine,
            inventory_payload=inventory,
            archive_schema=archive_schema,
            conversion_clone_id=labels["conversion_clone_id"],
            clone_marker_identity=labels["clone_marker_identity"],
            attestation_payload=planning_attestation,
        ).payload
    if plan["summary"] != {
        "total": blueprint.profile.recipe_count,
        "convert": blueprint.profile.convert_count,
        "quarantine": blueprint.profile.quarantine_count,
        "block": blueprint.profile.block_count,
    }:
        raise Phase5CPerformanceError("performance_fixture_classification_mismatch")

    with recorder.stage("execution_attestation_creation"):
        execution_attestation = _execution_attestation(
            engine,
            inventory=inventory,
            plan=plan,
            labels=labels,
            source_identity_digest=source_identity_digest,
        )

    with recorder.stage("migration_to_execution_head"):
        migrate(database_url, EXECUTION_REVISION)

    with recorder.stage("conversion"):
        execution_report = execute_historical_recipe_conversion(
            engine,
            plan_payload=plan,
            inventory_payload=inventory,
            archive_schema=archive_schema,
            conversion_clone_id=labels["conversion_clone_id"],
            clone_marker_identity=labels["clone_marker_identity"],
            attestation_payload=execution_attestation,
            performance_observer=recorder.converter_observer,
        )
    with recorder.stage("execution_receipt_generation"):
        execution_receipt_bytes = len(execution_report.to_json().encode("utf-8"))
        recorder.record_artifact_bytes(
            "execution_receipt_generation", execution_receipt_bytes
        )

    qualification_receipt: QualificationReceipt | None = None
    qualification_reason: str | None = None
    try:
        with recorder.stage("independent_qualification"):
            qualification_receipt = qualify_historical_recipe_conversion(
                engine,
                plan_payload=plan,
                inventory_payload=inventory,
                execution_attestation_payload=execution_attestation,
                execution_receipt_payload=execution_report.payload,
                archive_schema=archive_schema,
                conversion_clone_id=labels["conversion_clone_id"],
                clone_marker_identity=labels["clone_marker_identity"],
            )
            recorder.record_artifact_bytes(
                "independent_qualification",
                len(qualification_receipt.to_json().encode("utf-8")),
            )
    except Phase5CQualificationError as exc:
        qualification_reason = exc.reason_code

    restart_passed = False
    restart_reason: str | None = None
    try:
        with recorder.stage("restart_verification"):
            restarted = execute_historical_recipe_conversion(
                engine,
                plan_payload=plan,
                inventory_payload=inventory,
                archive_schema=archive_schema,
                conversion_clone_id=labels["conversion_clone_id"],
                clone_marker_identity=labels["clone_marker_identity"],
                attestation_payload=execution_attestation,
            )
            if restarted.payload != execution_report.payload:
                raise Phase5CPerformanceError(
                    "performance_restart_verification_failed"
                )
            restart_passed = True
    except (Phase5CAdmissionError, Phase5CPerformanceError):
        restart_reason = "performance_restart_verification_failed"

    qualification_payload = (
        qualification_receipt.payload if qualification_receipt is not None else None
    )
    qualification_passed = qualification_payload is not None
    if qualification_reason is not None:
        failure_reason = qualification_reason
    elif restart_reason is not None:
        failure_reason = restart_reason
    elif not qualification_passed:
        failure_reason = "performance_independent_qualification_failed"
    else:
        failure_reason = None
    return PerformancePathResult(
        fixture=fixture,
        inventory=inventory,
        plan=plan,
        execution_receipt=execution_report.payload,
        qualification_receipt=qualification_payload,
        independent_qualification_passed=qualification_passed,
        restart_verification_passed=restart_passed,
        failure_reason_code=failure_reason,
    )


def qualify_phase5c_performance(
    *,
    database_url: str,
    confirmed_database_name: str,
    tier: str,
    fixture_seed: int,
    storage_environment: str,
    cache_mode: str,
    allow_large_tier: bool,
    available_memory_bytes: int | None = None,
) -> PerformanceQualificationManifest:
    if tier not in PERFORMANCE_TIERS:
        raise Phase5CPerformanceError("performance_database_operation_failed")
    if tier != "T0" and not allow_large_tier:
        raise Phase5CPerformanceError("performance_large_tier_opt_in_required")
    if os.environ.get("NUTRITION_DEPLOYMENT_MODE") != "test":
        raise Phase5CPerformanceError("performance_deployment_mode_invalid")
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        raise Phase5CPerformanceError("performance_target_not_postgresql")
    engine = _benchmark_engine(url)
    try:
        admit_disposable_benchmark_target(
            engine,
            confirmed_database_name=confirmed_database_name,
        )
        environment = capture_performance_environment(
            engine,
            storage_environment=storage_environment,
            cache_mode=cache_mode,
            available_memory_bytes=available_memory_bytes,
        )
        blueprint = build_performance_fixture_blueprint(tier, fixture_seed)
        recorder = Phase5CPerformanceInstrumentation(
            archive_schema=DEFAULT_ARCHIVE_SCHEMA
        )
        with recorder.install():
            result = execute_performance_path(
                engine,
                database_url=database_url,
                confirmed_database_name=confirmed_database_name,
                blueprint=blueprint,
                recorder=recorder,
            )
            with recorder.ignore_queries():
                with engine.connect() as connection:
                    database_size = int(
                        connection.scalar(
                            text("SELECT pg_database_size(current_database())")
                        )
                    )
                    connection.rollback()
            recorder.record_database_size(database_size)
        measurements = recorder.snapshot()
        fixture_evidence = {
            "blueprint_digest": result.fixture.blueprint_digest,
            "logical_digest": result.fixture.logical_digest,
            "table_counts": result.fixture.table_counts,
        }
        return build_performance_manifest(
            tier=tier,
            fixture_seed=fixture_seed,
            fixture_evidence=fixture_evidence,
            environment=environment,
            dimensions=result.fixture.dimensions,
            measurements=measurements,
            correctness=result.correctness,
        )
    finally:
        engine.dispose()


def run_alembic_upgrade(database_url: str, revision: str) -> None:
    """Run real Alembic in-process so temporary Engine listeners can observe it."""

    from app.core.config import DeploymentMode, settings

    if settings.deployment_mode is not DeploymentMode.TEST:
        raise Phase5CPerformanceError("performance_deployment_mode_invalid")
    if make_url(settings.database_url) != make_url(database_url):
        raise Phase5CPerformanceError("performance_database_setting_mismatch")
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    command.upgrade(config, revision)


def _benchmark_engine(url: URL) -> Engine:
    return create_engine(
        url,
        pool_pre_ping=True,
        hide_parameters=True,
        poolclass=NullPool,
        connect_args=database_connect_args(url),
    )


def _assert_no_other_database_sessions(engine: Engine) -> None:
    with engine.connect() as connection:
        other_sessions = int(
            connection.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND pid <> pg_backend_pid()"
                )
            )
            or 0
        )
        connection.rollback()
    if other_sessions:
        raise Phase5CPerformanceError("performance_target_has_other_sessions")


def _benchmark_labels(blueprint: PerformanceFixtureBlueprint) -> dict[str, str]:
    suffix = canonical_digest(
        {
            "generator_version": blueprint.to_safe_dict()["generator_version"],
            "tier": blueprint.profile.tier_id,
            "seed": blueprint.seed,
            "blueprint_digest": blueprint.blueprint_digest,
        }
    )[:16]
    return {
        "clone_marker_identity": f"phase5c-benchmark-marker-{suffix}",
        "conversion_clone_id": f"phase5c-benchmark-clone-{suffix}",
        "planning_operator_identity": f"phase5c-benchmark-planner-{suffix}",
        "execution_operator_identity": f"phase5c-benchmark-executor-{suffix}",
    }


def _planning_attestation(
    engine: Engine,
    *,
    inventory: dict[str, Any],
    labels: dict[str, str],
) -> tuple[str, dict[str, Any]]:
    with engine.connect() as connection:
        clone_identity = safe_database_identity(connection)
        source_identity = {
            key: value
            for key, value in clone_identity.items()
            if key != "identity_digest"
        }
        source_identity["schema"] = "synthetic_benchmark_source"
        source_identity_digest = canonical_digest(source_identity)
        attestation = build_operator_attestation(
            connection,
            operator_attestation_identity=labels["planning_operator_identity"],
            scope="bridge_and_planning",
            clone_marker_identity=labels["clone_marker_identity"],
            conversion_clone_id=labels["conversion_clone_id"],
            source_production_identity_digest=source_identity_digest,
            inventory_digest=canonical_digest(inventory),
            schema_signature=SUPPORTED_SCHEMA_SIGNATURE,
            schema_signature_digest=SCHEMA_SIGNATURE_DIGEST,
        )
        connection.rollback()
    return source_identity_digest, attestation


def _execution_attestation(
    engine: Engine,
    *,
    inventory: dict[str, Any],
    plan: dict[str, Any],
    labels: dict[str, str],
    source_identity_digest: str,
) -> dict[str, Any]:
    with engine.connect() as connection:
        attestation = build_operator_attestation(
            connection,
            operator_attestation_identity=labels["execution_operator_identity"],
            scope="execution",
            clone_marker_identity=labels["clone_marker_identity"],
            conversion_clone_id=labels["conversion_clone_id"],
            source_production_identity_digest=source_identity_digest,
            inventory_digest=canonical_digest(inventory),
            schema_signature=SUPPORTED_SCHEMA_SIGNATURE,
            schema_signature_digest=SCHEMA_SIGNATURE_DIGEST,
            conversion_plan_payload=plan,
        )
        connection.rollback()
    return attestation


def _available_memory_bytes() -> int | None:
    names = os.sysconf_names
    if "SC_AVPHYS_PAGES" not in names or "SC_PAGE_SIZE" not in names:
        return None
    try:
        pages = int(os.sysconf("SC_AVPHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
    except (OSError, TypeError, ValueError):
        return None
    value = pages * page_size
    return value if value > 0 else None
