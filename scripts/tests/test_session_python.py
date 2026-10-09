"""Exercise public wrappers and real audit children with controlled executables."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / 'checkout'
    scripts = root / 'scripts'
    scripts.mkdir(parents=True)
    for name in ('session-start.sh', 'session-end.sh', 'project-audit.sh',
                 'selected-python.sh', 'toolchain-report.py', 'project-audit.py'):
        shutil.copy2(ROOT / 'scripts' / name, scripts / name)
    (root / '.python-version').write_text('.'.join(map(str, sys.version_info[:2])))
    (root / '.nvmrc').write_text('26')
    # Use actual audit child functions, with only unrelated repository checks
    # removed from this disposable wrapper fixture.
    audit = scripts / 'project-audit.py'
    text = audit.read_text().replace('raise SystemExit(main())', '''
    print(json.dumps({"audit_python": sys.executable}))
    raise SystemExit(validate_task_capsules() or focused_audit_tests(
        {"focused_audit_tests": ["apps/backend/test_child.py"]}))''')
    audit.write_text(text)
    (scripts / 'validate-task-capsules.py').write_text(
        'import sys,json; print(json.dumps({"capsule_python":sys.executable}))\n')
    backend = root / 'apps/backend'
    backend.mkdir(parents=True)
    (backend / 'test_child.py').write_text('''import sys,os,json
from pathlib import Path
def test_child():
    Path(os.environ['CHILD_IDENTITY']).write_text(json.dumps({'pytest_python':sys.executable}))
''')
    bins = tmp_path / 'bin'
    bins.mkdir()
    for name in ('bash', 'dirname'):
        (bins / name).symlink_to(shutil.which(name))
    (bins / 'python3').write_text('#!/bin/bash\necho PATH_PYTHON_CALLED >&2\nexit 91\n')
    (bins / 'python3').chmod(0o755)
    env = {**os.environ, 'PATH': str(bins), 'NUTRITION_DEPS_PYTHON': sys.executable,
           'CHILD_IDENTITY': str(tmp_path / 'child.json')}
    for key in ('GITHUB_ACTIONS', 'GITHUB_WORKSPACE', 'GITHUB_WORKFLOW_REF', 'PYTHONPATH'):
        env.pop(key, None)
    return root, env


@pytest.mark.parametrize('command', [
    ['session-start.sh'], ['session-start.sh', '--json'], ['session-end.sh'],
    ['project-audit.sh', 'pre-commit'], ['project-audit.sh', 'session', '--json'],
])
def test_wrappers_bind_configured_python_for_audit_and_children_without_node(checkout, command):
    root, env = checkout
    result = subprocess.run([str(root / 'scripts' / command[0]), *command[1:]],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PATH_PYTHON_CALLED' not in result.stdout + result.stderr
    assert json.loads(Path(env['CHILD_IDENTITY']).read_text())['pytest_python'] == sys.executable
    assert json.dumps({'audit_python': sys.executable}) in result.stdout
    assert json.dumps({'capsule_python': sys.executable}) in result.stdout
    assert 'PASS python:' in result.stderr
    if command == ['session-start.sh']:
        assert 'WARN TOOLCHAIN_UNAVAILABLE: node' in result.stdout


@pytest.mark.parametrize('command', [
    ['session-start.sh'], ['session-start.sh', '--json'], ['session-end.sh'],
    ['project-audit.sh', 'pre-commit'],
])
@pytest.mark.parametrize('failure', ['missing', 'unsuitable'])
def test_wrappers_refuse_before_audit_or_children(checkout, command, failure):
    root, env = checkout
    if failure == 'missing':
        env['NUTRITION_DEPS_PYTHON'] = str(root / 'missing-python')
    else:
        (root / '.python-version').write_text('99.99')
    result = subprocess.run([str(root / 'scripts' / command[0]), *command[1:]],
                            env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert 'SELECTED_PYTHON_UNAVAILABLE' in result.stderr if failure == 'missing' else 'TOOLCHAIN_MISMATCH' in result.stderr
    assert 'audit_python' not in result.stdout
    assert not Path(env['CHILD_IDENTITY']).exists()
    assert 'PATH_PYTHON_CALLED' not in result.stdout + result.stderr


def test_unset_selection_uses_path_python_and_standalone_report_is_diagnostic(checkout):
    root, env = checkout
    env.pop('NUTRITION_DEPS_PYTHON')
    path_python = Path(env['PATH']) / 'python3'
    path_python.unlink()
    path_python.write_text('#!/bin/bash\nexec "' + sys.executable + '" "$@"\n')
    path_python.chmod(0o755)
    result = subprocess.run([str(root / 'scripts/project-audit.sh'), 'session'],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    (root / '.python-version').write_text('99.99')
    diagnostic = subprocess.run([sys.executable, str(root / 'scripts/toolchain-report.py'), '--json'],
                                env=env, capture_output=True, text=True)
    assert diagnostic.returncode == 0
    assert json.loads(diagnostic.stdout)['python']['matches'] is False
