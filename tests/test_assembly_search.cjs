const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const FragmentSearch=require('../app/static/fragment-search.js');
const source=fs.readFileSync(path.join(__dirname,'../app/static/app.js'),'utf8');
const matching=source.slice(source.indexOf('function matchingPlasmidRecipes('),source.indexOf('function backboneChanged('));
const searching=source.slice(source.indexOf('async function searchFragments('),source.indexOf('async function checkAssembly('));
function setup(){
  const nodes=new Map(),calls=[],events=[];
  const $=id=>{if(!nodes.has(id)){const hidden=new Set();nodes.set(id,{value:'',checked:false,innerHTML:'',attributes:{},classList:{add:x=>hidden.add(x),remove:x=>hidden.delete(x),contains:x=>hidden.has(x)},setAttribute(k,v){this.attributes[k]=v;},querySelectorAll:()=>[],focus(){events.push('focus');}});}return nodes.get(id);};
  const recipes=[{name:'pHR_V2 · U6',enzyme:'BsaI',available:true,no_backbone_fragment_ids:[1,2],missing:[]},{name:'AAV6_V2',enzyme:'BsaI',available:false,no_backbone_fragment_ids:[1,null],missing:['F12']}];
  const state={recipes,parts:[],plasmids:[],nestedFragments:new Map(),fragments:[{id:1,name:'F1'},{id:2,name:'F2'}],nestedAssemblies:[{}],activeBuildId:5};
  const ctx=vm.createContext({state,$,FragmentSearch,setTimeout,clearTimeout,encodeURIComponent,esc:String,fmt:String,plateLabel:String,reverseCompFlag:()=>'<span>RC</span>',fusionEnds:(l,r)=>`${l}/${r}`,nextEnd:()=> 'ATGG',api:async url=>{calls.push(url);return[];},toast:message=>events.push(message),persistPendingBuild:async()=>events.push('persist'),refresh:async()=>events.push('refresh'),backboneChanged:()=>events.push('backbone'),checkAssembly:async()=>events.push('check'),renderParts:()=>events.push('parts'),invalidate:()=>events.push('invalidate')});
  ctx.selectedNested=()=>[];
  vm.runInContext('let searchCounter=0,searchTimer;'+source.slice(source.indexOf('function recommendedAssemblyName()'),source.indexOf('function payload()'))+matching+searching,ctx);
  $('enzyme').value='BsmBI';$('compatible-only').checked=true;
  return {ctx,state,$,calls,events};
}
test('Plasmid keyword and names find presets with case, punctuation and multiple tokens',()=>{
  const {ctx}=setup();
  assert.equal(ctx.matchingPlasmidRecipes('Plasmid').length,2);
  assert.equal(ctx.matchingPlasmidRecipes('PLASMID phr_v2 u6')[0].recipe.name,'pHR_V2 · U6');
  assert.equal(ctx.matchingPlasmidRecipes('pHR').length,0);
  assert.equal(ctx.matchingPlasmidRecipes('F12').length,0);
  assert.equal(ctx.matchingPlasmidRecipes('').length,0);
});
test('preset results ignore overhang/enzyme filters, show missing parts and keep fragments',async()=>{
  const s=setup();s.ctx.api=async url=>{s.calls.push(url);return[{id:3,name:'F3',plate_id:'plate',well:'A1',physical_length:300,digest:{left_overhang:'ATGG',right_overhang:'CAAA',errors:[]}}];};
  s.$('fragment-search').value='Plasmid';await s.ctx.searchFragments();
  const html=s.$('search-results').innerHTML;
  assert.match(html,/data-recipe="0"/);assert.match(html,/data-recipe="1" disabled aria-disabled="true"/);
  assert.match(html,/Missing from the plate maps: F12/);assert.match(html,/Plasmid/);assert.match(html,/data-add="3"/);assert.match(html,/RC/);
  assert.match(s.calls[0],/enzyme=BsmBI/);assert.match(s.calls[0],/left=ATGG/);
});
test('plasmid presets remain selectable before a backbone cassette is chosen',async()=>{
  const s=setup();s.$('backbone').value='p:1';s.$('fragment-search').value='plasmid';
  await s.ctx.searchFragments();
  assert.equal(s.calls.length,0);assert.match(s.$('search-results').innerHTML,/data-recipe="0"/);
  assert.match(s.$('search-results').innerHTML,/Choose cassette for fragments/);
});
test('loading a preset flushes the current build, applies enzyme and full chain, closes search',async()=>{
  const s=setup();s.$('fragment-search').value='plasmid';s.$('backbone').value='p:5';
  await s.ctx.loadRecipe(0);
  assert.deepEqual(s.events,['persist','refresh','backbone','check']);
  assert.equal(s.$('enzyme').value,'BsaI');assert.equal(s.$('backbone').value,'');
  assert.equal(s.$('assembly-name').value,'pHR_V2_U6');assert.equal(s.$('fragment-search').value,'');
  assert.deepEqual(Array.from(s.state.parts,p=>p.id),[1,2]);assert.equal(s.state.nestedAssemblies.length,0);
  assert.ok(s.$('search-results').classList.contains('hidden'));assert.equal(s.$('fragment-search').attributes['aria-expanded'],'false');
  await s.ctx.loadRecipe(1);assert.equal(s.events.length,4);
});
test('closing or loading a preset prevents delayed fragment results reopening the dropdown',async()=>{
  const s=setup();let resolve;s.ctx.api=()=>new Promise(done=>resolve=done);
  const pending=s.ctx.searchFragments();await s.ctx.loadRecipe(0);resolve([]);await pending;
  assert.ok(s.$('search-results').classList.contains('hidden'));
  assert.equal(s.$('search-results').innerHTML,'');
});
