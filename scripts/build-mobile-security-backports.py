"""Reproduce the owner-authorized deepmerge backport offline, without build hooks."""
from __future__ import annotations
import argparse
import base64
import difflib
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / 'apps/mobile/vendor/security/deepmerge'
UPSTREAM_SHA256 = '4003a0a348276a95543fa969f561f6b5968629acbbb59d66018dd23e7b8f1d5c'
PATCH_COMMIT = 'c5ad573121574db1c625b0aabcc6114ed7df6c5a'


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('upstream patch precondition changed')
    return text.replace(old, new, 1)


def build():
    original = (VENDOR / 'upstream.tgz').read_bytes()
    if hashlib.sha256(original).hexdigest() != UPSTREAM_SHA256:
        raise ValueError('upstream archive identity changed')
    with tarfile.open(fileobj=io.BytesIO(original), mode='r:gz') as archive:
        members = archive.getmembers()
        if any(not m.isfile() or not m.name.startswith('package/') or '..' in Path(m.name).parts for m in members):
            raise ValueError('unexpected archive member')
        before = {m.name: archive.extractfile(m).read() for m in members}
    after = dict(before)
    changed = ['package/index.js', 'package/dist/cjs.js', 'package/dist/umd.js']
    for name in changed:
        text = before[name].decode()
        indent = '\t' if name.endswith('umd.js') else ''
        prefix = indent + '// Protects from prototype poisoning'
        text = replace_once(text, prefix, indent + "function propertyIsForbidden(key) {\n" + indent + "\treturn key === '__proto__'\n" + indent + '}\n\n' + prefix)
        old = indent + '\t\t\tdestination[key] = cloneUnlessOtherwiseSpecified(target[key], options)'
        text = replace_once(text, old, indent + '\t\t\tif (propertyIsForbidden(key)) {\n' + indent + '\t\t\t\treturn\n' + indent + '\t\t\t}\n' + old)
        text = replace_once(text, 'if (propertyIsUnsafe(target, key)) {', 'if (propertyIsForbidden(key) || propertyIsUnsafe(target, key)) {')
        after[name] = text.encode()
    # Only the three identical algorithm copies change; package identity, license,
    # exports, bundled mergeability predicate and all other payload bytes survive.
    patch = ''.join(''.join(difflib.unified_diff(before[n].decode().splitlines(True), after[n].decode().splitlines(True), fromfile='a/'+n, tofile='b/'+n)) for n in changed).encode()
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for m in sorted(members, key=lambda m: m.name):
            info = tarfile.TarInfo(m.name)
            info.mode = m.mode
            info.size = len(after[m.name])
            archive.addfile(info, io.BytesIO(after[m.name]))
    packed = gzip.compress(stream.getvalue(), mtime=0)
    sha = lambda b: hashlib.sha256(b).hexdigest()
    provenance = {
        'package': 'deepmerge', 'version': '4.3.1',
        'upstream_url': 'https://registry.npmjs.org/deepmerge/-/deepmerge-4.3.1.tgz',
        'upstream_sha256': UPSTREAM_SHA256,
        'upstream_integrity': 'sha512-'+base64.b64encode(hashlib.sha512(original).digest()).decode(),
        'patch_commit': PATCH_COMMIT,
        'patch_url': 'https://github.com/TehShrike/deepmerge/pull/274',
        'patch_author': 'Cristian Flores (cristianfloresRC)',
        'advisory': 'GHSA-gcqx-w48m-w2h4',
        'status': 'owner-authorized repository backport; proposed upstream patch is unmerged; scanner findings remain visible',
        'recipe': 'scripts/build-mobile-security-backports.py; Python standard library, deterministic tar/gzip; no compiler or install hook',
        'changed_members': changed, 'patched_sha256': sha(packed),
        'patched_integrity': 'sha512-'+base64.b64encode(hashlib.sha512(packed).digest()).decode(),
        'patch_sha256': sha(patch),
        'members': {n: {'upstream_sha256': sha(before[n]), 'patched_sha256': sha(after[n])} for n in sorted(before)},
    }
    return {'patched.tgz': packed, 'security.patch': patch, 'LICENSE': before['package/license.txt'], 'provenance.json': (json.dumps(provenance, indent=2)+'\n').encode()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    for name, data in build().items():
        path = VENDOR / name
        if args.check:
            if path.is_symlink() or path.read_bytes() != data:
                raise ValueError('backport artifact drift: '+name)
        else:
            path.write_bytes(data)
    print('PASS: deterministic deepmerge source/CJS/UMD backport'+(' verified' if args.check else ' generated'))

if __name__ == '__main__':
    main()
