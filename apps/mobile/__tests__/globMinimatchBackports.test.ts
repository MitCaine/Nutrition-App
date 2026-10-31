const {Minimatch}=require('minimatch');
const {execFileSync}=require('node:child_process');
const path=require('node:path');
const checker=path.resolve(process.cwd(),'scripts/check-security-backports.cjs');

function check(method: string, timeout=120000): string {
  return execFileSync(process.execPath,['-e','require('+JSON.stringify(checker)+').'+method],{encoding:'utf8',timeout,maxBuffer:2*1024*1024});
}

it('bounds generated patterns and preserves ordinary matching below and at the cap', () => {
  const pattern='**/../a/b/**/../c/d';
  for(const cap of [4,8]) {
    const matcher=new Minimatch(pattern,{optimizationLevel:2,braceExpandMax:cap});
    expect(matcher.set).toHaveLength(4);
    expect(matcher.match('../a/b/../c/d')).toBe(true);
    expect(matcher.match('x/a/b/y/c/d')).toBe(true);
    expect(matcher.match('unrelated')).toBe(false);
  }
  const limited=new Minimatch(pattern,{optimizationLevel:2,braceExpandMax:2});
  expect(limited.set).toHaveLength(2);
  // Above-cap expansion is constrained, not falsely equivalent to unbounded work.
  expect(limited.match('unrelated')).toBe(false);
});

it('skips quadratic deduplication without dropping large-set positive and negative matches', () => {
  const large=new Minimatch('{x,*}/{0..999}',{optimizationLevel:2});
  expect(large.set).toHaveLength(2000);
  expect(large.match('x/5')).toBe(true);
  expect(large.match('y/999')).toBe(true);
  expect(large.match('.y/5')).toBe(false);
});

it('qualifies default/raw CJS/ESM cancellation, pause and actual Expo callers with bounded watchdogs', () => {
  expect(check('checkModernBehavior()')).toContain('default/raw CJS/ESM cancellation');
},150000);

it('rebases declaration source positions using an independent source-map decoder', () => {
  const result=check('checkSourceMaps()');
  for(const name of ['glob/commonjs','glob/esm','minimatch/commonjs','minimatch/esm']) expect(result).toContain('PASS declaration map: '+name);
});

it('rejects eighteen modern payload, bundle, owner, legacy and selector faults with valid controls', () => {
  expect(check("checkNegativeFixtures('modern')",240000)).toContain('eighteen modern installed-verifier faults reject; controls pass');
},270000);
