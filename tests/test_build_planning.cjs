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

function draftSetup(){
  const nodes=new Map(),calls=[],messages=[];
  const draft={name:'Original',enzyme:'BsaI',fragment_ids:[11,12],backbone_id:4,slot_id:'slot_1',circular:true,
    nested_assemblies:[{parent_fragment_id:11,fragment_ids:[13],mode:'separate'}],settings:{insert_ratio:2,backbone_stock_ng_ul:80,fragment_stock_overrides:{11:{stock_ng_ul:20}}}};
  const state={buildList:[{id:1,request:structuredClone(draft)}],activeBuildId:1,parts:[{id:11},{id:12}],buildBusy:false,result:null};
  const $=id=>{if(!nodes.has(id))nodes.set(id,{value:id==='assembly-name'?draft.name:id==='backbone'?'p:4':'',querySelector:()=>null});return nodes.get(id);};
  const context=vm.createContext({state,$,payload:()=>draft,structuredClone,window:{JunctionSandbox:{schedule(){}}},document:{querySelectorAll:()=>[]},setTimeout,clearTimeout,
    toast:message=>messages.push(message),renderBuildList(){},api:(url,options)=>new Promise((resolve,reject)=>calls.push({url,options,resolve,reject}))});
  vm.runInContext(source.slice(source.indexOf('let buildSaveTimer='),source.indexOf('const planInputTimers='))+
    source.slice(source.indexOf('async function loadBuildList()'),source.indexOf('function setPlannerInputs(')),context);
  return{state,draft,$,context,calls,messages,read:expression=>vm.runInContext(expression,context)};
}
test('changing a queued name or fragment selection creates a draft without overwriting the row',async()=>{
  for(const change of [s=>s.draft.name='Variant',s=>s.draft.fragment_ids=[11,14],s=>s.draft.backbone_id=5]){
    const s=draftSetup(),original=structuredClone(s.state.buildList[0]);change(s);
    s.context.scheduleBuildSettingsSave();await s.context.persistPendingBuild();
    assert.equal(s.state.activeBuildId,null);assert.equal(s.calls.length,0);
    assert.deepEqual(s.state.buildList[0],original);
  }
});
test('plus adds independent snapshots repeatedly while retaining the current assembly and settings',async()=>{
  const s=draftSetup(),original=structuredClone(s.state.buildList[0]);
  for(const id of [2,3]){
    const operation=s.context.addCurrentBuild();await tick();
    const call=s.calls.at(-1);assert.equal(call.url,'/api/build-list');assert.equal(call.options.method,'POST');
    assert.deepEqual(JSON.parse(call.options.body),s.draft);
    call.resolve({id,request:{...structuredClone(s.draft),name:'Original ('+id+')'}});await operation;
    assert.equal(s.state.activeBuildId,null);assert.equal(s.$('assembly-name').value,'Original');
    assert.deepEqual(s.state.parts,[{id:11},{id:12}]);
    assert.deepEqual(s.state.buildList[0],original);
  }
  assert.equal(s.state.buildList.length,3);
  assert.deepEqual(s.draft.nested_assemblies[0].fragment_ids,[13]);
  assert.equal(s.draft.settings.fragment_stock_overrides[11].stock_ng_ul,20);
});
test('pending planner edits save to the original before a renamed variant is added',async()=>{
  const s=draftSetup();s.draft.settings.insert_ratio=3;s.context.scheduleBuildSettingsSave();
  s.draft.name='Variant';s.context.scheduleBuildSettingsSave();
  const operation=s.context.addCurrentBuild();await tick();
  assert.equal(s.calls.length,1);assert.equal(s.calls[0].url,'/api/build-list/1');
  const original=JSON.parse(s.calls[0].options.body);assert.equal(original.name,'Original');assert.equal(original.settings.insert_ratio,3);
  s.calls[0].resolve({id:1,request:original});await tick();
  assert.equal(s.calls.length,2);assert.equal(s.calls[1].options.method,'POST');
  const variant=JSON.parse(s.calls[1].options.body);assert.equal(variant.name,'Variant');
  s.calls[1].resolve({id:2,request:variant});await operation;
  assert.deepEqual(s.state.buildList.map(item=>item.request.name),['Original','Variant']);
});
test('plus captures nested selections at click time even when the draft changes while saving',async()=>{
  const s=draftSetup();const operation=s.context.addCurrentBuild();
  s.draft.nested_assemblies[0].fragment_ids.push(99);s.draft.settings.insert_ratio=4;
  await tick();const captured=JSON.parse(s.calls[0].options.body);
  assert.deepEqual(captured.nested_assemblies[0].fragment_ids,[13]);assert.equal(captured.settings.insert_ratio,2);
  s.calls[0].resolve({id:2,request:captured});await operation;
  assert.deepEqual(s.draft.nested_assemblies[0].fragment_ids,[13,99]);assert.equal(s.draft.settings.insert_ratio,4);
});
test('choosing any backbone preserves the manually selected enzyme',()=>{
  for(const enzyme of ['BsaI','BsmBI','BsmBI + BsaI']){
    let recalculations=0;const s=draftSetup();s.$('enzyme').value=enzyme;
    s.context.backboneChanged=()=>recalculations++;
    s.context.changeAssemblyEnzyme=()=>{throw Error('Unexpected enzyme change');};
    vm.runInContext(source.slice(source.indexOf('function selectBackbone('),source.indexOf("$('backbone').onchange=selectBackbone")),s.context);
    for(const counts of [{'BsaI':2},{'BsmBI':2},{'BsaI':2,'BsmBI':2},{}]){
      s.state.plasmids=[{id:4,backbone_options:{site_counts:counts}}];s.context.selectBackbone();
      assert.equal(s.$('enzyme').value,enzyme);
    }
    assert.equal(recalculations,4);
  }
});

