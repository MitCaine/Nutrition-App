from __future__ import annotations

import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PROCESS_HELPER = (
    REPOSITORY_ROOT
    / "scripts"
    / "lib"
    / "project-process.sh"
)


def _bash(
    body: str,
    *,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()

    if environment:
        env.update(environment)

    script = (
        "set -Eeuo pipefail\n"
        f"source {shlex.quote(str(PROCESS_HELPER))}\n"
        f"{body}\n"
    )

    return subprocess.run(
        ["bash", "-c", script],
        cwd=REPOSITORY_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def disposable_processes() -> list[subprocess.Popen[bytes]]:
    processes: list[subprocess.Popen[bytes]] = []

    yield processes

    for process in reversed(processes):
        if process.poll() is None:
            process.kill()

        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _start_python(
    processes: list[subprocess.Popen[bytes]],
    code: str,
) -> subprocess.Popen[bytes]:
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            code,
        ],
        cwd=REPOSITORY_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    processes.append(process)

    time.sleep(0.15)

    assert process.poll() is None

    return process


def _start_identity(pid: int) -> str:
    result = _bash(
        'project_process_start_identity "$TARGET_PID"',
        environment={
            "TARGET_PID": str(pid),
        },
    )

    assert result.returncode == 0, result.stderr

    identity = result.stdout.strip()

    assert identity

    return identity


def _write_expo_record(
    record: Path,
    pid: int,
) -> None:
    result = _bash(
        'project_process_write_record "$RECORD" expo "$TARGET_PID"',
        environment={
            "RECORD": str(record),
            "TARGET_PID": str(pid),
        },
    )

    assert result.returncode == 0, (
        result.stdout,
        result.stderr,
    )


def _process_identity_still_matches(
    pid: int,
    start_identity: str,
) -> bool:
    result = _bash(
        (
            'project_process_identity_matches '
            '"$TARGET_PID" "$TARGET_START"'
        ),
        environment={
            "TARGET_PID": str(pid),
            "TARGET_START": start_identity,
        },
    )

    return result.returncode == 0


def test_process_record_contains_versioned_identity_and_command_contract(
    tmp_path: Path,
    disposable_processes: list[subprocess.Popen[bytes]],
) -> None:
    process = _start_python(
        disposable_processes,
        (
            'import time; '
            'marker = "expo run:ios"; '
            "time.sleep(60)"
        ),
    )

    record = tmp_path / "expo.pid"

    _write_expo_record(
        record,
        process.pid,
    )

    fields = dict(
        line.split("=", 1)
        for line in record.read_text(
            encoding="utf-8",
        ).splitlines()
    )

    assert fields["format"] == "nutrition-project-process-v1"
    assert fields["service"] == "expo"
    assert fields["pid"] == str(process.pid)
    assert fields["start"]
    assert fields["contract"] == "expo-ios-v1"
    assert "expo run:ios" in fields["command"]

    status = _bash(
        (
            'project_process_record_status "$RECORD" expo\n'
            'printf "%s\\n" "$PROJECT_PROCESS_STATUS_REASON"'
        ),
        environment={
            "RECORD": str(record),
        },
    )

    assert status.returncode == 0, status.stderr
    assert status.stdout.strip() == "owned"


def test_recycled_pid_start_identity_mismatch_is_never_signaled(
    tmp_path: Path,
    disposable_processes: list[subprocess.Popen[bytes]],
) -> None:
    process = _start_python(
        disposable_processes,
        (
            'import time; '
            'marker = "expo run:ios"; '
            "time.sleep(60)"
        ),
    )

    record = tmp_path / "expo.pid"

    _write_expo_record(
        record,
        process.pid,
    )

    lines = record.read_text(
        encoding="utf-8",
    ).splitlines()

    record.write_text(
        "\n".join(
            (
                "start=Thu Jan  1 00:00:00 1970"
                if line.startswith("start=")
                else line
            )
            for line in lines
        )
        + "\n",
        encoding="utf-8",
    )

    stopped = _bash(
        (
            'project_process_stop_from_record '
            '"$RECORD" expo "Expo"'
        ),
        environment={
            "RECORD": str(record),
            "PROJECT_PROCESS_GRACE_SECONDS": "1",
        },
    )

    assert stopped.returncode == 0, stopped.stderr
    assert "Refusing to signal Expo" in stopped.stdout
    assert "different process-start identity" in stopped.stdout
    assert process.poll() is None
    assert not record.exists()


def test_command_contract_mismatch_is_never_signaled(
    tmp_path: Path,
    disposable_processes: list[subprocess.Popen[bytes]],
) -> None:
    process = _start_python(
        disposable_processes,
        "import time; time.sleep(60)",
    )

    start_identity = _start_identity(
        process.pid,
    )

    record = tmp_path / "expo.pid"

    record.write_text(
        "\n".join(
            [
                "format=nutrition-project-process-v1",
                "service=expo",
                f"pid={process.pid}",
                f"start={start_identity}",
                "contract=expo-ios-v1",
                "command=npx expo run:ios --device Test",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    stopped = _bash(
        (
            'project_process_stop_from_record '
            '"$RECORD" expo "Expo"'
        ),
        environment={
            "RECORD": str(record),
            "PROJECT_PROCESS_GRACE_SECONDS": "1",
        },
    )

    assert stopped.returncode == 0, stopped.stderr
    assert "Refusing to signal Expo" in stopped.stdout
    assert "does not match the recorded service command contract" in (
        stopped.stdout
    )
    assert process.poll() is None


@pytest.mark.parametrize(
    "record_body",
    [
        "12345\n",
        "format=nutrition-project-process-v1\npid=12345\n",
        (
            "format=wrong-format\n"
            "service=expo\n"
            "pid=12345\n"
            "start=x\n"
            "contract=expo-ios-v1\n"
            "command=npx expo run:ios\n"
        ),
    ],
)
def test_legacy_and_malformed_records_cannot_authorize_signals(
    tmp_path: Path,
    record_body: str,
) -> None:
    record = tmp_path / "expo.pid"
    record.write_text(
        record_body,
        encoding="utf-8",
    )

    stopped = _bash(
        (
            'project_process_stop_from_record '
            '"$RECORD" expo "Expo"'
        ),
        environment={
            "RECORD": str(record),
        },
    )

    assert stopped.returncode == 0, stopped.stderr
    assert "untrusted process record" in stopped.stdout
    assert not record.exists()


def test_already_exited_record_is_removed_without_signal(
    tmp_path: Path,
    disposable_processes: list[subprocess.Popen[bytes]],
) -> None:
    process = _start_python(
        disposable_processes,
        (
            'import time; '
            'marker = "expo run:ios"; '
            "time.sleep(60)"
        ),
    )

    record = tmp_path / "expo.pid"

    _write_expo_record(
        record,
        process.pid,
    )

    process.terminate()
    process.wait(timeout=5)

    stopped = _bash(
        (
            'project_process_stop_from_record '
            '"$RECORD" expo "Expo"'
        ),
        environment={
            "RECORD": str(record),
        },
    )

    assert stopped.returncode == 0, stopped.stderr
    assert "process record is stale" in stopped.stdout
    assert "no longer running" in stopped.stdout
    assert not record.exists()


def test_backend_command_contract_accepts_shell_and_uvicorn_transition() -> None:
    result = _bash(
        """
project_process_command_matches_contract \
  backend-v1 \
  "/bin/bash /repo/scripts/start-backend.sh"

project_process_command_matches_contract \
  backend-v1 \
  "/repo/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0"

if project_process_command_matches_contract \
    backend-v1 \
    "/usr/bin/python unrelated.py"
then
  exit 9
fi
"""
    )

    assert result.returncode == 0, (
        result.stdout,
        result.stderr,
    )


def test_startup_rejects_owned_record_and_cleans_untrusted_record(
    tmp_path: Path,
    disposable_processes: list[subprocess.Popen[bytes]],
) -> None:
    process = _start_python(
        disposable_processes,
        (
            'import time; '
            'marker = "expo run:ios"; '
            "time.sleep(60)"
        ),
    )

    record = tmp_path / "expo.pid"

    _write_expo_record(
        record,
        process.pid,
    )

    owned = _bash(
        """
set +e
project_process_prepare_start_record \
  "$RECORD" \
  expo \
  "Expo"
rc=$?
set -e
printf "rc=%s\\n" "$rc"
exit 0
""",
        environment={
            "RECORD": str(record),
        },
    )

    assert owned.returncode == 0, owned.stderr
    assert "rc=1" in owned.stdout
    assert "already running" in owned.stdout
    assert record.exists()

    text = record.read_text(
        encoding="utf-8",
    )

    text = text.replace(
        "start=",
        "start=Thu Jan  1 00:00:00 1970\noriginal-start=",
        1,
    )

    record.write_text(
        text,
        encoding="utf-8",
    )

    cleaned = _bash(
        (
            'project_process_prepare_start_record '
            '"$RECORD" expo "Expo"'
        ),
        environment={
            "RECORD": str(record),
        },
    )

    assert cleaned.returncode == 0, cleaned.stderr
    assert "without signaling" in cleaned.stdout
    assert not record.exists()
    assert process.poll() is None


def test_verified_process_stops_gracefully(
    disposable_processes: list[subprocess.Popen[bytes]],
) -> None:
    process = _start_python(
        disposable_processes,
        "import time; time.sleep(60)",
    )

    start_identity = _start_identity(
        process.pid,
    )

    stopped = _bash(
        (
            'project_process_stop_identity_tree '
            '"$TARGET_PID" "$TARGET_START" "disposable"'
        ),
        environment={
            "TARGET_PID": str(process.pid),
            "TARGET_START": start_identity,
            "PROJECT_PROCESS_GRACE_SECONDS": "1",
        },
    )

    assert stopped.returncode == 0, stopped.stderr

    process.wait(timeout=5)

    assert "Stopping disposable PID" in stopped.stdout
    assert process.returncode == -signal.SIGTERM


def test_verified_process_uses_force_only_after_revalidation(
    disposable_processes: list[subprocess.Popen[bytes]],
) -> None:
    process = _start_python(
        disposable_processes,
        (
            "import signal, time; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "time.sleep(60)"
        ),
    )

    start_identity = _start_identity(
        process.pid,
    )

    stopped = _bash(
        (
            'project_process_stop_identity_tree '
            '"$TARGET_PID" "$TARGET_START" "disposable"'
        ),
        environment={
            "TARGET_PID": str(process.pid),
            "TARGET_START": start_identity,
            "PROJECT_PROCESS_GRACE_SECONDS": "1",
        },
    )

    assert stopped.returncode == 0, stopped.stderr

    process.wait(timeout=5)

    assert "validating identity before SIGKILL" in stopped.stdout
    assert process.returncode == -signal.SIGKILL


def test_force_kill_refuses_changed_start_identity(
    disposable_processes: list[subprocess.Popen[bytes]],
) -> None:
    process = _start_python(
        disposable_processes,
        "import time; time.sleep(60)",
    )

    result = _bash(
        """
set +e
project_process_force_kill_if_same_identity \
  "$TARGET_PID" \
  "Thu Jan  1 00:00:00 1970" \
  "disposable"
rc=$?
set -e
printf "rc=%s\\n" "$rc"
exit 0
""",
        environment={
            "TARGET_PID": str(process.pid),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "rc=1" in result.stdout
    assert "Refusing to signal" in result.stdout
    assert process.poll() is None


def test_verified_child_tree_is_stopped_by_captured_start_identity(
    tmp_path: Path,
    disposable_processes: list[subprocess.Popen[bytes]],
) -> None:
    child_file = tmp_path / "child.pid"

    parent_code = (
        "from pathlib import Path; "
        "import subprocess, sys, time; "
        f"p = subprocess.Popen([sys.executable, '-c', "
        f"'import time; time.sleep(60)']); "
        f"Path({str(child_file)!r}).write_text(str(p.pid)); "
        "p.wait(); "
        "time.sleep(60)"
    )

    parent = _start_python(
        disposable_processes,
        parent_code,
    )

    deadline = time.time() + 5

    while (
        not child_file.exists()
        and time.time() < deadline
    ):
        time.sleep(0.05)

    assert child_file.exists()

    child_pid = int(
        child_file.read_text(
            encoding="utf-8",
        )
    )

    parent_start = _start_identity(
        parent.pid,
    )

    child_start = _start_identity(
        child_pid,
    )

    stopped = _bash(
        (
            'project_process_stop_identity_tree '
            '"$TARGET_PID" "$TARGET_START" "parent"'
        ),
        environment={
            "TARGET_PID": str(parent.pid),
            "TARGET_START": parent_start,
            "PROJECT_PROCESS_GRACE_SECONDS": "1",
        },
    )

    assert stopped.returncode == 0, stopped.stderr

    parent.wait(timeout=5)

    assert not _process_identity_still_matches(
        child_pid,
        child_start,
    )


def test_ps_start_and_command_identity_are_stable_for_disposable_process(
    disposable_processes: list[subprocess.Popen[bytes]],
) -> None:
    process = _start_python(
        disposable_processes,
        "import time; time.sleep(60)",
    )

    first = _bash(
        """
project_process_capture_identity "$TARGET_PID"
printf "%s\\n" "$PROJECT_PROCESS_CAPTURE_START_IDENTITY"
printf "%s\\n" "$PROJECT_PROCESS_CAPTURE_PPID"
printf "%s\\n" "$PROJECT_PROCESS_CAPTURE_COMMAND"
""",
        environment={
            "TARGET_PID": str(process.pid),
        },
    )

    time.sleep(0.2)

    second = _bash(
        """
project_process_capture_identity "$TARGET_PID"
printf "%s\\n" "$PROJECT_PROCESS_CAPTURE_START_IDENTITY"
printf "%s\\n" "$PROJECT_PROCESS_CAPTURE_PPID"
printf "%s\\n" "$PROJECT_PROCESS_CAPTURE_COMMAND"
""",
        environment={
            "TARGET_PID": str(process.pid),
        },
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr

    first_lines = first.stdout.splitlines()
    second_lines = second.stdout.splitlines()

    assert len(first_lines) == 3
    assert len(second_lines) == 3
    assert all(first_lines)
    assert first_lines == second_lines
