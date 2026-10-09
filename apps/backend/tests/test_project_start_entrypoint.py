from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _script(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#!/bin/bash\nset -eu\n' + text)
    path.chmod(0o755)


@pytest.fixture
def entrypoint(tmp_path: Path):
    """Actual entrypoint and helper; isolate only external service boundaries."""
    (tmp_path / 'scripts/lib').mkdir(parents=True)
    (tmp_path / 'apps/mobile').mkdir(parents=True)
    for name in ['scripts/start-project.sh', 'scripts/lib/project-process.sh']:
        shutil.copy2(ROOT / name, tmp_path / name)
    runtime = tmp_path / '.project-runtime'
    runtime.mkdir()
    (tmp_path / 'compose.yaml').write_text('services: {}\n')
    _script(tmp_path / 'scripts/stop-project.sh',
            'printf called > "$TEST_ROOT/stop-called"\nexit "${STOP_EXIT:-0}"\n')
    _script(tmp_path / 'scripts/start-backend.sh',
            'echo "Application startup complete"\nsleep 30\n')
    binary = tmp_path / 'bin'
    _script(binary / 'xcrun', '''
case "$*" in
  'simctl list devices available -j'|'simctl list devices -j')
    echo '{"devices":{"test":[{"name":"Test Phone","udid":"fixture-udid","isAvailable":true,"state":"Shutdown"}]}}' ;;
  *) printf '%s\\n' "$*" >> "$TEST_ROOT/xcrun-called"
     if [[ "${FAIL_BOOT:-0}" == 1 ]]; then exit 7; fi ;;
esac
''')
    _script(binary / 'open', 'printf called > "$TEST_ROOT/open-called"\n')
    _script(binary / 'npm', 'exit 0\n')
    _script(binary / 'npx', 'echo "Build Succeeded"\nsleep 30\n')
    env = {**os.environ, 'PATH': f'{binary}:{os.environ["PATH"]}',
           'TEST_ROOT': str(tmp_path), 'SIMULATOR_NAME': 'Test Phone'}
    yield tmp_path, env
    # Only this harness's deliberately launched fixture PIDs, never real services.
    for record in runtime.glob('*.pid'):
        text = record.read_text() if record.is_file() else ''
        if text.startswith('fixture-pid='):
            pid = int(text.split('=', 1)[1])
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


def _start(root: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(['bash', 'scripts/start-project.sh'], cwd=root, env=env,
                          capture_output=True, text=True, timeout=10)


def _snapshot(root: Path) -> dict[str, bytes | str]:
    return {str(p.relative_to(root)): os.readlink(p) if p.is_symlink() else p.read_bytes()
            for p in root.rglob('*') if p.is_file() or p.is_symlink()}


@pytest.mark.parametrize('marker', [
    'backend.pid', 'expo.pid', 'simulator-udid', 'simulator-started',
])
@pytest.mark.parametrize('kind', ['malformed', 'empty', 'dangling-link'])
def test_duplicate_start_preserves_all_prior_session_state(entrypoint, marker, kind):
    root, env = entrypoint
    runtime = root / '.project-runtime'
    (runtime / 'backend.log').write_text('prior backend log\n')
    (runtime / 'expo.log').write_text('prior expo log\n')
    target = runtime / marker
    if kind == 'dangling-link':
        target.symlink_to('missing-prior-record')
    else:
        target.write_text('ambiguous prior ownership\n' if kind == 'malformed' else '')
    before = _snapshot(root)
    result = _start(root, env)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'Existing project session record' in result.stderr
    assert _snapshot(root) == before
    assert not (root / 'stop-called').exists()
    assert not (root / 'xcrun-called').exists()
    assert not (root / 'open-called').exists()


def test_duplicate_start_preserves_native_owned_and_unrelated_processes(entrypoint):
    root, env = entrypoint
    process = subprocess.Popen([sys.executable, '-c',
                                'import time; marker="expo run:ios"; time.sleep(30)'])
    unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    try:
        helper = shlex.quote(str(root / 'scripts/lib/project-process.sh'))
        record = shlex.quote(str(root / '.project-runtime/expo.pid'))
        written = subprocess.run(['bash', '-c',
                                  f'source {helper}; project_process_write_record {record} expo {process.pid}'],
                                 capture_output=True, text=True)
        assert written.returncode == 0, written.stdout + written.stderr
        before = _snapshot(root)
        result = _start(root, env)
        assert result.returncode == 1
        assert _snapshot(root) == before
        assert process.poll() is None and unrelated.poll() is None
    finally:
        for child in [process, unrelated]:
            child.terminate()
            child.wait(timeout=5)


def _fixture_records(root: Path) -> None:
    # Readiness and failure flow use synthetic identity, not a claim of native ownership.
    helper = root / 'scripts/lib/project-process.sh'
    helper.write_text(helper.read_text() + '''
project_process_write_record() { printf 'fixture-pid=%s' "$3" > "$1"; }
''')


def test_new_start_still_launches_services_and_disarms_cleanup(entrypoint):
    root, env = entrypoint
    _fixture_records(root)
    result = _start(root, env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Nutrition App started.' in result.stdout
    assert (root / '.project-runtime/backend.pid').read_text().startswith('fixture-pid=')
    assert (root / '.project-runtime/expo.pid').read_text().startswith('fixture-pid=')
    assert (root / '.project-runtime/simulator-started').exists()
    assert not (root / 'stop-called').exists()


def test_partial_start_failure_still_calls_cleanup_and_returns_failure(entrypoint):
    root, env = entrypoint
    result = _start(root, {**env, 'FAIL_BOOT': '1', 'STOP_EXIT': '9'})
    assert result.returncode == 7, result.stdout + result.stderr
    assert 'Startup failed.' in result.stdout
    assert (root / 'stop-called').exists()
    assert not (root / '.project-runtime/backend.pid').exists()
    assert 'Nutrition App started.' not in result.stdout


def test_actual_stop_caller_preserves_state_when_helper_reports_incomplete_cleanup(entrypoint):
    root, env = entrypoint
    shutil.copy2(ROOT / 'scripts/stop-project.sh', root / 'scripts/stop-project.sh')
    helper = root / 'scripts/lib/project-process.sh'
    helper.write_text(helper.read_text() + '''
project_process_stop_from_record() {
  echo 'Incomplete cleanup: ownership could not be established.' >&2
  return 1
}
''')
    (root / '.project-runtime/expo.pid').write_text('ambiguous prior record\n')
    (root / '.project-runtime/simulator-udid').write_text('prior-simulator\n')
    (root / '.project-runtime/simulator-started').touch()
    before = _snapshot(root)
    result = subprocess.run(['bash', 'scripts/stop-project.sh'], cwd=root, env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert 'Incomplete cleanup' in result.stderr
    assert 'project services stopped.' not in result.stdout
    assert _snapshot(root) == before


def test_actual_stop_caller_stops_only_native_owned_process(entrypoint):
    root, env = entrypoint
    shutil.copy2(ROOT / 'scripts/stop-project.sh', root / 'scripts/stop-project.sh')
    _script(root / 'bin/docker', 'exit 1\n')
    process = subprocess.Popen([sys.executable, '-c',
                                'import time; marker="expo run:ios"; time.sleep(30)'])
    unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    try:
        helper = shlex.quote(str(root / 'scripts/lib/project-process.sh'))
        record = shlex.quote(str(root / '.project-runtime/expo.pid'))
        written = subprocess.run(['bash', '-c',
                                  f'source {helper}; project_process_write_record {record} expo {process.pid}'],
                                 capture_output=True, text=True)
        assert written.returncode == 0, written.stdout + written.stderr
        result = subprocess.run(['bash', 'scripts/stop-project.sh'], cwd=root,
                                env={**env, 'PROJECT_PROCESS_GRACE_SECONDS': '1'},
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stdout + result.stderr
        process.wait(timeout=5)
        assert process.returncode == -signal.SIGTERM
        assert unrelated.poll() is None
        assert 'Docker is unavailable' in result.stdout
    finally:
        for child in [process, unrelated]:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=5)
