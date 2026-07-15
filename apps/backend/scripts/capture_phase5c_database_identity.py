from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from app.core.database_identity import database_connect_args
from app.operators.phase5c_contracts import Phase5CAdmissionError
from app.operators.phase5c_isolation import safe_identity_json


def main() -> None:
    database_url = os.environ.get("NUTRITION_DATABASE_URL")
    if not database_url:
        raise SystemExit(
            "NUTRITION_DATABASE_URL must be explicitly set for safe identity capture"
        )
    try:
        make_url(database_url)
        engine = create_engine(
            database_url,
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args=database_connect_args(database_url),
        )
        try:
            output = safe_identity_json(engine)
        finally:
            engine.dispose()
    except Phase5CAdmissionError as exc:
        raise SystemExit(str(exc)) from None
    except (ArgumentError, SQLAlchemyError, ValueError):
        raise SystemExit("Unable to capture the configured safe database identity") from None
    sys.stdout.write(output + "\n")


if __name__ == "__main__":
    main()
