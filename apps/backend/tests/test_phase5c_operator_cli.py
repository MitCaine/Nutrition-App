from __future__ import annotations

import inspect
import sys

import pytest

from app.operators import historical_recipe_qualification as qualification_module
from scripts.bridge_historical_recipes import main as bridge_main
from scripts.capture_phase5c_database_identity import main as identity_main
from scripts.create_phase5c_operator_attestation import main as attestation_main
from scripts.establish_phase5c_clone_marker import main as marker_main
from scripts.execute_historical_recipe_conversion import main as converter_main
from scripts.plan_historical_recipe_conversion import main as planner_main
from scripts.qualify_phase5c_performance import main as performance_main
from scripts.verify_historical_recipe_conversion import main as qualifier_main


@pytest.mark.parametrize(
    ("main", "argv", "message"),
    (
        (
            bridge_main,
            [
                "bridge_historical_recipes",
                "--inventory",
                "inventory.json",
                "--conversion-clone-id",
                "test-clone",
                "--clone-marker-id",
                "test-marker",
                "--attestation",
                "attestation.json",
            ],
            "NUTRITION_DATABASE_URL must be explicitly set for the historical bridge",
        ),
        (
            planner_main,
            [
                "plan_historical_recipe_conversion",
                "--inventory",
                "inventory.json",
                "--conversion-clone-id",
                "test-clone",
                "--clone-marker-id",
                "test-marker",
                "--attestation",
                "attestation.json",
            ],
            "NUTRITION_DATABASE_URL must be explicitly set for conversion planning",
        ),
        (
            identity_main,
            ["capture_phase5c_database_identity"],
            "NUTRITION_DATABASE_URL must be explicitly set for safe identity capture",
        ),
        (
            attestation_main,
            [
                "create_phase5c_operator_attestation",
                "--inventory",
                "inventory.json",
                "--source-production-identity",
                "production-identity.json",
                "--operator-attestation-id",
                "operator-id",
                "--clone-marker-id",
                "test-marker",
                "--conversion-clone-id",
                "test-clone",
            ],
            "NUTRITION_DATABASE_URL must be explicitly set for clone attestation",
        ),
        (
            marker_main,
            [
                "establish_phase5c_clone_marker",
                "--inventory",
                "inventory.json",
                "--attestation",
                "attestation.json",
                "--clone-marker-id",
                "test-marker",
                "--conversion-clone-id",
                "test-clone",
            ],
            "NUTRITION_DATABASE_URL must be explicitly set for clone-marker preflight",
        ),
        (
            converter_main,
            [
                "execute_historical_recipe_conversion",
                "--plan",
                "plan.json",
                "--inventory",
                "inventory.json",
                "--attestation",
                "attestation.json",
                "--clone-marker-id",
                "test-marker",
                "--conversion-clone-id",
                "test-clone",
            ],
            "NUTRITION_DATABASE_URL must be explicitly set for historical conversion",
        ),
        (
            qualifier_main,
            [
                "verify_historical_recipe_conversion",
                "--plan",
                "plan.json",
                "--inventory",
                "inventory.json",
                "--attestation",
                "attestation.json",
                "--execution-receipt",
                "execution-receipt.json",
                "--clone-marker-id",
                "test-marker",
                "--conversion-clone-id",
                "test-clone",
            ],
            "NUTRITION_DATABASE_URL must be explicitly set for conversion qualification",
        ),
        (
            performance_main,
            [
                "qualify_phase5c_performance",
                "--tier",
                "T0",
                "--fixture-seed",
                "1",
                "--storage-environment",
                "local disposable SSD",
                "--cache-mode",
                "warm",
                "--output",
                "performance.json",
                "--confirm-disposable-database",
                "nutrition_phase5c_benchmark_test",
            ],
            "NUTRITION_DATABASE_URL must be explicitly set for performance qualification",
        ),
    ),
)
def test_phase5c_operator_commands_require_explicit_database_configuration(
    monkeypatch,
    main,
    argv: list[str],
    message: str,
) -> None:
    monkeypatch.delenv("NUTRITION_DATABASE_URL", raising=False)
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert str(exc_info.value) == message


