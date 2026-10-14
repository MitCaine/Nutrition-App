// Authored literal oracle from accepted task-7 Fraction/Decimal controls; no application-derived expectations.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const {DB,req,setDirectory}=require('./acceptedRuntimeAdapter.cjs');const root=process.argv[2]; assert(root, 'owned temporary directory is required');setDirectory(root);
const owner='00000000-0000-4000-8000-000000000001',now=()=>new Date('2026-10-13T12:00:00Z'),uuid=()=>crypto.randomUUID();const output={root,checks:[]};
const check=(name,actual,expected)=>{assert.deepEqual(actual,expected,name);output.checks.push({name,actual,expected});console.log('PASS',name,JSON.stringify(actual));};
(async()=>{
let db=new DB(path.join(root,'synthetic.sqlite'));await req('storage/sqlite/migrations.ts').migrateNutritionDatabase(db);
await db.runAsync('INSERT INTO users(id,email) VALUES (?,?)',[owner,'audit@example.invalid']);await db.runAsync("INSERT INTO user_profiles(user_id,authoritative_time_zone,calendar_revision) VALUES (?,'UTC',0)",[owner]);
const foods=req('runtime/local/localFoodsRuntime.ts').createLocalFoodsRuntime(db,owner,{now}),recipes=req('runtime/local/localRecipesRuntime.ts').createLocalRecipesRuntime(db,owner,{now}),logs=req('runtime/local/localDailyLogsRuntime.ts').createLocalDailyLogsRuntime(db,owner,{now});
for(const c of JSON.parse(fs.readFileSync(path.join(__dirname,'acceptedNutritionOracle.json'))).cases){
 const input={name:'Matrix '+c.i,serving_definitions:[{label:'Measured serving',quantity:'.5'.replace(/^\./,'0.'),unit:'cup',gram_weight:c.grams,is_default:true}],nutrients:[{nutrient_id:'protein',amount:c.amount,unit:c.unit,basis:c.basis,data_status:'known'},{nutrient_id:'sodium',amount:'2.5',unit:'mg',basis:'per_serving',data_status:'estimated'},{nutrient_id:'calcium',amount:'0',unit:'mg',basis:'per_serving',data_status:'zero'},{nutrient_id:'iron',amount:null,unit:'mg',basis:'per_serving',data_status:'unknown'}]};
 // Inputs use the documented leading-zero decimal grammar.
 for(const n of input.nutrients)if(n.amount?.startsWith('.'))n.amount='0'+n.amount;
 const quantity=c.q.startsWith('.')?'0'+c.q:c.q;
 const f=await foods.create(input),sid=f.serving_definitions[0].id;
 const recipe=await recipes.create({name:'Recipe '+c.i,serving_count_yield:'3',ingredients:[{food_item_id:f.id,position:0,amount_quantity:quantity,amount_unit:'serving',serving_definition_id:sid}]});
 const nutrition=await recipes.getNutrition(recipe.id);check(c.i+' recipe total',nutrition.totals.find(x=>x.nutrientId==='protein').amountKnown,c.total);check(c.i+' recipe perServing',nutrition.perServing.find(x=>x.nutrientId==='protein').amountKnown,c.perServing);
 const pub=await recipes.publish({recipeId:recipe.id,clientRequestId:uuid()});
 const parent=await recipes.create({name:'Parent '+c.i,serving_count_yield:'1',ingredients:[{food_item_id:pub.food.id,position:0,amount_quantity:'0.375',amount_unit:'serving',serving_definition_id:pub.food.serving_definitions[0].id}]});check(c.i+' published nested scaling',(await recipes.getNutrition(parent.id)).totals.find(x=>x.nutrientId==='protein').amountKnown,c.nested);
 const payload={client_request_id:uuid(),calendar_revision:0,food_item_id:f.id,logged_date:'2026-10-12',amount_quantity:quantity,amount_unit:'serving',serving_definition_id:sid};const log=await logs.create(payload);
 const snapshots=()=>db.getAllAsync('SELECT nutrient_id,amount,unit,data_status,consumed_amount_quantity,consumed_gram_amount FROM daily_log_nutrient_snapshots WHERE daily_log_id=? ORDER BY nutrient_id',[log.id]);const initial=await snapshots();
 check(c.i+' log persisted rounding',initial.find(x=>x.nutrient_id==='protein').amount,c.log);check(c.i+' zero',[initial.find(x=>x.nutrient_id==='calcium').amount,initial.find(x=>x.nutrient_id==='calcium').data_status],['0.000000','zero']);check(c.i+' unknown',[initial.find(x=>x.nutrient_id==='iron').amount,initial.find(x=>x.nutrient_id==='iron').data_status],[null,'unknown']);check(c.i+' estimated',initial.find(x=>x.nutrient_id==='sodium').data_status,'estimated');
 const summary=await logs.getDailySummary('2026-10-12');
 check(c.i+' independently expected summary',summary.totals.find(x=>x.nutrientId==='protein').amountKnown.replace(/0+$/,'').replace(/\.$/,''),c.summaryCumulative.replace(/0+$/,'').replace(/\.$/,''));
 check(c.i+' independently expected estimated summary',summary.totals.find(x=>x.nutrientId==='sodium').amountEstimated.replace(/0+$/,'').replace(/\.$/,''),c.estimatedCumulative.replace(/0+$/,'').replace(/\.$/,''));
 const revBefore=await db.getAllAsync('SELECT * FROM recipe_publication_nutrients WHERE revision_id IN (SELECT id FROM recipe_publication_revisions WHERE recipe_id=?) ORDER BY id',[recipe.id]);
 assert.equal(revBefore.length,4,'publication control is nonempty');
 await foods.update(f.id,{...input,nutrients:input.nutrients.map(n=>n.nutrient_id==='protein'?{...n,amount:'99'}:n)});
 check(c.i+' Food edit historical snapshot',await snapshots(),initial);check(c.i+' Food edit publication',await db.getAllAsync('SELECT * FROM recipe_publication_nutrients WHERE revision_id IN (SELECT id FROM recipe_publication_revisions WHERE recipe_id=?) ORDER BY id',[recipe.id]),revBefore);check(c.i+' Food edit summary',await logs.getDailySummary('2026-10-12'),summary);
 await logs.update(log.id,{calendar_revision:0,notes:'Only a note'});check(c.i+' note edit immutable',await snapshots(),initial);check(c.i+' exact create replay',await logs.create(payload),log);
}
const before=await logs.getDailySummary('2026-10-12');await db.closeAsync();db=new DB(path.join(root,'synthetic.sqlite'));check('reopen summary',await req('runtime/local/localDailyLogsRuntime.ts').createLocalDailyLogsRuntime(db,owner,{now}).getDailySummary('2026-10-12'),before);await db.closeAsync();fs.writeFileSync(path.join(root,'results.json'),JSON.stringify(output,null,2));console.log('RESULT',root,output.checks.length);
})().catch(e=>{console.error(e);fs.writeFileSync(path.join(root,'results.json'),JSON.stringify({...output,error:{message:e.message,stack:e.stack,...e}},null,2));process.exitCode=1;});
