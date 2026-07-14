from __future__ import annotations

import argparse
import json
from uuid import UUID

from app.core.database import SessionLocal
from app.services.retention_audit_service import RetentionAuditService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only Recipe publication revision and projection retention audit."
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--user-id", type=UUID, help="Audit one explicit owner boundary.")
    scope.add_argument(
        "--all-users",
        action="store_true",
        help="Run the explicit operator-wide audit, preserving per-row owner boundaries.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with SessionLocal() as db:
        service = RetentionAuditService(db)
        report = (
            service.audit_operator()
            if args.all_users
            else service.audit_owner(args.user_id)
        )
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
