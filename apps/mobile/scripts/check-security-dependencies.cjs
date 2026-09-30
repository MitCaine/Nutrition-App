'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const { spawnSync } = require('node:child_process');

// Advisory payloads run separately so a regression cannot stall the evidence runner.
if (process.argv[2] === '--brace-worker') {
  const loaded = require(process.argv[3]);
  const expand = typeof loaded === 'function' ? loaded : loaded.expand;
  const vectors = {
    'parse-tail': '{' + '{a},'.repeat(10000) + 'b}',
    'parse-array': '{{x},' + 'a,'.repeat(150000) + 'b}',
    'nested-members': '{a,'.repeat(5000) + 'z' + '}'.repeat(5000),
    'nested-set': '{'.repeat(5000) + 'a,b' + '}'.repeat(5000),
    'rewrite-loop': '{a}' + '}'.repeat(64000) + ',z}',
  };
  assert.ok(Object.hasOwn(vectors, process.argv[4]));
  const result = expand(vectors[process.argv[4]]);
  assert.ok(Array.isArray(result));
  assert.ok(result.length > 0);
  assert.ok(result.every(value => typeof value === 'string'));
  console.log(JSON.stringify({ vector: process.argv[4], result_count: result.length }));
  process.exit(0);
}

const mobile = path.resolve(process.cwd(), 'apps/mobile');
const manifest = JSON.parse(fs.readFileSync(path.join(mobile, 'package.json')));
const lock = JSON.parse(fs.readFileSync(path.join(mobile, 'package-lock.json')));
const packages = lock.packages;
const version = value => value.split('.').map(Number);
const atLeast = (actual, minimum) => {
  const a = version(actual), b = version(minimum);
  return a[0] > b[0] || (a[0] === b[0] && (a[1] > b[1] || (a[1] === b[1] && a[2] >= b[2])));
};
assert.equal(manifest.overrides?.xcode?.uuid, '11.1.1');
const braces = Object.entries(packages).filter(([name]) => /(?:^|\/)node_modules\/brace-expansion$/.test(name));
assert.ok(braces.length > 0);
const covered = new Set();
for (const [location, record] of braces) {
  const major = version(record.version)[0];
  assert.ok(major === 1 || major === 5, `Unplanned brace major at ${location}`);
  assert.ok(atLeast(record.version, major === 1 ? '1.1.21' : '5.0.12'), `Vulnerable brace lock entry ${location}@${record.version}`);
  const directory = path.join(mobile, location);
  const installed = JSON.parse(fs.readFileSync(path.join(directory, 'package.json')));
  assert.equal(installed.version, record.version, `Installed/locked mismatch ${location}`);
  const loaded = require(directory);
  const expand = typeof loaded === 'function' ? loaded : loaded.expand;
  assert.equal(typeof expand, 'function');
  assert.deepEqual(expand('file-{a,b}-{1..2}.txt'), ['file-a-1.txt', 'file-a-2.txt', 'file-b-1.txt', 'file-b-2.txt']);
  assert.deepEqual(expand('literal.txt'), ['literal.txt']);
  for (const vector of ['parse-tail', 'parse-array', 'nested-members', 'nested-set', 'rewrite-loop']) {
    const child = spawnSync(process.execPath, [__filename, '--brace-worker', directory, vector], {
      encoding: 'utf8', timeout: 15000, maxBuffer: 1024 * 1024,
    });
    assert.ifError(child.error);
    assert.equal(child.signal, null, `${location}: ${vector} signal ${child.signal}`);
    assert.equal(child.status, 0, `${location}: ${vector}\n${child.stderr}`);
    console.log(JSON.stringify({ package: location, version: record.version, gate: 'hostile-brace', ...JSON.parse(child.stdout) }));
  }
  covered.add(major);
}
assert.deepEqual([...covered].sort(), [1, 5]);
const uuids = Object.entries(packages).filter(([name]) => /(?:^|\/)node_modules\/uuid$/.test(name));
assert.ok(uuids.length > 0);
for (const [location, record] of uuids) {
  assert.equal(record.version, '11.1.1', `Unplanned uuid resolution ${location}`);
  assert.equal(JSON.parse(fs.readFileSync(path.join(mobile, location, 'package.json'))).version, record.version);
}
const mobileRequire = createRequire(path.join(mobile, 'package.json'));
const xcodePath = mobileRequire.resolve('xcode');
const xcodeRequire = createRequire(xcodePath);
const uuidPath = xcodeRequire.resolve('uuid');
const uuid = xcodeRequire('uuid');
assert.equal(xcodeRequire('uuid/package.json').version, '11.1.1');
assert.equal(typeof uuid.v4, 'function');
assert.match(uuid.v4(), /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
const ns = '6ba7b810-9dad-11d1-80b4-00c04fd430c8';
for (const method of ['v3', 'v5', 'v6']) {
  assert.equal(typeof uuid[method], 'function');
  for (const [length, offset] of [[8, 4], [16, 1], [16, -1]]) {
    const buffer = new Uint8Array(length).fill(170);
    const before = buffer.slice();
    const call = method === 'v6' ? () => uuid[method]({}, buffer, offset) : () => uuid[method]('x', ns, buffer, offset);
    assert.throws(call, RangeError, `${method}: invalid bounds must throw`);
    assert.deepEqual(buffer, before, `${method}: invalid write changed caller buffer`);
  }
  const valid = new Uint8Array(20).fill(170);
  const result = method === 'v6' ? uuid[method]({}, valid, 4) : uuid[method]('x', ns, valid, 4);
  assert.equal(result, valid);
  assert.deepEqual(valid.slice(0, 4), new Uint8Array(4).fill(170));
  assert.ok(valid.slice(4).some(byte => byte !== 170));
  console.log(JSON.stringify({ package: path.relative(mobile, uuidPath), version: '11.1.1', gate: 'uuid-buffer-bounds', method }));
}
const project = mobileRequire('xcode').project('security-check-unused.pbxproj');
project.hash = { project: { objects: {} } };
const ids = new Set();
for (let i = 0; i < 1000; i++) {
  const id = project.generateUuid();
  assert.match(id, /^[0-9A-F]{24}$/);
  assert.ok(!ids.has(id), 'Actual xcode caller generated duplicate ID');
  ids.add(id);
}
console.log(JSON.stringify({ gate: 'xcode-real-caller', uuid_path: path.relative(mobile, uuidPath), generated_unique_ids: ids.size }));
console.log(JSON.stringify({ result: 'PASS', brace_copies: braces.length, uuid_copies: uuids.length, node: process.version }));
