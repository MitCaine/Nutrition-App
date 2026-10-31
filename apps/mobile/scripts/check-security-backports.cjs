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

const MODERN_BACKPORTS={
  "glob": {
    "version": "13.0.6",
    "archive": "ca77434806ba1299cc733d71edcae4bffe3d403c8c2c3d88556a41e893c6c611",
    "provenance": "53173ecc800be0c1e57236e46d1c22756352b9401dd0fd8feb02d9bad62313ea",
    "integrity": "sha512-Ivy/mh1w5lthba4Nt4NMhQ3+LWsUifK/f00Bh22zL2RHa9EEY6F2xfgSch/y8oaNuxaxpEDgFgVScmXvQUWQZA=="
  },
  "minimatch": {
    "version": "10.2.6",
    "archive": "b549c07ec5ec21c79f9d6c8ae6f8b13430a5d84defc366b40beb6e3c083d0f30",
    "provenance": "b3787c19467c78fd03940c3e11e9cc752b6d46d5b8dd2e0593a2810baf7022b8",
    "integrity": "sha512-/LidICrcWJK7RVzX7QfOoaboT6KwEb0b8w3Vyc9z1BunU8KYCpR222/IPP+PEGqD4JhiyN4a8uJctb+CzSo73w=="
  }
};
const LEGACY_MINIMATCH_SOURCE="746849f267c4868a53729225bd85c7dccd387712136fb305fcc0a3eadd4a3d9d";
const LEGACY_OWNERS=['@jest/reporters','jest-config','jest-runtime','test-exclude'];
function verifyModernPayload(name,expected) {
  const directory=path.join(root,'node_modules',name);
  assert(!fs.lstatSync(directory).isSymbolicLink(),name+' package symlink');
  const location=path.join(root,'vendor/security',name);
  for(const input of [path.join(root,'vendor'),path.join(root,'vendor/security'),location,...['patched.tgz','provenance.json','security.patch'].map(n=>path.join(location,n))]) assert(!fs.lstatSync(input).isSymbolicLink(),name+' artifact symlink');
  const provenanceBytes=fs.readFileSync(path.join(location,'provenance.json'));
  assert.equal(sha(provenanceBytes),expected.provenance,name+' provenance drift');
  assert.equal(sha(fs.readFileSync(path.join(location,'patched.tgz'))),expected.archive,name+' archive drift');
  const provenance=JSON.parse(provenanceBytes);
  assert.deepEqual(Object.keys(provenance.build_inputs).sort(),['package-lock.json','package.json']);
  for(const [name,identity] of Object.entries(provenance.build_inputs)) {
    const input=path.join(root,'vendor/security/build',name);assert(!fs.lstatSync(input).isSymbolicLink(),'compiler input symlink');
    assert.equal(sha(fs.readFileSync(input)),identity,'compiler input identity drift');
  }
  assert.equal(provenance.patched_integrity,expected.integrity);
  assert.equal(sha(fs.readFileSync(path.join(location,'security.patch'))),provenance.patch_sha256);
  const actual=[];
  function walk(directory,prefix='') {for(const e of fs.readdirSync(directory,{withFileTypes:true})){assert(!e.isSymbolicLink(),name+' member symlink');if(e.isDirectory())walk(path.join(directory,e.name),prefix+e.name+'/');else actual.push(prefix+e.name);}}
  walk(directory);
  assert.deepEqual(actual.sort(),Object.keys(provenance.members).map(n=>n.slice(8)).sort(),name+' member inventory drift');
  for(const [member,identity] of Object.entries(provenance.members)) {
    const relative=member.slice(8);assert.equal(member,'package/'+relative);assert(!relative.split('/').includes('..'));
    assert.equal(sha(fs.readFileSync(path.join(directory,relative))),identity.patched_sha256,name+' payload: '+relative);
  }
  const basename=name==='glob'?'walker':'index';
  const source=fs.readFileSync(path.join(directory,'src',basename+'.ts'),'utf8');
  for(const kind of ['commonjs','esm']) for(const suffix of ['.js.map','.d.ts.map']) {
    const map=JSON.parse(fs.readFileSync(path.join(directory,'dist',kind,basename+suffix)));
    assert.deepEqual(map.sources,['../../src/'+basename+'.ts']);assert.deepEqual(map.sourcesContent,[source]);
  }
  return directory;
}
function checkModernArtifacts() {
  const manifest=JSON.parse(fs.readFileSync(path.join(root,'package.json')));
  const lock=JSON.parse(fs.readFileSync(path.join(root,'package-lock.json')));
  for(const [name,expected] of Object.entries(MODERN_BACKPORTS)) {
    const spec='file:vendor/security/'+name+'/patched.tgz';
    assert.equal(manifest.dependencies[name],spec,name+' declaration drift');
    assert.equal(manifest.overrides[name+'@'+expected.version],'$'+name,name+' selector/reference drift');
    const entry=lock.packages['node_modules/'+name];
    assert.equal(entry.version,expected.version);assert.equal(entry.resolved,spec);assert.equal(entry.integrity,expected.integrity);
    const expectedLocations=['node_modules/'+name,...LEGACY_OWNERS.map(o=>'node_modules/'+o+'/node_modules/'+name)].sort();
    assert.deepEqual(Object.keys(lock.packages).filter(p=>p.endsWith('node_modules/'+name)).sort(),expectedLocations,name+' lock closure drift');
    const directory=verifyModernPayload(name,expected);
    const owners=name==='glob'?['@expo/cli','@expo/config','@expo/config-plugins','@expo/fingerprint','@expo/metro-config']:['glob','@expo/fingerprint'];
    for(const owner of owners) {
      const caller=createRequire(path.join(root,'node_modules',owner,'package.json'));
      assert.equal(fs.realpathSync(caller.resolve(name)),fs.realpathSync(path.join(directory,'dist/commonjs',name==='glob'?'index.min.js':'index.js')),name+' owner resolution drift: '+owner);
    }
    const installed=cp.execFileSync('npm',['ls',name,'--all','--parseable'],{cwd:root,encoding:'utf8'}).trim().split('\n').filter(Boolean).map(p=>fs.realpathSync(p)).sort();
    assert.deepEqual(installed,expectedLocations.map(p=>fs.realpathSync(path.join(root,p))).sort(),name+' installed closure drift');
    for(const owner of LEGACY_OWNERS) {
      const legacy=path.join(root,'node_modules',owner,'node_modules',name);
      assert.equal(JSON.parse(fs.readFileSync(path.join(legacy,'package.json'))).version,name==='glob'?'7.2.3':'3.1.5');
      if(name==='minimatch') {
        assert.equal(sha(fs.readFileSync(path.join(legacy,'minimatch.js'))),LEGACY_MINIMATCH_SOURCE,'legacy minimatch source drift');
        assert.equal(typeof require(legacy),'function');assert(require(legacy)('a.ts','*.ts'));
      } else assert.equal(typeof require(legacy),'function');
    }

  }
  // Default glob entrypoints must not reintroduce a hidden unguarded matcher.
  for(const kind of ['commonjs','esm']) {
    const directory=path.join(root,'node_modules/glob/dist',kind);
    const forward=fs.readFileSync(path.join(directory,'security-forwarder.js'),'utf8');
    assert.equal(fs.readFileSync(path.join(directory,'index.min.js'),'utf8'),forward+'//# sourceMappingURL=index.min.js.map\n');
    const map=JSON.parse(fs.readFileSync(path.join(directory,'index.min.js.map')));
    assert.deepEqual(map.sourcesContent,[forward]);assert(forward.length<100);
  }
}
function checkMinimatchBehavior(library) {
  const {Minimatch}=library;
  const pattern='**/../a/b/**/../c/d';
  const below=new Minimatch(pattern,{optimizationLevel:2,braceExpandMax:8});
  const at=new Minimatch(pattern,{optimizationLevel:2,braceExpandMax:4});
  for(const matcher of [below,at]) {
    assert.equal(matcher.set.length,4);assert(matcher.match('../a/b/../c/d'));assert(matcher.match('x/a/b/y/c/d'));assert(!matcher.match('not-the-pattern'));
  }
  const limited=new Minimatch(pattern,{optimizationLevel:2,braceExpandMax:2});
  assert.equal(limited.set.length,2);
  // As with existing brace expansion caps, beyond-cap expansion is incomplete;
  // do not falsely claim unrestricted matching equivalence after clipping.
  assert.equal(limited.match('not-the-pattern'),false);
  const small=new Minimatch('{x,*}/{0..9}',{optimizationLevel:2});assert.equal(small.set.length,10);
  const large=new Minimatch('{x,*}/{0..999}',{optimizationLevel:2});assert.equal(large.set.length,2000);assert(large.match('x/5'));assert(large.match('y/999'));assert(!large.match('.y/5'));
  for(const count of [1000,1001]) {
    const instance=Object.create(Minimatch.prototype);let comparisons=0;instance.partsMatch=()=>{comparisons++;return false;};
    const parts=Array.from({length:count},(_,n)=>['x'+n]);const result=instance.secondPhasePreProcess(parts);assert.deepEqual(result,parts);if(count===1001)assert.equal(result,parts);assert.equal(comparisons,count===1000?499500:0);
  }
  assert(library.minimatch('src/a.ts','src/*.ts'));assert(!library.minimatch('src/a.js','src/*.ts'));
}
function checkSourceMaps() {
  const {TraceMap,decodedMappings}=require('@jridgewell/trace-mapping');
  for(const name of ['glob','minimatch']) for(const kind of ['commonjs','esm']) {
    const basename=name==='glob'?'walker':'index';
    const relative='package/dist/'+kind+'/'+basename+'.d.ts.map';
    const original=JSON.parse(cp.execFileSync('tar',['-xOf',path.join(root,'vendor/security',name,'upstream.tgz'),relative],{encoding:'utf8',timeout:30000,maxBuffer:4*1024*1024}));
    const originalSource=JSON.parse(cp.execFileSync('tar',['-xOf',path.join(root,'vendor/security',name,'upstream.tgz'),'package/dist/'+kind+'/'+basename+'.js.map'],{encoding:'utf8',timeout:30000,maxBuffer:4*1024*1024})).sourcesContent[0].split('\n');
    const updated=JSON.parse(fs.readFileSync(path.join(root,'node_modules',name,'dist',kind,basename+'.d.ts.map')));
    const newSource=updated.sourcesContent[0].split('\n');
    const before=decodedMappings(new TraceMap(original)),after=decodedMappings(new TraceMap(updated));
    assert.equal(before.length,after.length);let shifted=0,mapped=0;
    for(let row=0;row<before.length;row++) {
      assert.equal(before[row].length,after[row].length);
      for(let i=0;i<before[row].length;i++) {
        const a=before[row][i],b=after[row][i];assert.equal(a[0],b[0]);assert.equal(a.length,b.length);
        if(a.length>=4){mapped++;assert.equal(a[1],b[1]);assert.equal(a[3],b[3]);assert.equal(originalSource[a[2]],newSource[b[2]]);if(a[2]!==b[2])shifted++;if(a.length===5)assert.equal(a[4],b[4]);}
      }
    }
    assert(mapped>10&&shifted>0,name+' declaration mappings must actually rebase preserved tokens');
    console.log('PASS declaration map: '+name+'/'+kind+' '+mapped+' tokens, '+shifted+' shifted');
  }
}
function checkDefaultMinimatchLimit() {
  const {Minimatch}=require(path.join(root,'node_modules/minimatch'));
  const matcher=Object.create(Minimatch.prototype);matcher.options={};
  const parts=[Array(30).fill('**/../a/b').join('/').split('/')];
  matcher.firstPhasePreProcess(parts);assert.equal(parts.length,100000);
  console.log('PASS: default optimizer expansion cap100000 without compiling100000 regexes');
}
async function checkGlobBehavior(library,cwd) {
  const expected=library.globSync('**/*.ts',{cwd}).sort();assert(expected.length>20);
  assert.deepEqual((await library.glob('**/*.ts',{cwd})).sort(),expected);
  assert.deepEqual([...library.globIterateSync('**/*.ts',{cwd})].sort(),expected);
  const iterator=[];for await(const x of library.globIterate('**/*.ts',{cwd}))iterator.push(x);assert.deepEqual(iterator.sort(),expected);
  assert.deepEqual(new library.Glob('**/*.ts',{cwd}).walkSync().sort(),expected);
  const reason=new Error('bounded fixture abort');const pre=new AbortController();pre.abort(reason);
  await assert.rejects(library.glob('**',{cwd,signal:pre.signal}),e=>e===reason);
  function counted(controller,mode) {
    const count={calls:0};const source={...fs};
    for(const name of ['readdir','readdirSync']) source[name]=(...args)=>{if(++count.calls===1&&mode==='first-read')controller.abort(reason);return fs[name](...args);};
    return {count,source};
  }
  const controller=new AbortController();const {count,source}=counted(controller,'first-read');
  await assert.rejects(library.glob('**',{cwd,signal:controller.signal,fs:source}),e=>e===reason);
  const atReject=count.calls;await new Promise(r=>setTimeout(r,100));assert.equal(atReject,1);assert.equal(count.calls,atReject,'no new reads scheduled after rejected abort');
  const syncController=new AbortController();const sync=counted(syncController,'first-read');
  await new Promise((resolve,reject)=>{const stream=library.globStreamSync('**',{cwd,signal:syncController.signal,fs:sync.source});stream.on('error',e=>{try{assert.equal(e,reason);assert.equal(sync.count.calls,1);resolve();}catch(error){reject(error);}});stream.resume();});
  const firstController=new AbortController();const first=counted(firstController,'data');let firstAtAbort;
  await new Promise((resolve,reject)=>{const stream=library.globStream('**/*.ts',{cwd,signal:firstController.signal,fs:first.source});stream.once('data',()=>{firstAtAbort=first.count.calls;firstController.abort(reason);});stream.on('error',e=>e===reason?resolve():reject(e));stream.once('end',resolve);});
  assert(firstAtAbort!==undefined);await new Promise(r=>setTimeout(r,100));assert.equal(first.count.calls,firstAtAbort,'first-result cancellation must stop new reads');
  const pending=library.globStream('**',{cwd});await new Promise(r=>setTimeout(r,50));const found=[];for await(const x of pending)found.push(x);assert.deepEqual(found.sort(),library.globSync('**',{cwd}).sort(),'paused stream must finish without losing entries');
  const signal=AbortSignal.timeout(5);const delayed={...fs,readdir:(...args)=>{setTimeout(()=>fs.readdir(...args),20);}};
  await assert.rejects(library.glob('**',{cwd,signal,fs:delayed}),e=>e.name==='TimeoutError');await new Promise(r=>setTimeout(r,40));
  assert(library.hasMagic('*.ts'));assert.equal(library.escape('a*b'),'a\\*b');assert.equal(library.unescape('a\\*b'),'a*b');
  const ignored=await library.glob('**/*.ts',{cwd,ignore:'**/skip.ts'});assert(!ignored.some(p=>p.endsWith('skip.ts')));
}
async function checkModernBehavior() {
  const {pathToFileURL}=require('node:url');
  const variants=[require(path.join(root,'node_modules/glob')),require(path.join(root,'node_modules/glob/dist/commonjs/index.js')),await import(pathToFileURL(path.join(root,'node_modules/glob/dist/esm/index.min.js')).href),await import(pathToFileURL(path.join(root,'node_modules/glob/dist/esm/index.js')).href)];
  const matchers=[require(path.join(root,'node_modules/minimatch')),await import(pathToFileURL(path.join(root,'node_modules/minimatch/dist/esm/index.js')).href)];
  const globKeys=['Glob','Ignore','escape','glob','globIterate','globIterateSync','globStream','globStreamSync','globSync','hasMagic','iterate','iterateSync','stream','streamSync','sync','unescape'].sort();
  const matcherKeys=['AST','GLOBSTAR','Minimatch','braceExpand','defaults','escape','filter','makeRe','match','minimatch','sep','unescape'].sort();
  for(const m of matchers){assert.deepEqual(Object.keys(m).sort(),matcherKeys);checkMinimatchBehavior(m);}
  const fixture=fs.mkdtempSync(path.join(require('node:os').tmpdir(),'nutrition-glob-contract-'));let passed=false;
  try {
    function tree(directory,level){fs.mkdirSync(directory,{recursive:true});fs.writeFileSync(path.join(directory,'fixture.ts'),'');fs.writeFileSync(path.join(directory,'skip.ts'),'');if(level)for(const branch of ['a','b'])tree(path.join(directory,branch),level-1);}
    tree(fixture,4);
    for(const g of variants){assert.deepEqual(Object.keys(g).sort(),globKeys);await checkGlobBehavior(g,fixture);}
    // Reach the actual Expo helper and its unchanged five-second prerequisite.
    const helper=require(path.join(root,'node_modules/@expo/cli/build/src/utils/glob.js'));
    assert.deepEqual((await helper.everyMatchAsync('**/*.ts',{cwd:fixture})).sort(),variants[0].globSync('**/*.ts',{cwd:fixture}).sort());assert.equal((await helper.anyMatchAsync('**/*.ts',{cwd:fixture})).length,1);
    const prerequisitePath=path.join(root,'node_modules/@expo/cli/build/src/start/doctor/typescript/TypeScriptProjectPrerequisite.js');assert.match(fs.readFileSync(prerequisitePath,'utf8'),/AbortSignal\.timeout\(5000\)/);
    const {TypeScriptProjectPrerequisite}=require(prerequisitePath);const first=await TypeScriptProjectPrerequisite.prototype._queryFirstTypeScriptFileAsync.call({projectRoot:fixture});assert(first.endsWith('.ts'));
    passed=true;
  } finally {if(passed)fs.rmSync(fixture,{recursive:true,force:true});else console.error('Retained failed glob fixture: '+fixture);}
  const result=cp.spawnSync(process.execPath,['--max-old-space-size=512','-e','require('+JSON.stringify(__filename)+').checkDefaultMinimatchLimit()'],{encoding:'utf8',timeout:10000,maxBuffer:1024*1024});assert(!result.error,result.error?.message);assert.equal(result.signal,null);assert.equal(result.status,0,result.stderr);assert.match(result.stdout,/cap100000/);
  console.log('PASS: glob default/raw CJS/ESM cancellation, pause and API parity; minimatch capped work; actual Expo callers');
}

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
  assert.equal(manifest.overrides['deepmerge@4.3.1'],'$deepmerge','deepmerge selector/reference drift');
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
  const directory=path.join(root,'node_modules/deepmerge');assert.equal(fs.lstatSync(directory).isSymbolicLink(),false,'deepmerge package symlink');
  for(const [name,identity] of Object.entries(provenance.members)) {
    const relative=name.replace(/^package\//,'');assert.equal(name,'package/'+relative);assert(!relative.split('/').includes('..'));
    const file=path.join(directory,relative);assert.equal(fs.lstatSync(file).isSymbolicLink(),false,'deepmerge member symlink: '+relative);assert.equal(sha(fs.readFileSync(file)),identity.patched_sha256,relative);
  }
  function members(directory,prefix='') {return fs.readdirSync(directory,{withFileTypes:true}).flatMap(e=>{assert(!e.isSymbolicLink());return e.isDirectory()?members(path.join(directory,e.name),prefix+e.name+'/'):[prefix+e.name];});}
  assert.deepEqual(members(directory).sort(),Object.keys(provenance.members).map(n=>n.slice(8)).sort(),'deepmerge member inventory drift');
  for(const owner of ['@expo/config','jest-config']) {
    const ownerRequire=createRequire(require.resolve(owner+'/package.json',{paths:[root]}));
    assert.equal(fs.realpathSync(ownerRequire.resolve('deepmerge')),fs.realpathSync(path.join(directory,'dist/cjs.js')),'deepmerge owner resolution drift: '+owner);
    checkBehavior(ownerRequire('deepmerge'));
  }
  checkBehavior(require(path.join(directory,'dist/umd.js')));
  const installed=cp.execFileSync('npm',['ls','deepmerge','--all','--parseable'],{cwd:root,encoding:'utf8'}).trim().split('\n').filter(Boolean);
  assert.deepEqual(installed.map(p=>fs.realpathSync(p)),[fs.realpathSync(directory)],'deepmerge installed closure drift');
  assert.equal(require(path.join(root,'node_modules/postcss/package.json')).version,'8.5.30');
  checkModernArtifacts();
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
// Exercise the actual verifier against one private, otherwise valid installed graph.
// No mocks bypass resolution/inventory. The original installation is never mutated.
function checkNegativeFixtures(family='deepmerge') {
  const os=require('node:os');
  const fixture=fs.mkdtempSync(path.join(os.tmpdir(),'nutrition-backport-negative-'));
  let passed=false;
  try {
    for(const name of ['package.json','package-lock.json']) fs.copyFileSync(path.join(root,name),path.join(fixture,name));
    for(const name of ['node_modules','vendor','scripts']) fs.cpSync(path.join(root,name),path.join(fixture,name),{recursive:true,verbatimSymlinks:true});
    const checker=path.join(fixture,'scripts/check-security-backports.cjs');
    const invoke=()=>cp.spawnSync(process.execPath,['-e','require('+JSON.stringify(checker)+').checkArtifacts()'],{cwd:fixture,encoding:'utf8',timeout:30000,maxBuffer:1024*1024});
    const control=()=>{const r=invoke();assert(!r.error,r.error?.message);assert.equal(r.signal,null);assert.equal(r.status,0,r.stdout+r.stderr);};
    const rejects=(label,expected,mutate)=>{
      control(); const restore=mutate();
      try {const r=invoke();assert(!r.error,r.error?.message);assert.equal(r.signal,null);assert.notEqual(r.status,0,label);assert.match(r.stderr,expected,label);}
      finally {restore();}
      control(); console.log('PASS negative fixture: '+label);
    };
    if(family==='modern') {
      for(const [name,basename] of [['glob','walker'],['minimatch','index']]) {
        const directory=path.join(fixture,'node_modules',name);
        for(const suffix of ['.js','.js.map']) {
          const file=path.join(directory,'dist/commonjs',basename+suffix),bytes=fs.readFileSync(file);
          rejects(name+' '+suffix+' corruption',new RegExp(name+' payload:'),()=>{fs.appendFileSync(file,'corruption');return()=>fs.writeFileSync(file,bytes);});
        }
        for(const filename of ['patched.tgz','provenance.json']) {
          const artifact=path.join(fixture,'vendor/security',name,filename),bytes=fs.readFileSync(artifact);
          rejects(name+' '+filename+' symlink',new RegExp(name+' artifact symlink'),()=>{fs.unlinkSync(artifact);fs.symlinkSync(path.join(root,'vendor/security',name,filename),artifact);return()=>{fs.unlinkSync(artifact);fs.writeFileSync(artifact,bytes);};});
        }
        const saved=path.join(fixture,'saved-'+name);
        rejects(name+' package symlink',new RegExp(name+' package symlink'),()=>{fs.renameSync(directory,saved);fs.symlinkSync(saved,directory,'dir');return()=>{fs.unlinkSync(directory);fs.renameSync(saved,directory);};});
        const owner=name==='glob'?'@expo/config':'@expo/fingerprint';
        const nested=path.join(fixture,'node_modules',owner,'node_modules',name);
        rejects(name+' owner-local copy',new RegExp(name+' owner resolution drift'),()=>{fs.mkdirSync(path.dirname(nested),{recursive:true});fs.cpSync(directory,nested,{recursive:true});return()=>fs.rmSync(nested,{recursive:true});});
        const manifest=path.join(fixture,'package.json'),bytes=fs.readFileSync(manifest);
        rejects(name+' selector',new RegExp(name+' selector/reference drift'),()=>{const d=JSON.parse(bytes);delete d.overrides[name+'@'+MODERN_BACKPORTS[name].version];d.overrides[name]='$'+name;fs.writeFileSync(manifest,JSON.stringify(d));return()=>fs.writeFileSync(manifest,bytes);});
      }
      const bundle=path.join(fixture,'node_modules/glob/dist/commonjs/index.min.js'),saved=fs.readFileSync(bundle);
      const originalBundle=cp.execFileSync('tar',['-xOf',path.join(fixture,'vendor/security/glob/upstream.tgz'),'package/dist/commonjs/index.min.js'],{timeout:30000,maxBuffer:1024*1024});
      rejects('hidden vulnerable default bundle',/glob payload:/,()=>{fs.writeFileSync(bundle,originalBundle);return()=>fs.writeFileSync(bundle,saved);});
      const legacy=path.join(fixture,'node_modules/jest-config/node_modules/minimatch/minimatch.js'),legacyBytes=fs.readFileSync(legacy);
      rejects('legacy matcher preservation',/legacy minimatch source drift/,()=>{fs.appendFileSync(legacy,'\n// drift');return()=>fs.writeFileSync(legacy,legacyBytes);});
      const member=path.join(fixture,'node_modules/glob/dist/commonjs/walker.js'),memberBytes=fs.readFileSync(member);
      rejects('missing glob runtime',/glob member inventory drift/,()=>{fs.unlinkSync(member);return()=>fs.writeFileSync(member,memberBytes);});
      const extra=path.join(fixture,'node_modules/minimatch/unregistered.js');
      rejects('extra matcher member',/minimatch member inventory drift/,()=>{fs.writeFileSync(extra,'extra');return()=>fs.unlinkSync(extra);});
      passed=true;console.log('PASS: eighteen modern installed-verifier faults reject; controls pass');return;
    }
    const directory=path.join(fixture,'node_modules/deepmerge');
    const file=path.join(directory,'dist/cjs.js');
    const bytes=fs.readFileSync(file);
    rejects('runtime corruption',/dist\/cjs.js/,()=>{fs.appendFileSync(file,'\n// corruption');return()=>fs.writeFileSync(file,bytes);});
    rejects('missing member',/ENOENT/,()=>{fs.unlinkSync(file);return()=>fs.writeFileSync(file,bytes);});
    const extra=path.join(directory,'unexpected.js');
    rejects('extra member',/member inventory drift/,()=>{fs.writeFileSync(extra,'extra');return()=>fs.unlinkSync(extra);});
    rejects('member symlink',/member symlink/,()=>{fs.unlinkSync(file);fs.symlinkSync(path.join(root,'node_modules/deepmerge/dist/cjs.js'),file);return()=>{fs.unlinkSync(file);fs.writeFileSync(file,bytes);};});
    const saved=path.join(fixture,'saved-deepmerge');
    rejects('package symlink',/package symlink/,()=>{fs.renameSync(directory,saved);fs.symlinkSync(saved,directory,'dir');return()=>{fs.unlinkSync(directory);fs.renameSync(saved,directory);};});
    const nested=path.join(fixture,'node_modules/@expo/config/node_modules/deepmerge');
    rejects('owner-local extra copy',/owner resolution drift/,()=>{fs.mkdirSync(path.dirname(nested),{recursive:true});fs.cpSync(directory,nested,{recursive:true});return()=>fs.rmSync(nested,{recursive:true});});
    const rogue=path.join(fixture,'node_modules/nutrition-rogue-fixture');
    rejects('unregistered extra installed copy',/installed closure drift|Command failed/,()=>{fs.mkdirSync(path.join(rogue,'node_modules'),{recursive:true});fs.writeFileSync(path.join(rogue,'package.json'),JSON.stringify({name:'nutrition-rogue-fixture',version:'1.0.0',dependencies:{deepmerge:'4.3.1'}}));fs.cpSync(directory,path.join(rogue,'node_modules/deepmerge'),{recursive:true});return()=>fs.rmSync(rogue,{recursive:true});});
    const manifest=path.join(fixture,'package.json');const original=fs.readFileSync(manifest);
    for(const fault of ['selector','reference']) rejects('override '+fault,/selector\/reference drift/,()=>{const d=JSON.parse(original);if(fault==='selector'){delete d.overrides['deepmerge@4.3.1'];d.overrides.deepmerge='$deepmerge';}else d.overrides['deepmerge@4.3.1']='4.3.1';fs.writeFileSync(manifest,JSON.stringify(d));return()=>fs.writeFileSync(manifest,original);});
    passed=true;console.log('PASS: nine installed-verifier faults reject; controls pass');
  } finally {
    if(passed) fs.rmSync(fixture,{recursive:true,force:true});
    else console.error('Retained failed negative fixture for recovery: '+fixture);
  }
}
module.exports={checkBehavior,checkArtifacts,checkOwners,checkNegativeFixtures,checkModernArtifacts,checkModernBehavior,checkMinimatchBehavior,checkDefaultMinimatchLimit,checkSourceMaps};
if(require.main===module) {
  (async()=>{checkArtifacts();await checkOwners();await checkModernBehavior();console.log('PASS: deepmerge backport payload, all owners, hostile/ordinary semantics; PostCSS8.5.30');})().catch(e=>{console.error(e);process.exitCode=1;});
}
