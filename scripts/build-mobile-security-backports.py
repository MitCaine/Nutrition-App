"""Reproduce the owner-authorized mobile security backports without build hooks."""
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
import subprocess

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


MODERN = {
    'glob': ('13.0.6', '020f184fa9c4e2905cf33c3d1dbba4b25a58e05f6f785f81cc931394e07b8970',
             '4682e8c9babee1b385202ede36389634e12076d7', 'isaacs/node-glob', 'walker'),
    'minimatch': ('10.2.6', '5a3d2c8074a28229665727e47b8a1090941856a7962905efe05d20d3760355f8',
                  '77a0f5c4b80bdc641c3c930a1d9edf5ad2db57f8', 'isaacs/minimatch', 'index'),
}
BASE64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'


def decode_segment(text):
    result, value, shift = [], 0, 0
    for char in text:
        digit = BASE64.index(char)
        value |= (digit & 31) << shift
        if digit & 32:
            shift += 5
        else:
            result.append(-(value >> 1) if value & 1 else value >> 1)
            value, shift = 0, 0
    if shift:
        raise ValueError('invalid source-map VLQ')
    return result


def encode_segment(values):
    result = ''
    for value in values:
        unsigned = (-value << 1 | 1) if value < 0 else value << 1
        while True:
            digit = unsigned & 31
            unsigned >>= 5
            result += BASE64[digit | (32 if unsigned else 0)]
            if not unsigned:
                break
    return result


def rebase_declaration_map(raw, before, after):
    # Declaration bytes/signatures do not change. Rebase their original-source
    # line references only; every referenced source line must remain identical.
    mapping = json.loads(raw)
    if len(mapping['sources']) != 1:
        raise ValueError('unexpected declaration source count')
    old_lines, new_lines = before.splitlines(), after.splitlines()
    line_map = {}
    for block in difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False).get_matching_blocks():
        line_map.update({block.a + i: block.b + i for i in range(block.size)})
    old_line = new_previous_line = 0
    rows = []
    for row in mapping['mappings'].split(';'):
        segments = []
        for segment in row.split(',') if row else []:
            fields = decode_segment(segment)
            if len(fields) >= 4:
                old_line += fields[2]
                if old_line not in line_map:
                    raise ValueError('declaration maps to a changed source line')
                new_line = line_map[old_line]
                if old_lines[old_line] != new_lines[new_line]:
                    raise ValueError('source-map token correspondence changed')
                fields[2] = new_line - new_previous_line
                new_previous_line = new_line
            segments.append(encode_segment(fields))
        rows.append(','.join(segments))
    mapping['mappings'] = ';'.join(rows)
    mapping['sourcesContent'] = [after]
    return (json.dumps(mapping, separators=(',', ':'))+'\n').encode()


def transform_typescript(source, filename, format, tools):
    build_inputs = ROOT / 'apps/mobile/vendor/security/build'
    for name in ('package.json', 'package-lock.json'):
        if (tools / name).read_bytes() != (build_inputs / name).read_bytes():
            raise ValueError('selected compiler input identity changed: '+name)
    script = """const fs=require('node:fs'),p=require('node:path');
const es=require(p.join(process.argv[1],'node_modules/esbuild'));
if(es.version!=='0.28.2') throw Error('compiler version drift');
const r=JSON.parse(fs.readFileSync(0,'utf8'));
const out=es.transformSync(r.source,{loader:'ts',sourcefile:'../../src/'+r.filename+'.ts',format:r.format,target:'es2022',sourcemap:'external',sourcesContent:true});
if(out.warnings.length) throw Error(JSON.stringify(out.warnings));
process.stdout.write(JSON.stringify(out));"""
    result = subprocess.run(['node', '-e', script, str(tools)],
                            input=json.dumps({'source': source, 'filename': filename, 'format': format}),
                            text=True, capture_output=True, timeout=30, check=True)
    result = json.loads(result.stdout)
    source_map = json.loads(result['map'])
    source_map['file'] = filename+'.js'
    if source_map['sourcesContent'] != [source]:
        raise ValueError('compiler source map content mismatch')
    return ((result['code']+'//# sourceMappingURL='+filename+'.js.map\n').encode(),
            (json.dumps(source_map, separators=(',', ':'))+'\n').encode())


