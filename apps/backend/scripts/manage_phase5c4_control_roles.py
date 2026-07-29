from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.operators.phase5c_contracts import canonical_json
from app.operators.phase5c4_control_roles import (
    Phase5C4ControlRoleError,
    provision_cutback_authorization_verifier_role,
    provision_emergency_close_role,
    provision_execution_authorization_verifier_role,
    provision_promotion_authorization_verifier_role,
    provision_authorization_verifier_role,
    provision_control_roles,
    qualify_promotion_authorization_verifier_role,
    qualify_authorization_verifier_role,
    qualify_control_roles,
    qualify_cutback_authorization_verifier_role,
    qualify_emergency_close_role,
    qualify_execution_authorization_verifier_role,
    remove_promotion_authorization_verifier_role,
    remove_authorization_verifier_role,
    remove_emergency_close_role,
    remove_execution_authorization_verifier_role,
    remove_cutback_authorization_verifier_role,
    serialize_cutback_authorization_privilege_manifest,
    serialize_emergency_close_privilege_manifest,
    serialize_execution_authorization_privilege_manifest,
    serialize_promotion_authorization_privilege_manifest,
    serialize_authorization_privilege_manifest,
    serialize_privilege_manifest,
)


def _database_url() -> str:
    value = os.environ.get("NUTRITION_CONTROL_MIGRATION_DATABASE_URL")
    if not value:
        raise Phase5C4ControlRoleError(
            "NUTRITION_CONTROL_MIGRATION_DATABASE_URL must be explicitly set"
        )
    url = make_url(value)
    if url.get_backend_name() != "postgresql":
        raise Phase5C4ControlRoleError("Control role management requires PostgreSQL")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage the Stage 5C4.3 control role policy.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("manifest")
    subparsers.add_parser("authorization-manifest")
    subparsers.add_parser("promotion-authorization-manifest")
    subparsers.add_parser("execution-authorization-manifest")
    subparsers.add_parser("emergency-close-manifest")
    subparsers.add_parser("cutback-authorization-manifest")
    for name in ("provision", "qualify"):
        command = subparsers.add_parser(name)
        command.add_argument("--confirm-database", required=True)
    for name in (
        "provision-authorization-verifier",
        "qualify-authorization-verifier",
        "remove-authorization-verifier",
        "provision-promotion-authorization-verifier",
        "qualify-promotion-authorization-verifier",
        "remove-promotion-authorization-verifier",
        "provision-execution-authorization-verifier",
        "qualify-execution-authorization-verifier",
        "remove-execution-authorization-verifier",
        "provision-emergency-close",
        "qualify-emergency-close",
        "remove-emergency-close",
        "provision-cutback-authorization-verifier",
        "qualify-cutback-authorization-verifier",
        "remove-cutback-authorization-verifier",
    ):
        command = subparsers.add_parser(name)
        command.add_argument("--confirm-database", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "manifest":
        sys.stdout.write(serialize_privilege_manifest() + "\n")
        return
    if args.command == "authorization-manifest":
        sys.stdout.write(serialize_authorization_privilege_manifest() + "\n")
        return
    if args.command == "promotion-authorization-manifest":
        sys.stdout.write(serialize_promotion_authorization_privilege_manifest() + "\n")
        return
    if args.command == "execution-authorization-manifest":
        sys.stdout.write(serialize_execution_authorization_privilege_manifest() + "\n")
        return
    if args.command == "emergency-close-manifest":
        sys.stdout.write(serialize_emergency_close_privilege_manifest() + "\n")
        return
    if args.command == "cutback-authorization-manifest":
        sys.stdout.write(serialize_cutback_authorization_privilege_manifest() + "\n")
        return
    engine = None
    try:
        engine = create_engine(
            _database_url(),
            poolclass=NullPool,
            pool_pre_ping=True,
            hide_parameters=True,
        )
        if args.command == "provision":
            result = provision_control_roles(engine, expected_database=args.confirm_database)
        elif args.command == "qualify":
            result = qualify_control_roles(engine, expected_database=args.confirm_database)
        elif args.command == "provision-authorization-verifier":
            result = provision_authorization_verifier_role(
                engine, expected_database=args.confirm_database
            )
        elif args.command == "qualify-authorization-verifier":
            result = qualify_authorization_verifier_role(
                engine, expected_database=args.confirm_database
            )
        elif args.command == "remove-authorization-verifier":
            result = remove_authorization_verifier_role(
                engine, expected_database=args.confirm_database
            )
        elif args.command == "provision-promotion-authorization-verifier":
            result = provision_promotion_authorization_verifier_role(
                engine, expected_database=args.confirm_database
            )
        elif args.command == "qualify-promotion-authorization-verifier":
            result = qualify_promotion_authorization_verifier_role(
                engine, expected_database=args.confirm_database
            )
        elif args.command == "remove-promotion-authorization-verifier":
            result = remove_promotion_authorization_verifier_role(
                engine, expected_database=args.confirm_database
            )
        elif args.command == "provision-execution-authorization-verifier":
            result = provision_execution_authorization_verifier_role(
                engine,
                expected_database=args.confirm_database,
            )
        elif args.command == "qualify-execution-authorization-verifier":
            result = qualify_execution_authorization_verifier_role(
                engine,
                expected_database=args.confirm_database,
            )
        elif args.command == "remove-execution-authorization-verifier":
            result = remove_execution_authorization_verifier_role(
                engine,
                expected_database=args.confirm_database,
            )
        elif args.command == "provision-emergency-close":
            result = provision_emergency_close_role(
                engine,
                expected_database=args.confirm_database,
            )
        elif args.command == "qualify-emergency-close":
            result = qualify_emergency_close_role(
                engine,
                expected_database=args.confirm_database,
            )
        elif args.command == "provision-cutback-authorization-verifier":
            result = provision_cutback_authorization_verifier_role(
                engine,
                expected_database=args.confirm_database,
            )
        elif args.command == "qualify-cutback-authorization-verifier":
            result = qualify_cutback_authorization_verifier_role(
                engine,
                expected_database=args.confirm_database,
            )
        elif args.command == "remove-cutback-authorization-verifier":
            result = remove_cutback_authorization_verifier_role(
                engine,
                expected_database=args.confirm_database,
            )
        else:
            result = remove_emergency_close_role(
                engine,
                expected_database=args.confirm_database,
            )
        sys.stdout.write(canonical_json(result) + "\n")
    except (Phase5C4ControlRoleError, SQLAlchemyError):
        raise SystemExit("Stage 5C4.3 control role operation failed") from None
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    main()
