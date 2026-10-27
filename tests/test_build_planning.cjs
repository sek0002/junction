const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../app/static/app.js'),'utf8');
const code=source.slice(source.indexOf('const planInputTimers='),source.indexOf('function renderBuildList()'));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function setup(){
  const nodes=new Map(),calls=[];
  const state={buildList:[],plasmids:[{id:1,name:'Backbone A'},{id:2,name:'Backbone B'}],fragments:[],activeBuildId:null,parts:[]};
  const $=id=>{if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',innerHTML:'',classList:{toggle(){}},setAttribute(){},removeAttribute(){},checkValidity:()=>true,reportValidity(){},querySelector:()=>null,querySelectorAll:()=>[],contains:()=>false});return nodes.get(id);};
  const context=vm.createContext({state,$,esc:String,document:{activeElement:null},console,setTimeout,clearTimeout,toast(){},inventoryQuantity:String,updateBackboneVolume(){},persistPendingBuild:async()=>{},api:(url,options)=>new Promise((resolve,reject)=>calls.push({url,options,resolve,reject}))});
  vm.runInContext('let buildWriteChain=Promise.resolve();'+code,context);
  vm.runInContext('renderBuildList=()=>{};updateBuildPlanOutputs=()=>{};loadResuspension=()=>{};checkAssembly=()=>{};replaceBuild=item=>{state.buildList[state.buildList.findIndex(i=>i.id===item.id)]=item;}',context);
  return{state,$,context,calls,read:expression=>vm.runInContext(expression,context)};
}
const item=(id,backbone,stock=100)=>({id,request:{name:'Build '+id,backbone_id:backbone,fragment_ids:[1],settings:{insert_ratio:1,backbone_stock_ng_ul:stock}}});
test('backbones are grouped by identity and switching never leaks another stock',()=>{
  const s=setup();s.state.buildList=[item(1,1),item(2,1),item(3,2,50),{id:4,request:{starter_fragment_id:1,settings:{backbone_stock_ng_ul:5}}}];
  const groups=s.context.backboneStockGroups();assert.equal(groups.length,3);assert.equal(groups[0].items.length,2);
  s.context.switchBackboneStock(s.state.plasmids[0]);assert.equal(s.$('backbone-stock').value,100);
  s.$('backbone-stock').value='125';s.context.switchBackboneStock(s.state.plasmids[1]);assert.equal(s.$('backbone-stock').value,50);
  s.context.switchBackboneStock(s.state.plasmids[0]);assert.equal(s.$('backbone-stock').value,125);
  s.context.switchBackboneStock(null);assert.equal(s.$('backbone-stock').value,'');
});
test('rapid row edits are serialized and an earlier response cannot clear a newer draft',async()=>{
  const s=setup();s.state.buildList=[item(1,1)];
  const input=value=>({value,dataset:{buildId:'1',buildSetting:'insert_ratio'},checkValidity:()=>true});
  const one=s.context.saveBuildPlanField(input('2'));await tick();const two=s.context.saveBuildPlanField(input('3'));await tick();
  assert.equal(s.calls.length,1);assert.deepEqual(JSON.parse(s.calls[0].options.body),{insert_ratio:2});
  s.calls[0].resolve({...item(1,1),request:{...item(1,1).request,settings:{insert_ratio:2}}});await tick();
  assert.equal(s.calls.length,2);assert.equal(s.read('planRowDrafts.get(1).insert_ratio'),3);
  assert.deepEqual(JSON.parse(s.calls[1].options.body),{insert_ratio:3});
  s.calls[1].resolve({...item(1,1),request:{...item(1,1).request,settings:{insert_ratio:3}}});await Promise.all([one,two]);
  assert.equal(s.state.buildList[0].request.settings.insert_ratio,3);assert.equal(s.read('planRowDrafts.size'),0);
});
test('a grouped stock update targets one backbone and retains other backbone settings',async()=>{
  const s=setup();s.state.buildList=[item(1,1),item(2,1),item(3,2,50)];
  const operation=s.context.applyBackboneStock('plasmid',1,{value:'80',checkValidity:()=>true});await tick();
  assert.equal(s.calls.length,1);assert.deepEqual(JSON.parse(s.calls[0].options.body),{kind:'plasmid',id:1,stock_ng_ul:80});
  s.calls[0].resolve({items:[item(1,1,80),item(2,1,80)]});await operation;
  assert.deepEqual(s.state.buildList.map(i=>i.request.settings.backbone_stock_ng_ul),[80,80,50]);
});
test('export flushes debounced edits once and invalid edits cancel pending writes',()=>{
  const s=setup();let commits=0;const input={checkValidity:()=>true,setAttribute(){}};
  s.context.queuePlanInput(input,'row:1:insert_ratio',()=>commits++);
  s.context.queuePlanInput(input,'row:1:insert_ratio',()=>commits++);
  s.context.flushPlanInputs();assert.equal(commits,1);assert.equal(s.read('planInputTimers.size'),0);
  s.context.queuePlanInput(input,'row:1:insert_ratio',()=>commits++);
  s.context.queuePlanInput({...input,checkValidity:()=>false},'row:1:insert_ratio',()=>commits++);
  s.context.flushPlanInputs();assert.equal(commits,1);
});

test('backbone dropdown preserves selection, mixed stocks and independent current stock',()=>{
  const s=setup();s.state.buildList=[item(1,1),item(2,1,120),item(3,2,50)];
  s.$('backbone').value='p:1';s.context.switchBackboneStock(s.state.plasmids[0]);s.context.renderBackboneStocks();
  assert.equal(s.$('backbone-stock-select').value,'plasmid:1');
  assert.equal(s.$('planner-backbone-stock').value,'');assert.equal(s.$('planner-backbone-stock').placeholder,'Mixed stocks');
  s.$('backbone-stock').value='100';s.$('backbone-stock-select').value='plasmid:2';s.context.selectPlannerBackboneStock();
  assert.equal(s.$('planner-backbone-stock').value,50);assert.equal(s.$('backbone-stock').value,'100');
  s.context.renderBackboneStocks();assert.equal(s.$('backbone-stock-select').value,'plasmid:2');
  s.state.buildList=[item(1,1)];s.context.renderBackboneStocks();assert.equal(s.$('backbone-stock-select').value,'plasmid:1');
  s.state.buildList=[];s.$('backbone').value='';s.context.switchBackboneStock(null);s.context.renderBackboneStocks();
  assert.ok(s.$('planner-backbone-stock').disabled);assert.ok(s.$('backbone-stock-select').disabled);
});
test('switching dropdown flushes the previous stock to its captured backbone only',async()=>{
  const s=setup();s.state.buildList=[item(1,1),item(2,1),item(3,2,50)];
  s.context.renderBackboneStocks();s.$('planner-backbone-stock').value='80';s.context.editPlannerBackboneStock();
  s.$('backbone-stock-select').value='plasmid:2';s.context.selectPlannerBackboneStock();
  assert.equal(s.$('planner-backbone-stock').value,50);await tick();
  assert.deepEqual(JSON.parse(s.calls[0].options.body),{kind:'plasmid',id:1,stock_ng_ul:80});
  s.calls[0].resolve({items:[item(1,1,80),item(2,1,80)]});await tick();await tick();
  assert.deepEqual(s.state.buildList.map(i=>i.request.settings.backbone_stock_ng_ul),[80,80,50]);
  assert.equal(s.$('planner-backbone-stock').value,50);assert.equal(s.$('backbone-stock').value,'');
});
