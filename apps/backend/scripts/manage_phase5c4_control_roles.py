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
    provision_control_roles,
    qualify_control_roles,
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
    for name in ("provision", "qualify"):
        command = subparsers.add_parser(name)
        command.add_argument("--confirm-database", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "manifest":
        sys.stdout.write(serialize_privilege_manifest() + "\n")
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
        else:
            result = qualify_control_roles(engine, expected_database=args.confirm_database)
        sys.stdout.write(canonical_json(result) + "\n")
    except (Phase5C4ControlRoleError, SQLAlchemyError):
        raise SystemExit("Stage 5C4.3 control role operation failed") from None
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    main()
