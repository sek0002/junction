const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('app/static/app.js','utf8');
const viewer=source.slice(source.indexOf('let plasmidViewerSession='),source.indexOf('function renderPlasmidLibraries()'));
function fixture(result={name:'Draft',sequence:'ACGT',circular:false}){
  const nodes=new Map();
  const node=id=>{if(!nodes.has(id))nodes.set(id,{id,value:'',textContent:'',open:false,isConnected:true,
    classList:{items:new Set(),contains(x){return this.items.has(x);},add(x){this.items.add(x);},remove(x){this.items.delete(x);},toggle(x,on){on?this.add(x):this.remove(x);}},
    append(child){child.parentNode=this;},insertBefore(child){child.parentNode=this;},focus(){},showModal(){this.open=true;}});return nodes.get(id);};
  const panel=node('panel'),tooltip=node('map-tooltip');panel.parentNode=node('results');panel.nextSibling=null;tooltip.parentNode=node('body');tooltip.nextSibling=null;
  node('sequence-start').value='121';node('map-site-filter').value='all';node('feature-detail').textContent='Draft selection';node('viewer-name-status').textContent='Updated';
  let resolve;const pending=new Promise(r=>resolve=r);const renders=[];
  const state={result,mapMode:'linear',selectedFeature:{start:120},parts:[]};
  const context={state,$:node,document:{activeElement:node('view-button'),querySelector:()=>panel},assemblyCheckTimer:null,checkCounter:0,viewerRenameTimer:null,
    clearTimeout(){},setTimeout(){},checkAssembly(){},hideMapTooltip(){},api:()=>pending,renderResult:()=>renders.push(state.result)};
  vm.createContext(context);vm.runInContext(viewer,context);
  return {...context,node,panel,resolve,renders,context};
}
test('saved viewer restores draft, selection, sequence position and DOM on return',async()=>{
  const f=fixture(),original=f.state.result;const opening=f.viewPlasmid(7);
  f.resolve({id:7,name:'Saved',sequence:'GGCC',circular:true});await opening;
  assert.equal(f.state.result.name,'Saved');assert.equal(f.panel.parentNode.id,'plasmid-view-host');
  f.node('sequence-start').value=1;f.node('map-site-filter').value='none';f.node('plasmid-view-dialog').open=false;f.restorePlasmidViewer();
  assert.equal(f.state.result,original);assert.equal(f.state.mapMode,'linear');assert.equal(f.state.selectedFeature.start,120);
  assert.equal(f.node('sequence-start').value,'121');assert.equal(f.node('map-site-filter').value,'all');
  assert.equal(f.panel.parentNode.id,'results');assert.equal(f.node('map-tooltip').parentNode.id,'body');
});
test('outside close while loading ignores the late response',async()=>{
  const f=fixture(),original=f.state.result;const opening=f.viewPlasmid(7);
  f.node('plasmid-view-dialog').open=false;f.restorePlasmidViewer();const count=f.renders.length;
  f.resolve({id:7,name:'Late',sequence:'ACGT',circular:true});await opening;
  assert.equal(f.state.result,original);assert.equal(f.renders.length,count);assert.equal(f.panel.parentNode.id,'results');
});
test('opening and closing from an empty builder keeps its result hidden',async()=>{
  const f=fixture(null);f.node('results').classList.add('hidden');const opening=f.viewPlasmid(7);
  f.resolve({id:7,name:'Saved',sequence:'ACGT',circular:true});await opening;
  f.node('plasmid-view-dialog').open=false;f.restorePlasmidViewer();
  assert.equal(f.state.result,null);assert.ok(f.node('results').classList.contains('hidden'));
});
