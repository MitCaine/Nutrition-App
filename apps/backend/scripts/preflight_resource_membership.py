from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.core.database_identity import database_connect_args
from app.operators.resource_membership_preflight import (
    ResourceMembershipPreflightBlockedError,
    ResourceMembershipPreflightError,
    run_resource_membership_operator_preflight,
)


def main() -> None:
    database_url = os.environ.get("NUTRITION_DATABASE_URL")
    if not database_url:
        raise SystemExit(
            "NUTRITION_DATABASE_URL must be explicitly set for resource membership preflight"
        )
    try:
        url = make_url(database_url)
        if url.get_backend_name() != "postgresql":
            raise ValueError
        engine = create_engine(
            database_url,
            poolclass=NullPool,
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args=database_connect_args(database_url),
        )
        try:
            report = run_resource_membership_operator_preflight(engine)
        finally:
            engine.dispose()
    except ResourceMembershipPreflightBlockedError as exc:
        sys.stdout.write(exc.report.to_json() + "\n")
        raise SystemExit(2) from None
    except (ArgumentError, ResourceMembershipPreflightError, SQLAlchemyError, ValueError):
        raise SystemExit(
            "Unable to run resource membership preflight on the configured database"
        ) from None

    sys.stdout.write(report.to_json() + "\n")


if __name__ == "__main__":
    main()
