const test=require('node:test'),assert=require('node:assert/strict');
const F=require('../app/static/compare-files.js');
const match=(name,identity=1)=>({name,identity,exact:identity===1,reference_coverage:1,query_coverage:1});
const job=(id,path,identity=1)=>({id,path,status:'Done',expanded:true,recordIndex:0,result:{records:[{query_name:'Sample '+id,matches:[match('Plasmid '+id,identity)],fragment_matches:[{name:'Fragment '+id}]}]}});
test('file search finds names, samples, candidate aliases and fragments without changing jobs',()=>{
 const jobs=[job(1,'folder/Run2.gb'),job(2,'Run10.gb',.95)];jobs[0].result.records[0].matches[0].aliases=[{name:'pHR alternate'}];jobs[0].result.records[0].fragment_matches[0].name='Unique payload';
 for(const search of ['run2','FOLDER sample 1','phr alternate','unique payload'])assert.deepEqual(F.select(jobs,{search}).map(j=>j.id),[1]);
 assert.deepEqual(F.select(jobs,{search:'not found'}),[]);assert.deepEqual(jobs.map(j=>j.id),[1,2]);assert.equal(jobs[0].expanded,true);
});
test('filters distinguish exact files, mixed differences, no matches and processing errors',()=>{
 const exact=job(1,'exact'),mixed=job(2,'mixed');mixed.result.records.push({query_name:'second',matches:[match('Near',.99)]});
 const empty=job(3,'empty');empty.result.records[0].matches=[];
 const partial=job(4,'partial');partial.result.records.push({error:'Invalid record'});
 const jobs=[exact,mixed,empty,partial,{id:5,path:'error',status:'Error'},{id:6,path:'queued',status:'Queued'},{id:7,path:'reading',status:'Comparing'},{id:8,path:'unsupported',status:'Skipped'}];
 const ids=filter=>F.select(jobs,{filter}).map(j=>j.id);
 assert.deepEqual(ids('exact'),[1]);assert.deepEqual(ids('differences'),[2,4]);assert.deepEqual(ids('no-matches'),[3]);
 assert.deepEqual(ids('errors'),[4,5]);assert.deepEqual(ids('queued'),[6]);assert.deepEqual(ids('comparing'),[7]);assert.deepEqual(ids('skipped'),[8]);
});
test('numeric identity and fragment sorts put missing results last in either direction',()=>{
 const jobs=[job(1,'file10',.9),job(2,'file2',.99999),job(3,'file1',1),{id:4,path:'pending',status:'Queued'}];
 assert.deepEqual(F.select(jobs,{sort:'identity',direction:-1}).map(j=>j.id),[3,2,1,4]);
 assert.deepEqual(F.select(jobs,{sort:'identity',direction:1}).map(j=>j.id),[1,2,3,4]);
 assert.deepEqual(F.select(jobs,{sort:'file'}).map(j=>j.id),[3,2,1,4]);
 assert.deepEqual(jobs.map(j=>j.id),[1,2,3,4]);
 jobs[1].result.records[0].fragment_matches=[];
 assert.deepEqual(F.select(jobs,{sort:'fragments',direction:1}).map(j=>j.id),[2,1,3,4]);
});
test('sort values follow the record actually displayed and ties retain upload order',()=>{
 const jobs=[job(1,'one',.8),job(2,'two',.8)];jobs[0].result.records.push({matches:[match('Alternate',1)],fragment_matches:[]});
 assert.deepEqual(F.select(jobs,{sort:'identity',direction:-1}).map(j=>j.id),[1,2]);
 jobs[0].recordIndex=1;assert.equal(F.value(jobs[0],'identity'),1);assert.equal(F.value(jobs[0],'match'),'Alternate');
});
test('select all affects visible completed files and preserves hidden selections',()=>{
 const jobs=[job(1,'first'),job(2,'second'),{id:3,path:'third',status:'Queued'}],selected=new Set([2]);
 F.selectVisible(selected,[jobs[0],jobs[2]],true);assert.deepEqual([...selected].sort(),[1,2]);
 F.selectVisible(selected,[jobs[0]],false);assert.deepEqual([...selected],[2]);
 assert.deepEqual(F.select(jobs,{filter:'selected'},selected).map(j=>j.id),[2]);
});
