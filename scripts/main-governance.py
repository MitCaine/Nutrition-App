#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

RULESET_NAME = "Qualified main updates"
CHECK_NAME = "Main qualification"

GITHUB_ACTIONS_APP_ID = 15368


class GovernanceError(RuntimeError):
    pass


def validate_integration_id(
    integration_id: int,
) -> int:
    if (
        type(integration_id) is not int
        or integration_id < 1
    ):
        raise GovernanceError(
            "DEDICATED_APP_INTEGRATION_ID_INVALID"
        )

    if integration_id == GITHUB_ACTIONS_APP_ID:
        raise GovernanceError(
            (
                "DEDICATED_APP_REQUIRED: "
                "generic GitHub Actions integration "
                "cannot be the authoritative source"
            )
        )

    return integration_id


def build_ruleset_payload(
    integration_id: int,
) -> dict[str, Any]:
    integration_id = validate_integration_id(
        integration_id
    )

    return {
        "name": RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {
            "ref_name": {
                "include": [
                    "refs/heads/main",
                ],
                "exclude": [],
            }
        },
        "rules": [
            {
                "type": "deletion",
            },
            {
                "type": "non_fast_forward",
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": False,
                    "do_not_enforce_on_create": False,
                    "required_status_checks": [
                        {
                            "context": CHECK_NAME,
                            "integration_id": integration_id,
                        }
                    ],
                },
            },
        ],
    }


def validate_ruleset_payload(
    payload: dict[str, Any],
    *,
    integration_id: int,
) -> None:
    expected = build_ruleset_payload(
        integration_id
    )

    if payload != expected:
        raise GovernanceError(
            "RULESET_PAYLOAD_MISMATCH"
        )


def command_plan(
    args: argparse.Namespace,
) -> int:
    payload = build_ruleset_payload(
        args.integration_id
    )

    if args.output is not None:
        args.output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        args.output.write_text(
            json.dumps(
                payload,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    print(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        )
    )

    return 0


def command_validate(
    args: argparse.Namespace,
) -> int:
    try:
        payload = json.loads(
            args.input.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ) as exc:
        raise GovernanceError(
            "RULESET_PAYLOAD_INVALID"
        ) from exc

    if not isinstance(payload, dict):
        raise GovernanceError(
            "RULESET_PAYLOAD_INVALID"
        )

    validate_ruleset_payload(
        payload,
        integration_id=args.integration_id,
    )

    print(
        json.dumps(
            {
                "result": "PASS",
                "integration_id": (
                    args.integration_id
                ),
                "check": CHECK_NAME,
                "live_mutation": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run main governance planning for "
            "the dedicated qualification App."
        )
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    plan = commands.add_parser(
        "plan"
    )
    plan.add_argument(
        "--integration-id",
        type=int,
        required=True,
    )
    plan.add_argument(
        "--output",
        type=Path,
    )
    plan.set_defaults(
        handler=command_plan
    )

    validate = commands.add_parser(
        "validate"
    )
    validate.add_argument(
        "--integration-id",
        type=int,
        required=True,
    )
    validate.add_argument(
        "--input",
        type=Path,
        required=True,
    )
    validate.set_defaults(
        handler=command_validate
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        return args.handler(args)
    except GovernanceError as exc:
        print(
            json.dumps(
                {
                    "result": "FAIL",
                    "error": str(exc),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())
