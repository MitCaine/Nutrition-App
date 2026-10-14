// Accepted synthetic SIGKILL/reopen controls; desktop SQLite and atomic file storage only.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { fork, spawnSync } = require('node:child_process');
const crypto = require('node:crypto');
const { DB, req, source } = require('./acceptedRuntimeAdapter.cjs');
const Module = require('node:module');
const originalLoad = Module._load;
Module._load = function(id, parent, ...rest) {
  if (id === 'react-native') return { AppState: { addEventListener: () => ({remove(){}}) } };
  // Recovery is exercised without a QueryClient; projection functions are never invoked.
  if (id === '../hooks/useLogs' && parent.filename.endsWith('logMutationRecovery.ts')) return {};
  return originalLoad.call(this,id,parent,...rest);
};
const { migrateNutritionDatabase } = req('storage/sqlite/migrations.ts');
const { SQLITE_SEMANTIC_TABLES, SQLITE_SNAPSHOT_SCOPE_TABLE } = req('storage/sqlite/schema.ts');
const { createLocalFoodsRuntime } = req('runtime/local/localFoodsRuntime.ts');
const { createLocalDailyLogsRuntime } = req('runtime/local/localDailyLogsRuntime.ts');
const { markLocalDailyLogComplete, getLocalDailyLogCompleteMutationStatus } = req('runtime/local/localDailyLogCompleteState.ts');
const { importPersonalTransfer } = req('transfer/e2_15/transferImporter.ts');
const recovery = req('features/logging/recovery/logMutationRecovery.ts');
const OWNER = '00000000-0000-4000-8000-000000000001';
const DATE = '2026-10-12';
const now = () => new Date('2026-10-13T12:00:00Z');
const authority = req('runtime/authorityIdentity.ts').localAuthorityIdentity(OWNER);
const uuid = () => crypto.randomUUID();
const json = p => JSON.parse(fs.readFileSync(p,'utf8'));
const save = (p,v) => fs.writeFileSync(p,JSON.stringify(v,null,2));
const plain = v => JSON.parse(JSON.stringify(v));
const fixture = req('transfer/e2_15/transferPackage.ts').canonicalTransferJson(json(path.join(source,'packages/shared-contracts/e2-15/representative-package.json')));
async function dump(db) {
  const out = {};
  for (const table of [...SQLITE_SEMANTIC_TABLES,SQLITE_SNAPSHOT_SCOPE_TABLE]) out[table] = await db.getAllAsync(`SELECT * FROM "${table}" ORDER BY rowid`);
  return plain(out);
}
function storage(dir) {
  const p=path.join(dir,'journal.json');
  return { getItem: async k => fs.existsSync(p) ? json(p)[k] ?? null : null,
    setItem: async (k,v) => { const data=fs.existsSync(p)?json(p):{}; data[k]=v; save(p+'.tmp',data); fs.renameSync(p+'.tmp',p); },
    removeItem: async k => { const data=fs.existsSync(p)?json(p):{}; delete data[k]; save(p+'.tmp',data); fs.renameSync(p+'.tmp',p); } };
}
function runtime(db) {
  const logs = createLocalDailyLogsRuntime(db,OWNER,{now});
  const get = logs.getMutationStatus.bind(logs);
  logs.markDayComplete = input => markLocalDailyLogComplete(db,OWNER,input,now);
  logs.getMutationStatus = (id,op) => op==='complete' ? getLocalDailyLogCompleteMutationStatus(db,OWNER,id) : get(id,op);
  return logs;
}
async function perform(logs,m) {
  if(m.operation==='create') return logs.create(m.input);
  if(m.operation==='update') return logs.update(m.targetId,m.input);
  if(m.operation==='delete') return logs.delete(m.targetId,m.input);
  return logs.markDayComplete(m.input);
}
async function setup(dir, operation, boundary) {
  fs.mkdirSync(dir,{recursive:true});
  const db=new DB(path.join(dir,'nutrition.sqlite')); await migrateNutritionDatabase(db);
  const m={operation,boundary};
  if(operation!=='import') {
    await db.runAsync('INSERT INTO users(id,email) VALUES (?,?)',[OWNER,'audit@example.invalid']);
    await db.runAsync("INSERT INTO user_profiles(user_id,authoritative_time_zone,calendar_revision) VALUES (?,'UTC',0)",[OWNER]);
    const food=await createLocalFoodsRuntime(db,OWNER,{now}).create({name:'Synthetic oats',serving_definitions:[{label:'100 g',quantity:'100',unit:'g',gram_weight:'100',is_default:true}],nutrients:[{nutrient_id:'protein',amount:'10',unit:'g',basis:'per_100g',data_status:'known'}]});
    const logs=runtime(db);
    const base={client_request_id:uuid(),calendar_revision:0,food_item_id:food.id,logged_date:DATE,amount_quantity:'1',amount_unit:'serving',serving_definition_id:food.serving_definitions[0].id};
    const log=await logs.create(base); m.targetId=log.id;
    if(operation!=='complete') await logs.markDayComplete({client_request_id:uuid(),calendar_revision:0,logged_date:DATE});
    m.input=operation==='create'?{...base,client_request_id:uuid()} : operation==='update'?{client_request_id:uuid(),calendar_revision:0,amount_quantity:'2'} : operation==='delete'?{client_request_id:uuid(),calendar_revision:0} : {client_request_id:uuid(),calendar_revision:0,logged_date:DATE};
  }
  save(path.join(dir,'before.json'),await dump(db)); save(path.join(dir,'manifest.json'),m); await db.closeAsync();
}
async function pause(label) {
  const keepalive=setInterval(()=>{},1000);
  process.send({checkpoint:label,pid:process.pid});
  await new Promise(()=>{}); clearInterval(keepalive);
}
async function execute(dir) {
  const m=json(path.join(dir,'manifest.json'));
  const db=new DB(path.join(dir,'nutrition.sqlite')); await migrateNutritionDatabase(db);
  if(m.operation!=='import') {
    const rec=recovery.createLogMutationRecoveryRecord({authority,clientRequestId:m.input.client_request_id,mutationType:m.operation==='update'?'edit':m.operation,targetId:m.operation==='create'?null:m.targetId,sourceDate:DATE,displayContext:{item_name:'Synthetic oats',amount_label:'100 g',meal_label:null},payload:m.operation==='create'||m.operation==='complete'?{operation:m.operation,input:m.input}:{operation:m.operation,log_id:m.targetId,input:m.input}});
    await recovery.persistRecoveryBeforeTransmission(rec,storage(dir));
  }
  const original=db.withExclusiveTransactionAsync.bind(db);
  db.withExclusiveTransactionAsync=async fn => {
    if(m.boundary==='before') await pause('before_transaction');
    await original(async tx => {
      await fn(tx);
      if(m.boundary==='precommit') await pause('after_callback_before_commit');
    });
    if(m.boundary==='postcommit') await pause('after_commit_before_return');
  };
  if(m.operation==='import') await importPersonalTransfer(db,fixture,{onCheckpoint:async c=>{if(c===m.boundary)await pause(c);}});
  else await perform(runtime(db),m);
  throw new Error('checkpoint was not reached');
}
async function verify(dir) {
  const m=json(path.join(dir,'manifest.json')),before=json(path.join(dir,'before.json'));
  const db=new DB(path.join(dir,'nutrition.sqlite')); await migrateNutritionDatabase(db);
  const actual=await dump(db); const committed=m.boundary==='postcommit';
  assert.deepEqual(await db.getAllAsync('PRAGMA foreign_key_check'),[]);
  assert.equal((await db.getFirstAsync('PRAGMA integrity_check')).integrity_check,'ok');
  assert.deepEqual(actual[SQLITE_SNAPSHOT_SCOPE_TABLE],[]);
  const result={...m,verifierPid:process.pid,committed,checks:[]};
  if(!committed) {assert.deepEqual(actual,before); result.checks.push('all semantic rows exactly unchanged after SIGKILL');}
  if(m.operation==='import') {
    if(committed) {
      await assert.rejects(importPersonalTransfer(db,fixture),e=>e.code==='target_not_empty');
      assert.deepEqual(await dump(db),actual);
      result.checks.push('committed import preserved; second import refused without mutation');
    } else {
      await importPersonalTransfer(db,fixture);
      result.checks.push('empty target accepts full retry after process death');
    }
    const final=await dump(db); result.counts=Object.fromEntries(Object.entries(final).map(([k,v])=>[k,v.length]));
    for(const c of final.daily_log_day_completions) assert(final.daily_logs.some(l=>l.logged_date===c.logged_date));
    result.checks.push('Complete dates remain backed by transferred Logs');
  } else {
    const logs=runtime(db),records=await recovery.loadLogMutationRecoveryJournal(authority,storage(dir)); assert.equal(records.length,1);
    const status=await logs.getMutationStatus(m.input.client_request_id,m.operation);
    assert.equal(status.status,committed?'confirmed_success':'confirmed_non_commit'); result.status=status;
    const outcome=await recovery.reconcileLogMutationRecoveryRecord(records[0],null,{authority,dailyLogs:logs},{storage:storage(dir)});
    assert.equal(outcome,committed?'confirmed':'retryable');
    if(committed) assert.equal((await recovery.loadLogMutationRecoveryJournal(authority,storage(dir))).length,0);
    else {
      const retry=(await recovery.loadLogMutationRecoveryJournal(authority,storage(dir)))[0];
      assert.equal(await recovery.retryLogMutationRecoveryRecord(retry,null,{authority,dailyLogs:logs},storage(dir)),'confirmed');
    }
    const settled=await dump(db),summary=await logs.getDailySummary(DATE);
    const expectedLogs=m.operation==='create'?2:m.operation==='delete'?0:1;
    assert.equal(settled.daily_logs.length,expectedLogs);
    const protein=summary.totals.find(x=>x.nutrientId==='protein');
    assert.equal(Number(protein?.amountKnown??0),m.operation==='create'||m.operation==='update'?20:m.operation==='delete'?0:10);
    assert.equal(summary.is_complete,m.operation==='complete');
    await perform(logs,m); assert.deepEqual(await dump(db),settled);
    assert.equal((await recovery.loadLogMutationRecoveryJournal(authority,storage(dir))).length,0);
    result.summary=summary; result.checks.push('durable journal reconciled or retried once','exact replay changes no rows','Log count, protein summary and Complete correct');
    if(m.operation==='complete') {
      await logs.update(m.targetId,{client_request_id:uuid(),calendar_revision:0,amount_quantity:'2'});
      assert.equal((await logs.getDailySummary(DATE)).is_complete,false);
      await logs.markDayComplete(m.input);
      assert.equal((await logs.getDailySummary(DATE)).is_complete,false);
      result.checks.push('old Complete replay after nutrition edit does not restore Complete');
    }
  }
  await db.closeAsync(); save(path.join(dir,'result.json'),result); console.log('PASS',m.operation,m.boundary,JSON.stringify(result.checks));
}
async function main() {
  if(process.argv[2]==='execute') return execute(process.argv[3]);
  if(process.argv[2]==='verify') return verify(process.argv[3]);
  const root=process.argv[3]; assert(root, 'owned temporary directory is required');console.log('RUN_ROOT',root);
  const cases=[];
  for(const op of (process.argv[2]==='imports' ? [] : ['create','update','delete','complete'])) for(const b of ['before','precommit','postcommit']) cases.push([op,b]);
  for(const b of ['daily_log_nutrient_snapshots','daily_log_day_completions','qualification_exclusions','postcommit'])cases.push(['import',b]);
  for(const [op,b] of cases) {
    const dir=path.join(root,`${op}-${b}`);await setup(dir,op,b);
    const evidence=await new Promise((resolve,reject)=>{
      const child=fork(__filename,['execute',dir],{silent:true});let out='',err='',marker;
      child.stdout.on('data',x=>out+=x);child.stderr.on('data',x=>err+=x);
      const timer=setTimeout(()=>{child.kill('SIGKILL');reject(new Error('checkpoint timeout '+dir));},15000);
      child.on('message',m=>{marker=m;child.kill('SIGKILL');});
      child.on('exit',(code,signal)=>{clearTimeout(timer);fs.writeFileSync(path.join(dir,'child.log'),out+err);if(!marker||signal!=='SIGKILL')return reject(new Error('unexpected child exit '+out+err));resolve({marker,code,signal});});
    }); save(path.join(dir,'kill.json'),evidence);
    const check=spawnSync(process.execPath,[__filename,'verify',dir],{encoding:'utf8',timeout:15000});
    fs.writeFileSync(path.join(dir,'verify.log'),check.stdout+check.stderr);process.stdout.write(check.stdout);if(check.status!==0)throw new Error(check.stderr);
  }
  save(path.join(root,'results.json'),cases.map(([op,b])=>json(path.join(root,`${op}-${b}`,'result.json'))));
}
module.exports={DB,req,source,recovery,runtime,storage,setup,dump,OWNER,DATE,authority,now,save,json,fixture};
if(require.main===module)main().catch(e=>{console.error(e);process.exitCode=1;});
