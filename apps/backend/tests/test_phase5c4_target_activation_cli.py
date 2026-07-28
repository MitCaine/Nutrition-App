from __future__ import annotations

import json
from pathlib import Path
import stat
from types import SimpleNamespace
from typing import Any

import pytest

from app.operators.phase5c_contracts import canonical_json, sha256_digest_bytes
from app.operators.phase5c4_target_activation import (
    Phase5C4TargetActivationError,
)
from scripts import manage_phase5c4_target_activation as cli


_ACTION_ID = "00000000-0000-4000-8000-000000000001"


class _Control:
    def __init__(self, action: dict[str, Any] | None) -> None:
        self.action = action
        self.calls: list[tuple[str, str]] = []

    def read_schema_migration_action(self, action_id: str) -> dict[str, Any] | None:
        self.calls.append(("migration", action_id))
        return self.action

    def read_target_activation_action(self, action_id: str) -> dict[str, Any] | None:
        self.calls.append(("activation", action_id))
        return self.action

    def read_emergency_close_action(self, action_id: str) -> dict[str, Any] | None:
        self.calls.append(("emergency_close", action_id))
        return self.action


def _action() -> dict[str, Any]:
    return {
        "action_id": _ACTION_ID,
        "action_type": "test-fixed-purpose-action",
        "control_derived": True,
    }


def _target() -> dict[str, Any]:
    return {
        "deployment_descriptor_digest": "a" * 64,
        "fence_mode": "closed_cutover",
        "schema_revision": "0021_target_activation_execution",
        "target_identity_digest": "b" * 64,
        "runtime_write_admitted": False,
    }


def test_parser_exposes_only_fixed_target_actions_and_requires_action_ids() -> None:
    parser = cli._parser()
    choices = parser._subparsers._group_actions[0].choices

    assert set(choices) == {
        "emergency-close-target",
        "inspect-target",
        "migrate-target",
        "open-target",
    }
    for name in (
        "emergency-close-target",
        "migrate-target",
        "open-target",
    ):
        destinations = {action.dest for action in choices[name]._actions}
        assert destinations == {"action_id", "help", "observation_out"}
        with pytest.raises(SystemExit):
            parser.parse_args([name, "--observation-out", "/tmp/observation.json"])

    all_destinations = {action.dest for command in choices.values() for action in command._actions}
    assert (
        not {
            "authorization_id",
            "deployment_digest",
            "environment_id",
            "manifest_digest",
            "target_id",
        }
        & all_destinations
    )


def test_migrate_target_uses_only_control_derived_action_and_writes_observation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    action = _action()
    control = _Control(action)
    target = _target()
    observation = b'{"contract_version":"migration-observation"}'
    calls: list[tuple[str, Any]] = []
    monkeypatch.setenv(cli.TARGET_MIGRATION_URL_ENV, "postgresql://migrator/target")
    monkeypatch.setenv(cli.TARGET_OPS_URL_ENV, "postgresql://ops/target")
    monkeypatch.setenv(
        cli.TARGET_QUALIFIER_URL_ENV,
        "postgresql://qualifier/target",
    )
    monkeypatch.setattr(cli, "_control", lambda: control)
    monkeypatch.setattr(
        cli,
        "execute_schema_migration",
        lambda value, **kwargs: (
            calls.append(("execute", (value, kwargs))) or {"result": "installed"}
        ),
    )
    monkeypatch.setattr(
        cli,
        "qualify_migration_target",
        lambda url: calls.append(("qualify", url)) or {"qualified": True},
    )
    monkeypatch.setattr(
        cli,
        "inspect_target",
        lambda url: calls.append(("inspect", url)) or target,
    )
    monkeypatch.setattr(
        cli,
        "build_schema_migration_observation",
        lambda value, observed, **kwargs: (
            calls.append(("build", (value, observed, kwargs))) or observation
        ),
    )
    output = tmp_path / "migration-observation.json"

    assert (
        cli.main(
            [
                "migrate-target",
                "--action-id",
                _ACTION_ID,
                "--observation-out",
                str(output),
            ]
        )
        == 0
    )

    assert control.calls == [("migration", _ACTION_ID)]
    assert calls[0][0] == "execute"
    assert calls[0][1][0] is action
    assert calls[0][1][1]["migration_database_url"] == "postgresql://migrator/target"
    assert calls[1] == ("qualify", "postgresql://qualifier/target")
    assert calls[2] == ("inspect", "postgresql://ops/target")
    assert calls[3] == ("build", (action, target, {"result": "installed"}))
    assert output.read_bytes() == observation
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert json.loads(capsys.readouterr().out) == {
        "action_id": _ACTION_ID,
        "command": "migrate-target",
        "observation_digest": sha256_digest_bytes(observation),
        "observation_path": str(output),
        "result": "installed",
    }


