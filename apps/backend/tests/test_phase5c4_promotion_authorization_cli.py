from __future__ import annotations

import base64
import json
from pathlib import Path
import stat
import struct
from typing import Any

import pytest

from app.operators.phase5c_contracts import canonical_json, sha256_digest_bytes
from app.operators.phase5c4_promotion_authorization import (
    PROMOTION_AUTHORIZATION_SIGNING_DOMAIN,
    build_promotion_envelope,
    build_promotion_signed_statement,
)
from app.operators.phase5c4_promotion_authorization_control import (
    Phase5C4PromotionAuthorizationControlError,
)
from scripts import manage_phase5c4_promotion_authorization as cli


_KEY_ID = "a" * 64


def _digest(character: str) -> str:
    return character * 64


def _payload() -> dict[str, Any]:
    return {
        "attempt": {
            "artifact_set_digest": _digest("1"),
            "artifact_set_id": "00000000-0000-4000-8000-000000000005",
            "attempt_generation": 7,
            "attempt_id": "00000000-0000-4000-8000-000000000004",
            "attempt_state_version": 11,
            "required_workflow_state": "RESTORE_EVIDENCE_ADMITTED",
        },
        "authorization_id": "00000000-0000-4000-8000-000000000001",
        "deployment": {
            "application_build_digest": _digest("a"),
            "descriptor_artifact_id": "00000000-0000-4000-8000-000000000008",
            "descriptor_digest": _digest("b"),
            "expected_provider_revision": "provider-revision-42",
            "provider_config_digest": _digest("c"),
            "target_direct_identity_digest": _digest("d"),
        },
        "environment": {
            "environment_id": "00000000-0000-4000-8000-000000000003",
            "environment_key": "production",
            "environment_state_version": 13,
            "fencing_generation": 17,
        },
        "expires_at": "2026-01-02T03:14:05.000000Z",
        "fence": {
            "chain_head_digest": _digest("e"),
            "epoch": 19,
            "required_mode": "closed_cutover",
        },
        "issued_at": "2026-01-02T03:04:05.000000Z",
        "nonce": base64.urlsafe_b64encode(bytes(range(32))).rstrip(b"=").decode(),
        "not_before": "2026-01-02T03:04:05.000000Z",
        "policy_versions": {
            "promotion_policy": "phase5c4_production_promotion_policy_v2",
            "route_switch_policy": "phase5c4_route_switch_policy_v1",
            "trust_policy": "phase5c4_promotion_ed25519_trust_policy_v1",
        },
        "purpose": "production_historical_conversion_promotion",
        "recovery": {
            "immutable_provenance_artifact_digest": _digest("3"),
            "immutable_provenance_qualification_digest": _digest("4"),
            "recovery_artifact_digest": _digest("5"),
            "recovery_evidence_digest": _digest("6"),
            "recovery_id": "00000000-0000-4000-8000-000000000007",
            "role_manifest_digest": _digest("7"),
            "role_policy_version": "phase5c4_postgresql_role_policy_v1",
            "runtime_privilege_digest": _digest("8"),
            "schema_revision": "0020_immutable_provenance_enforcement",
        },
        "route_switch_command_id": "00000000-0000-4000-8000-000000000002",
        "signer": {
            "approver_subject": "portfolio_owner_v1",
            "audience": "nutrition-phase5c4-promotion-control",
            "change_reference": "change-2026-0001",
            "issuer": ("portfolio_owner_v1@phase5c4_promotion_ed25519_trust_policy_v1"),
        },
        "source": {
            "database_incarnation_digest": _digest("9"),
            "database_instance_id": "00000000-0000-4000-8000-00000000000a",
            "safe_identity_digest": _digest("0"),
        },
        "target": {
            "database_incarnation_digest": _digest("9"),
            "database_instance_id": "00000000-0000-4000-8000-000000000006",
            "physical_identity_digest": _digest("a"),
            "provider_identity_digest": _digest("b"),
            "safe_identity_digest": _digest("c"),
            "target_identity_digest": _digest("d"),
        },
    }


def _write(path: Path, value: bytes) -> None:
    path.write_bytes(value)


def _statement_bytes() -> bytes:
    return canonical_json(build_promotion_signed_statement(_payload(), key_id=_KEY_ID)).encode()


def _envelope_bytes() -> bytes:
    statement = json.loads(_statement_bytes())
    return canonical_json(build_promotion_envelope(statement, signature=bytes(range(64)))).encode()


