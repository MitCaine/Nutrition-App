"""Public record/prepare barriers for the explicitly selected engineering route."""
import argparse
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import task  # noqa: E402


def record():
    return (ROOT / 'engineering/tasks/ENGINEERING_TEMPLATE.md').read_text()


def test_engineering_record_is_explicit_and_not_capsule_alias(tmp_path, capsys):
    path = tmp_path / 'engineering.md'
    path.write_text(record())
    args = argparse.Namespace(task_record=path, route='engineering', repo_root=ROOT)
    assert task.command_validate_record(args) == 0
    assert '"route":"engineering"' in capsys.readouterr().out
    args.route = 'normal'
    with pytest.raises(task.TaskControllerError, match='TASK_RECORD_INVALID'):
        task.command_validate_record(args)


@pytest.mark.parametrize('section', ['Original requirements', 'Engineering decisions', 'Source boundaries',
                                     'Proof and sequencing', 'Closeout'])
def test_missing_commented_or_fenced_section_cannot_satisfy_plan(tmp_path, section):
    path = tmp_path / 'engineering.md'
    for replacement in ['', '<!-- ## ' + section + ' -->', '```\n## ' + section + '\n```']:
        path.write_text(record().replace('## ' + section, replacement))
        with pytest.raises(task.TaskControllerError, match='TASK_RECORD_INVALID'):
            task.command_validate_record(argparse.Namespace(task_record=path, route='engineering', repo_root=ROOT))


def test_engineering_prepare_refuses_before_git_without_real_record(monkeypatch, tmp_path):
    args = task.build_parser().parse_args(['--state-dir', str(tmp_path), 'prepare', '422',
        '--task-id', 'GH-422', '--route', 'engineering', '--allowed-path', 'x', '--profile', 'repository'])
    monkeypatch.setattr(task, 'git', lambda *a, **kw: pytest.fail('Invalid engineering preparation reached Git'))
    with pytest.raises(task.TaskControllerError, match='SELECTED_ROUTE_REQUIRES_TASK_RECORD'):
        task.command_prepare(args)
    assert not list(tmp_path.iterdir())


def test_engineering_duplicate_heading_refuses(tmp_path):
    path = tmp_path / 'engineering.md'
    path.write_text(record() + '\n## Engineering decisions\nContradictory second decision.\n')
    with pytest.raises(task.TaskControllerError, match='TASK_RECORD_INVALID'):
        task.command_validate_record(argparse.Namespace(task_record=path, route='engineering', repo_root=ROOT))


def test_engineering_prepare_persists_record_identity_and_preserves_existing_checkpoint(tmp_path, monkeypatch):
    import hashlib
    import json
    specification = tmp_path / 'plan.md'
    specification.write_text(record())
    args = task.build_parser().parse_args(['--repo-root', str(ROOT), '--state-dir', str(tmp_path / 'state'),
        'prepare', '422', '--task-id', 'GH-422', '--repository', 'MitCaine/Nutrition-App',
        '--route', 'engineering', '--task-record', str(specification), '--base-sha', 'a' * 40,
        '--allowed-path', 'scripts/worker_execution.py', '--profile', 'repository'])
    # Fixture transport supplies the authenticated main; the real preparation,
    # payload, lock, transaction and durable checkpoint code are exercised.
    monkeypatch.setattr(task, 'git', lambda *a, **kw: 'a' * 40)
    monkeypatch.setattr(task, 'require_trusted_main_controller', lambda *a, **kw: None)
    assert task.command_prepare(args) == 0
    checkpoint = tmp_path / 'state/issue-422.json'
    before = checkpoint.read_bytes()
    state = json.loads(before)
    assert state['phase'] == 'PREPARED' and state['authorization']['base_sha'] == 'a' * 40
    assert state['execution']['preparation_record'] == {
        'route': 'engineering', 'path': str(specification),
        'sha256': hashlib.sha256(specification.read_bytes()).hexdigest(),
    }
    with pytest.raises(task.TaskControllerError, match='TASK_STATE_EXISTS_PRESERVE_HISTORY'):
        task.command_prepare(args)
    assert checkpoint.read_bytes() == before
