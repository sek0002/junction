const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../app/static/app.js'),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function setup(){
  const nodes=new Map(),downloads=[],events=[],state={result:null,buildList:[],buildBusy:false};
  const $=id=>{if(!nodes.has(id))nodes.set(id,{hidden:false,disabled:false});return nodes.get(id);};
  const context=vm.createContext({state,$,JSON,Date,Promise,renameViewer(){},flushPlanInputs:()=>events.push('flush'),persistPendingBuild:async()=>events.push('save'),planEditOperations:new Set(),loadBuildList:async()=>events.push('refresh'),updateBuildActions(){},toast:message=>events.push(message),fileDownload:async(...args)=>downloads.push(args),confirmAssemblyExportWarnings:async groups=>{events.push(groups);return true;}});
  vm.runInContext('let assemblyExportBusy=false,viewerRenameChain=Promise.resolve();'+source.slice(source.indexOf('function genbankExportDate()'),source.indexOf("$('viewer-download-gb').onclick=")),context);
  return {context,state,$,events,downloads,run:code=>vm.runInContext(code,context)};
}
const displayed=()=>({name:'Displayed',sequence:'ACGT',errors:[],warnings:[],recipe:{name:'Previous name',enzyme:'BsmBI',fragment_ids:[3,4],nested_assemblies:[{fragment_ids:[7]}]}});
test('viewer exports its displayed recipe and current edited name, never a different draft',async()=>{
  const s=setup();s.state.result=displayed();s.context.payload=()=>{throw Error('Do not use the current draft');};
  s.context.renameViewer=()=>s.state.result.name='Edited in viewer';
  let finishRename;s.context.renameWait=new Promise(resolve=>finishRename=resolve);s.run('viewerRenameChain=renameWait');
  const operation=s.context.downloadViewedGenbank();await tick();assert.equal(s.downloads.length,0);
  s.state.result.recipe.fragment_ids.push(99);s.state.result={name:'Another selected plasmid'};
  finishRename();await operation;
  assert.equal(s.downloads.length,1);const [url,request]=s.downloads[0];
  assert.equal(url,'/api/assemblies/genbank');assert.equal(request.name,'Edited in viewer');assert.deepEqual([...request.fragment_ids],[3,4]);assert.deepEqual([...request.nested_assemblies[0].fragment_ids],[7]);
});
test('stored viewer downloads that stored plasmid; read-only Design previews cannot export a different draft',async()=>{
  const s=setup();s.state.result={...displayed(),storedReference:true,viewerPlasmidId:9};
  await s.context.downloadViewedGenbank();assert.equal(s.downloads[0][0],'/api/plasmids/9/genbank');assert.equal(s.downloads[0][1],null);
  s.state.result={...displayed(),storedReference:true,viewerReadOnly:true};await s.context.downloadViewedGenbank();assert.equal(s.downloads.length,1);
  s.state.result={...displayed(),errors:['Overhang mismatch']};await s.context.downloadViewedGenbank();assert.equal(s.downloads.length,1);
});
test('batch saves edits and refreshes before exporting, independent of reaction warnings or a new draft',async()=>{
  const s=setup();s.state.buildList=[{request:{name:'Queued'},plan:{errors:[],warnings:[],reaction:{warnings:['Overfilled'],water_ul:-2}}}];
  s.state.result=displayed();await s.context.downloadBuildGenbanks();
  assert.deepEqual(s.events,['flush','save','refresh']);assert.equal(s.downloads.length,1);
  assert.match(s.downloads[0][0],/^\/api\/build-list\/genbank\?export_date=\d{4}-\d{2}-\d{2}$/);
});
test('invalid or missing queued entries block the entire archive; empty lists are explained',async()=>{
  for(const entry of [{request:{name:'Mismatch'},plan:{errors:['Overhang mismatch']}},{request:{name:'Missing'},error:'Fragment archived'}]){
    const s=setup();s.state.buildList=[entry];let close;
    s.context.confirmAssemblyExportWarnings=groups=>{s.events.push(groups);return new Promise(resolve=>close=resolve);};
    const operation=s.context.downloadBuildGenbanks();await tick();
    assert.equal(s.$('assembly-warning-continue').hidden,true);assert.equal(s.downloads.length,0);
    close(true);await operation;assert.equal(s.downloads.length,0);assert.equal(s.$('assembly-warning-continue').hidden,false);
  }
  const s=setup();await s.context.downloadBuildGenbanks();assert.equal(s.downloads.length,0);assert.match(s.events.at(-1)[0].messages[0],/Add an assembly/);
});
test('assembly warnings can cancel exports, duplicate clicks do not duplicate downloads, and failed refresh can retry',async()=>{
  const s=setup();s.state.buildList=[{request:{name:'Queued'},plan:{errors:[],warnings:['Palindromic overhang']}}];let confirm;
  s.context.confirmAssemblyExportWarnings=()=>new Promise(resolve=>confirm=resolve);
  let operation=s.context.downloadBuildGenbanks();await tick();await s.context.downloadBuildGenbanks();confirm(false);await operation;assert.equal(s.downloads.length,0);
  s.context.loadBuildList=async()=>{throw Error('Refresh failed');};await s.context.downloadBuildGenbanks();assert.ok(s.events.includes('Refresh failed'));
  s.context.loadBuildList=async()=>{};operation=s.context.downloadBuildGenbanks();await tick();confirm(true);await operation;assert.equal(s.downloads.length,1);
});
test('Build list header exports all GenBanks while fragment chain retains its add action',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../app/static/index.html'),'utf8');
  assert.match(html,/id="export-build-genbank"/);assert.doesNotMatch(html,/id="add-build"/);assert.match(html,/id="viewer-download-gb"/);
  const actions=source.slice(source.indexOf('function renderFragmentAssemblyActions()'),source.indexOf('function renderParts('));
  assert.match(actions,/add.id='add-build-inline'/);assert.match(actions,/add.onclick=addCurrentBuild/);assert.doesNotMatch(actions,/\$\('add-build'\)/);
});
