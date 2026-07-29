from __future__ import annotations

import json
from pathlib import Path
import stat
import struct
from typing import Any

import pytest

from app.operators.phase5c_contracts import canonical_json, sha256_digest_bytes
from app.operators.phase5c4_cutback import (
    CUTBACK_AUTHORIZATION_SIGNING_DOMAIN,
    build_cutback_envelope,
    build_cutback_signed_statement,
)
from app.operators.phase5c4_cutback_authorization_control import (
    Phase5C4CutbackAuthorizationControlError,
)
from scripts import manage_phase5c4_cutback_authorization as cli
from tests import test_phase5c4_cutback as contract_support


_KEY_ID = "a" * 64


def _write(path: Path, value: bytes) -> None:
    path.write_bytes(value)


def _payload_bytes() -> bytes:
    return canonical_json(contract_support._payload()).encode()


def _statement_bytes() -> bytes:
    statement = build_cutback_signed_statement(
        contract_support._payload(),
        key_id=_KEY_ID,
    )
    return canonical_json(statement).encode()


def _envelope_bytes() -> bytes:
    statement = json.loads(_statement_bytes())
    return canonical_json(build_cutback_envelope(statement, signature=bytes(range(64)))).encode()


def _assert_private(path: Path) -> None:
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_parser_is_signerless_and_has_no_operational_authority() -> None:
    parser = cli._parser()
    choices = parser._subparsers._group_actions[0].choices

    assert set(choices) == {
        "admit",
        "assemble",
        "bootstrap-key",
        "export",
        "revoke-authorization",
        "revoke-key",
        "status",
        "verify",
    }
    assert all(
        "private" not in action.dest for command in choices.values() for action in command._actions
    )
    assert not {
        "cutback",
        "restore-source",
        "route",
        "sign",
    } & set(choices)


def test_export_writes_exact_statement_and_framed_message(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = tmp_path / "payload.json"
    statement = tmp_path / "statement.json"
    message = tmp_path / "message.bin"
    _write(payload, _payload_bytes())

    result = cli.main(
        [
            "export",
            "--payload",
            str(payload),
            "--key-id",
            _KEY_ID,
            "--statement-out",
            str(statement),
            "--message-out",
            str(message),
        ]
    )

    statement_bytes = _statement_bytes()
    expected_message = (
        CUTBACK_AUTHORIZATION_SIGNING_DOMAIN
        + struct.pack(">Q", len(statement_bytes))
        + statement_bytes
    )
    assert result == 0
    assert statement.read_bytes() == statement_bytes
    assert message.read_bytes() == expected_message
    _assert_private(statement)
    _assert_private(message)
    assert json.loads(capsys.readouterr().out) == {
        "command": "export",
        "key_id": _KEY_ID,
        "message_digest": sha256_digest_bytes(expected_message),
        "result": "exported",
        "statement_digest": sha256_digest_bytes(statement_bytes),
    }


def test_assemble_accepts_only_raw_detached_signature(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    statement = tmp_path / "statement.json"
    signature = tmp_path / "signature.bin"
    output = tmp_path / "cutback-authorization.json"
    _write(statement, _statement_bytes())
    _write(signature, bytes(range(64)))

    result = cli.main(
        [
            "assemble",
            "--statement",
            str(statement),
            "--signature-file",
            str(signature),
            "--cutback-authorization-out",
            str(output),
        ]
    )

    document = _envelope_bytes()
    assert result == 0
    assert output.read_bytes() == document
    _assert_private(output)
    assert json.loads(capsys.readouterr().out) == {
        "authorization_id": contract_support._payload()["authorization_id"],
        "command": "assemble",
        "envelope_digest": sha256_digest_bytes(document),
        "key_id": _KEY_ID,
        "result": "assembled",
    }


@pytest.mark.parametrize("size", [0, 63, 65])
def test_assemble_rejects_wrong_signature_lengths_without_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    size: int,
) -> None:
    statement = tmp_path / "statement.json"
    signature = tmp_path / "signature.bin"
    output = tmp_path / "cutback-authorization.json"
    _write(statement, _statement_bytes())
    _write(signature, b"x" * size)

    result = cli.main(
        [
            "assemble",
            "--statement",
            str(statement),
            "--signature-file",
            str(signature),
            "--cutback-authorization-out",
            str(output),
        ]
    )

    assert result == 3
    assert not output.exists()
    assert json.loads(capsys.readouterr().err) == {
        "command": "assemble",
        "reason": (
            "cutback_authorization_file_invalid"
            if size in {0, 65}
            else "cutback_authorization_signature_invalid"
        ),
        "result": "rejected",
    }


def test_verify_and_admit_use_only_the_verifier_surface(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = tmp_path / "cutback-authorization.json"
    _write(document, _envelope_bytes())
    monkeypatch.setenv(cli.VERIFIER_URL_ENV, "postgresql://verifier/control")
    calls: list[tuple[str, str, bytes]] = []

    def verify(url: str, value: bytes) -> dict[str, Any]:
        calls.append(("verify", url, value))
        return {
            "authorization_id": contract_support._payload()["authorization_id"],
            "key_id": _KEY_ID,
        }

    def admit(url: str, value: bytes) -> dict[str, Any]:
        calls.append(("admit", url, value))
        return {
            "authorization_id": contract_support._payload()["authorization_id"],
            "reason": "cutback_authorization_admitted",
            "result": "accepted",
        }

    monkeypatch.setattr(cli, "verify_cutback_with_trust_store", verify)
    monkeypatch.setattr(cli, "verify_and_admit_cutback_authorization", admit)

    assert cli.main(["verify", "--cutback-authorization", str(document)]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == "verified"
    assert cli.main(["admit", "--cutback-authorization", str(document)]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == "accepted"
    assert calls == [
        ("verify", "postgresql://verifier/control", _envelope_bytes()),
        ("admit", "postgresql://verifier/control", _envelope_bytes()),
    ]


def test_control_failure_is_redacted_and_has_stable_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = tmp_path / "cutback-authorization.json"
    _write(document, _envelope_bytes())
    secret_url = "postgresql://secret-user:secret-password@control/database"
    monkeypatch.setenv(cli.VERIFIER_URL_ENV, secret_url)

    def reject(_url: str, _value: bytes) -> dict[str, Any]:
        raise Phase5C4CutbackAuthorizationControlError(
            "cutback_authorization_database_unavailable",
            retryable=True,
        )

    monkeypatch.setattr(cli, "verify_cutback_with_trust_store", reject)

    assert cli.main(["verify", "--cutback-authorization", str(document)]) == 6
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "command": "verify",
        "reason": "cutback_authorization_database_unavailable",
        "result": "rejected",
    }
    assert secret_url not in captured.err
