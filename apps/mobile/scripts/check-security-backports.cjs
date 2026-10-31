'use strict';
// A repository backport is identified by bytes and provenance, never its version alone.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { createRequire } = require('node:module');
const cp = require('node:child_process');
const root = path.resolve(__dirname, '..');
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const vendor = path.join(root, 'vendor/security/deepmerge');
const EXPECTED_ARTIFACT = 'c219514b29aa8f22c9e6b73b00886e3e175eddb11cde7cbbe98366c6e3a61a36';
function checkBehavior(merge) {
  const poison = () => JSON.parse('{"__proto__":{"nutritionFixtureAdmin":true}}');
  const safe = x => {
    assert.equal(Object.getPrototypeOf(x), Object.prototype);
    assert.equal(x.nutritionFixtureAdmin, undefined);
    assert.equal(Object.hasOwn(x, '__proto__'), false);
  };
  safe(merge(Object.create(null), poison()));
  safe(merge({session:null}, {session:poison()}).session);
  safe(merge(poison(), {ok:true}));
  safe(merge({list:[]}, {list:[poison()]}).list[0]);
  assert.equal(Object.prototype.nutritionFixtureAdmin, undefined);
  const symbol = Symbol('ordinary');
  const value = merge({a:{b:1},items:[1],[symbol]:'old'}, {a:{c:2},items:[2],[symbol]:'new'});
  assert.deepEqual(value.a,{b:1,c:2}); assert.deepEqual(value.items,[1,2]); assert.equal(value[symbol],'new');
  assert.deepEqual(merge({items:[1]}, {items:[2]}, {arrayMerge:(_,b)=>b}).items,[2]);
  assert.deepEqual(merge({a:{b:1}}, {a:{c:2}}, {customMerge:key=>key==='a'?()=>({custom:true}):undefined}),{a:{custom:true}});
  const original={a:{b:1}}; assert.equal(merge({},original,{clone:false}).a,original.a);
  assert.deepEqual(merge.all([{a:1},{b:2}]),{a:1,b:2});
}
function checkArtifacts() {
  const manifest=JSON.parse(fs.readFileSync(path.join(root,'package.json')));
  const lock=JSON.parse(fs.readFileSync(path.join(root,'package-lock.json')));
  assert.equal(manifest.dependencies.deepmerge,'file:vendor/security/deepmerge/patched.tgz');
  assert.equal(manifest.overrides['deepmerge@4.3.1'],'$deepmerge');
  const provenanceBytes=fs.readFileSync(path.join(vendor,'provenance.json'));
  assert.equal(sha(provenanceBytes),'ad49fc2e20d14dcbdda381654d961e56867021f5a23f5d104935e242e391e6c6');
  const provenance=JSON.parse(provenanceBytes);
  const archive=fs.readFileSync(path.join(vendor,'patched.tgz'));
  assert.equal(sha(archive),EXPECTED_ARTIFACT);
  assert.equal(provenance.patched_sha256,EXPECTED_ARTIFACT);
  assert.equal(provenance.patch_commit,'c5ad573121574db1c625b0aabcc6114ed7df6c5a');
  assert.equal(sha(fs.readFileSync(path.join(vendor,'security.patch'))),provenance.patch_sha256);
  assert.deepEqual(Object.keys(lock.packages).filter(p=>p.endsWith('node_modules/deepmerge')),['node_modules/deepmerge']);
  const entry=lock.packages['node_modules/deepmerge'];
  assert.equal(entry.version,'4.3.1');assert.equal(entry.resolved,manifest.dependencies.deepmerge);assert.equal(entry.integrity,provenance.patched_integrity);
  for(const [location,entry] of Object.entries(lock.packages)) if(location.endsWith('node_modules/postcss')) assert.equal(entry.version,'8.5.30');
  assert.equal(lock.packages['node_modules/postcss'].version,'8.5.30');
  const directory=path.join(root,'node_modules/deepmerge');assert.equal(fs.lstatSync(directory).isSymbolicLink(),false);
  for(const [name,identity] of Object.entries(provenance.members)) {
    const relative=name.replace(/^package\//,'');assert.equal(name,'package/'+relative);assert(!relative.split('/').includes('..'));
    const file=path.join(directory,relative);assert.equal(fs.lstatSync(file).isSymbolicLink(),false);assert.equal(sha(fs.readFileSync(file)),identity.patched_sha256,relative);
  }
  function members(directory,prefix='') {return fs.readdirSync(directory,{withFileTypes:true}).flatMap(e=>{assert(!e.isSymbolicLink());return e.isDirectory()?members(path.join(directory,e.name),prefix+e.name+'/'):[prefix+e.name];});}
  assert.deepEqual(members(directory).sort(),Object.keys(provenance.members).map(n=>n.slice(8)).sort());
  for(const owner of ['@expo/config','jest-config']) {
    const ownerRequire=createRequire(require.resolve(owner+'/package.json',{paths:[root]}));
    assert.equal(fs.realpathSync(ownerRequire.resolve('deepmerge')),fs.realpathSync(path.join(directory,'dist/cjs.js')));
    checkBehavior(ownerRequire('deepmerge'));
  }
  checkBehavior(require(path.join(directory,'dist/umd.js')));
  const installed=cp.execFileSync('npm',['ls','deepmerge','--all','--parseable'],{cwd:root,encoding:'utf8'}).trim().split('\n').filter(Boolean);
  assert.deepEqual(installed.map(p=>fs.realpathSync(p)),[fs.realpathSync(directory)]);
  assert.equal(require(path.join(root,'node_modules/postcss/package.json')).version,'8.5.30');
}
async function checkOwners() {
  const os=require('node:os');const fixture=fs.mkdtempSync(path.join(os.tmpdir(),'nutrition-deepmerge-contract-'));
  try {
    fs.writeFileSync(path.join(fixture,'package.json'),JSON.stringify({name:'nutrition-security-fixture',version:'1.0.0'}));
    const poison=JSON.parse('{"__proto__":{"nutritionFixtureAdmin":true}}');
    fs.writeFileSync(path.join(fixture,'app.json'),JSON.stringify({expo:{name:'Fixture',slug:'fixture',sdkVersion:'57.0.0',extra:{session:null},plugins:[['fixture-plugin',{session:null}]]}}));
    // Resolve no external plugins. Exercise actual Expo modification/merge caller.
    const config=require(require.resolve('@expo/config',{paths:[root]}));
    const result=await config.modifyConfigAsync(fixture,{extra:{session:poison},plugins:[['fixture-plugin',{session:poison}]]},{skipPlugins:true},{dryRun:true});
    assert.equal(result.type,'success');
    for(const value of [result.config.extra.session,result.config.plugins[0][1].session]) {
      assert.equal(Object.getPrototypeOf(value),Object.prototype);assert.equal(value.nutritionFixtureAdmin,undefined);assert(!Object.hasOwn(value,'__proto__'));
    }
    const preset=path.join(fixture,'jest-preset.js');
    fs.writeFileSync(preset,'module.exports = {globals:{session:null,ordinary:{a:1}}};\n');
    const jest=require(require.resolve('jest-config',{paths:[root]}));
    const normalized=(await jest.normalize({...jest.defaults,rootDir:fixture,preset:fixture,globals:{session:poison,ordinary:{b:2}}},{})).options;
    assert.equal(normalized.globals.session.nutritionFixtureAdmin,undefined);assert.equal(Object.getPrototypeOf(normalized.globals.session),Object.prototype);
    assert.deepEqual(normalized.globals.ordinary,{a:1,b:2});
  } finally {fs.rmSync(fixture,{recursive:true,force:true});}
}
module.exports={checkBehavior,checkArtifacts,checkOwners};
if(require.main===module) {
  (async()=>{checkArtifacts();await checkOwners();console.log('PASS: deepmerge backport payload, all owners, hostile/ordinary semantics; PostCSS8.5.30');})().catch(e=>{console.error(e);process.exitCode=1;});
}
