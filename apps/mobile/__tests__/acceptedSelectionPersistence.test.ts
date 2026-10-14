// Accepted task-9 passing rendered/persistence controls. The fixed defect is covered in logServingReplacement.test.ts.
jest.mock("@expo/vector-icons", () => ({Ionicons: "Ionicons"}));
import React from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { Pressable, TextInput } from "react-native";
import TestRenderer, { act, type ReactTestRenderer } from "react-test-renderer";

import type { Food, FoodResolvedNutrition, ResolvedFoodAmount } from "../src/features/foods/api/types";
import type {
  DailyLog,
  DailyLogCreateInput,
  DailyLogUpdateInput,
} from "../src/features/logging/api/types";
import { LogFoodScreen } from "../src/features/logging/screens/LogFoodScreen";
import { loadLogMutationRecoveryJournal as loadRecoveryJournalWithAuthority } from "../src/features/logging/recovery/logMutationRecovery";
import { remoteNutritionRuntime } from "../src/runtime/remote/remoteNutritionRuntime";
import { createNutritionTestRuntime, withNutritionRuntime } from "./nutritionRuntimeTestSupport";

type Deferred = {
  promise: Promise<unknown>;
  resolve: (value?: unknown) => void;
  reject: (reason?: unknown) => void;
};

const mockUpdateFood = jest.fn();
const mockUpdateRecipe = jest.fn();
let mockFoodQuery: Record<string, unknown>;
let mockResolvedQuery: Record<string, unknown>;
let mockEditContextQuery: Record<string, unknown>;
let mockCreateDeferred: Deferred;
let mockUpdateDeferred: Deferred;
let mockRequestIds: string[];
const activeRenderers = new Set<ReactTestRenderer>();
const mockCreateLog = jest.fn((_input: DailyLogCreateInput) => mockCreateDeferred.promise);
const mockUpdateLog = jest.fn((
  _params: { logId: string; input: Partial<DailyLogUpdateInput> },
) => mockUpdateDeferred.promise);
const mockCreateClientRequestId = jest.fn(() => mockRequestIds.shift() as string);
const testRuntime = createNutritionTestRuntime({
  dailyLogs: {
    ...remoteNutritionRuntime.dailyLogs,
    create: async (input) => await mockCreateLog(input) as DailyLog,
    update: async (logId, input) => await mockUpdateLog({ logId, input }) as DailyLog,
  },
});

function loadLogMutationRecoveryJournal() {
  return loadRecoveryJournalWithAuthority(testRuntime.authority);
}

jest.mock("../src/features/foods/hooks/useFoods", () => ({
  useFood: () => mockFoodQuery,
  useFoodResolvedNutrition: () => mockResolvedQuery,
  useFoodMutations: () => ({deleteFood:{isPending:false},setFavorite:{isPending:false},duplicateFood:{isPending:false},updateFood:{mutateAsync:mockUpdateFood,isPending:false},createFood:{mutateAsync:jest.fn(),isPending:false}}),
  useNutrients: () => ({data:[],isLoading:false,isError:false}),
}));

jest.mock("../src/features/logging/hooks/useLogs", () => ({
  useLogEditContext: () => mockEditContextQuery,
  useLogMutations: () => ({
    createLog: { mutateAsync: mockCreateLog },
    updateLog: { mutateAsync: mockUpdateLog },
  }),
}));

jest.mock("../src/features/logging/utils/clientRequestId", () => ({
  createClientRequestId: () => mockCreateClientRequestId(),
}));

const food: Food = {
  id: "food-1",
  name: "Submission Food",
  source_type: "manual",
  source_id: null,
  is_recipe: false,
  source_kind: "manual", source_label: "Manual", is_favorite: false, can_favorite: true,
  updated_at: "2026-07-13T12:00:00+00:00",
  serving_definitions: [
    {
      id: "default-serving",
      label: "Default serving",
      quantity: "1",
      unit: "serving",
      gram_weight: "100",
      is_default: true,
      source: "manual",
      is_user_confirmed: true,
    },
    {
      id: "selected-serving",
      label: "Selected serving",
      quantity: "1",
      unit: "serving",
      gram_weight: "150",
      is_default: false,
      source: "manual",
      is_user_confirmed: true,
    },
  ],
  nutrients: [],
};

