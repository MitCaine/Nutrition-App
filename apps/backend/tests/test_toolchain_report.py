from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "toolchain-report.py"

SPEC = importlib.util.spec_from_file_location("nutrition_toolchain_report", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
TOOLCHAINS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOLCHAINS
SPEC.loader.exec_module(TOOLCHAINS)


@pytest.mark.parametrize(
    ("actual", "expected", "matches"),
    [
        ("24.19.0", "24", True),
        ("v24.19.0", "24", True),
        ("3.12.13", "3.12", True),
        ("3.13.0", "3.12", False),
        ("26.5.0", "24", False),
    ],
)
def test_version_matches_repository_prefix(
    actual: str,
    expected: str,
    matches: bool,
) -> None:
    assert TOOLCHAINS.version_matches(actual, expected) is matches


def test_version_file_rejects_non_numeric_specs(tmp_path: Path) -> None:
    version_file = tmp_path / ".nvmrc"
    version_file.write_text("lts/*\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported version specification"):
        TOOLCHAINS.read_version_spec(version_file)


def test_check_toolchains_blocks_mismatch_and_unavailable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = {
        "python": {
            "expected": "3.12",
            "actual": "3.12.13",
            "available": True,
            "matches": True,
            "path": "/usr/bin/python3",
        },
        "node": {
            "expected": "24",
            "actual": "26.5.0",
            "available": True,
            "matches": False,
            "path": "/usr/bin/node",
        },
    }

    assert TOOLCHAINS.check_toolchains(payload, ("python", "node")) == 1
    output = capsys.readouterr().out
    assert "PASS python" in output
    assert "ERROR TOOLCHAIN_MISMATCH: node 26.5.0, expected 24" in output


def test_report_warns_when_node_is_unavailable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = {
        "python": {
            "expected": "3.12",
            "actual": "3.12.13",
            "available": True,
            "matches": True,
            "path": "/usr/bin/python3",
        },
        "node": {
            "expected": "24",
            "actual": None,
            "available": False,
            "matches": False,
            "path": None,
        },
    }

    TOOLCHAINS.print_report(payload)
    output = capsys.readouterr().out
    assert "WARN TOOLCHAIN_UNAVAILABLE: node expected 24, command unavailable" in output