function nameSetup(){
  const state={parts:[],plasmids:[],fragments:[],nestedFragments:new Map(),nestedAssemblies:[]};
  let edits=0;
  const nodes={'backbone':{value:''},'assembly-name':{value:'My custom name',oninput:()=>edits++,focus(){}},'assembly-name-recommendation':{textContent:'',setAttribute(){},classList:{toggle(key,value){this[key]=value;}}}};
  const context=vm.createContext({state,$:id=>nodes[id],selectedNested:()=>state.nestedAssemblies.filter(group=>group.fragment_ids.length&&state.parts.some(part=>part.id===group.parent_fragment_id))});
  vm.runInContext(source.slice(source.indexOf('function recommendedAssemblyName()'),source.indexOf('function payload()')),context);
  return{state,nodes,context,get edits(){return edits;}};
}
test('recommended names follow fragment order, backbone and selected nested fragments',()=>{
  const s=nameSetup();s.state.parts=[{id:1,name:'F1'},{id:2,name:'D2 Cargo'}];
  assert.equal(s.context.recommendedAssemblyName(),'F1_D2_Cargo');
  s.state.parts.reverse();assert.equal(s.context.recommendedAssemblyName(),'D2_Cargo_F1');
  s.state.plasmids=[{id:7,name:'pHR V2'}];s.nodes.backbone.value='p:7';
  s.state.nestedAssemblies=[{parent_fragment_id:1,fragment_ids:[3,4]},{parent_fragment_id:99,fragment_ids:[5]}];
  s.state.nestedFragments.set('BsmBI:3',{id:3,name:'HA tag'});s.state.fragments=[{id:4,name:'Cargo'}];
  assert.equal(s.context.recommendedAssemblyName(),'pHR_V2_D2_Cargo_F1[HA_tag+Cargo]');
});
test('recommendations leave custom names untouched until applied through the normal save flow',()=>{
  const s=nameSetup();s.state.parts=[{id:1,name:'F1'},{id:2,name:'F2'}];
  s.context.refreshRecommendedAssemblyName();
  assert.equal(s.nodes['assembly-name'].value,'My custom name');assert.equal(s.edits,0);
  assert.equal(s.nodes['assembly-name-recommendation'].textContent,'↳ F1_F2');
  s.context.applyRecommendedAssemblyName();assert.equal(s.nodes['assembly-name'].value,'F1_F2');assert.equal(s.edits,1);
  s.state.parts=[];s.context.refreshRecommendedAssemblyName();
  assert.equal(s.nodes['assembly-name-recommendation'].classList.hidden,true);
  s.context.applyRecommendedAssemblyName();assert.equal(s.nodes['assembly-name'].value,'F1_F2');assert.equal(s.edits,1);
});
test('recommended names fit the 100-character limit',()=>{
  const s=nameSetup();s.state.parts=[{id:1,name:'Long fragment '.repeat(20)}];
  const name=s.context.recommendedAssemblyName();assert.equal(name.length,100);assert.ok(name.endsWith('...'));
});
