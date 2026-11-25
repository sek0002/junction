const {test}=require('node:test');const assert=require('node:assert/strict');const {create}=require('../app/static/sandbox.js');
const pause=()=>new Promise(resolve=>setImmediate(resolve));
test('sandbox waits for authenticated hydration and saves only its explicit snapshot',async()=>{
  let current={draft:{name:'Alice'},plannerOverrides:{insert_ratio:2}},writes=[];
  const sandbox=create({capture:()=>structuredClone(current),request:async(url,body)=>writes.push([url,body])});
  sandbox.schedule();await sandbox.flush();assert.equal(writes.length,0);
  sandbox.start(current);await sandbox.flush();assert.equal(writes.length,0);
  current.draft.name='Alice changed';await sandbox.flush();assert.equal(writes.length,1);assert.deepEqual(writes[0],['/api/workspace',{data:current}]);
  sandbox.stop();current.draft.name='Not saved after stopping';await sandbox.flush();assert.equal(writes.length,1);
});
test('sandbox serializes rapid edits and retries a failed write without losing the newer draft',async()=>{
  let current={name:'first'},complete,fail=true,writes=[];
  const sandbox=create({capture:()=>structuredClone(current),request:async(url,body)=>{writes.push(body.data.name);if(fail){fail=false;throw Error('offline');}if(body.data.name==='second')await new Promise(resolve=>complete=resolve);}});
  sandbox.start({});await assert.rejects(sandbox.flush(),/offline/);current={name:'second'};const second=sandbox.flush();await pause();current={name:'latest'};const latest=sandbox.flush();await pause();assert.deepEqual(writes,['first','second']);complete();await Promise.all([second,latest]);assert.deepEqual(writes,['first','second','latest']);
});
test('queued autosaves keep the worksheet identity captured with their design',async()=>{
  const ids={design:'worksheet-a'};let name='A',release,writes=[];
  const sandbox=create({capture:()=>({worksheet_ids:ids,design:{name}}),request:async(url,body)=>{
    if(!writes.length){writes.push(structuredClone(body));await new Promise(resolve=>release=resolve);}
    else writes.push(structuredClone(body));
  }});
  sandbox.start({});const first=sandbox.flush();await pause();
  name='A edited';const queued=sandbox.flush();ids.design='worksheet-b';name='B';
  release();await Promise.all([first,queued]);
  assert.equal(writes[1].data.worksheet_ids.design,'worksheet-a');
  assert.equal(writes[1].data.design.name,'A edited');
});
test('pausing autosave waits for every queued save before a worksheet switch',async()=>{
  let name='A',release,writes=[],stopped=false;
  const sandbox=create({capture:()=>({name}),request:async(url,body)=>{writes.push(body.data.name);if(writes.length===1)await new Promise(resolve=>release=resolve);}});
  sandbox.start({});const first=sandbox.flush();await pause();name='A edited';const second=sandbox.flush();
  const stopping=Promise.resolve(sandbox.stop()).then(()=>{stopped=true;});
  await pause();assert.equal(stopped,false);assert.equal(sandbox.ready,false);
  release();await Promise.all([first,second,stopping]);assert.deepEqual(writes,['A','A edited']);
  name='B';await sandbox.flush();assert.deepEqual(writes,['A','A edited']);
});
test('queued saves and page-exit bodies carry their original loaded context',async()=>{
  let version=4,name='A',release,writes=[];
  const sandbox=create({context:()=>version,capture:()=>({name}),request:async(url,body)=>{writes.push(body);if(writes.length===1)await new Promise(resolve=>release=resolve);}});
  sandbox.start({});const first=sandbox.flush();await pause();name='A edited';const second=sandbox.flush();
  version=5;name='B';release();await Promise.all([first,second]);
  assert.deepEqual(writes.map(body=>body.context_version),[4,4]);
  assert.deepEqual(sandbox.body(),{data:{name:'B'},context_version:5});
});
test('a failed pending save prevents the switch and can be retried on resume',async()=>{
  let fail=true,writes=0;
  const sandbox=create({capture:()=>({name:'Retain edits'}),request:async()=>{writes++;if(fail)throw Error('offline');}});
  sandbox.start({});const saving=sandbox.flush();await assert.rejects(saving,/offline/);
  await assert.rejects(sandbox.stop(),/offline/);fail=false;sandbox.start();await sandbox.flush();assert.equal(writes,2);
});
test('save waits for autosave, skips duplicate writes, and persists a queued undo',async()=>{
  let name='A',release;
  const writes=[];
  const sandbox=create({capture:()=>({name}),request:async(url,body)=>{
    writes.push(body.data.name);
    if(writes.length===1)await new Promise(resolve=>release=resolve);
  }});
  sandbox.start({name});name='B';const autosave=sandbox.flush();await pause();
  const duplicate=sandbox.flush();name='A';const undo=sandbox.flush();
  release();await Promise.all([autosave,duplicate,undo]);
  assert.deepEqual(writes,['B','A']);
});
