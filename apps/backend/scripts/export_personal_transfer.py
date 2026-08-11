#!/usr/bin/env python3
"""Thin operator CLI for the one-time E2-15 personal transfer."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.transfer.e2_15_exporter import TransferExportError, export_personal_transfer


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export one owner to an E2-15 transfer package.")
    parser.add_argument("--owner-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--acknowledge-frozen-writes",
        action="store_true",
        help="Confirm application writes are stopped for the point-in-time cutover.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    database_url = os.environ.get("NUTRITION_DATABASE_URL")
    if not database_url:
        _parser().error("NUTRITION_DATABASE_URL is required")
    try:
        result = export_personal_transfer(
            database_url,
            args.owner_id,
            args.output,
            frozen_writes_acknowledged=args.acknowledge_frozen_writes,
        )
    except TransferExportError as error:
        print(json.dumps({"code": error.code, "status": "failed"}, sort_keys=True))
        return 1
    print(
        json.dumps(
            {
                "byte_count": result.byte_count,
                "format_version": "1",
                "overall_digest": result.overall_digest,
                "schema_contract": "e2-15.pg-0025.v1",
                "section_counts": dict(result.section_counts),
                "status": "complete",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
