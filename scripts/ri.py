#!/usr/bin/env python3
"""Pinned controller-only Repository Intelligence installation and navigation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib import ri_consumer as ri


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("bootstrap", help="Offline install from authorized private archive and pinned public wheels")
    install.add_argument("--source-archive", type=Path, required=True)
    install.add_argument("--wheelhouse", type=Path, required=True)
    install.add_argument("--destination", type=Path, required=True)
    inspect = commands.add_parser("verify", help="Revalidate controller-owned installed bytes and contracts")
    inspect.add_argument("--runtime", type=Path, required=True)
    query = commands.add_parser("query", help="Navigate exact committed source; never grants edit authority")
    query.add_argument("--repo-root", type=Path, default=ri.ROOT)
    query.add_argument("--revision", required=True)
    selection = query.add_mutually_exclusive_group(required=True)
    selection.add_argument("--scope", choices=sorted(ri.SCOPES))
    selection.add_argument("--path", action="append")
    query.add_argument("--query", required=True)
    query.add_argument("--limit", type=int, default=8)
    query.add_argument("--runtime", type=Path, required=True)
    query.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "bootstrap":
            result = ri.bootstrap(args.source_archive, args.wheelhouse, args.destination)
            print(json.dumps({"revision": result["revision"], "manifest_sha256": result["manifest_sha256"],
                              "manifest": str(args.destination.resolve() / "manifest.json"), "offline": True}))
        elif args.command == "verify":
            result, _ = ri.verify_runtime(args.runtime)
            print(json.dumps({"revision": result["revision"], "manifest_sha256": result["manifest_sha256"], "result": "PASS"}))
        else:
            result = ri.navigate(args.repo_root, args.revision, ri.SCOPES[args.scope] if args.scope else args.path,
                                 args.query, args.limit, args.runtime, args.output_dir)
            print(json.dumps(result, indent=2))
            return 0 if result["mapping_status"] == "navigation_only" else 2
        return 0
    except (ri.RIError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"result": "STOP_REPLAN", "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
