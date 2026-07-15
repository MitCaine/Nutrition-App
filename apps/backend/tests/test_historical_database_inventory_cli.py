from __future__ import annotations

import sys

import pytest

from scripts.inventory_historical_database import main


def test_inventory_cli_requires_explicit_database_configuration(monkeypatch) -> None:
    monkeypatch.delenv("NUTRITION_DATABASE_URL", raising=False)
    monkeypatch.setattr(sys, "argv", ["inventory_historical_database"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert str(exc_info.value) == (
        "NUTRITION_DATABASE_URL must be explicitly set for historical inventory"
    )


def test_inventory_cli_configuration_failure_does_not_echo_value(monkeypatch) -> None:
    secret_value = "SENSITIVE_DATABASE_CONFIGURATION_TOKEN"
    monkeypatch.setenv("NUTRITION_DATABASE_URL", f"not-a-database-url-{secret_value}")
    monkeypatch.setattr(sys, "argv", ["inventory_historical_database", "--format", "json"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert str(exc_info.value) == "Unable to inspect the explicitly configured database"
    assert secret_value not in str(exc_info.value)
