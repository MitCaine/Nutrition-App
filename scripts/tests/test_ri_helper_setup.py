"""Pinned setup source refusal; provisioning never adopts an existing environment."""
import importlib.util
import json
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[2]


def module():
    spec = importlib.util.spec_from_file_location('nutrition_helper_setup', ROOT / 'scripts/setup-ri-helpers.py')
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.mark.parametrize('fault', ['head', 'dirty', 'definition', 'source'])
def test_changed_source_is_rejected_before_install(tmp_path, monkeypatch, fault):
    value = module()
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'pyproject.toml').write_text('bound dependency definition')
    (source / 'helper.py').write_text('bound source')
    lock = {'revision': 'a' * 40,
            'pyproject_sha256': value.digest(source / 'pyproject.toml'),
            'source_files': {'helper.py': value.digest(source / 'helper.py')}}
    def git(args, **kw):
        return ('b' * 40 if fault == 'head' else 'a' * 40) if args[-1] == 'HEAD' else ('M helper.py' if fault == 'dirty' else '')
    monkeypatch.setattr(value.subprocess, 'check_output', git)
    if fault == 'definition':
        (source / 'pyproject.toml').write_text('changed')
    if fault == 'source':
        (source / 'helper.py').write_text('changed')
    with pytest.raises(ValueError, match='changed'):
        value.authenticate_source(source, lock)


def test_lock_does_not_duplicate_upstream_dependency_inventory():
    lock = json.loads((ROOT / 'engineering/tooling/ri-helper-lock.json').read_text())
    assert lock['revision'] == '8db4d56323db31f27af151c542967b4ef13a79af'
    assert lock['instruction_revision'] == 'c25603685e66cd057db12026f3701e33cb456b60'
    assert len(lock['pyproject_sha256']) == 64
    assert 'dependencies' not in lock
    assert 'src/repository_intelligence/obligation_reconciliation.py' in lock['source_files']
    source = (ROOT / 'scripts/setup-ri-helpers.py').read_text()
    assert "tomllib.loads((source / 'pyproject.toml').read_text())['project']['dependencies']" in source
    assert "'--copies'" in source