def build_modern(name, tools):
    version, upstream_sha, commit, repository, filename = MODERN[name]
    vendor = ROOT / 'apps/mobile/vendor/security' / name
    original = (vendor / 'upstream.tgz').read_bytes()
    if hashlib.sha256(original).hexdigest() != upstream_sha:
        raise ValueError(name+' upstream archive identity changed')
    with tarfile.open(fileobj=io.BytesIO(original), mode='r:gz') as archive:
        members = archive.getmembers()
        if any(not m.isfile() or not m.name.startswith('package/') or '..' in Path(m.name).parts for m in members):
            raise ValueError('unexpected archive member')
        before = {m.name: archive.extractfile(m).read() for m in members}
    source = json.loads(before['package/dist/commonjs/'+filename+'.js.map'])['sourcesContent'][0]
    original_source = source
    esm_source = json.loads(before['package/dist/esm/'+filename+'.js.map'])['sourcesContent'][0]
    if source != esm_source:
        raise ValueError('CJS/ESM original source mismatch')
    if name == 'glob':
        source = replace_once(source, '  onResume(fn: () => any) {\n    if (this.signal?.aborted) return\n', '  onResume(fn: () => any) {\n')
        old = 'if (this.signal?.aborted) cb()'
        if source.count(old) != 4:
            raise ValueError('expected four cancellation branches')
        source = source.replace(old, 'if (this.signal?.aborted) return cb()')
    else:
        source = replace_once(source, 'firstPhasePreProcess(globParts: string[][]) {\n',
                              'firstPhasePreProcess(globParts: string[][]) {\n    // Security backport: bound generated patterns by the existing expansion limit.\n    const { braceExpandMax = 100_000 } = this.options\n')
        source = replace_once(source, "            p2 === '..'\n", "            p2 === '..' ||\n            globParts.length >= braceExpandMax\n")
        source = replace_once(source, 'secondPhasePreProcess(globParts: string[][]): string[][] {\n',
                              'secondPhasePreProcess(globParts: string[][]): string[][] {\n    // Security backport: avoid pairwise work on large matching sets.\n    if (globParts.length > 1000) return globParts\n')
    after = dict(before)
    after['package/src/'+filename+'.ts'] = source.encode()
    for directory, format in [('commonjs', 'cjs'), ('esm', 'esm')]:
        prefix = 'package/dist/'+directory+'/'
        after[prefix+filename+'.js'], after[prefix+filename+'.js.map'] = transform_typescript(source, filename, format, tools)
        after[prefix+filename+'.d.ts.map'] = rebase_declaration_map(before[prefix+filename+'.d.ts.map'], original_source, source)
        if name == 'glob':
            # The upstream default bundle embeds a private minimatch copy.
            # Preserve its public paths while routing to the patched readable
            # module and the declared, lock-verified minimatch dependency.
            code = ('"use strict";\nmodule.exports = require("./index.js");\n' if directory == 'commonjs'
                    else 'export * from "./index.js";\n')
            after[prefix+'security-forwarder.js'] = code.encode()
            after[prefix+'index.min.js'] = (code+'//# sourceMappingURL=index.min.js.map\n').encode()
            forward_map = {'version': 3, 'file': 'index.min.js', 'sources': ['security-forwarder.js'],
                           'sourcesContent': [code], 'names': [], 'mappings': 'AAAA;AACA' if directory == 'commonjs' else 'AAAA'}
            after[prefix+'index.min.js.map'] = (json.dumps(forward_map, separators=(',', ':'))+'\n').encode()
    stream = io.BytesIO()
    modes = {m.name: m.mode for m in members}
    with tarfile.open(fileobj=stream, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for path, data in sorted(after.items()):
            info = tarfile.TarInfo(path)
            info.mode, info.size = modes.get(path, 0o644), len(data)
            archive.addfile(info, io.BytesIO(data))
    packed = gzip.compress(stream.getvalue(), mtime=0)
    sha = lambda b: hashlib.sha256(b).hexdigest()
    patch = ''.join(difflib.unified_diff(original_source.splitlines(True), source.splitlines(True),
                                       fromfile='a/src/'+filename+'.ts', tofile='b/src/'+filename+'.ts')).encode()
    license_name = next(n for n in before if n.rsplit('/', 1)[-1].lower() in ['license', 'license.md', 'license.txt'])
    provenance = {
        'package': name, 'version': version,
        'upstream_url': 'https://registry.npmjs.org/'+name+'/-/'+name+'-'+version+'.tgz',
        'upstream_sha256': upstream_sha,
        'upstream_integrity': 'sha512-'+base64.b64encode(hashlib.sha512(original).digest()).decode(),
        'patch_commit': commit, 'patch_url': 'https://github.com/'+repository+'/commit/'+commit,
        'patched_sha256': sha(packed), 'patched_integrity': 'sha512-'+base64.b64encode(hashlib.sha512(packed).digest()).decode(),
        'patch_sha256': sha(patch), 'source_before_sha256': sha(original_source.encode()), 'source_after_sha256': sha(source.encode()),
        'compiler': 'esbuild0.28.2; loader ts; target es2022; CJS/ESM; external maps with exact source content',
        'build_inputs': {n: sha((ROOT / 'apps/mobile/vendor/security/build' / n).read_bytes()) for n in ['package.json', 'package-lock.json']},
        'delivery': ('Default bundled entrypoints forward to readable index.js; no embedded third-party runtime; declared locked minimatch used' if name == 'glob' else 'Same matching engine; generated-entry cap and large-set deduplication bypass only'),
        'changed_members': [n for n in before if before[n] != after[n]], 'added_members': sorted(set(after)-set(before)),
        'members': {n: {'upstream_sha256': sha(before[n]) if n in before else None, 'patched_sha256': sha(data)} for n, data in sorted(after.items())},
        'status': 'owner-authorized maintained backport; original identity/version retained; advisory/scanner findings not dismissed',
    }
    return {'patched.tgz': packed, 'security.patch': patch, 'LICENSE': before[license_name],
            'provenance.json': (json.dumps(provenance, indent=2)+'\n').encode()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--package', choices=['deepmerge', 'glob', 'minimatch', 'all'], default='deepmerge')
    parser.add_argument('--tools-root', type=Path)
    args = parser.parse_args()
    names = ['deepmerge', 'glob', 'minimatch'] if args.package == 'all' else [args.package]
    if any(n != 'deepmerge' for n in names) and args.tools_root is None:
        parser.error('modern backports require the explicit isolated --tools-root; no automatic install')
    for package in names:
        outputs = build() if package == 'deepmerge' else build_modern(package, args.tools_root.resolve())
        vendor = ROOT / 'apps/mobile/vendor/security' / package
        for name, data in outputs.items():
            path = vendor / name
            if args.check:
                if path.is_symlink() or path.read_bytes() != data:
                    raise ValueError('backport artifact drift: '+package+'/'+name)
            else:
                path.write_bytes(data)
        print('PASS: deterministic '+package+' backport'+(' verified' if args.check else ' generated'))

if __name__ == '__main__':
    main()
