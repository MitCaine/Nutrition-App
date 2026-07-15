from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from app.core.database_identity import database_connect_args
from app.operators.historical_recipe_qualification import (
    Phase5CQualificationError,
    QualificationDiagnostic,
    load_execution_receipt_file,
    qualify_historical_recipe_conversion,
)
from app.operators.phase5c_contracts import (
    DEFAULT_ARCHIVE_SCHEMA,
    Phase5CAdmissionError,
    load_conversion_plan_file,
    load_inventory_file,
)
from app.operators.phase5c_isolation import load_operator_attestation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Independently qualify a completed Phase 5C conversion clone."
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--execution-receipt", type=Path, required=True)
    parser.add_argument("--clone-marker-id", required=True)
    parser.add_argument("--conversion-clone-id", required=True)
    parser.add_argument("--archive-schema", default=DEFAULT_ARCHIVE_SCHEMA)
    parser.add_argument("--format", choices=("human", "json"), default="human")
    parser.add_argument(
        "--diagnostic-only",
        action="store_true",
        help="Return a bounded non-qualification reason instead of a receipt.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    database_url = os.environ.get("NUTRITION_DATABASE_URL")
    if not database_url:
        raise SystemExit(
            "NUTRITION_DATABASE_URL must be explicitly set for conversion qualification"
        )
    engine = None
    try:
        plan = load_conversion_plan_file(args.plan)
        inventory = load_inventory_file(args.inventory)
        attestation = load_operator_attestation(args.attestation)
        execution_receipt = load_execution_receipt_file(args.execution_receipt)
        make_url(database_url)
        engine = create_engine(
            database_url,
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args=database_connect_args(database_url),
        )
        report = qualify_historical_recipe_conversion(
            engine,
            plan_payload=plan,
            inventory_payload=inventory,
            execution_attestation_payload=attestation,
            execution_receipt_payload=execution_receipt,
            archive_schema=args.archive_schema,
            conversion_clone_id=args.conversion_clone_id,
            clone_marker_identity=args.clone_marker_id,
        )
    except Phase5CQualificationError as exc:
        if not args.diagnostic_only:
            raise SystemExit(exc.reason_code) from None
        report = QualificationDiagnostic(exc.reason_code)
    except Phase5CAdmissionError:
        if not args.diagnostic_only:
            raise SystemExit("qualification_evidence_mismatch") from None
        report = QualificationDiagnostic("qualification_evidence_mismatch")
    except (ArgumentError, SQLAlchemyError, OSError, ValueError, json.JSONDecodeError):
        if not args.diagnostic_only:
            raise SystemExit("qualification_evidence_mismatch") from None
        report = QualificationDiagnostic("qualification_evidence_mismatch")
    except Exception:
        if not args.diagnostic_only:
            raise SystemExit("qualification_evidence_mismatch") from None
        report = QualificationDiagnostic("qualification_evidence_mismatch")
    finally:
        if engine is not None:
            engine.dispose()
    rendered = report.to_json() if args.format == "json" else report.to_human()
    sys.stdout.write(rendered + "\n")


if __name__ == "__main__":
    main()
