from __future__ import annotations

from importlib import import_module

from app.migrations.immutable_provenance_0020_contracts import (
    EXACT_0020_FUNCTION_DEFINITION_SHA256,
    EXACT_0024_FUNCTION_DEFINITION_SHA256,
    exact_0020_snapshot_replacement_function_sql,
)
from app.operators import immutable_provenance_contracts as current_contracts
from app.operators.immutable_provenance_contracts import (
    DAILY_LOG_GUARD_FUNCTION,
    FUNCTION_DEFINITION_SHA256,
    IMMUTABLE_PROVENANCE_VALIDATOR_FUNCTION,
)
from app.operators.immutable_provenance_postgres import (
    snapshot_replacement_function_sql,
)


EXACT_0020_DAILY_LOG_GUARD_SHA256 = (
    "4b3d96d7c61e880480367b54cad754bb89bc3d19351887130bd693fdc3010298"
)
POST_0024_DAILY_LOG_GUARD_SHA256 = (
    "a89f7f97a0e3d88dc78e42a4921c21b41a04a31b09ede963328c42238db2b8b0"
)
POST_0024_IMMUTABLE_VALIDATOR_SHA256 = (
    "fb68f194cb23753b88f890876dff535f909a5e45ca3bae5f0bd32a7c724960d4"
)


def test_exact_0020_exact_0024_and_current_evidence_are_explicit() -> None:
    assert set(EXACT_0020_FUNCTION_DEFINITION_SHA256) == set(
        EXACT_0024_FUNCTION_DEFINITION_SHA256
    )
    assert (
        EXACT_0020_FUNCTION_DEFINITION_SHA256[DAILY_LOG_GUARD_FUNCTION]
        == EXACT_0020_DAILY_LOG_GUARD_SHA256
    )
    assert (
        EXACT_0024_FUNCTION_DEFINITION_SHA256[DAILY_LOG_GUARD_FUNCTION]
        == POST_0024_DAILY_LOG_GUARD_SHA256
    )
    assert (
        EXACT_0024_FUNCTION_DEFINITION_SHA256[
            IMMUTABLE_PROVENANCE_VALIDATOR_FUNCTION
        ]
        == POST_0024_IMMUTABLE_VALIDATOR_SHA256
    )
    assert FUNCTION_DEFINITION_SHA256 == EXACT_0024_FUNCTION_DEFINITION_SHA256


def test_exact_0020_validator_and_snapshot_installer_are_revision_scoped() -> None:
    migration = import_module(
        "app.migrations.versions.0020_immutable_provenance_enforcement"
    )
    validator_sql = migration._immutable_validator_sql(  # noqa: SLF001
        function_definition_sha256=EXACT_0020_FUNCTION_DEFINITION_SHA256,
    )

    assert EXACT_0020_DAILY_LOG_GUARD_SHA256 in validator_sql
    assert POST_0024_DAILY_LOG_GUARD_SHA256 not in validator_sql
    assert (
        exact_0020_snapshot_replacement_function_sql()
        == snapshot_replacement_function_sql()
    )


def test_0024_regenerates_validator_with_frozen_evidence(
    monkeypatch,
) -> None:
    migration = import_module(
        "app.migrations.versions.0024_recipe_log_current_provenance"
    )
    executed: list[str] = []

    class _Dialect:
        name = "postgresql"

    class _Bind:
        dialect = _Dialect()

    monkeypatch.setattr(migration.op, "get_bind", lambda: _Bind())
    monkeypatch.setattr(migration.op, "execute", executed.append)
    monkeypatch.setitem(
        FUNCTION_DEFINITION_SHA256,
        DAILY_LOG_GUARD_FUNCTION,
        "0" * 64,
    )
    monkeypatch.setattr(
        current_contracts,
        "FUNCTION_DEFINITION_SHA256",
        {DAILY_LOG_GUARD_FUNCTION: "1" * 64},
    )

    migration.upgrade()

    assert len(executed) == 2
    assert "CREATE OR REPLACE FUNCTION" in executed[1]
    assert POST_0024_DAILY_LOG_GUARD_SHA256 in executed[1]
    assert EXACT_0020_DAILY_LOG_GUARD_SHA256 not in executed[1]
