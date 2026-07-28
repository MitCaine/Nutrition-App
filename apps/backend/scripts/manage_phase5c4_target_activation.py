"""Execute bounded Phase 5C4.7b target-local actions.

Every action is first reconstructed from the control database. The CLI never
accepts caller-supplied authority, identity, manifest, or evidence digests.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any
from uuid import UUID

from app.operators.phase5c_contracts import (
    canonical_json,
    sha256_digest_bytes,
)
from app.operators.phase5c4_control import (
    Phase5C4ControlDatabase,
    Phase5C4ControlError,
)
from app.operators.phase5c4_control_evidence import write_private_file
from app.operators.phase5c4_target_activation import (
    Phase5C4TargetActivationError,
    build_activation_runtime_observation,
    build_emergency_close_observation,
    build_schema_migration_observation,
    emergency_close_target,
    execute_schema_migration,
    inspect_target,
    open_target_runtime,
    qualify_migration_target,
)


CONTROL_AUDIT_URL_ENV = "NUTRITION_PHASE5C4_CONTROL_AUDIT_DATABASE_URL"
TARGET_MIGRATION_URL_ENV = "NUTRITION_PHASE5C4_TARGET_MIGRATION_DATABASE_URL"
TARGET_OPS_URL_ENV = "NUTRITION_PHASE5C4_TARGET_OPS_DATABASE_URL"
TARGET_QUALIFIER_URL_ENV = "NUTRITION_PHASE5C4_TARGET_QUALIFIER_DATABASE_URL"


def _uuid(value: str) -> str:
    try:
        canonical = str(UUID(value))
    except ValueError:
        raise argparse.ArgumentTypeError("must be a canonical UUID") from None
    if value != canonical:
        raise argparse.ArgumentTypeError("must be a canonical UUID")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Execute fixed-purpose Phase 5C4.7b target actions from durable "
            "control-plane intent. This is not a routing or cutback tool."
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)

    migrate = commands.add_parser("migrate-target")
    migrate.add_argument("--action-id", required=True, type=_uuid)
    migrate.add_argument("--observation-out", required=True, type=Path)

    inspect = commands.add_parser("inspect-target")
    inspect.add_argument("--output", type=Path)

    open_target = commands.add_parser("open-target")
    open_target.add_argument("--action-id", required=True, type=_uuid)
    open_target.add_argument("--observation-out", required=True, type=Path)

    close_target = commands.add_parser("emergency-close-target")
    close_target.add_argument("--action-id", required=True, type=_uuid)
    close_target.add_argument("--observation-out", required=True, type=Path)
    return parser


def _required_url(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise Phase5C4TargetActivationError(
            "target_database_unavailable",
            retryable=True,
        )
    return value


def _control() -> Phase5C4ControlDatabase:
    return Phase5C4ControlDatabase(_required_url(CONTROL_AUDIT_URL_ENV))


def _require_action(
    value: dict[str, Any] | None,
) -> dict[str, Any]:
    if value is None:
        raise Phase5C4TargetActivationError("target_action_unknown")
    return value


def _write_observation(
    path: Path,
    document: bytes,
) -> dict[str, Any]:
    write_private_file(path, document, maximum_bytes=65_536)
    return {
        "observation_digest": sha256_digest_bytes(document),
        "observation_path": str(path),
    }


def execute(arguments: argparse.Namespace) -> dict[str, Any]:
    if arguments.command == "inspect-target":
        observed = inspect_target(_required_url(TARGET_OPS_URL_ENV))
        if arguments.output is not None:
            document = canonical_json(observed).encode("utf-8")
            write_private_file(
                arguments.output,
                document,
                maximum_bytes=65_536,
            )
        return {
            "command": arguments.command,
            "result": "observed",
            "target": observed,
        }

    if arguments.command == "migrate-target":
        action = _require_action(_control().read_schema_migration_action(arguments.action_id))
        backend = Path(__file__).resolve().parents[1]
        result = execute_schema_migration(
            action,
            migration_database_url=_required_url(TARGET_MIGRATION_URL_ENV),
            backend_directory=backend,
        )
        if result["result"] == "installed":
            qualify_migration_target(
                _required_url(TARGET_QUALIFIER_URL_ENV)
            )
            target = inspect_target(_required_url(TARGET_OPS_URL_ENV))
            observation_result = "installed"
        else:
            observation_result = str(result["result"])
            target = {
                "fence_mode": "unknown",
                "schema_revision": "unknown",
                "target_identity_digest": action[
                    "target_identity_digest"
                ],
            }
        observation = build_schema_migration_observation(
            action,
            target,
            result=observation_result,
        )
        output = {
            "action_id": arguments.action_id,
            "command": arguments.command,
            "result": observation_result,
            **_write_observation(
                arguments.observation_out,
                observation,
            ),
        }
        if observation_result != "installed":
            raise Phase5C4TargetActivationError("target_migration_failed")
        return output

    if arguments.command == "open-target":
        action = _require_action(_control().read_target_activation_action(arguments.action_id))
        open_target_runtime(
            _required_url(TARGET_OPS_URL_ENV),
            action=action,
        )
        target = inspect_target(_required_url(TARGET_OPS_URL_ENV))
        observation = build_activation_runtime_observation(
            action,
            target,
            result="open",
            target_identity_digest=str(target["target_identity_digest"]),
        )
        return {
            "action_id": arguments.action_id,
            "command": arguments.command,
            "result": "open_observed",
            **_write_observation(
                arguments.observation_out,
                observation,
            ),
        }

    if arguments.command == "emergency-close-target":
        action = _require_action(_control().read_emergency_close_action(arguments.action_id))
        emergency_close_target(
            _required_url(TARGET_OPS_URL_ENV),
            action=action,
        )
        target = inspect_target(_required_url(TARGET_OPS_URL_ENV))
        observation = build_emergency_close_observation(
            action,
            target,
            result="closed",
            deployment_descriptor_digest=str(target["deployment_descriptor_digest"]),
            target_identity_digest=str(target["target_identity_digest"]),
        )
        return {
            "action_id": arguments.action_id,
            "command": arguments.command,
            "result": "closed_observed",
            **_write_observation(
                arguments.observation_out,
                observation,
            ),
        }
    raise Phase5C4TargetActivationError("target_action_invalid")


def _exit_code(error: Exception) -> int:
    reason = str(error)
    if getattr(error, "retryable", False):
        return 6
    if reason in {
        "target_action_conflict",
        "target_action_unknown",
        "target_fence_stale",
    }:
        return 5
    if reason in {
        "target_migration_failed",
        "target_postcondition_failed",
    }:
        return 8
    if reason == "target_operation_unauthorized":
        return 4
    return 3


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        result = execute(arguments)
        sys.stdout.write(canonical_json(result) + "\n")
        return 0
    except (
        Phase5C4ControlError,
        Phase5C4TargetActivationError,
    ) as exc:
        reason = str(exc)
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
        return _exit_code(exc)
    except Exception:
        sys.stderr.write(
            canonical_json(
                {
                    "command": arguments.command,
                    "reason": "target_operation_failed",
                    "result": "rejected",
                }
            )
            + "\n"
        )
        return 9


if __name__ == "__main__":
    raise SystemExit(main())
