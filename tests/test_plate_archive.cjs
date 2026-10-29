const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../app/static/app.js'),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function setup(){
  function node(){const classes=new Set();return{disabled:false,hidden:false,checked:false,value:'auto',textContent:'',dataset:{},attributes:{},style:{setProperty(){}},
    classList:{add:(...values)=>values.forEach(v=>classes.add(v)),remove:(...values)=>values.forEach(v=>classes.delete(v)),contains:v=>classes.has(v),toggle(v,on){if(on)classes.add(v);else classes.delete(v);}},
    setAttribute(k,v){this.attributes[k]=v;},focus(){this.focused=true;},querySelectorAll(){return[];}};}
  const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);};
  const plate={plate_id:'P1',format:96,occupied_wells:3,archived_at:null,fragments:[{id:1,well:'A1',name:'One',archived_at:null},{id:2,well:'B2',name:'Two',archived_at:null},{id:3,well:'C3',name:'Old',archived_at:'old'}]};
  const state={plateView:plate,plateWell:'A1',plateWellSelection:new Set([1,2]),plateSelection:new Set(['P1']),plateArchiveBusy:false,
    inventoryDrafts:new Map([[1,{}],[2,{}],[9,{}]]),fragmentSelection:new Set([1,2,9]),parts:[{id:1},{id:2},{id:9}]};
  $('plate-viewer').open=true;let buttons=[];
  Object.defineProperty($('plate-grid'),'innerHTML',{get(){return this.html||'';},set(html){this.html=html;buttons=[...html.matchAll(/<button[^>]*data-plate-well="([^"]+)"[^>]*data-plate-row="([^"]+)"[^>]*data-plate-col="([^"]+)"[^>]*>/g)].map(match=>Object.assign(node(),{dataset:{plateWell:match[1],plateRow:match[2],plateCol:match[3]}}));}});
  $('plate-grid').querySelectorAll=()=>buttons;$('plate-grid').querySelector=selector=>buttons.find(b=>selector.includes('"'+b.dataset.plateWell+'"'));
  const events=[];let allowed=true;
  const context=vm.createContext({state,$,Date,Promise,Set,Map,window:{JunctionAccount:{allowed:()=>allowed}},
    esc:String,plateLabel:String,Overhangs:{labels:()=>[]},plateOverhangValues:()=>[],hidePlateTooltip(){},showPlateTooltip(){},
    renderPlateWellDetails(){events.push('details');},inventoryIcon:String,
    archiveIconButton(button,count){button.disabled=!count;},jsonBody:body=>({body:JSON.stringify(body)}),
    persistInventoryRow:async id=>events.push('save:'+id),api:async(url,options)=>{events.push({url,body:JSON.parse(options.body)});return{count:JSON.parse(options.body).fragment_ids?.length||1};},
    loadPlateView:async id=>events.push('plate:'+id),refresh:async()=>events.push('refresh'),backboneChanged:()=>events.push('backbone'),loadInventory:async()=>events.push('inventory'),loadUploads:async()=>events.push('uploads'),loadBin:async()=>events.push('bin'),toast:message=>events.push(message)});
  vm.runInContext(source.slice(source.indexOf('function renderPlateView()'),source.indexOf('function platePosition('))+source.slice(source.indexOf('function canArchivePlate()'),source.indexOf('function hidePlateTooltip()')),context);
  return{context,state,$,plate,events,allowed(value){allowed=value;},button:well=>buttons.find(b=>b.dataset.plateWell===well)};
}
test('well selection works in both layouts and skips empty or archived wells',()=>{
  for(const format of [96,384]){const s=setup();s.plate.format=format;s.state.plateWellSelection.clear();s.$('plate-select-wells').checked=true;
    s.context.renderPlateView();s.button('A1').onclick();s.button('B2').onclick();assert.deepEqual([...s.state.plateWellSelection],[1,2]);
    assert.match(s.$('plate-grid').innerHTML,/archive-selected/);s.button('C3').onclick();s.button('A2').onclick();assert.deepEqual([...s.state.plateWellSelection],[1,2]);
    s.context.renderPlateView();assert.deepEqual([...s.state.plateWellSelection],[1,2]);
    s.button('B2').onkeydown({key:'ArrowRight',preventDefault(){}});assert.equal(s.state.plateWell,'B3');assert.deepEqual([...s.state.plateWellSelection],[1,2]);
    s.button('A1').onclick();assert.deepEqual([...s.state.plateWellSelection],[2]);
  }
});
test('archiving wells saves pending edits and only archives active IDs from this plate',async()=>{
  const s=setup();await s.context.archiveFromPlate([1,3,999]);
  const request=s.events.find(e=>e?.url);assert.deepEqual(request,{url:'/api/bin/archive',body:{fragment_ids:[1]}});
  assert.equal(s.events.indexOf('save:1')<s.events.indexOf(request),true);
  assert.deepEqual(s.state.parts.map(p=>p.id),[2,9]);assert.deepEqual([...s.state.plateWellSelection],[2]);
  assert.deepEqual([...s.state.inventoryDrafts.keys()],[2,9]);assert.deepEqual([...s.state.fragmentSelection],[2,9]);
  assert.ok(s.plate.fragments[0].archived_at);assert.equal(s.plate.fragments[1].archived_at,null);assert.equal(s.plate.archived_at,null);
  assert.equal(s.$('plate-archive-status').textContent,'1 well archived');assert.equal(s.state.plateArchiveBusy,false);
  assert.ok(s.events.includes('inventory'));assert.ok(s.events.includes('uploads'));assert.ok(s.events.includes('plate:P1'));
});
test('whole-plate archiving preserves independent well archive flags for later plate restoration',async()=>{
  const s=setup();await s.context.archiveFromPlate([],true);
  assert.deepEqual(s.events.find(e=>e?.url).body,{plate_ids:['P1']});assert.ok(s.plate.archived_at);
  assert.equal(s.plate.fragments[0].archived_at,null);assert.equal(s.plate.fragments[1].archived_at,null);assert.equal(s.plate.fragments[2].archived_at,'old');
  assert.deepEqual(s.state.parts.map(p=>p.id),[9]);assert.equal(s.state.plateSelection.has('P1'),false);
  assert.equal(s.$('plate-archive-map').disabled,true);assert.equal(s.state.plateWellSelection.size,0);
});
test('read-only accounts, archived plates and empty selections cannot archive',async()=>{
  const s=setup();s.allowed(false);await s.context.archiveFromPlate([1]);s.context.updatePlateArchiveControls();
  assert.equal(s.$('plate-archive-map').disabled,true);assert.equal(s.$('plate-archive-wells').disabled,true);
  s.allowed(true);s.plate.archived_at='old';await s.context.archiveFromPlate([],true);s.plate.archived_at=null;await s.context.archiveFromPlate([3,999]);
  assert.equal(s.events.some(e=>e?.url),false);
});
test('duplicate clicks are blocked and failed requests retain the selection for retry',async()=>{
  const s=setup();let reject;s.context.api=()=>new Promise((resolve,no)=>reject=no);
  const pending=s.context.archiveFromPlate([1,2]);await tick();assert.equal(s.$('plate-archive-wells').disabled,true);
  await s.context.archiveFromPlate([1,2]);reject(Error('No permission'));await pending;
  assert.equal(s.plate.fragments[0].archived_at,null);assert.deepEqual([...s.state.plateWellSelection],[1,2]);
  assert.equal(s.$('plate-archive-status').textContent,'No permission');assert.equal(s.state.plateArchiveBusy,false);assert.equal(s.$('plate-archive-wells').disabled,false);
});
test('invalid pending stocks stop archiving; closing before saves finish cancels the mutation',async()=>{
  const s=setup();s.context.persistInventoryRow=async()=>{throw Error('Invalid stock');};await s.context.archiveFromPlate([1]);
  assert.equal(s.events.some(e=>e?.url),false);assert.equal(s.$('plate-archive-status').textContent,'Invalid stock');
  let done;s.context.persistInventoryRow=()=>new Promise(resolve=>done=resolve);const operation=s.context.archiveFromPlate([1]);
  s.$('plate-viewer').open=false;done();await operation;assert.equal(s.events.some(e=>e?.url),false);assert.equal(s.state.plateArchiveBusy,false);
});
test('an archive finishing after another plate opens never overwrites that plate',async()=>{
  const s=setup();let complete;s.context.api=()=>new Promise(resolve=>complete=resolve);const operation=s.context.archiveFromPlate([1]);await tick();
  const other={plate_id:'P2',archived_at:null,fragments:[{id:9,well:'A1',name:'Other',archived_at:null}]};s.state.plateView=other;s.state.plateWellSelection=new Set([9]);s.$('plate-archive-status').textContent='Other plate';
  complete({count:1});await operation;assert.equal(s.state.plateView,other);assert.equal(other.fragments[0].archived_at,null);
  assert.equal(s.$('plate-archive-status').textContent,'Other plate');assert.deepEqual([...s.state.plateWellSelection],[9]);assert.equal(s.events.includes('plate:P1'),false);
});
