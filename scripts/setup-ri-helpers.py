#!/usr/bin/env python3
"""Explicit, pinned helper provisioning; never run implicitly by a worker."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def authenticate_source(source, lock):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(source), *args], text=True).strip()
    if git('rev-parse', 'HEAD') != lock['revision'] or git('status', '--porcelain'):
        raise ValueError('Selected helper checkout is changed')
    if digest(source / 'pyproject.toml') != lock['pyproject_sha256']:
        raise ValueError('Selected helper dependency definition changed')
    for name, expected in lock['source_files'].items():
        path = source / name
        if path.is_symlink() or not path.is_file() or digest(path) != expected:
            raise ValueError('Selected helper source changed: ' + name)


def verify(source, environment, lock):
    authenticate_source(source, lock)
    executable = environment / 'bin/python'
    # The installed project owns the dependency list. Never reconstruct it here.
    requirements = tomllib.loads((source / 'pyproject.toml').read_text())['project']['dependencies']
    code = '''import importlib.metadata as md, json, sys, hashlib
from pathlib import Path
expected=json.loads(sys.argv[1]); requirements=json.loads(sys.argv[2]); environment=Path(sys.argv[3])
assert Path(sys.prefix).resolve()==environment.resolve(), 'Helper interpreter prefix differs'
for requirement in requirements:
 name,version=requirement.split('=='); assert md.version(name)==version, 'Helper dependency drift: '+name
import repository_intelligence.worker_execution as worker
base=Path(worker.__file__).resolve().parent
for name,digest in expected.items():
 path=base/Path(name).relative_to('src/repository_intelligence')
 assert path.is_file() and not path.is_symlink() and hashlib.sha256(path.read_bytes()).hexdigest()==digest, 'Installed helper source drift: '+name
print(json.dumps({'interpreter':sys.executable,'prefix':sys.prefix,'module':str(worker.__file__),'dependencies':{r.split('==')[0]:md.version(r.split('==')[0]) for r in requirements}},sort_keys=True))
'''
    clean = {key: value for key, value in os.environ.items() if key not in ('PYTHONPATH', 'PYTHONHOME')}
    clean['PYTHONDONTWRITEBYTECODE'] = '1'
    result = subprocess.run([str(executable), '-I', '-c', code, json.dumps(lock['source_files']),
                             json.dumps(requirements), str(environment)], env=clean,
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--environment', type=Path, required=True)
    parser.add_argument('--mode', choices=('provision', 'verify'), required=True)
    args = parser.parse_args()
    lock = json.loads((ROOT / 'engineering/tooling/ri-helper-lock.json').read_text())
    source, environment = args.source.resolve(strict=True), args.environment.absolute()
    authenticate_source(source, lock)
    if environment.is_relative_to(ROOT) or environment.is_relative_to(source):
        raise ValueError('Helper environment must be separate from source repositories')
    if args.mode == 'provision':
        if environment.exists() or environment.is_symlink():
            raise ValueError('Existing helper environments are verified, never overwritten')
        subprocess.run([sys.executable, '-m', 'venv', '--copies', str(environment)], check=True)
        subprocess.run([str(environment / 'bin/python'), '-m', 'pip', 'install', str(source)], check=True)
    result = verify(source, environment, lock)
    print(json.dumps(dict(result='PASS', revision=lock['revision'], source=str(source), **result), sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps({'result': 'FAIL', 'error': str(error)}))
        raise SystemExit(1)
