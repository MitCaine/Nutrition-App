from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from app.operators.historical_recipe_performance import (
    Phase5CPerformanceError,
    qualify_phase5c_performance,
)
from app.operators.phase5c_contracts import Phase5CAdmissionError
from app.operators.phase5c_performance_contracts import PERFORMANCE_TIERS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Qualify Phase 5C performance on an empty disposable PostgreSQL database."
        )
    )
    parser.add_argument("--tier", choices=PERFORMANCE_TIERS, required=True)
    parser.add_argument("--fixture-seed", type=int, required=True)
    parser.add_argument("--storage-environment", required=True)
    parser.add_argument("--cache-mode", choices=("cold", "warm"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm-disposable-database", required=True)
    parser.add_argument(
        "--opt-in-large-tier",
        action="store_true",
        help="Required for T1, T2, and T3 resource-intensive fixtures.",
    )
    parser.add_argument(
        "--available-memory-mib",
        type=int,
        help="Optional operator-supplied available memory when the OS cannot report it.",
    )
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    database_url = os.environ.get("NUTRITION_DATABASE_URL")
    if not database_url:
        raise SystemExit(
            "NUTRITION_DATABASE_URL must be explicitly set for performance qualification"
        )
    if args.output.exists():
        raise SystemExit("Performance qualification output path already exists")
    available_memory_bytes = None
    if args.available_memory_mib is not None:
        if args.available_memory_mib <= 0:
            raise SystemExit("Available memory must be a positive MiB value")
        available_memory_bytes = args.available_memory_mib * 1024 * 1024

    try:
        make_url(database_url)
        manifest = qualify_phase5c_performance(
            database_url=database_url,
            confirmed_database_name=args.confirm_disposable_database,
            tier=args.tier,
            fixture_seed=args.fixture_seed,
            storage_environment=args.storage_environment,
            cache_mode=args.cache_mode,
            allow_large_tier=args.opt_in_large_tier,
            available_memory_bytes=available_memory_bytes,
        )
        args.output.write_text(manifest.to_json() + "\n", encoding="utf-8")
    except Phase5CPerformanceError as exc:
        raise SystemExit(exc.reason_code) from None
    except Phase5CAdmissionError:
        raise SystemExit("performance_configuration_invalid") from None
    except (ArgumentError, SQLAlchemyError, OSError, TypeError, ValueError):
        raise SystemExit("performance_database_operation_failed") from None
    except Exception:
        raise SystemExit("performance_database_operation_failed") from None

    rendered = manifest.to_json() if args.format == "json" else manifest.to_human()
    sys.stdout.write(rendered + "\n")
    if manifest.payload["overall_result"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
