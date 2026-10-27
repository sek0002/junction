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
