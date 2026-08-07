#!/usr/bin/env python3
"""Report and verify repository-owned Python and Node toolchain versions."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILES = {
    "python": ROOT / ".python-version",
    "node": ROOT / ".nvmrc",
}


def read_version_spec(path: Path) -> str:
    value = path.read_text(encoding="utf-8").strip().removeprefix("v")
    if not value:
        raise ValueError(f"empty version file: {path}")
    if not re.fullmatch(r"\d+(?:\.\d+)*", value):
        raise ValueError(f"unsupported version specification {value!r} in {path}")
    return value


def version_matches(actual: str, expected: str) -> bool:
    actual_parts = actual.removeprefix("v").split(".")
    expected_parts = expected.removeprefix("v").split(".")
    return actual_parts[: len(expected_parts)] == expected_parts


def _node_version() -> tuple[str | None, str | None]:
    executable = shutil.which("node")
    if executable is None:
        return None, None
    result = subprocess.run(
        [executable, "--version"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None, executable
    value = result.stdout.strip().removeprefix("v")
    return value or None, executable


def collect_toolchains() -> dict[str, dict[str, Any]]:
    python_expected = read_version_spec(VERSION_FILES["python"])
    node_expected = read_version_spec(VERSION_FILES["node"])
    python_actual = ".".join(str(value) for value in sys.version_info[:3])
    node_actual, node_path = _node_version()
    return {
        "python": {
            "expected": python_expected,
            "actual": python_actual,
            "available": True,
            "matches": version_matches(python_actual, python_expected),
            "path": sys.executable,
        },
        "node": {
            "expected": node_expected,
            "actual": node_actual,
            "available": node_actual is not None,
            "matches": bool(node_actual and version_matches(node_actual, node_expected)),
            "path": node_path,
        },
    }


def print_report(payload: dict[str, dict[str, Any]]) -> None:
    print("Repository toolchain report")
    for name in ("python", "node"):
        record = payload[name]
        expected = record["expected"]
        actual = record["actual"] or "UNAVAILABLE"
        if record["matches"]:
            print(f"PASS {name}: {actual} (expected {expected})")
        elif not record["available"]:
            print(f"WARN TOOLCHAIN_UNAVAILABLE: {name} expected {expected}, command unavailable")
        else:
            print(f"WARN TOOLCHAIN_MISMATCH: {name} {actual}, expected {expected}")


def check_toolchains(
    payload: dict[str, dict[str, Any]], names: Sequence[str]
) -> int:
    failed: list[str] = []
    for name in names:
        record = payload[name]
        expected = record["expected"]
        actual = record["actual"] or "UNAVAILABLE"
        if record["matches"]:
            print(f"PASS {name}: {actual} matches {expected}")
        else:
            print(f"ERROR TOOLCHAIN_MISMATCH: {name} {actual}, expected {expected}")
            failed.append(name)
    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="print machine-readable state")
    mode.add_argument(
        "--check",
        choices=("python", "node", "all"),
        help="fail unless the selected toolchain matches its repository version file",
    )
    args = parser.parse_args(argv)

    try:
        payload = collect_toolchains()
    except (OSError, ValueError) as exc:
        print(f"ERROR TOOLCHAIN_CONFIG: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.check:
        names = ("python", "node") if args.check == "all" else (args.check,)
        return check_toolchains(payload, names)
    print_report(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
