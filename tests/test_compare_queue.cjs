const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../app/static/app.js'),'utf8');
const code=source.slice(source.indexOf('const compareJobs=[]'),source.indexOf('function renderAlignment('));
function setup(){
  const elements=new Map(),calls=[],notices=[];
  const element=id=>{if(!elements.has(id))elements.set(id,{value:id==='compare-enzyme'?'auto':'',classList:{add(){},remove(){},toggle(){}},querySelectorAll:()=>[],click(){}});return elements.get(id);};
  const context=vm.createContext({CompareFiles:require('../app/static/compare-files.js'),CompareVisuals:require('../app/static/compare-visuals.js'),console,document:{querySelectorAll:()=>[],addEventListener(){}},FormData:class{append(...args){this.value=args;}},$ :element,toast:message=>notices.push(message),
    api:(url,options)=>new Promise((resolve,reject)=>calls.push({url,options,resolve,reject}))});
  vm.runInContext(code,context);
  vm.runInContext('comparisonQueue=()=>{};renderComparison=()=>{}',context);
  return {context,calls,element,notices,read:expression=>vm.runInContext(expression,context)};
}
const file=(name,size=100)=>({name,size,lastModified:1});
const tick=()=>new Promise(resolve=>setImmediate(resolve));

test('adding files while comparing preserves the first results and runs automatically in order',async()=>{
  const s=setup();s.context.addCompareFile(file('one.gb'));s.context.addCompareFile(file('two.fa'));
  assert.equal(s.calls.length,1);assert.equal(s.read('compareJobs[1].status'),'Queued');
  s.calls[0].resolve({records:[{query_name:'one',matches:[],fragment_matches:[]}]});await tick();
  assert.equal(s.calls.length,2);assert.equal(s.read('compareJobs[0].status'),'Done');
  s.context.addCompareFile(file('three.gb'));s.context.addCompareFile(file('three.gb'));
  assert.equal(s.read('compareJobs.length'),3);
  s.calls[1].resolve({records:[{query_name:'two'}]});await tick();
  assert.equal(s.calls.length,3);s.calls[2].resolve({records:[{query_name:'three'}]});await tick();
  assert.equal(s.read('compareJobs.every(j=>j.status==="Done")'),true);
  assert.equal(s.read('compareJobs[0].result.records[0].query_name'),'one');
});

test('a changed enzyme discards an in-flight old result and reruns without concurrent requests',async()=>{
  const s=setup();s.context.initializeCompare();s.context.addCompareFile(file('one.gb'));
  s.element('compare-enzyme').value='BsmBI';s.element('compare-enzyme').onchange();
  assert.equal(s.calls.length,1);
  s.calls[0].resolve({records:[{query_name:'stale'}]});await tick();
  assert.equal(s.calls.length,2);assert.match(s.calls[1].url,/enzyme=BsmBI/);
  assert.equal(s.read('compareJobs[0].status'),'Comparing');
  s.calls[1].resolve({records:[{query_name:'fresh'}]});await tick();
  assert.equal(s.read('compareJobs[0].result.records[0].query_name'),'fresh');
});

test('dropped folders drain every directory batch, recurse and list unsupported files',async()=>{
  const s=setup();vm.runInContext('runCompareQueue=()=>{}',s.context);
  const entry=name=>({isFile:true,name,file:resolve=>resolve(file(name))});
  const directory=(name,batches)=>({isDirectory:true,name,createReader:()=>({readEntries:resolve=>resolve(batches.shift()||[])})});
  const nested=directory('inner',[[entry('inside.fasta'),entry('notes.pdf')],[]]);
  const batch=Array.from({length:100},(_,i)=>entry(i+'.gb'));
  await s.context.droppedCompareEntry(directory('folder',[batch,[nested,entry('last.fa')],[]]));
  assert.equal(s.read('compareJobs.length'),103);
  assert.equal(s.read('compareJobs.some(j=>j.path==="folder/inner/inside.fasta")'),true);
  assert.equal(s.read('compareJobs.find(j=>j.path.endsWith("notes.pdf")).status'),'Skipped');
  assert.equal(s.read('compareJobs.at(-1).path'),'folder/last.fa');
});

test('an invalid file does not block later files and removing an in-flight file ignores its result',async()=>{
  const s=setup();s.context.addCompareFile(file('bad.fa'));s.context.addCompareFile(file('good.gb'));
  s.calls[0].reject(new Error('Invalid DNA'));await tick();
  assert.equal(s.read('compareJobs[0].status'),'Error');assert.equal(s.calls.length,2);
  s.read('compareJobs.splice(1,1)');s.calls[1].resolve({records:[{query_name:'removed'}]});await tick();
  assert.equal(s.read('compareJobs.length'),1);assert.equal(s.read('compareWorker'),false);
  s.context.addCompareFile(file('after.fa'));assert.equal(s.calls.length,3);
  s.calls[2].resolve({records:[]});await tick();
  assert.equal(s.read('compareJobs[1].status'),'Done');
});


test('search and selected-file filtering preserve queue order and hidden selections',()=>{
  const s=setup();s.context.initializeCompare();
  s.read("compareJobs.push({id:1,path:'A.gb',status:'Done',result:{records:[]}},{id:2,path:'B.gb',status:'Done',result:{records:[]}});compareSelection.add(2)");
  s.element('compare-file-search').oninput({target:{value:'A.gb'}});
  assert.equal(s.read('visibleCompareJobs().map(j=>j.id).join()'),'1');
  s.element('compare-select-all').onchange({target:{checked:true}});
  assert.equal(s.read('[...compareSelection].sort().join()'),'1,2');
  s.element('compare-select-all').onchange({target:{checked:false}});
  assert.equal(s.read('[...compareSelection].join()'),'2');
  s.element('compare-file-search').oninput({target:{value:''}});s.element('compare-file-filter').onchange({target:{value:'selected'}});
  assert.equal(s.read('visibleCompareJobs().map(j=>j.id).join()'),'2');
  assert.equal(s.read('compareJobs.map(j=>j.id).join()'),'1,2');
});
