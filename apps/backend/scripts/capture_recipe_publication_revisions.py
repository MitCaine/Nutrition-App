from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from uuid import UUID

from app.core.database import SessionLocal
from app.services.recipe_revision_capture_service import (
    CAPTURE_APPLY_RETIRED_MESSAGE,
    CaptureReport,
    RecipeRevisionCaptureService,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect and classify legacy Recipe compatibility projections."
    )
    parser.add_argument(
        "--recipe-id",
        type=UUID,
        help="Inspect one Recipe instead of all Recipes.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Retired: apply mode is no longer supported.",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    if args.apply:
        print(CAPTURE_APPLY_RETIRED_MESSAGE, file=sys.stderr)
        raise SystemExit(2)

    with SessionLocal() as db:
        service = RecipeRevisionCaptureService(db)
        if args.recipe_id is None:
            report = service.capture_all()
        else:
            result = service.capture_one(args.recipe_id)
            report = CaptureReport(dry_run=True, results=(result,))
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
