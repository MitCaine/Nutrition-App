"""Execute, validate, admit, and audit bounded Phase 5C4.5 recovery evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

from app.operators.phase5c4_control_evidence import (
    Phase5C4EvidenceError,
    write_private_file,
)
from app.operators.phase5c4_recovery import (
    DockerComposePgBackRestRecoveryProvider,
    ProviderRestoreEvidence,
    RecoveryExpectation,
    RecoveryValidationError,
    RestoreRequest,
    admit_recovery_validation,
    audit_recovery_validation,
    build_recovery_validation_receipt,
    collect_recovery_database_observation,
)
from app.operators.phase5c_contracts import canonical_json


def _read_object(path: Path) -> dict[str, Any]:
    try:
        document = path.read_bytes()
        value = json.loads(document)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise RecoveryValidationError("recovery_metadata_mismatch") from None
    if not isinstance(value, dict):
        raise RecoveryValidationError("recovery_metadata_mismatch")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Execute or validate one Docker Compose/pgBackRest recovery. "
            "This command never activates a target."
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)
    execute = commands.add_parser("execute")
    execute.add_argument("--request", type=Path, required=True)
    execute.add_argument("--evidence-out", type=Path, required=True)

    validate = commands.add_parser("validate")
    validate.add_argument("--expectation", type=Path, required=True)
    validate.add_argument("--provider-evidence", type=Path, required=True)
    validate.add_argument("--receipt-out", type=Path, required=True)
    validate.add_argument("--admit", action="store_true")

    audit = commands.add_parser("audit")
    audit.add_argument("--recovery-id", required=True)
    return parser


def _restore_request(value: dict[str, Any]) -> RestoreRequest:
    expected = {
        "compose_file",
        "compose_project",
        "operation_id",
        "operation_directory",
        "postgres_service",
        "provider_backup_id",
        "recovery_target_lsn",
        "restore_service",
        "stanza",
    }
    if set(value) != expected:
        raise RecoveryValidationError("recovery_metadata_mismatch")
    request = RestoreRequest(
        operation_id=value["operation_id"],
        operation_directory=Path(value["operation_directory"]),
        compose_file=Path(value["compose_file"]),
        compose_project=value["compose_project"],
        restore_service=value["restore_service"],
        postgres_service=value["postgres_service"],
        stanza=value["stanza"],
        provider_backup_id=value["provider_backup_id"],
        recovery_target_lsn=value["recovery_target_lsn"],
    )
    request.validate()
    return request


def _execute(arguments: argparse.Namespace) -> None:
    request = _restore_request(_read_object(arguments.request))
    evidence = DockerComposePgBackRestRecoveryProvider().restore(request)
    write_private_file(
        arguments.evidence_out,
        canonical_json(evidence.to_dict()).encode("utf-8"),
    )
    sys.stdout.write(canonical_json(evidence.to_dict()) + "\n")


def _validate(arguments: argparse.Namespace) -> None:
    expectation = RecoveryExpectation.from_mapping(
        _read_object(arguments.expectation)
    )
    provider = ProviderRestoreEvidence.from_mapping(
        _read_object(arguments.provider_evidence)
    )
    database_url = os.environ.get("NUTRITION_DATABASE_URL")
    if not database_url:
        raise RecoveryValidationError("validation_database_unavailable")
    observation = collect_recovery_database_observation(database_url)
    receipt = build_recovery_validation_receipt(
        expectation,
        provider,
        observation,
    )
    if arguments.admit:
        control_url = os.environ.get("NUTRITION_PHASE5C4_CONTROL_DATABASE_URL")
        if not control_url:
            raise RecoveryValidationError("validation_database_unavailable")
        admit_recovery_validation(control_url, receipt)
    write_private_file(arguments.receipt_out, receipt.to_bytes())
    sys.stdout.write(receipt.to_json() + "\n")
    if not receipt.passed:
        raise SystemExit(2)


def _audit(arguments: argparse.Namespace) -> None:
    control_url = os.environ.get("NUTRITION_PHASE5C4_CONTROL_DATABASE_URL")
    if not control_url:
        raise RecoveryValidationError("validation_database_unavailable")
    receipt = audit_recovery_validation(control_url, arguments.recovery_id)
    sys.stdout.write(receipt.to_json() + "\n")


def main() -> None:
    arguments = _parser().parse_args()
    try:
        if arguments.command == "execute":
            _execute(arguments)
        elif arguments.command == "validate":
            _validate(arguments)
        else:
            _audit(arguments)
    except (RecoveryValidationError, Phase5C4EvidenceError) as exc:
        reason = getattr(exc, "reason_code", "recovery_evidence_write_failed")
        raise SystemExit(f"Recovery operation failed: {reason}") from None


if __name__ == "__main__":
    main()
