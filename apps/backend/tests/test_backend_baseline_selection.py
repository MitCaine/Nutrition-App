from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPOSITORY_ROOT / "apps" / "backend"
BASELINE_RUNNER = REPOSITORY_ROOT / "scripts" / "run-backend-baseline.sh"

OPT_IN_MARKERS = (
    "postgres_concurrency",
    "phase5c_performance_t0",
    "phase5c4_control_postgres",
    "phase5c4_minio",
    "phase5c4_docker_integration",
)

EXPECTED_MARKER_EXPRESSION = " and ".join(
    f"not {marker}" for marker in OPT_IN_MARKERS
)


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTEST_ADDOPTS", None)
    environment["NUTRITION_BACKEND_PYTHON"] = sys.executable
    return environment


def _run_runner(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(BASELINE_RUNNER), *arguments],
        cwd=REPOSITORY_ROOT,
        env=_environment(),
        capture_output=True,
        text=True,
        check=False,
    )


def _run_pytest(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", *arguments],
        cwd=BACKEND_ROOT,
        env=_environment(),
        capture_output=True,
        text=True,
        check=False,
    )


def _node_ids(output: str) -> tuple[str, ...]:
    return tuple(
        line.strip()
        for line in output.splitlines()
        if line.startswith("tests/") and "::" in line
    )


def test_baseline_runner_declares_exact_opt_in_exclusion() -> None:
    result = _run_runner("--print-marker-expression")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == EXPECTED_MARKER_EXPRESSION


def test_baseline_runner_collection_matches_canonical_expression() -> None:
    via_runner = _run_runner("--collect-only", "-q")
    direct = _run_pytest(
        "--collect-only",
        "-q",
        "-m",
        EXPECTED_MARKER_EXPRESSION,
    )

    assert via_runner.returncode == 0, via_runner.stderr
    assert direct.returncode == 0, direct.stderr
    assert _node_ids(via_runner.stdout)
    assert _node_ids(via_runner.stdout) == _node_ids(direct.stdout)


@pytest.mark.parametrize("marker", OPT_IN_MARKERS)
def test_opt_in_marker_remains_explicitly_selectable(marker: str) -> None:
    selected = _run_pytest("--collect-only", "-q", "-m", marker)

    assert selected.returncode == 0, selected.stderr
    assert _node_ids(selected.stdout), (
        f"expected explicit selection for {marker} to collect tests"
    )