function amount(id: string, quantity: string, isDefault = false): ResolvedFoodAmount {
  return {
    amount_definition_id: id,
    display_label: id === "default-serving" ? "Default serving" : "Selected serving",
    is_default: isDefault,
    entered_quantity: quantity,
    semantic_amount_mode: "serving",
    resolved_grams: "100",
    valid_for_logging: true,
    nutrients: [],
  };
}

const resolvedNutrition: FoodResolvedNutrition = {
  nutrition_authority: "food_item",
  recipe_id: null,
  recipe_publication_revision_id: null,
  amounts: [
    amount("default-serving", "1", true),
    amount("selected-serving", "2.5"),
  ],
};

function deferred(): Deferred {
  let resolve!: (value?: unknown) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<unknown>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

beforeEach(async () => {
  await AsyncStorage.clear();
  await loadLogMutationRecoveryJournal();
  mockCreateDeferred = deferred();
  mockUpdateDeferred = deferred();
  mockUpdateFood.mockClear();
  mockUpdateRecipe.mockClear();
  mockCreateLog.mockClear();
  mockUpdateLog.mockClear();
  mockCreateClientRequestId.mockClear();
  mockRequestIds = [
    "00000000-0000-4000-8000-000000000001",
    "00000000-0000-4000-8000-000000000002",
    "00000000-0000-4000-8000-000000000003",
    "00000000-0000-4000-8000-000000000004",
  ];
  mockFoodQuery = {
    data: food,
    isLoading: false,
    isError: false,
    error: null,
    refetch: jest.fn(),
  };
  mockResolvedQuery = {
    data: resolvedNutrition,
    isLoading: false,
    isFetching: false,
    isError: false,
    error: null,
    refetch: jest.fn(),
  };
  mockEditContextQuery = {
    data: undefined,
    isLoading: false,
    isError: false,
    error: null,
  };
});

afterEach(async () => {
  await act(async () => {
    activeRenderers.forEach((renderer) => {
      try {
        void renderer.root;
        renderer.unmount();
      } catch {
        // The test already unmounted this renderer.
      }
    });
  });
  activeRenderers.clear();
});

async function render(element: React.ReactElement): Promise<ReactTestRenderer> {
  let renderer: ReactTestRenderer | undefined;
  await act(async () => {
    renderer = TestRenderer.create(withNutritionRuntime(element, testRuntime));
  });
  const mountedRenderer = renderer as ReactTestRenderer;
  activeRenderers.add(mountedRenderer);
  return mountedRenderer;
}

import * as Crypto from 'expo-crypto';
import { LocalSQLiteTestDatabase } from './localSQLiteTestSupport';
import { migrateNutritionDatabase } from '../src/storage/sqlite/migrations';
import { createLocalFoodsRuntime } from '../src/runtime/local/localFoodsRuntime';
import { createLocalRecipesRuntime } from '../src/runtime/local/localRecipesRuntime';
import { createLocalDailyLogsRuntime } from '../src/runtime/local/localDailyLogsRuntime';
const fs = require('node:fs'), path = require('node:path');
const { tmpdir } = require('node:os');
const auditRoot = fs.mkdtempSync(path.join(tmpdir(), 'nutrition-selection-controls-'));
afterAll(() => fs.rmSync(auditRoot, { recursive: true, force: true }));
const owner='00000000-0000-4000-8000-000000000001';
async function fixture(grams='100') {
  let n=1000;(Crypto.randomUUID as jest.Mock).mockImplementation(()=>`00000000-0000-4000-8000-${(++n).toString().padStart(12,'0')}`);
  const dir=fs.mkdtempSync(path.join(auditRoot,'db-')); const dbPath=path.join(dir,'synthetic.sqlite'); const db=new LocalSQLiteTestDatabase(dbPath); await migrateNutritionDatabase(db.asExpoDatabase());
  await db.runAsync('INSERT INTO users(id,email) VALUES (?,?)',[owner,'audit@example.invalid']);
  await db.runAsync("INSERT INTO user_profiles(user_id,authoritative_time_zone,calendar_revision) VALUES (?,'UTC',0)",[owner]);
  let tick=0; const now=()=>new Date(Date.parse('2026-07-13T12:00:00Z')+(tick++)*1000);
  const foods=createLocalFoodsRuntime(db.asExpoDatabase(),owner,{now});
  const recipes=createLocalRecipesRuntime(db.asExpoDatabase(),owner,{now});
  const logs=createLocalDailyLogsRuntime(db.asExpoDatabase(),owner,{now});
  const f=await foods.create({name:'Audit food',serving_definitions:[{label:grams+' g',quantity:grams,unit:'g',gram_weight:grams,is_default:true}],nutrients:[{nutrient_id:'protein',amount:'40',unit:'g',basis:'per_100g',data_status:'known'}]});
  mockCreateLog.mockImplementation(async input=>logs.create(input));
  mockUpdateLog.mockImplementation(async ({logId,input})=>logs.update(logId,input));
  mockUpdateFood.mockImplementation(async ({foodId,input})=>foods.update(foodId,input));
  return {db,dbPath,foods,recipes,logs,f};
}
function showFood(f:Food,resolved:FoodResolvedNutrition){mockFoodQuery={data:f,isLoading:false,isError:false,refetch:jest.fn()};mockResolvedQuery={data:resolved,isLoading:false,isError:false,isFetching:false,refetch:jest.fn()};}
function record(_name:string, _value:unknown) { /* Original observation output remains in retained audit evidence. */ }

async function twoServingFixture(){
 const x=await fixture();
 const f=await x.foods.update(x.f.id,{name:'Audit food',serving_definitions:[{label:'100 g',quantity:'100',unit:'g',gram_weight:'100',is_default:true},{label:'1 slice',quantity:'1',unit:'slice',gram_weight:'50',is_default:false}],nutrients:[{nutrient_id:'protein',amount:'40',unit:'g',basis:'per_100g',data_status:'known'}]});
 return {...x,f};
}
async function editScreen(x:any,log:any,onCancel=jest.fn()){
 showFood(await x.foods.get(x.f.id),await x.foods.getResolvedNutrition(x.f.id));
 mockEditContextQuery={data:await x.logs.getEditContext(log.id),isLoading:false,isError:false};
 return render(React.createElement(LogFoodScreen,{foodId:x.f.id,date:'2026-07-13',calendarRevision:0,initialCalendarRevision:0,log,showMealAndNotes:true,strictSourceReview:true,onSaved:jest.fn(),onCancel}));
}
async function press(renderer:any,label:string){await act(async()=>{await renderer.root.findByProps({accessibilityLabel:label}).props.onPress();});}
async function change(renderer:any,label:string,value:string){await act(async()=>renderer.root.findByProps({accessibilityLabel:label}).props.onChangeText(value));}
async function snapshots(db:any){return db.getAllAsync('SELECT amount,consumed_gram_amount,consumed_amount_quantity,serving_definition_id FROM daily_log_nutrient_snapshots');}
function radios(renderer:any){return renderer.root.findAllByType(Pressable).filter((n:any)=>n.props.accessibilityRole==='radio').map((n:any)=>({label:n.props.accessibilityLabel,state:n.props.accessibilityState}));}


test('AUDIT changed Food alternate serving selected explicitly persists choice',async()=>{
 const x=await twoServingFixture();try{
 const base=x.f.serving_definitions.find((s:any)=>s.is_default)!;
 await x.logs.create({client_request_id:Crypto.randomUUID(),calendar_revision:0,food_item_id:x.f.id,logged_date:'2026-07-13',amount_quantity:'1',amount_unit:'serving',serving_definition_id:base.id});
 x.f=await x.foods.update(x.f.id,{...x.f,name:'Renamed audit food'});
 const log=(await x.logs.list('2026-07-13'))[0];const renderer=await editScreen(x,log);
 await press(renderer,'1 slice, 50g');await press(renderer,'Save changes');
 const after=await snapshots(x.db);record('replaced-food-alternate-control',{dbPath:x.dbPath,input:mockUpdateLog.mock.calls,after});
 expect(after[0].consumed_gram_amount).toBe('50.000000');expect(after[0].amount).toBe('20.000000');
 }finally{x.db.close();}
});

test('AUDIT ordinary edit cancel and reopen preserves original saved portion',async()=>{
 const x=await twoServingFixture();try{
 const slice=x.f.serving_definitions.find((s:any)=>s.label==='1 slice')!;
 const log=await x.logs.create({client_request_id:Crypto.randomUUID(),calendar_revision:0,food_item_id:x.f.id,logged_date:'2026-07-13',amount_quantity:'2',amount_unit:'serving',serving_definition_id:slice.id});
 const before=await snapshots(x.db);const cancel=jest.fn();const renderer=await editScreen(x,log,cancel);
 await change(renderer,'Amount quantity','3');await press(renderer,'Grams');await change(renderer,'Notes','Canceled note');
 const cancelLabels=renderer.root.findAllByType(Pressable).map((n:any)=>n.props.accessibilityLabel).filter((s:any)=>/Cancel/i.test(s));
 await press(renderer,cancelLabels[0]);expect(cancel).toHaveBeenCalledTimes(1);expect(mockUpdateLog).not.toHaveBeenCalled();
 await act(async()=>renderer.unmount());
 const loaded=(await x.logs.list('2026-07-13'))[0];const reopened=await editScreen(x,loaded);const after=await snapshots(x.db);
 record('cancel-edit-control',{dbPath:x.dbPath,before,after,loaded,radios:radios(reopened)});
 expect(after).toEqual(before);expect(loaded.notes).toBeNull();expect(reopened.root.findByProps({accessibilityLabel:'Amount quantity'}).props.value).toBe('2');
 expect(reopened.root.findByProps({accessibilityLabel:'1 slice, 50g'}).props.accessibilityState.selected).toBe(true);
 }finally{x.db.close();}
});

import { FoodFormScreen } from '../src/features/foods/screens/FoodFormScreen';
async function openUnit(renderer:any){
 const label=renderer.root.findAllByType(Pressable).map((n:any)=>n.props.accessibilityLabel).find((s:any)=>s?.startsWith('Choose unit for'));
 if(!label)throw new Error('missing public unit picker');await press(renderer,label);
}
test('AUDIT Food unit change saves accepted descriptor and unchanged physical grams',async()=>{
 const x=await twoServingFixture();try{
 const renderer=await render(React.createElement(FoodFormScreen,{food:x.f,onSaved:jest.fn(),onCancel:jest.fn()}));
 await press(renderer,'Edit 1 slice');await openUnit(renderer);await press(renderer,'cup');
 await change(renderer,'Serving quantity','0.25');
 await press(renderer,'Save food');
 expect(mockUpdateFood).toHaveBeenCalledTimes(1);
 const saved=await x.foods.get(x.f.id);const cup=saved.serving_definitions.find((s:any)=>s.unit==='cup')!;
 const reopened=await render(React.createElement(FoodFormScreen,{food:saved,onSaved:jest.fn(),onCancel:jest.fn()}));
 await press(reopened,'Edit 1/4 cup');
 record('food-unit-save-control',{dbPath:x.dbPath,input:mockUpdateFood.mock.calls,cup,fields:reopened.root.findAllByType(TextInput).map((n:any)=>({label:n.props.accessibilityLabel,value:n.props.value}))});
 expect(cup.quantity).toBe('0.250000');expect(cup.gram_weight).toBe('50.000000');
 expect(reopened.root.findByProps({accessibilityLabel:'Serving quantity'}).props.value).toBe('0.25');
 expect(reopened.root.findByProps({accessibilityLabel:'Serving grams'}).props.value).toBe('50');
 }finally{x.db.close();}
});
test('AUDIT Food unit-picker draft cancel and Food edit cancel do not persist',async()=>{
 const x=await twoServingFixture();try{
 const before=await x.foods.get(x.f.id);const cancel=jest.fn();
 const renderer=await render(React.createElement(FoodFormScreen,{food:before,onSaved:jest.fn(),onCancel:cancel}));
 await press(renderer,'Edit 1 slice');await openUnit(renderer);await press(renderer,'Custom unit');
 const inputs=renderer.root.findAllByType(TextInput).map((n:any)=>({label:n.props.accessibilityLabel,value:n.props.value}));
 record('picker-custom-input-labels',inputs);
 const custom=renderer.root.findAllByType(TextInput).find((n:any)=>n.props.accessibilityLabel==='Custom unit name');
 if(!custom)throw new Error('missing editable custom unit field');
 await act(async()=>custom.props.onChangeText('audit scoop'));
 await press(renderer,'Cancel choosing unit');
 expect(renderer.root.findByProps({accessibilityLabel:'Unit'}).props.value).toBe('slice');
 await openUnit(renderer);await press(renderer,'cup');await change(renderer,'Serving grams','75');
 await press(renderer,'Cancel editing food');expect(cancel).toHaveBeenCalledTimes(1);expect(mockUpdateFood).not.toHaveBeenCalled();
 const after=await x.foods.get(x.f.id);const fresh=new LocalSQLiteTestDatabase(x.dbPath);const rows=await fresh.getAllAsync('SELECT label,quantity,unit,gram_weight FROM serving_definitions WHERE food_item_id=?',[x.f.id]);fresh.close();
 record('food-cancel-control',{dbPath:x.dbPath,before,after,rows});expect(after).toEqual(before);
 }finally{x.db.close();}
});

import { FoodDetailsScreen } from '../src/features/foods/screens/FoodDetailsScreen';
test.each(['save','cancel'])('AUDIT Food Details chosen portion to Log confirmation %s',async(action)=>{
 const x=await twoServingFixture();try{
 showFood(x.f,await x.foods.getResolvedNutrition(x.f.id));const handoff=jest.fn();
 const detail=await render(React.createElement(FoodDetailsScreen,{foodId:x.f.id,onBack:jest.fn(),onDeleted:jest.fn(),onEdit:jest.fn(),onLog:handoff}));
 const choice=detail.root.findAllByType(Pressable).find((n:any)=>n.props.accessibilityRole==='radio'&&n.props.accessibilityLabel?.startsWith('1 slice'))!;
 if(!choice)throw new Error('missing visible slice choice');await act(async()=>choice.props.onPress());await press(detail,'Log food');
 const cancel=jest.fn();const screen=await render(React.createElement(LogFoodScreen,{foodId:x.f.id,date:'2026-07-13',calendarRevision:0,initialAmount:handoff.mock.calls[0][0],showMealAndNotes:true,strictSourceReview:true,onSaved:jest.fn(),onCancel:cancel}));
 if(action==='save'){
 await press(screen,'Save log');const saved=(await x.logs.list('2026-07-13'))[0];const rows=await snapshots(x.db);
 const reopened=await editScreen(x,saved);record('details-log-save-control',{dbPath:x.dbPath,handoff:handoff.mock.calls,rows,radios:radios(reopened)});
 expect(rows[0].amount).toBe('20.000000');expect(rows[0].consumed_gram_amount).toBe('50.000000');
 expect(reopened.root.findByProps({accessibilityLabel:'1 slice, 50g'}).props.accessibilityState.selected).toBe(true);
 }else{
 const label=screen.root.findAllByType(Pressable).map((n:any)=>n.props.accessibilityLabel).find((s:any)=>s?.includes('Cancel'))!;
 await press(screen,label);expect(cancel).toHaveBeenCalledTimes(1);expect(mockCreateLog).not.toHaveBeenCalled();expect(await x.logs.list('2026-07-13')).toEqual([]);record('details-log-cancel-control',{dbPath:x.dbPath,rows:await snapshots(x.db)});
 }
 }finally{x.db.close();}
});
test('AUDIT Log unit change saves explicit grams and reopens in grams',async()=>{
 const x=await twoServingFixture();try{
 const log=await x.logs.create({client_request_id:Crypto.randomUUID(),calendar_revision:0,food_item_id:x.f.id,logged_date:'2026-07-13',amount_quantity:'1',amount_unit:'serving',serving_definition_id:x.f.serving_definitions.find((s:any)=>s.label==='1 slice')!.id});
 const screen=await editScreen(x,log);await press(screen,'Grams');await change(screen,'Amount quantity','75');await press(screen,'Save changes');
 const loaded=(await x.logs.list('2026-07-13'))[0];const rows=await snapshots(x.db);const reopened=await editScreen(x,loaded);
 record('log-unit-save-control',{dbPath:x.dbPath,input:mockUpdateLog.mock.calls,loaded,rows,radios:radios(reopened)});
 expect(rows[0].amount).toBe('30.000000');expect(loaded.amount_unit).toBe('g');expect(loaded.amount_quantity).toBe('75.000000');expect(reopened.root.findByProps({accessibilityLabel:'Amount quantity'}).props.value).toBe('75');expect(reopened.root.findByProps({accessibilityLabel:'Grams'}).props.accessibilityState.selected).toBe(true);
 }finally{x.db.close();}
});
test('AUDIT changed Food metadata-only edit preserves historical physical quantity',async()=>{
 const x=await twoServingFixture();try{
 await x.logs.create({client_request_id:Crypto.randomUUID(),calendar_revision:0,food_item_id:x.f.id,logged_date:'2026-07-13',amount_quantity:'1',amount_unit:'serving',serving_definition_id:x.f.serving_definitions.find((s:any)=>s.label==='1 slice')!.id});
 x.f=await x.foods.update(x.f.id,{...x.f,name:'Renamed audit food'});const log=(await x.logs.list('2026-07-13'))[0];const before=await snapshots(x.db);const screen=await editScreen(x,log);
 await change(screen,'Notes','Metadata only');await press(screen,'Save changes');const after=await snapshots(x.db);record('changed-food-note-control',{dbPath:x.dbPath,before,after,input:mockUpdateLog.mock.calls});expect(after).toEqual(before);expect(mockUpdateLog.mock.calls[0][0].input).not.toHaveProperty('amount_quantity');
 }finally{x.db.close();}
});

import { RecipeFormScreen } from '../src/features/recipes/screens/RecipeFormScreen';
import { recipeToDraft, type RecipeDraft } from '../src/features/recipes/utils/recipeDraft';
jest.mock('../src/features/recipes/hooks/useRecipes',()=>({useRecipeMutations:()=>({updateRecipe:{mutateAsync:mockUpdateRecipe,isPending:false,isError:false},createRecipe:{isPending:false,isError:false}})}));
function RecipeHarness({initial,onCancel}:{initial:RecipeDraft;onCancel:any}){
 const [draft,setDraft]=React.useState(initial);
 return React.createElement(RecipeFormScreen,{draft,setDraft,draftBaseline:initial,onCancel,onSaved:jest.fn(),onAddIngredient:jest.fn(),onManageServingSizes:jest.fn()});
}
test.each(['save','cancel'])('AUDIT Recipe ingredient choice %s persists only accepted changes',async(action)=>{
 const x=await twoServingFixture();try{
 const recipe=await x.recipes.create({name:'Selection recipe',serving_count_yield:'2',ingredients:[{food_item_id:x.f.id,position:0,amount_quantity:'1',amount_unit:'serving',serving_definition_id:x.f.serving_definitions.find((s:any)=>s.label==='1 slice')!.id}]});
 mockUpdateRecipe.mockImplementation(async({recipeId,input})=>x.recipes.update(recipeId,input));
 const original=await x.recipes.get(recipe.id);const init=recipeToDraft(original,[x.f]);if(!init.ok)throw new Error('bad recipe fixture');
 const cancel=jest.fn();const screen=await render(React.createElement(RecipeHarness,{initial:init.draft,onCancel:cancel}));
 await press(screen,'Select saved serving for Audit food');
 const options=screen.root.findAllByType(Pressable).filter((n:any)=>n.props.accessibilityRole==='radio').map((n:any)=>n.props.accessibilityLabel);
 const label=options.find((s:any)=>s==='100 g'||s?.includes('100 g'))!;
 if(!label)throw new Error('missing 100g serving option '+JSON.stringify(options));await press(screen,label);
 await change(screen,'Audit food number of servings','2');
 await press(screen,action==='save'?'Save Recipe':'Cancel Recipe editing');
 const loaded=await x.recipes.get(recipe.id);record('recipe-selection-'+action+'-control',{dbPath:x.dbPath,original,input:mockUpdateRecipe.mock.calls,loaded});
 if(action==='save'){
 expect(mockUpdateRecipe).toHaveBeenCalledTimes(1);expect(loaded.ingredients[0].serving_definition_id).toBe(x.f.serving_definitions.find((s:any)=>s.is_default)!.id);expect(loaded.ingredients[0].amount_quantity).toBe('2.000000');
 const next=recipeToDraft(loaded,[x.f]);if(!next.ok)throw new Error('reopen failed');const reopened=await render(React.createElement(RecipeHarness,{initial:next.draft,onCancel:jest.fn()}));expect(reopened.root.findByProps({accessibilityLabel:'Audit food number of servings'}).props.value).toBe('2');expect(reopened.root.findByProps({accessibilityLabel:'Select saved serving for Audit food'}).props.accessibilityHint).toContain('100 g');
 }else{expect(mockUpdateRecipe).not.toHaveBeenCalled();expect(cancel).toHaveBeenCalledTimes(1);expect(loaded).toEqual(original);}
 }finally{x.db.close();}
});
