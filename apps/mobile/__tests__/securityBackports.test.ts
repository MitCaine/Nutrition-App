const merge = require('deepmerge');

describe('maintained deepmerge backport', () => {
  const poison = () => JSON.parse('{"__proto__":{"nutritionFixtureAdmin":true}}');
  const safe = (value: object) => {
    expect(Object.getPrototypeOf(value)).toBe(Object.prototype);
    expect((value as any).nutritionFixtureAdmin).toBeUndefined();
    expect(Object.prototype.hasOwnProperty.call(value, '__proto__')).toBe(false);
  };
  it('rejects a source key for a null-prototype target', () => safe(merge(Object.create(null), poison())));
  it('rejects a key when recursively merging a null placeholder', () => safe(merge({session:null},{session:poison()}).session));
  it('does not copy a target-owned key', () => safe(merge(poison(),{ordinary:true})));
  it('protects cloned array elements', () => safe(merge({items:[]},{items:[poison()]}).items[0]));
  it('preserves ordinary symbols, arrays and custom merge options', () => {
    const key = Symbol('fixture');
    const result=merge({[key]:1,items:[1],nested:{a:1}},{[key]:2,items:[2],nested:{b:2}});
    expect(result).toEqual({[key]:2,items:[1,2],nested:{a:1,b:2}});
    expect(merge({items:[1]},{items:[2]},{arrayMerge:(_:unknown,b:unknown)=>b})).toEqual({items:[2]});
    expect((Object.prototype as any).nutritionFixtureAdmin).toBeUndefined();
  });
});


it('rejects installed payload, closure, symlink and selector drift from valid baselines', () => {
  const {execFileSync}=require('node:child_process');
  const path=require('node:path');
  const checker=path.resolve(__dirname,'../scripts/check-security-backports.cjs');
  const output=execFileSync(process.execPath,['-e','require('+JSON.stringify(checker)+').checkNegativeFixtures()'],{encoding:'utf8',timeout:120000,maxBuffer:1024*1024});
  expect(output).toContain('nine installed-verifier faults reject; controls pass');
},150000);
