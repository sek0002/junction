const {test}=require('node:test'),assert=require('node:assert/strict');
const {create,bindDrop}=require('../app/static/upload-queue.js');
const file=(name,size=100,lastModified=1)=>({name,size,lastModified});
test('picker and drop batches append files, ignore duplicates, and flag invalid files',()=>{
  const q=create({extensions:['csv','xlsx']});
  assert.equal(q.add([file('a.csv'),file('b.XLSX')]),2);
  assert.equal(q.add([file('a.csv'),file('c.csv'),file('bad.gb'),file('empty.csv',0),file('large.csv',11*1024*1024)]),4);
  assert.deepEqual(q.jobs.map(j=>j.status),['Queued','Queued','Queued','Error','Error','Error']);
  assert.equal(q.jobs.length,6);assert.match(q.jobs[3].error,/Unsupported/);
});
test('a failed file does not block other imports and completed files are not repeated',async()=>{
  const q=create({extensions:['gbk']}),seen=[];q.add([file('one.gbk'),file('bad.gbk'),file('three.gbk')]);
  await q.run({request:async f=>{seen.push(f.name);if(f.name==='bad.gbk')throw Error('invalid sequence');return {count:1};}});
  assert.deepEqual(q.jobs.map(j=>j.status),['Imported','Error','Imported']);
  await q.run({request:async f=>{seen.push(f.name);return{count:1};}});
  assert.deepEqual(seen,['one.gbk','bad.gbk','three.gbk','bad.gbk']);
  assert.ok(q.jobs.every(j=>j.status==='Imported'));
});
test('preview signatures invalidate when rules change and preserve completed imports',async()=>{
  const q=create({extensions:['csv']});q.add([file('a.csv'),file('b.csv')]);
  await q.run({preview:true,signature:'old',request:async()=>({count:1})});
  assert.ok(q.jobs.every(j=>j.status==='Ready'&&j.signature==='old'));
  let calls=0;await q.run({preview:true,signature:'old',request:async()=>{calls++;}});assert.equal(calls,0);
  await q.run({signature:'old',request:async()=>({count:1})});
  q.add([file('new.csv')]);q.invalidate();
  assert.deepEqual(q.jobs.map(j=>j.status),['Imported','Imported','Queued']);
  assert.equal(q.jobs[2].result,null);
});
test('batch is serialized, busy queues cannot be cleared, and new files wait for next run',async()=>{
  const q=create({extensions:['fa']});q.add([file('a.fa'),file('b.fa')]);
  let release;const pending=new Promise(resolve=>release=resolve),seen=[];
  const running=q.run({request:async f=>{seen.push(f.name);if(f.name==='a.fa')await pending;return{count:1};}});
  assert.equal(q.running,true);assert.equal(q.clear(),false);assert.equal(q.remove(q.jobs[1].id),false);
  q.add([file('c.fa')]);assert.equal(await q.run({request:async()=>{throw Error('parallel upload');}}),false);
  release();await running;
  assert.deepEqual(seen,['a.fa','b.fa']);assert.equal(q.jobs[2].status,'Queued');
  await q.run({request:async f=>{seen.push(f.name);return{count:1};}});
  assert.deepEqual(seen,['a.fa','b.fa','c.fa']);assert.equal(q.clear(),true);
});
test('drop prevents browser file navigation and file picker accepts reselection',()=>{
  const handlers={},input={files:[file('a.csv'),file('b.csv')],value:'selected',addEventListener:(event,fn)=>handlers['input-'+event]=fn};
  const classes=new Set(),zone={classList:{add:v=>classes.add(v),remove:v=>classes.delete(v)},addEventListener:(event,fn)=>handlers[event]=fn},batches=[];
  bindDrop(zone,input,files=>batches.push(files));handlers['input-change']();
  assert.equal(input.value,'');assert.equal(batches[0].length,2);
  let prevented=0;handlers.dragenter({preventDefault:()=>prevented++});assert.ok(classes.has('drag-over'));
  handlers.drop({preventDefault:()=>prevented++,dataTransfer:{files:[file('c.csv'),file('d.csv')]}});
  assert.equal(prevented,2);assert.equal(classes.size,0);assert.equal(batches[1].length,2);
});
test('importing previewed rows preserves errors from rejected plate maps',async()=>{
  const q=create({extensions:['csv']});q.add([file('valid.csv'),file('invalid.csv')]);
  await q.run({preview:true,signature:'rules',request:async f=>{if(f.name==='invalid.csv')throw Error('missing sequence');return{count:1};}});
  const committed=[];await q.run({signature:'rules',eligible:j=>j.status==='Ready'&&j.signature==='rules',request:async f=>{committed.push(f.name);return{count:1};}});
  assert.deepEqual(committed,['valid.csv']);assert.equal(q.jobs[1].error,'missing sequence');
});
