from __future__ import annotations

import argparse
import json
from uuid import UUID

from app.core.database import SessionLocal
from app.services.recipe_revision_capture_service import CaptureReport, RecipeRevisionCaptureService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Classify legacy Recipe projections and capture eligible transition baselines."
    )
    parser.add_argument(
        "--recipe-id",
        type=UUID,
        help="Inspect or capture one Recipe instead of all Recipes.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist eligible captures. Without this flag the command is a dry run.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dry_run = not args.apply
    with SessionLocal() as db:
        service = RecipeRevisionCaptureService(db)
        if args.recipe_id is None:
            report = service.capture_all(dry_run=dry_run)
        else:
            result = service.capture_one(args.recipe_id, dry_run=dry_run)
            report = CaptureReport(dry_run=dry_run, results=(result,))
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