def test_failed_migration_writes_reconcilable_observation_before_rejecting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    action = {
        **_action(),
        "target_identity_digest": "b" * 64,
    }
    observation = b'{"contract_version":"failed-migration-observation"}'
    monkeypatch.setenv(cli.TARGET_MIGRATION_URL_ENV, "postgresql://migrator/target")
    monkeypatch.setattr(cli, "_control", lambda: _Control(action))
    monkeypatch.setattr(
        cli,
        "execute_schema_migration",
        lambda *args, **kwargs: {"result": "failed"},
    )
    monkeypatch.setattr(
        cli,
        "build_schema_migration_observation",
        lambda value, observed, **kwargs: observation,
    )
    output = tmp_path / "failed-migration-observation.json"
    arguments = cli._parser().parse_args(
        [
            "migrate-target",
            "--action-id",
            _ACTION_ID,
            "--observation-out",
            str(output),
        ]
    )

    with pytest.raises(
        Phase5C4TargetActivationError,
        match="target_migration_failed",
    ):
        cli.execute(arguments)

    assert output.read_bytes() == observation
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    (
        "command",
        "read_call",
        "operator_name",
        "builder_name",
        "expected_result",
        "observation",
    ),
    [
        (
            "open-target",
            "activation",
            "open_target_runtime",
            "build_activation_runtime_observation",
            "open_observed",
            b'{"contract_version":"activation-observation"}',
        ),
        (
            "emergency-close-target",
            "emergency_close",
            "emergency_close_target",
            "build_emergency_close_observation",
            "closed_observed",
            b'{"contract_version":"emergency-close-observation"}',
        ),
    ],
)
def test_open_and_emergency_close_dispatch_exact_control_actions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    command: str,
    read_call: str,
    operator_name: str,
    builder_name: str,
    expected_result: str,
    observation: bytes,
) -> None:
    action = _action()
    control = _Control(action)
    target = _target()
    calls: list[tuple[str, Any]] = []
    monkeypatch.setenv(cli.TARGET_OPS_URL_ENV, "postgresql://ops/target")
    monkeypatch.setattr(cli, "_control", lambda: control)
    monkeypatch.setattr(
        cli,
        operator_name,
        lambda url, **kwargs: calls.append(("operate", (url, kwargs))),
    )
    monkeypatch.setattr(
        cli,
        "inspect_target",
        lambda url: calls.append(("inspect", url)) or target,
    )
    monkeypatch.setattr(
        cli,
        builder_name,
        lambda value, observed, **kwargs: (
            calls.append(("build", (value, observed, kwargs))) or observation
        ),
    )
    output = tmp_path / f"{command}-observation.json"

    assert (
        cli.main(
            [
                command,
                "--action-id",
                _ACTION_ID,
                "--observation-out",
                str(output),
            ]
        )
        == 0
    )

    assert control.calls == [(read_call, _ACTION_ID)]
    assert calls[0] == (
        "operate",
        ("postgresql://ops/target", {"action": action}),
    )
    assert calls[1] == ("inspect", "postgresql://ops/target")
    assert calls[2][0] == "build"
    assert calls[2][1][0] is action
    assert calls[2][1][1] is target
    assert output.read_bytes() == observation
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    result = json.loads(capsys.readouterr().out)
    assert result["action_id"] == _ACTION_ID
    assert result["command"] == command
    assert result["result"] == expected_result
    assert result["observation_digest"] == sha256_digest_bytes(observation)