def test_export_writes_exact_statement_and_framed_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = tmp_path / "payload.json"
    _write(payload, canonical_json(_payload()).encode())
    statement = tmp_path / "statement.json"
    message = tmp_path / "message.bin"

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
        PROMOTION_AUTHORIZATION_SIGNING_DOMAIN
        + struct.pack(">Q", len(statement_bytes))
        + statement_bytes
    )
    assert result == 0
    assert statement.read_bytes() == statement_bytes
    assert message.read_bytes() == expected_message
    assert stat.S_IMODE(statement.stat().st_mode) == 0o600
    assert stat.S_IMODE(message.stat().st_mode) == 0o600
    output = json.loads(capsys.readouterr().out)
    assert output["statement_digest"] == sha256_digest_bytes(statement_bytes)
    assert output["message_digest"] == sha256_digest_bytes(expected_message)


def test_assemble_accepts_only_raw_detached_signature(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    statement = tmp_path / "statement.json"
    signature = tmp_path / "signature.bin"
    output = tmp_path / "promotion.json"
    _write(statement, _statement_bytes())
    _write(signature, bytes(range(64)))

    result = cli.main(
        [
            "assemble",
            "--statement",
            str(statement),
            "--signature-file",
            str(signature),
            "--promotion-authorization-out",
            str(output),
        ]
    )

    assert result == 0
    assert output.read_bytes() == _envelope_bytes()
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert json.loads(capsys.readouterr().out)["result"] == "assembled"


@pytest.mark.parametrize("size", [0, 63, 65])
def test_assemble_rejects_invalid_signature_length(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    size: int,
) -> None:
    statement = tmp_path / "statement.json"
    signature = tmp_path / "signature.bin"
    output = tmp_path / "promotion.json"
    _write(statement, _statement_bytes())
    _write(signature, b"x" * size)

    assert (
        cli.main(
            [
                "assemble",
                "--statement",
                str(statement),
                "--signature-file",
                str(signature),
                "--promotion-authorization-out",
                str(output),
            ]
        )
        != 0
    )
    assert not output.exists()
    assert json.loads(capsys.readouterr().err)["result"] == "rejected"


def test_cli_never_accepts_private_key_or_operational_commands() -> None:
    parser = cli._parser()
    choices = parser._subparsers._group_actions[0].choices
    assert set(choices) == {
        "admit",
        "assemble",
        "bootstrap-key",
        "export",
        "revoke-authorization",
        "revoke-key",
        "verify",
    }
    assert all(
        "private" not in action.dest for command in choices.values() for action in command._actions
    )
    assert not {"sign", "route", "activate", "open-production"} & set(choices)


def test_verify_and_admit_use_only_verifier_surface(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    envelope = tmp_path / "promotion.json"
    _write(envelope, _envelope_bytes())
    monkeypatch.setenv(cli.VERIFIER_URL_ENV, "postgresql://verifier/control")
    calls: list[tuple[str, str, bytes]] = []

    def verify(url: str, document: bytes) -> dict[str, Any]:
        calls.append(("verify", url, document))
        return {"authorization_id": _payload()["authorization_id"]}

    def admit(url: str, document: bytes) -> dict[str, Any]:
        calls.append(("admit", url, document))
        return {
            "authorization_id": _payload()["authorization_id"],
            "reason": "promotion_authorization_admitted",
            "result": "accepted",
        }

    monkeypatch.setattr(cli, "verify_promotion_with_trust_store", verify)
    monkeypatch.setattr(cli, "verify_and_admit_promotion_authorization", admit)

    assert cli.main(["verify", "--promotion-authorization", str(envelope)]) == 0
    assert cli.main(["admit", "--promotion-authorization", str(envelope)]) == 0
    capsys.readouterr()
    assert calls == [
        ("verify", "postgresql://verifier/control", _envelope_bytes()),
        ("admit", "postgresql://verifier/control", _envelope_bytes()),
    ]


def test_database_failures_have_stable_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    envelope = tmp_path / "promotion.json"
    _write(envelope, _envelope_bytes())
    monkeypatch.setenv(cli.VERIFIER_URL_ENV, "postgresql://verifier/control")
    monkeypatch.setattr(
        cli,
        "verify_and_admit_promotion_authorization",
        lambda *_: (_ for _ in ()).throw(
            Phase5C4PromotionAuthorizationControlError("promotion_authorization_binding_stale")
        ),
    )
    assert cli.main(["admit", "--promotion-authorization", str(envelope)]) == 5
    assert json.loads(capsys.readouterr().err) == {
        "command": "admit",
        "reason": "promotion_authorization_binding_stale",
        "result": "rejected",
    }


def test_existing_output_and_symlink_are_not_overwritten(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = tmp_path / "payload.json"
    statement = tmp_path / "statement.json"
    message = tmp_path / "message.bin"
    _write(payload, canonical_json(_payload()).encode())
    _write(statement, b"keep")
    message.symlink_to(statement)

    assert (
        cli.main(
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
        != 0
    )
    assert statement.read_bytes() == b"keep"
    assert message.is_symlink()
    capsys.readouterr()
