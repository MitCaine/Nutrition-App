"""Export, assemble, verify, and admit Phase 5C4.6 authorization."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import stat
import sys
from typing import Any

from app.operators.phase5c_contracts import canonical_json, parse_canonical_json
from app.operators.phase5c4_authorization import (
    AUTHORIZATION_MAXIMUM_BYTES,
    Phase5C4AuthorizationError,
    build_envelope,
    build_signed_statement,
    canonical_timestamp,
    parse_authorization_envelope,
    parse_signed_statement,
    public_key_der_and_id,
    signing_message,
)
from app.operators.phase5c4_authorization_control import (
    Phase5C4AuthorizationControlError,
    bootstrap_authorization_key,
    revoke_authorization,
    revoke_authorization_key,
    verify_and_admit_authorization,
    verify_with_trust_store,
)
from app.operators.phase5c4_control_evidence import (
    Phase5C4EvidenceError,
    write_private_file,
)


VERIFIER_URL_ENV = "NUTRITION_PHASE5C4_AUTHORIZATION_VERIFIER_DATABASE_URL"
MIGRATOR_URL_ENV = "NUTRITION_CONTROL_MIGRATION_DATABASE_URL"


def _read_stable_file(
    path: Path, *, maximum_bytes: int = AUTHORIZATION_MAXIMUM_BYTES
) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise Phase5C4AuthorizationError("authorization_file_invalid") from None
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size <= 0
            or before.st_size > maximum_bytes
        ):
            raise Phase5C4AuthorizationError("authorization_file_invalid")
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
            raise Phase5C4AuthorizationError("authorization_file_invalid")
        return document
    finally:
        os.close(descriptor)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Manage public Phase 5C4.6 authorization material. "
            "This command cannot sign or activate a target."
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
    assemble.add_argument("--authorization-out", type=Path, required=True)

    verify = commands.add_parser("verify")
    verify.add_argument("--authorization", type=Path, required=True)

    admit = commands.add_parser("admit")
    admit.add_argument("--authorization", type=Path, required=True)

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
    revoke.add_argument("--authorization-id", required=True)
    revoke.add_argument("--reason", required=True)
    revoke.add_argument("--change-reference", required=True)
    return parser


def _required_url(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise Phase5C4AuthorizationControlError(
            "authorization_database_unavailable", retryable=True
        )
    return value


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        raise Phase5C4AuthorizationError("authorization_time_invalid") from None
    if canonical_timestamp(parsed) != value:
        raise Phase5C4AuthorizationError("authorization_time_invalid")
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
            document, max_bytes=AUTHORIZATION_MAXIMUM_BYTES
        )
    except Exception:
        raise Phase5C4AuthorizationError("authorization_invalid") from None
    statement = build_signed_statement(payload, key_id=arguments.key_id)
    statement_bytes = canonical_json(statement).encode("utf-8")
    message = signing_message(statement)
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
    from app.operators.phase5c_contracts import sha256_digest_bytes

    return {
        "command": "export",
        "key_id": arguments.key_id,
        "message_digest": sha256_digest_bytes(message),
        "result": "exported",
        "statement_digest": sha256_digest_bytes(statement_bytes),
    }


def _assemble(arguments: argparse.Namespace) -> dict[str, Any]:
    statement = parse_signed_statement(_read_stable_file(arguments.statement))
    signature = _read_stable_file(arguments.signature_file, maximum_bytes=64)
    if len(signature) != 64:
        raise Phase5C4AuthorizationError("authorization_signature_invalid")
    envelope = build_envelope(statement, signature=signature)
    envelope_bytes = canonical_json(envelope).encode("utf-8")
    write_private_file(
        arguments.authorization_out,
        envelope_bytes,
        maximum_bytes=AUTHORIZATION_MAXIMUM_BYTES,
    )
    from app.operators.phase5c_contracts import sha256_digest_bytes

    return {
        "authorization_id": statement["payload"]["authorization_id"],
        "command": "assemble",
        "envelope_digest": sha256_digest_bytes(envelope_bytes),
        "key_id": statement["key_id"],
        "result": "assembled",
    }


def _verify(arguments: argparse.Namespace) -> dict[str, Any]:
    document = _read_stable_file(arguments.authorization)
    parse_authorization_envelope(document)
    result = verify_with_trust_store(_required_url(VERIFIER_URL_ENV), document)
    return {"command": "verify", "result": "verified", **result}


def _admit(arguments: argparse.Namespace) -> dict[str, Any]:
    document = _read_stable_file(arguments.authorization)
    parse_authorization_envelope(document)
    result = verify_and_admit_authorization(
        _required_url(VERIFIER_URL_ENV), document
    )
    if result["result"] == "rejected":
        raise Phase5C4AuthorizationControlError(str(result["reason"]))
    return {"command": "admit", **result}


def _bootstrap(arguments: argparse.Namespace) -> dict[str, Any]:
    public_key = _read_stable_file(
        arguments.public_key_der, maximum_bytes=1024
    )
    public_key_der_and_id(public_key)
    result = bootstrap_authorization_key(
        _required_url(MIGRATOR_URL_ENV),
        public_key_der=public_key,
        valid_from=_parse_time(arguments.valid_from),
        valid_until=_parse_time(arguments.valid_until),
        bootstrap_reference=arguments.bootstrap_reference,
    )
    return {"command": "bootstrap-key", **result}


def _revoke_key(arguments: argparse.Namespace) -> dict[str, Any]:
    result = revoke_authorization_key(
        _required_url(MIGRATOR_URL_ENV),
        key_id=arguments.key_id,
        reason=arguments.reason,
        change_reference=arguments.change_reference,
    )
    return {"command": "revoke-key", **result}


def _revoke(arguments: argparse.Namespace) -> dict[str, Any]:
    result = revoke_authorization(
        _required_url(MIGRATOR_URL_ENV),
        authorization_id=arguments.authorization_id,
        reason=arguments.reason,
        change_reference=arguments.change_reference,
    )
    return {"command": "revoke-authorization", **result}


def _exit_code(reason: str) -> int:
    if reason in {
        "authorization_key_unknown",
        "authorization_key_untrusted",
        "authorization_revoked",
        "authorization_unauthorized",
    }:
        return 4
    if reason in {
        "authorization_binding_stale",
        "authorization_conflict",
        "authorization_key_conflict",
    }:
        return 5
    if reason in {
        "authorization_database_unavailable",
        "authorization_retry",
    }:
        return 6
    if reason == "authorization_internal_failure":
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
        "verify": _verify,
    }
    try:
        result = operations[arguments.command](arguments)
        sys.stdout.write(canonical_json(_json_safe(result)) + "\n")
        return 0
    except (
        Phase5C4AuthorizationError,
        Phase5C4AuthorizationControlError,
        Phase5C4EvidenceError,
    ) as exc:
        reason = getattr(exc, "reason_code", "authorization_file_invalid")
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
                    "reason": "authorization_internal_failure",
                    "result": "rejected",
                }
            )
            + "\n"
        )
        return 9


if __name__ == "__main__":
    raise SystemExit(main())
