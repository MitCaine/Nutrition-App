from __future__ import annotations

import sys

import pytest

from scripts.bridge_historical_recipes import main as bridge_main
from scripts.capture_phase5c_database_identity import main as identity_main
from scripts.create_phase5c_operator_attestation import main as attestation_main
from scripts.establish_phase5c_clone_marker import main as marker_main
from scripts.execute_historical_recipe_conversion import main as converter_main
from scripts.plan_historical_recipe_conversion import main as planner_main


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
