from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from app.core.database_identity import database_connect_args
from app.operators.historical_recipe_bridge import establish_conversion_clone_marker
from app.operators.phase5c_contracts import (
    DEFAULT_ARCHIVE_SCHEMA,
    Phase5CAdmissionError,
    canonical_json,
    load_inventory_file,
)
from app.operators.phase5c_isolation import load_operator_attestation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record non-destructive admission evidence on a conversion clone."
    )
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--archive-schema", default=DEFAULT_ARCHIVE_SCHEMA)
    parser.add_argument("--clone-marker-id", required=True)
    parser.add_argument("--conversion-clone-id", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    database_url = os.environ.get("NUTRITION_DATABASE_URL")
    if not database_url:
        raise SystemExit(
            "NUTRITION_DATABASE_URL must be explicitly set for clone-marker preflight"
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
            marker = establish_conversion_clone_marker(
                engine,
                inventory_payload=inventory,
                archive_schema=args.archive_schema,
                clone_marker_identity=args.clone_marker_id,
                conversion_clone_id=args.conversion_clone_id,
                attestation_payload=attestation,
            )
        finally:
            engine.dispose()
    except Phase5CAdmissionError as exc:
        raise SystemExit(str(exc)) from None
    except (ArgumentError, SQLAlchemyError, ValueError):
        raise SystemExit("Unable to establish the conversion-clone marker") from None
    sys.stdout.write(canonical_json(marker) + "\n")


if __name__ == "__main__":
    main()
