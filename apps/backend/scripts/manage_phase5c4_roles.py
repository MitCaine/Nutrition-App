from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.core.database_identity import database_connect_args
from app.operators.phase5c_contracts import canonical_json
from app.operators.phase5c4_roles import (
    Phase5C4RoleError,
    close_runtime_maintenance,
    provision_role_policy,
    qualify_source_role_policy,
    restore_runtime_privileges,
    serialize_privilege_manifest,
    serialize_source_eligibility,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Provision or inspect the bounded Stage 5C4.2a PostgreSQL role policy."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("manifest", help="Print the canonical privilege manifest.")

    provision = subparsers.add_parser(
        "provision", help="Provision a disposable database using the bootstrap administrator."
    )
    provision.add_argument("--confirm-database", required=True)
    provision.add_argument(
        "--acknowledge-disposable",
        action="store_true",
        help="Acknowledge that the target is isolated/disposable and may be ownership-converted.",
    )

    qualify = subparsers.add_parser(
        "qualify", help="Emit canonical read-only source-eligibility evidence."
    )
    qualify.add_argument("--expected-state", choices=("normal", "maintenance"), default="normal")

    close = subparsers.add_parser(
        "close-maintenance", help="Revoke runtime writes/connect and drain sessions as operations."
    )
    close.add_argument("--confirm-database", required=True)
    close.add_argument("--quiet-period-seconds", type=float, default=2.0)
    close.add_argument("--drain-timeout-seconds", type=float, default=30.0)

    restore = subparsers.add_parser(
        "restore", help="Restore only the exact runtime privilege manifest as operations."
    )
    restore.add_argument("--confirm-database", required=True)
    return parser.parse_args()


def _database_url() -> str:
    database_url = os.environ.get("NUTRITION_DATABASE_URL")
    if not database_url:
        raise Phase5C4RoleError("NUTRITION_DATABASE_URL must be explicitly set")
    try:
        make_url(database_url)
    except (ArgumentError, TypeError, ValueError):
        raise Phase5C4RoleError("NUTRITION_DATABASE_URL is invalid") from None
    return database_url


def _engine(database_url: str):
    return create_engine(
        database_url,
        poolclass=NullPool,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args=database_connect_args(database_url),
    )


def _confirm_database(engine, expected: str) -> None:
    with engine.connect() as connection:
        actual = str(connection.scalar(text("SELECT current_database()")))
    if actual != expected:
        raise Phase5C4RoleError("Configured database does not match --confirm-database")


def main() -> None:
    args = parse_args()
    if args.command == "manifest":
        sys.stdout.write(serialize_privilege_manifest() + "\n")
        return

    engine = None
    try:
        engine = _engine(_database_url())
        if args.command in {"provision", "close-maintenance", "restore"}:
            _confirm_database(engine, args.confirm_database)
        if args.command == "provision":
            output = serialize_source_eligibility(
                provision_role_policy(
                    engine,
                    disposable=args.acknowledge_disposable,
                )
            )
        elif args.command == "qualify":
            with engine.connect() as connection:
                output = serialize_source_eligibility(
                    qualify_source_role_policy(
                        connection,
                        expected_state=args.expected_state,
                    )
                )
        elif args.command == "close-maintenance":
            output = canonical_json(
                close_runtime_maintenance(
                    engine,
                    quiet_period_seconds=args.quiet_period_seconds,
                    drain_timeout_seconds=args.drain_timeout_seconds,
                )
            )
        else:
            output = canonical_json(restore_runtime_privileges(engine))
    except Phase5C4RoleError as exc:
        raise SystemExit(str(exc)) from None
    except SQLAlchemyError:
        raise SystemExit("Stage 5C4.2a database operation failed") from None
    finally:
        if engine is not None:
            engine.dispose()
    sys.stdout.write(output + "\n")


if __name__ == "__main__":
    main()
