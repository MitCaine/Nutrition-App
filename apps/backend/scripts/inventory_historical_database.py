from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from app.core.database_identity import database_connect_args
from app.operators.historical_database_inventory import inventory_database


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only aggregate inventory of historical database state."
    )
    parser.add_argument(
        "--format",
        choices=("human", "json"),
        default="human",
        help="Output format (default: human).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    database_url = os.environ.get("NUTRITION_DATABASE_URL")
    if not database_url:
        raise SystemExit(
            "NUTRITION_DATABASE_URL must be explicitly set for historical inventory"
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
            report = inventory_database(engine)
        finally:
            engine.dispose()
    except (ArgumentError, SQLAlchemyError, ValueError):
        raise SystemExit("Unable to inspect the explicitly configured database") from None

    output = report.to_json() if args.format == "json" else report.to_human()
    sys.stdout.write(output + "\n")


if __name__ == "__main__":
    main()
