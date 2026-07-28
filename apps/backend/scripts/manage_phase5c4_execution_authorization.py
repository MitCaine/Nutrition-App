"""Manage public Phase 5C4.7b execution-authorization material.

This signerless CLI never accepts or loads a private key.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import stat
import sys
from typing import Any
from uuid import UUID

from app.operators.phase5c_contracts import (
    canonical_json,
    parse_canonical_json,
    sha256_digest_bytes,
)
from app.operators.phase5c4_activation_execution import (
    build_execution_envelope,
    build_execution_signed_statement,
    execution_signing_message,
    parse_execution_authorization_envelope,
    parse_execution_signed_statement,
)
from app.operators.phase5c4_authorization import (
    AUTHORIZATION_MAXIMUM_BYTES,
    Phase5C4AuthorizationError,
    canonical_timestamp,
    public_key_der_and_id,
)
from app.operators.phase5c4_control_evidence import (
    Phase5C4EvidenceError,
    write_private_file,
)
from app.operators.phase5c4_execution_authorization_control import (
    Phase5C4ExecutionAuthorizationControlError,
    bootstrap_execution_authorization_key,
    read_execution_authorization_status,
    revoke_execution_authorization,
    revoke_execution_authorization_key,
    verify_and_admit_execution_authorization,
    verify_execution_with_trust_store,
)


VERIFIER_URL_ENV = "NUTRITION_PHASE5C4_EXECUTION_AUTHORIZATION_VERIFIER_DATABASE_URL"
MIGRATOR_URL_ENV = "NUTRITION_CONTROL_MIGRATION_DATABASE_URL"
AUDIT_URL_ENV = "NUTRITION_PHASE5C4_CONTROL_AUDIT_DATABASE_URL"


def _read_stable_file(
    path: Path,
    *,
    maximum_bytes: int = AUTHORIZATION_MAXIMUM_BYTES,
) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise Phase5C4AuthorizationError("execution_authorization_file_invalid") from None
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size <= 0
            or before.st_size > maximum_bytes
        ):
            raise Phase5C4AuthorizationError("execution_authorization_file_invalid")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        document = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(document) != before.st_size
            or before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
        ):
            raise Phase5C4AuthorizationError("execution_authorization_file_invalid")
        return document
    finally:
        os.close(descriptor)


def _uuid(value: str) -> str:
    try:
        parsed = str(UUID(value))
    except ValueError:
        raise argparse.ArgumentTypeError("must be a canonical UUID") from None
    if parsed != value:
        raise argparse.ArgumentTypeError("must be a canonical UUID")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Manage public Phase 5C4.7b execution authorization material. "
            "This command cannot sign, switch routes, migrate, activate, "
            "open a target, or load a private key."
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)

    export = commands.add_parser("export")
    export.add_argument("--payload", type=Path, required=True)
    export.add_argument("--key-id", required=True)
    export.add_argument("--statement-out", type=Path, required=True)
    export.add_argument("--message-out", type=Path, required=True)

    assemble = commands.add_parser("assemble")
    assemble.add_argument("--statement", type=Path, required=True)
    assemble.add_argument("--signature-file", type=Path, required=True)
    assemble.add_argument("--execution-authorization-out", type=Path, required=True)

    verify = commands.add_parser("verify")
    verify.add_argument("--execution-authorization", type=Path, required=True)

    admit = commands.add_parser("admit")
    admit.add_argument("--execution-authorization", type=Path, required=True)

    bootstrap = commands.add_parser("bootstrap-key")
    bootstrap.add_argument("--public-key-der", type=Path, required=True)
    bootstrap.add_argument("--valid-from", required=True)
    bootstrap.add_argument("--valid-until", required=True)
    bootstrap.add_argument("--bootstrap-reference", required=True)

    revoke_key = commands.add_parser("revoke-key")
    revoke_key.add_argument("--key-id", required=True)
    revoke_key.add_argument("--reason", required=True)
    revoke_key.add_argument("--change-reference", required=True)

    revoke = commands.add_parser("revoke-authorization")
    revoke.add_argument("--authorization-id", required=True, type=_uuid)
    revoke.add_argument("--reason", required=True)
    revoke.add_argument("--change-reference", required=True)

    status = commands.add_parser("status")
    status.add_argument("--authorization-id", required=True, type=_uuid)
    return parser


def _required_url(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise Phase5C4ExecutionAuthorizationControlError(
            "execution_authorization_database_unavailable",
            retryable=True,
        )
    return value


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.strptime(
            value,
            "%Y-%m-%dT%H:%M:%S.%fZ",
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        raise Phase5C4AuthorizationError("execution_authorization_time_invalid") from None
    if canonical_timestamp(parsed) != value:
        raise Phase5C4AuthorizationError("execution_authorization_time_invalid")
    return parsed


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return canonical_timestamp(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _export(arguments: argparse.Namespace) -> dict[str, Any]:
    document = _read_stable_file(arguments.payload)
    try:
        payload = parse_canonical_json(
            document,
            max_bytes=AUTHORIZATION_MAXIMUM_BYTES,
        )
    except Exception:
        raise Phase5C4AuthorizationError("execution_authorization_invalid") from None
    statement = build_execution_signed_statement(
        payload,
        key_id=arguments.key_id,
    )
    statement_bytes = canonical_json(statement).encode("utf-8")
    message = execution_signing_message(statement)
    write_private_file(
        arguments.statement_out,
        statement_bytes,
        maximum_bytes=AUTHORIZATION_MAXIMUM_BYTES,
    )
    write_private_file(
        arguments.message_out,
        message,
        maximum_bytes=AUTHORIZATION_MAXIMUM_BYTES,
    )
    return {
        "command": "export",
        "key_id": arguments.key_id,
        "message_digest": sha256_digest_bytes(message),
        "result": "exported",
        "statement_digest": sha256_digest_bytes(statement_bytes),
    }


def _assemble(arguments: argparse.Namespace) -> dict[str, Any]:
    statement = parse_execution_signed_statement(_read_stable_file(arguments.statement))
    signature = _read_stable_file(
        arguments.signature_file,
        maximum_bytes=64,
    )
    if len(signature) != 64:
        raise Phase5C4AuthorizationError("execution_authorization_signature_invalid")
    envelope = build_execution_envelope(statement, signature=signature)
    document = canonical_json(envelope).encode("utf-8")
    write_private_file(
        arguments.execution_authorization_out,
        document,
        maximum_bytes=AUTHORIZATION_MAXIMUM_BYTES,
    )
    return {
        "authorization_id": statement["payload"]["authorization_id"],
        "command": "assemble",
        "envelope_digest": sha256_digest_bytes(document),
        "key_id": statement["key_id"],
        "result": "assembled",
    }


def _verify(arguments: argparse.Namespace) -> dict[str, Any]:
    document = _read_stable_file(arguments.execution_authorization)
    parse_execution_authorization_envelope(document)
    result = verify_execution_with_trust_store(
        _required_url(VERIFIER_URL_ENV),
        document,
    )
    return {"command": "verify", "result": "verified", **result}


def _admit(arguments: argparse.Namespace) -> dict[str, Any]:
    document = _read_stable_file(arguments.execution_authorization)
    parse_execution_authorization_envelope(document)
    result = verify_and_admit_execution_authorization(
        _required_url(VERIFIER_URL_ENV),
        document,
    )
    if result["result"] == "rejected":
        raise Phase5C4ExecutionAuthorizationControlError(str(result["reason"]))
    return {"command": "admit", **result}


def _bootstrap(arguments: argparse.Namespace) -> dict[str, Any]:
    public_key = _read_stable_file(
        arguments.public_key_der,
        maximum_bytes=1024,
    )
    public_key_der_and_id(public_key)
    result = bootstrap_execution_authorization_key(
        _required_url(MIGRATOR_URL_ENV),
        public_key_der=public_key,
        valid_from=_parse_time(arguments.valid_from),
        valid_until=_parse_time(arguments.valid_until),
        bootstrap_reference=arguments.bootstrap_reference,
    )
    return {"command": "bootstrap-key", **result}


def _revoke_key(arguments: argparse.Namespace) -> dict[str, Any]:
    result = revoke_execution_authorization_key(
        _required_url(MIGRATOR_URL_ENV),
        key_id=arguments.key_id,
        reason=arguments.reason,
        change_reference=arguments.change_reference,
    )
    return {"command": "revoke-key", **result}


def _revoke(arguments: argparse.Namespace) -> dict[str, Any]:
    result = revoke_execution_authorization(
        _required_url(MIGRATOR_URL_ENV),
        authorization_id=arguments.authorization_id,
        reason=arguments.reason,
        change_reference=arguments.change_reference,
    )
    return {"command": "revoke-authorization", **result}


def _status(arguments: argparse.Namespace) -> dict[str, Any]:
    row = read_execution_authorization_status(
        _required_url(AUDIT_URL_ENV),
        arguments.authorization_id,
    )
    if row is None:
        raise Phase5C4ExecutionAuthorizationControlError("execution_authorization_unknown")
    return {"command": "status", "result": "accepted", **row}


def _exit_code(reason: str) -> int:
    if reason in {
        "execution_authorization_key_unknown",
        "execution_authorization_key_untrusted",
        "execution_authorization_revoked",
        "execution_authorization_unauthorized",
        "execution_authorization_unknown",
    }:
        return 4
    if reason in {
        "execution_authorization_binding_stale",
        "execution_authorization_conflict",
        "execution_authorization_key_conflict",
    }:
        return 5
    if reason in {
        "execution_authorization_database_unavailable",
        "execution_authorization_retry",
    }:
        return 6
    if reason == "execution_authorization_internal_failure":
        return 9
    return 3


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    operations = {
        "admit": _admit,
        "assemble": _assemble,
        "bootstrap-key": _bootstrap,
        "export": _export,
        "revoke-authorization": _revoke,
        "revoke-key": _revoke_key,
        "status": _status,
        "verify": _verify,
    }
    try:
        result = operations[arguments.command](arguments)
        sys.stdout.write(canonical_json(_json_safe(result)) + "\n")
        return 0
    except (
        Phase5C4AuthorizationError,
        Phase5C4ExecutionAuthorizationControlError,
        Phase5C4EvidenceError,
    ) as exc:
        reason = getattr(
            exc,
            "reason_code",
            "execution_authorization_file_invalid",
        )
        sys.stderr.write(
            canonical_json(
                {
                    "command": arguments.command,
                    "reason": reason,
                    "result": "rejected",
                }
            )
            + "\n"
        )
        return _exit_code(reason)
    except Exception:
        sys.stderr.write(
            canonical_json(
                {
                    "command": arguments.command,
                    "reason": "execution_authorization_internal_failure",
                    "result": "rejected",
                }
            )
            + "\n"
        )
        return 9


if __name__ == "__main__":
    raise SystemExit(main())