@pytest.mark.parametrize(
    ("command", "read_call"),
    [
        ("migrate-target", "migration"),
        ("open-target", "activation"),
        ("emergency-close-target", "emergency_close"),
    ],
)
def test_unknown_action_fails_before_any_target_operation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    command: str,
    read_call: str,
) -> None:
    control = _Control(None)
    monkeypatch.setattr(cli, "_control", lambda: control)
    monkeypatch.setattr(
        cli,
        "execute_schema_migration",
        lambda *_args, **_kwargs: pytest.fail("target migration must not run"),
    )
    monkeypatch.setattr(
        cli,
        "open_target_runtime",
        lambda *_args, **_kwargs: pytest.fail("target open must not run"),
    )
    monkeypatch.setattr(
        cli,
        "emergency_close_target",
        lambda *_args, **_kwargs: pytest.fail("emergency close must not run"),
    )

    assert (
        cli.main(
            [
                command,
                "--action-id",
                _ACTION_ID,
                "--observation-out",
                str(tmp_path / "unused.json"),
            ]
        )
        == 5
    )
    assert control.calls == [(read_call, _ACTION_ID)]
    assert json.loads(capsys.readouterr().err) == {
        "command": command,
        "reason": "target_action_unknown",
        "result": "rejected",
    }


def test_inspect_target_has_no_control_action_and_optional_private_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = _target()
    monkeypatch.setenv(cli.TARGET_OPS_URL_ENV, "postgresql://ops/target")
    monkeypatch.setattr(cli, "inspect_target", lambda url: target)
    monkeypatch.setattr(
        cli,
        "_control",
        lambda: pytest.fail("inspection must not request a control action"),
    )
    output = tmp_path / "target.json"

    assert cli.main(["inspect-target", "--output", str(output)]) == 0
    assert output.read_bytes() == canonical_json(target).encode()
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert json.loads(capsys.readouterr().out) == {
        "command": "inspect-target",
        "result": "observed",
        "target": target,
    }


def test_target_error_output_is_deterministic_and_redacts_operator_details(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    action = _action()
    monkeypatch.setattr(cli, "_control", lambda: _Control(action))
    monkeypatch.setenv(
        cli.TARGET_OPS_URL_ENV,
        "postgresql://secret-user:secret-password@target/database",
    )

    def explode(_url: str, **_kwargs: Any) -> None:
        raise RuntimeError("provider-secret-operation-detail")

    monkeypatch.setattr(cli, "open_target_runtime", explode)

    assert (
        cli.main(
            [
                "open-target",
                "--action-id",
                _ACTION_ID,
                "--observation-out",
                str(tmp_path / "unused.json"),
            ]
        )
        == 9
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "command": "open-target",
        "reason": "target_operation_failed",
        "result": "rejected",
    }
    assert "secret-password" not in captured.err
    assert "provider-secret-operation-detail" not in captured.err


def test_retryable_missing_target_url_has_stable_exit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(cli.TARGET_OPS_URL_ENV, raising=False)
    arguments = SimpleNamespace(command="inspect-target", output=None)

    with pytest.raises(
        Phase5C4TargetActivationError,
        match="target_database_unavailable",
    ) as raised:
        cli.execute(arguments)
    assert raised.value.retryable is True

    assert cli.main(["inspect-target"]) == 6
    assert json.loads(capsys.readouterr().err) == {
        "command": "inspect-target",
        "reason": "target_database_unavailable",
        "result": "rejected",
    }
