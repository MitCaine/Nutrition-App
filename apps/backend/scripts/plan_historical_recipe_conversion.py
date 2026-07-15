from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from app.core.database_identity import database_connect_args
from app.operators.historical_recipe_planner import plan_historical_recipe_conversion
from app.operators.phase5c_contracts import (
    DEFAULT_ARCHIVE_SCHEMA,
    Phase5CAdmissionError,
    load_inventory_file,
)
from app.operators.phase5c_isolation import load_operator_attestation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan deterministic historical Recipe conversion without converting rows."
    )
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--archive-schema", default=DEFAULT_ARCHIVE_SCHEMA)
    parser.add_argument("--conversion-clone-id", required=True)
    parser.add_argument("--clone-marker-id", required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    database_url = os.environ.get("NUTRITION_DATABASE_URL")
    if not database_url:
        raise SystemExit(
            "NUTRITION_DATABASE_URL must be explicitly set for conversion planning"
        )
    try:
        inventory = load_inventory_file(args.inventory)
        attestation = load_operator_attestation(args.attestation)
        make_url(database_url)
        engine = create_engine(
            database_url,
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args=database_connect_args(database_url),
        )
        try:
            plan = plan_historical_recipe_conversion(
                engine,
                inventory_payload=inventory,
                archive_schema=args.archive_schema,
                conversion_clone_id=args.conversion_clone_id,
                clone_marker_identity=args.clone_marker_id,
                attestation_payload=attestation,
            )
        finally:
            engine.dispose()
    except Phase5CAdmissionError as exc:
        raise SystemExit(str(exc)) from None
    except (ArgumentError, SQLAlchemyError, ValueError):
        raise SystemExit("Unable to plan against the configured conversion clone") from None

    output = plan.to_json() if args.format == "json" else plan.to_human()
    sys.stdout.write(output + "\n")


if __name__ == "__main__":
    main()
