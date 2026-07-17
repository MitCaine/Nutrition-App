from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from app.operators.phase5c4_control_contracts import build_command_result
from app.operators.phase5c4_minio import AUDIT_BUCKET, WormReceipt
from scripts import manage_phase5c_promotion as cli


def _uuid(value: int) -> str:
    return str(UUID(int=value))


def test_cli_emits_exact_canonical_result_and_exit(monkeypatch, capsys) -> None:
    expected = build_command_result(
        command="status",
        environment_id=_uuid(1),
        result="accepted",
        reason="ok",
        retryable=False,
        maintenance_required=False,
    )
    monkeypatch.setattr(cli, "execute", lambda _args: expected)
    assert cli.main(["status", "--environment-id", _uuid(1)]) == 0
    output = capsys.readouterr().out
    assert json.loads(output) == expected
    assert output == cli.serialize_command_result(expected) + "\n"


def test_cli_failure_redacts_database_and_object_store_secrets(monkeypatch, capsys) -> None:
    monkeypatch.setenv(
        "NUTRITION_PHASE5C4_CONTROL_DATABASE_URL",
        "postgresql+psycopg://private-user:private-password@example.invalid/control",
    )
    monkeypatch.setenv("NUTRITION_PHASE5C4_MINIO_SECRET_KEY", "private-object-secret")

    def fail(_args):
        raise RuntimeError("private-password private-object-secret authored content")

    monkeypatch.setattr(cli, "execute", fail)
    assert cli.main(["status", "--environment-id", _uuid(1)]) == 9
    output = capsys.readouterr().out
    assert "private" not in output
    assert "postgresql" not in output
    assert json.loads(output)["reason"] == "internal_failure"


def test_cli_surface_is_exactly_stage_5c4_3() -> None:
    parser = cli.parse_args
    for command in (
        "initialize-environment",
        "create-attempt",
        "register-evidence",
        "request-transition",
        "record-action-intent",
        "record-action-result",
        "reconcile-action",
        "status",
        "export-evidence",
        "deliver-outbox",
    ):
        with pytest.raises(SystemExit) as missing:
            parser([command])
        assert missing.value.code == 2
    source = Path(cli.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "activate-target",
        "switch-endpoint",
        "create-backup",
        "verify-restore",
        "cutback",
    ):
        assert f'add_parser("{forbidden}")' not in source


def test_control_cli_does_not_read_application_database_url(monkeypatch) -> None:
    monkeypatch.setenv("NUTRITION_DATABASE_URL", "postgresql://application-secret")
    monkeypatch.delenv("NUTRITION_PHASE5C4_CONTROL_DATABASE_URL", raising=False)
    with pytest.raises(cli.Phase5C4ControlError):
        cli.Phase5C4ControlDatabase()
    assert os.environ["NUTRITION_DATABASE_URL"].endswith("application-secret")


def test_deliver_outbox_does_not_turn_stale_ack_into_failure_mutation(
    monkeypatch, capsys
) -> None:
    message_id = _uuid(10)
    lease_token = _uuid(11)
    payload = b'{"event":"exact"}'
    receipt = WormReceipt(
        bucket=AUDIT_BUCKET,
        object_key="audit/v1/exact.json",
        object_version="immutable-version",
        etag="exact-etag",
        byte_count=len(payload),
        payload_digest="a" * 64,
        lock_mode="COMPLIANCE",
        retain_until=datetime.now(timezone.utc) + timedelta(days=180),
        observed_at=datetime.now(timezone.utc),
    )

    class Database:
        failure_calls = 0

        def claim_outbox(self, **_values):
            return [
                {
                    "message_id": message_id,
                    "lease_token": lease_token,
                    "object_key": receipt.object_key,
                    "payload_bytes": payload,
                }
            ]

        def acknowledge_outbox(self, **_values):
            raise cli.Phase5C4ControlError("invalid_transition")

        def fail_outbox(self, **_values):
            self.failure_calls += 1

    database = Database()

    class Adapter:
        def deliver(self, **_values):
            return receipt

    monkeypatch.setattr(cli, "Phase5C4ControlDatabase", lambda: database)
    monkeypatch.setattr(cli, "Phase5C4MinioAdapter", Adapter)
    assert cli.main(["deliver-outbox", "--request-id", _uuid(12)]) == 9
    result = json.loads(capsys.readouterr().out)
    assert result["result"] == "rejected"
    assert result["reason"] == "invalid_transition"
    assert database.failure_calls == 0


def test_deliver_outbox_surfaces_database_terminal_mismatch(monkeypatch) -> None:
    payload = b'{"event":"conflict"}'
    receipt = WormReceipt(
        bucket=AUDIT_BUCKET,
        object_key="audit/v1/conflict.json",
        object_version="immutable-version",
        etag="conflict-etag",
        byte_count=len(payload),
        payload_digest="b" * 64,
        lock_mode="COMPLIANCE",
        retain_until=datetime.now(timezone.utc) + timedelta(days=180),
        observed_at=datetime.now(timezone.utc),
    )

    class Database:
        def claim_outbox(self, **_values):
            return [
                {
                    "message_id": _uuid(20),
                    "lease_token": _uuid(21),
                    "object_key": receipt.object_key,
                    "payload_bytes": payload,
                }
            ]

        def acknowledge_outbox(self, **_values):
            return {
                "result": "terminal_mismatch",
                "reason": "object_store_mismatch",
                "receipt_digest": None,
            }

    class Adapter:
        def deliver(self, **_values):
            return receipt

    monkeypatch.setattr(cli, "Phase5C4ControlDatabase", Database)
    monkeypatch.setattr(cli, "Phase5C4MinioAdapter", Adapter)
    result = cli.execute(
        cli.parse_args(["deliver-outbox", "--request-id", _uuid(22)])
    )
    assert result["result"] == "terminal_mismatch"
    assert result["reason"] == "object_store_mismatch"
