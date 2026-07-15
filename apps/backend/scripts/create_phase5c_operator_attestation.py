from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from app.core.database_identity import database_connect_args
from app.operators.historical_recipe_bridge import SCHEMA_SIGNATURE_DIGEST
from app.operators.phase5c_contracts import (
    Phase5CAdmissionError,
    SUPPORTED_SCHEMA_SIGNATURE,
    canonical_digest,
    canonical_json,
    load_inventory_file,
)
from app.operators.phase5c_isolation import (
    build_operator_attestation,
    load_safe_database_identity,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create deterministic operator evidence for an isolated conversion clone."
    )
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--source-production-identity", type=Path, required=True)
    parser.add_argument("--operator-attestation-id", required=True)
    parser.add_argument(
        "--scope",
        choices=("bridge", "planning", "bridge_and_planning"),
        default="bridge_and_planning",
    )
    parser.add_argument("--clone-marker-id", required=True)
    parser.add_argument("--conversion-clone-id", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    database_url = os.environ.get("NUTRITION_DATABASE_URL")
    if not database_url:
        raise SystemExit(
            "NUTRITION_DATABASE_URL must be explicitly set for clone attestation"
        )
    try:
        inventory = load_inventory_file(args.inventory)
        source_identity = load_safe_database_identity(args.source_production_identity)
        make_url(database_url)
        engine = create_engine(
            database_url,
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args=database_connect_args(database_url),
        )
        try:
            with engine.connect() as connection:
                attestation = build_operator_attestation(
                    connection,
                    operator_attestation_identity=args.operator_attestation_id,
                    scope=args.scope,
                    clone_marker_identity=args.clone_marker_id,
                    conversion_clone_id=args.conversion_clone_id,
                    source_production_identity_digest=source_identity[
                        "identity_digest"
                    ],
                    inventory_digest=canonical_digest(inventory),
                    schema_signature=SUPPORTED_SCHEMA_SIGNATURE,
                    schema_signature_digest=SCHEMA_SIGNATURE_DIGEST,
                )
        finally:
            engine.dispose()
    except Phase5CAdmissionError as exc:
        raise SystemExit(str(exc)) from None
    except (ArgumentError, SQLAlchemyError, ValueError):
        raise SystemExit("Unable to attest the configured conversion clone") from None
    sys.stdout.write(canonical_json(attestation) + "\n")


if __name__ == "__main__":
    main()
