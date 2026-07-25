from __future__ import annotations

import base64
import json
from pathlib import Path
import stat
import struct
from typing import Any

import pytest

from app.operators.phase5c_contracts import canonical_json, sha256_digest_bytes
from app.operators.phase5c4_authorization import (
    AUTHORIZATION_SIGNING_DOMAIN,
    Phase5C4AuthorizationError,
    build_envelope,
    build_signed_statement,
)
from app.operators.phase5c4_authorization_control import (
    Phase5C4AuthorizationControlError,
)
from scripts import manage_phase5c4_authorization as cli


_KEY_ID = "a" * 64


def _digest(character: str) -> str:
    return character * 64


def _payload() -> dict[str, Any]:
    return {
        "activation_command_id": "00000000-0000-4000-8000-000000000002",
        "attempt": {
            "artifact_set_digest": _digest("1"),
            "artifact_set_id": "00000000-0000-4000-8000-000000000005",
            "attempt_generation": 7,
            "attempt_id": "00000000-0000-4000-8000-000000000004",
            "attempt_state_version": 11,
            "required_workflow_state": "POST_CUTOVER_VERIFIED",
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
        "nonce": base64.urlsafe_b64encode(bytes(range(32)))
        .rstrip(b"=")
        .decode("ascii"),
        "not_before": "2026-01-02T03:04:05.000000Z",
        "policy_versions": {
            "activation_policy": "phase5c4_target_activation_policy_v1",
            "post_cutover_verification_policy": (
                "phase5c4_post_cutover_verification_policy_v1"
            ),
            "route_observation_policy": "phase5c4_route_observation_policy_v1",
            "trust_policy": "phase5c4_local_ed25519_trust_policy_v1",
        },
        "post_cutover": {
            "route_observation_digest": _digest("f"),
            "route_observation_id": "00000000-0000-4000-8000-00000000000a",
            "verification_receipt_digest": _digest("0"),
            "verification_receipt_id": "00000000-0000-4000-8000-000000000009",
        },
        "prior_authority": {
            "promotion_authorization_envelope_digest": _digest("2"),
            "promotion_authorization_id": "00000000-0000-4000-8000-00000000000b",
        },
        "purpose": "production_target_activation",
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
        "signer": {
            "approver_subject": "portfolio_owner_v1",
            "audience": "nutrition-phase5c4-control",
            "change_reference": "change-2026-0001",
            "issuer": (
                "portfolio_owner_v1@phase5c4_local_ed25519_trust_policy_v1"
            ),
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


def _write_payload(path: Path) -> bytes:
    document = canonical_json(_payload()).encode("utf-8")
    path.write_bytes(document)
    return document


def _write_statement(path: Path) -> bytes:
    statement = build_signed_statement(_payload(), key_id=_KEY_ID)
    document = canonical_json(statement).encode("utf-8")
    path.write_bytes(document)
    return document


def _write_envelope(path: Path) -> bytes:
    statement = build_signed_statement(_payload(), key_id=_KEY_ID)
    document = canonical_json(
        build_envelope(statement, signature=bytes(range(64)))
    ).encode("utf-8")
    path.write_bytes(document)
    return document


def _assert_private(path: Path) -> None:
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_export_writes_exact_statement_and_framed_message(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload_path = tmp_path / "payload.json"
    _write_payload(payload_path)
    statement_path = tmp_path / "statement.json"
    message_path = tmp_path / "message.bin"

    exit_code = cli.main(
        [
            "export",
            "--payload",
            str(payload_path),
            "--key-id",
            _KEY_ID,
            "--statement-out",
            str(statement_path),
            "--message-out",
            str(message_path),
        ]
    )

    statement = build_signed_statement(_payload(), key_id=_KEY_ID)
    statement_bytes = canonical_json(statement).encode("utf-8")
    expected_message = (
        AUTHORIZATION_SIGNING_DOMAIN
        + struct.pack(">Q", len(statement_bytes))
        + statement_bytes
    )
    output = capsys.readouterr()
    expected_result = {
        "command": "export",
        "key_id": _KEY_ID,
        "message_digest": sha256_digest_bytes(expected_message),
        "result": "exported",
        "statement_digest": sha256_digest_bytes(statement_bytes),
    }

    assert exit_code == 0
    assert output.err == ""
    assert output.out == canonical_json(expected_result) + "\n"
    assert statement_path.read_bytes() == statement_bytes
    assert message_path.read_bytes() == expected_message
    _assert_private(statement_path)
    _assert_private(message_path)


def test_assemble_accepts_only_raw_64_byte_detached_signature(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    statement_path = tmp_path / "statement.json"
    statement_bytes = _write_statement(statement_path)
    statement = json.loads(statement_bytes)
    signature = bytes(range(64))
    signature_path = tmp_path / "signature.bin"
    signature_path.write_bytes(signature)
    envelope_path = tmp_path / "authorization.json"

    exit_code = cli.main(
        [
            "assemble",
            "--statement",
            str(statement_path),
            "--signature-file",
            str(signature_path),
            "--authorization-out",
            str(envelope_path),
        ]
    )

    expected_bytes = canonical_json(
        build_envelope(statement, signature=signature)
    ).encode("utf-8")
    output = capsys.readouterr()
    expected_result = {
        "authorization_id": _payload()["authorization_id"],
        "command": "assemble",
        "envelope_digest": sha256_digest_bytes(expected_bytes),
        "key_id": _KEY_ID,
        "result": "assembled",
    }
    assert exit_code == 0
    assert output.err == ""
    assert output.out == canonical_json(expected_result) + "\n"
    assert envelope_path.read_bytes() == expected_bytes
    assert json.loads(expected_bytes)["signature"] == (
        base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    )
    _assert_private(envelope_path)


@pytest.mark.parametrize(
    ("signature", "reason"),
    [
        (b"x" * 63, "authorization_signature_invalid"),
        (b"x" * 65, "authorization_file_invalid"),
        (b"A" * 86, "authorization_file_invalid"),
    ],
)
def test_assemble_rejects_non_raw_or_wrong_length_signature(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    signature: bytes,
    reason: str,
) -> None:
    statement_path = tmp_path / "statement.json"
    _write_statement(statement_path)
    signature_path = tmp_path / "signature.bin"
    signature_path.write_bytes(signature)
    envelope_path = tmp_path / "authorization.json"

    exit_code = cli.main(
        [
            "assemble",
            "--statement",
            str(statement_path),
            "--signature-file",
            str(signature_path),
            "--authorization-out",
            str(envelope_path),
        ]
    )

    output = capsys.readouterr()
    assert exit_code == 3
    assert output.out == ""
    assert output.err == canonical_json(
        {
            "command": "assemble",
            "reason": reason,
            "result": "rejected",
        }
    ) + "\n"
    assert not envelope_path.exists()


def test_export_never_overwrites_and_rejects_symlink_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload_path = tmp_path / "payload.json"
    _write_payload(payload_path)
    sentinel = b"existing statement"
    statement_path = tmp_path / "statement.json"
    statement_path.write_bytes(sentinel)
    target = tmp_path / "message-target.bin"
    target.write_bytes(b"target")
    message_path = tmp_path / "message.bin"
    message_path.symlink_to(target)

    exit_code = cli.main(
        [
            "export",
            "--payload",
            str(payload_path),
            "--key-id",
            _KEY_ID,
            "--statement-out",
            str(statement_path),
            "--message-out",
            str(message_path),
        ]
    )

    output = capsys.readouterr()
    assert exit_code == 3
    assert output.out == ""
    assert json.loads(output.err)["result"] == "rejected"
    assert statement_path.read_bytes() == sentinel
    assert target.read_bytes() == b"target"


def test_export_rejects_noncanonical_payload_without_outputs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(_payload(), indent=2), encoding="utf-8")
    statement_path = tmp_path / "statement.json"
    message_path = tmp_path / "message.bin"

    exit_code = cli.main(
        [
            "export",
            "--payload",
            str(payload_path),
            "--key-id",
            _KEY_ID,
            "--statement-out",
            str(statement_path),
            "--message-out",
            str(message_path),
        ]
    )

    output = capsys.readouterr()
    assert exit_code == 3
    assert output.out == ""
    assert json.loads(output.err) == {
        "command": "export",
        "reason": "authorization_invalid",
        "result": "rejected",
    }
    assert not statement_path.exists()
    assert not message_path.exists()


def test_verify_uses_verifier_trust_store_and_emits_canonical_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorization_path = tmp_path / "authorization.json"
    document = _write_envelope(authorization_path)
    verifier_url = "postgresql+psycopg://verifier@example.invalid/control"
    monkeypatch.setenv(cli.VERIFIER_URL_ENV, verifier_url)
    observed: list[tuple[str, bytes]] = []
    trusted_result = {
        "authorization_id": _payload()["authorization_id"],
        "contract_version": "phase5c4_target_activation_authorization_v2",
        "envelope_digest": sha256_digest_bytes(document),
        "key_id": _KEY_ID,
        "signed_message_digest": _digest("7"),
        "verified": True,
    }

    def verify(database_url: str, canonical_bytes: bytes) -> dict[str, Any]:
        observed.append((database_url, canonical_bytes))
        return trusted_result

    monkeypatch.setattr(cli, "verify_with_trust_store", verify)

    exit_code = cli.main(
        ["verify", "--authorization", str(authorization_path)]
    )

    output = capsys.readouterr()
    expected = {"command": "verify", "result": "verified", **trusted_result}
    assert exit_code == 0
    assert observed == [(verifier_url, document)]
    assert output.err == ""
    assert output.out == canonical_json(expected) + "\n"


def test_admit_uses_verifier_api_and_preserves_idempotent_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorization_path = tmp_path / "authorization.json"
    document = _write_envelope(authorization_path)
    verifier_url = "postgresql+psycopg://verifier@example.invalid/control"
    monkeypatch.setenv(cli.VERIFIER_URL_ENV, verifier_url)
    observed: list[tuple[str, bytes]] = []
    admitted = {
        "authorization_id": _payload()["authorization_id"],
        "envelope_digest": sha256_digest_bytes(document),
        "reason": "exact_replay",
        "result": "idempotent_replay",
    }

    def admit(database_url: str, canonical_bytes: bytes) -> dict[str, Any]:
        observed.append((database_url, canonical_bytes))
        return admitted

    monkeypatch.setattr(cli, "verify_and_admit_authorization", admit)

    exit_code = cli.main(
        ["admit", "--authorization", str(authorization_path)]
    )

    output = capsys.readouterr()
    assert exit_code == 0
    assert observed == [(verifier_url, document)]
    assert output.err == ""
    assert output.out == canonical_json({"command": "admit", **admitted}) + "\n"


def test_admit_rejection_has_stable_conflict_exit_and_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorization_path = tmp_path / "authorization.json"
    _write_envelope(authorization_path)
    monkeypatch.setenv(
        cli.VERIFIER_URL_ENV,
        "postgresql+psycopg://verifier@example.invalid/control",
    )
    monkeypatch.setattr(
        cli,
        "verify_and_admit_authorization",
        lambda _url, _document: {
            "reason": "authorization_conflict",
            "result": "rejected",
        },
    )

    exit_code = cli.main(
        ["admit", "--authorization", str(authorization_path)]
    )

    output = capsys.readouterr()
    assert exit_code == 5
    assert output.out == ""
    assert output.err == canonical_json(
        {
            "command": "admit",
            "reason": "authorization_conflict",
            "result": "rejected",
        }
    ) + "\n"


def test_failure_redacts_database_url_exception_and_authorization_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorization_path = tmp_path / "authorization.json"
    document = _write_envelope(authorization_path)
    secret = "private-password"
    monkeypatch.setenv(
        cli.VERIFIER_URL_ENV,
        f"postgresql+psycopg://verifier:{secret}@example.invalid/control",
    )

    def fail(_url: str, _document: bytes) -> dict[str, Any]:
        raise RuntimeError(f"{secret} {document.decode('ascii')}")

    monkeypatch.setattr(cli, "verify_with_trust_store", fail)

    exit_code = cli.main(
        ["verify", "--authorization", str(authorization_path)]
    )

    output = capsys.readouterr()
    assert exit_code == 9
    assert output.out == ""
    assert output.err == canonical_json(
        {
            "command": "verify",
            "reason": "authorization_internal_failure",
            "result": "rejected",
        }
    ) + "\n"
    assert secret not in output.err
    assert document.decode("ascii") not in output.err
    assert "postgresql" not in output.err


def test_known_trust_failure_has_stable_authorization_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorization_path = tmp_path / "authorization.json"
    _write_envelope(authorization_path)
    monkeypatch.setenv(
        cli.VERIFIER_URL_ENV,
        "postgresql+psycopg://verifier@example.invalid/control",
    )

    def reject(_url: str, _document: bytes) -> dict[str, Any]:
        raise Phase5C4AuthorizationControlError("authorization_key_unknown")

    monkeypatch.setattr(cli, "verify_with_trust_store", reject)

    assert (
        cli.main(["verify", "--authorization", str(authorization_path)]) == 4
    )
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err) == {
        "command": "verify",
        "reason": "authorization_key_unknown",
        "result": "rejected",
    }


def test_parser_exposes_no_private_key_or_signing_operation() -> None:
    parser = cli._parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, cli.argparse._SubParsersAction)
    )
    commands = set(subparsers.choices)
    options = {
        option
        for command_parser in subparsers.choices.values()
        for action in command_parser._actions
        for option in action.option_strings
    }

    assert "sign" not in commands
    assert {
        "--private-key",
        "--private-key-file",
        "--seed",
        "--pem",
        "--sign",
        "--signing-command",
    }.isdisjoint(options)
    assert "--signature-file" in options


def test_authorization_error_reason_is_not_replaced_by_exception_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorization_path = tmp_path / "authorization.json"
    _write_envelope(authorization_path)
    monkeypatch.setenv(
        cli.VERIFIER_URL_ENV,
        "postgresql+psycopg://verifier@example.invalid/control",
    )

    def reject(_url: str, _document: bytes) -> dict[str, Any]:
        raise Phase5C4AuthorizationError("authorization_signature_invalid")

    monkeypatch.setattr(cli, "verify_with_trust_store", reject)

    assert (
        cli.main(["verify", "--authorization", str(authorization_path)]) == 3
    )
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["reason"] == "authorization_signature_invalid"
