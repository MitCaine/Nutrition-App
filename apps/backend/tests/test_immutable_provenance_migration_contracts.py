from __future__ import annotations

from importlib import import_module
from pathlib import Path

from app.migrations.immutable_provenance_0020_contracts import (
    EXACT_0020_FUNCTION_DEFINITION_SHA256,
    EXACT_0024_FUNCTION_DEFINITION_SHA256,
    exact_0020_snapshot_replacement_function_sql,
)
from app.migrations.immutable_provenance_0025_contracts import (
    EXACT_0025_FUNCTION_DEFINITION_SHA256,
    EXPECTED_0025_ACTIVATION_V4_EXECUTE_ACL,
    EXPECTED_0025_ACTIVATION_V4_ROUTINE,
    EXPECTED_0025_APPLICATION_HEAD,
    EXPECTED_0025_RUNTIME_EXECUTE_ROUTINES,
    EXPECTED_0025_RUNTIME_RELATION_PRIVILEGES,
    immutable_validator_0025_sql,
)
from app.operators import immutable_provenance_contracts as current_contracts
from app.operators.immutable_provenance_contracts import (
    DAILY_LOG_GUARD_FUNCTION,
    FUNCTION_DEFINITION_SHA256,
    IMMUTABLE_PROVENANCE_VALIDATOR_FUNCTION,
    FROZEN_RUNTIME_EXECUTE_ROUTINES,
    FROZEN_RUNTIME_RELATION_PRIVILEGES,
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
POST_0025_IMMUTABLE_VALIDATOR_SHA256 = (
    "59a0bc3d25b6bb99f01bd3629edac86a50c7ec0c216337ea02ea5622be2746bb"
)


def test_exact_0020_exact_0024_exact_0025_and_current_evidence_are_explicit() -> None:
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
    assert set(EXACT_0024_FUNCTION_DEFINITION_SHA256) == set(
        EXACT_0025_FUNCTION_DEFINITION_SHA256
    )
    assert {
        name
        for name in EXACT_0025_FUNCTION_DEFINITION_SHA256
        if EXACT_0025_FUNCTION_DEFINITION_SHA256[name]
        != EXACT_0024_FUNCTION_DEFINITION_SHA256[name]
    } == {IMMUTABLE_PROVENANCE_VALIDATOR_FUNCTION}
    assert (
        EXACT_0025_FUNCTION_DEFINITION_SHA256[DAILY_LOG_GUARD_FUNCTION]
        == POST_0024_DAILY_LOG_GUARD_SHA256
    )
    assert (
        EXACT_0025_FUNCTION_DEFINITION_SHA256[
            IMMUTABLE_PROVENANCE_VALIDATOR_FUNCTION
        ]
        == POST_0025_IMMUTABLE_VALIDATOR_SHA256
    )
    assert FUNCTION_DEFINITION_SHA256 == EXACT_0025_FUNCTION_DEFINITION_SHA256


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


def test_0025_replaces_only_the_validator_with_its_explicit_current_head(
    monkeypatch,
) -> None:
    migration = import_module(
        "app.migrations.versions.0025_immutable_validator_head"
    )
    executed: list[str] = []
    preconditions: list[bool] = []

    class _Dialect:
        name = "postgresql"

    class _Bind:
        dialect = _Dialect()

    monkeypatch.setattr(migration.op, "get_bind", lambda: _Bind())
    monkeypatch.setattr(migration.op, "execute", executed.append)
    monkeypatch.setattr(
        migration,
        "_require_closed_fence_and_drained_runtime",
        lambda: preconditions.append(True),
    )

    migration.upgrade()

    assert migration.revision == EXPECTED_0025_APPLICATION_HEAD
    assert migration.down_revision == "0024_recipe_log_current_provenance"
    assert preconditions == [True]
    assert len(executed) == 1
    assert "CREATE OR REPLACE FUNCTION" in executed[0]
    assert f"version_num = '{EXPECTED_0025_APPLICATION_HEAD}'" in executed[0]
    assert "version_num = '0020_immutable_provenance_enforcement'" not in executed[0]


def test_0025_freezes_the_established_current_runtime_authority() -> None:
    assert EXPECTED_0025_RUNTIME_RELATION_PRIVILEGES == (
        FROZEN_RUNTIME_RELATION_PRIVILEGES
    )
    assert EXPECTED_0025_RUNTIME_EXECUTE_ROUTINES == tuple(
        sorted(
            (
                *FROZEN_RUNTIME_EXECUTE_ROUTINES,
                EXPECTED_0025_ACTIVATION_V4_ROUTINE,
            )
        )
    )
    assert EXPECTED_0025_ACTIVATION_V4_EXECUTE_ACL == (
        ("nutrition_canary", False),
        ("nutrition_owner", False),
        ("nutrition_runtime", False),
    )

    rendered = immutable_validator_0025_sql()

    assert EXPECTED_0025_ACTIVATION_V4_ROUTINE == (
        "public.phase5c_local_admission_v4()"
    )
    assert rendered.count(EXPECTED_0025_ACTIVATION_V4_ROUTINE) == 1
    assert "public.phase5c_local_admission_v3()" in rendered
    assert "public.phase0020_delete_log_snapshots_for_replacement(uuid, uuid)" in rendered


def test_0025_revision_contract_does_not_import_current_activation_operator() -> None:
    contract = import_module("app.migrations.immutable_provenance_0025_contracts")
    source = Path(contract.__file__).read_text(encoding="utf-8")

    assert "phase5c4_activation_execution" not in source


def test_0025_is_forward_only() -> None:
    migration = import_module(
        "app.migrations.versions.0025_immutable_validator_head"
    )

    try:
        migration.downgrade()
    except RuntimeError as error:
        assert "forward-only" in str(error)
    else:  # pragma: no cover - explicit fail branch
        raise AssertionError("0025 downgrade must fail closed")