def test_execution_attestation_command_requires_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "NUTRITION_DATABASE_URL",
        "postgresql+psycopg://example.invalid/conversion_clone",
    )
    monkeypatch.setattr(
        "scripts.create_phase5c_operator_attestation.load_inventory_file",
        lambda _path: {},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "create_phase5c_operator_attestation",
            "--inventory",
            "inventory.json",
            "--source-production-identity",
            "production-identity.json",
            "--operator-attestation-id",
            "operator-id",
            "--scope",
            "execution",
            "--clone-marker-id",
            "test-marker",
            "--conversion-clone-id",
            "test-clone",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        attestation_main()

    assert str(exc_info.value) == "Execution-capable attestation requires --plan"


def test_execution_attestation_command_rejects_invalid_plan_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    invalid_plan = tmp_path / "invalid-plan.json"
    invalid_plan.write_text(
        '{"manifest_version":"unsupported-plan","authored":"private text"}',
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "NUTRITION_DATABASE_URL",
        "postgresql+psycopg://example.invalid/conversion_clone",
    )
    monkeypatch.setattr(
        "scripts.create_phase5c_operator_attestation.load_inventory_file",
        lambda _path: {},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "create_phase5c_operator_attestation",
            "--inventory",
            "inventory.json",
            "--source-production-identity",
            "production-identity.json",
            "--operator-attestation-id",
            "operator-id",
            "--scope",
            "execution",
            "--clone-marker-id",
            "test-marker",
            "--conversion-clone-id",
            "test-clone",
            "--plan",
            str(invalid_plan),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        attestation_main()

    error = str(exc_info.value)
    assert "Conversion plan" in error
    assert "private text" not in error
    assert "postgresql" not in error


def test_qualification_diagnostic_redacts_invalid_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invalid_plan = tmp_path / "invalid-qualification-plan.json"
    invalid_plan.write_text(
        '{"authored":"private qualification text","url":"postgresql://secret"}',
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "NUTRITION_DATABASE_URL",
        "postgresql+psycopg://example.invalid/conversion_clone",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_historical_recipe_conversion",
            "--plan",
            str(invalid_plan),
            "--inventory",
            "inventory.json",
            "--attestation",
            "attestation.json",
            "--execution-receipt",
            "execution-receipt.json",
            "--clone-marker-id",
            "test-marker",
            "--conversion-clone-id",
            "test-clone",
            "--diagnostic-only",
            "--format",
            "json",
        ],
    )

    qualifier_main()

    output = capsys.readouterr().out
    assert "qualification_evidence_mismatch" in output
    assert "private qualification text" not in output
    assert "postgresql" not in output
    assert "secret" not in output


def test_qualification_module_has_no_converter_or_write_statement_dependency() -> None:
    source = inspect.getsource(qualification_module)

    assert "historical_recipe_converter" not in source
    for write_statement in (
        "INSERT INTO",
        "UPDATE phase5c",
        "DELETE FROM",
        "ALTER TABLE",
        "CREATE TABLE",
    ):
        assert write_statement not in source


def test_qualification_cli_redacts_unexpected_exceptions(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "NUTRITION_DATABASE_URL",
        "postgresql+psycopg://example.invalid/conversion_clone",
    )
    for loader in (
        "load_conversion_plan_file",
        "load_inventory_file",
        "load_operator_attestation",
        "load_execution_receipt_file",
    ):
        monkeypatch.setattr(
            f"scripts.verify_historical_recipe_conversion.{loader}",
            lambda _path: {},
        )

    def fail_safely(*args, **kwargs):
        raise RuntimeError(
            "private authored text postgresql://operator:secret@example.invalid"
        )

    monkeypatch.setattr(
        "scripts.verify_historical_recipe_conversion.qualify_historical_recipe_conversion",
        fail_safely,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_historical_recipe_conversion",
            "--plan",
            "plan.json",
            "--inventory",
            "inventory.json",
            "--attestation",
            "attestation.json",
            "--execution-receipt",
            "execution-receipt.json",
            "--clone-marker-id",
            "test-marker",
            "--conversion-clone-id",
            "test-clone",
            "--diagnostic-only",
            "--format",
            "json",
        ],
    )

    qualifier_main()

    output = capsys.readouterr().out
    assert "qualification_evidence_mismatch" in output
    assert "private authored text" not in output
    assert "postgresql" not in output
    assert "secret" not in output


def test_performance_cli_redacts_unexpected_exceptions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    output = tmp_path / "performance.json"
    monkeypatch.setenv(
        "NUTRITION_DATABASE_URL",
        "postgresql+psycopg://operator:private-value@example.invalid/"
        "nutrition_phase5c_benchmark_test",
    )

    def fail_safely(**_kwargs):
        raise RuntimeError(
            "authored fixture content postgresql://operator:private-value@example.invalid"
        )

    monkeypatch.setattr(
        "scripts.qualify_phase5c_performance.qualify_phase5c_performance",
        fail_safely,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "qualify_phase5c_performance",
            "--tier",
            "T0",
            "--fixture-seed",
            "1",
            "--storage-environment",
            "local disposable SSD",
            "--cache-mode",
            "warm",
            "--output",
            str(output),
            "--confirm-disposable-database",
            "nutrition_phase5c_benchmark_test",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        performance_main()

    error = str(exc_info.value)
    assert error == "performance_database_operation_failed"
    assert "private-value" not in error
    assert "authored fixture" not in error
    assert not output.exists()
