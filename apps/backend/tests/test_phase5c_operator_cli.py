from __future__ import annotations

import sys

import pytest

from scripts.bridge_historical_recipes import main as bridge_main
from scripts.capture_phase5c_database_identity import main as identity_main
from scripts.create_phase5c_operator_attestation import main as attestation_main
from scripts.establish_phase5c_clone_marker import main as marker_main
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
