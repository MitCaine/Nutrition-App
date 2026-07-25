from __future__ import annotations

import argparse
import os
import sys

from app.operators.immutable_provenance_qualification import (
    ImmutableProvenanceQualificationError,
    admit_immutable_provenance_qualification,
    collect_immutable_provenance_qualification,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Independently qualify exact 0020 immutable provenance."
    )
    parser.add_argument(
        "--admit",
        action="store_true",
        help="Register the artifact through the separate control database API.",
    )
    return parser.parse_args()


def main() -> None:
    arguments = _arguments()
    database_url = os.environ.get("NUTRITION_DATABASE_URL")
    if not database_url:
        raise SystemExit(
            "NUTRITION_DATABASE_URL must be explicitly set for immutable "
            "provenance qualification"
        )
    control_url = os.environ.get("NUTRITION_PHASE5C4_CONTROL_DATABASE_URL")
    if arguments.admit and not control_url:
        raise SystemExit(
            "NUTRITION_PHASE5C4_CONTROL_DATABASE_URL must be explicitly set "
            "for admission"
        )
    try:
        qualification = collect_immutable_provenance_qualification(database_url)
        if arguments.admit:
            assert control_url is not None
            admit_immutable_provenance_qualification(control_url, qualification)
    except ImmutableProvenanceQualificationError:
        raise SystemExit("Immutable provenance qualification failed") from None
    sys.stdout.write(qualification.to_json() + "\n")


if __name__ == "__main__":
    main()
