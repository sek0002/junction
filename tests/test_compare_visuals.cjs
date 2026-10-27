const test=require('node:test');
const assert=require('node:assert/strict');
const {perfect,percent}=require('../app/static/compare-visuals.js');
test('green tick requires exact full identity and fragment coverage',()=>{
  assert.ok(perfect({exact:true,identity:1}));assert.ok(perfect({exact:true,identity:1,coverage:1}));
  assert.equal(perfect({exact:true,identity:1,coverage:.5}),false);
  assert.equal(perfect({exact:false,identity:.999999}),false);
  assert.equal(percent({exact:false,identity:.999999}),'>99.99%');
  assert.equal(perfect({exact:true,identity:1,reference_coverage:.5}),false);
});
test('coverage is distinct from identity and excludes alignment gaps',()=>{
  const {coverage,coveragePercent}=require('../app/static/compare-visuals.js');
  assert.equal(coverage({identity:.7,reference_coverage:1}),1);
  assert.equal(coverage({aligned_reference:'ACGT',aligned_query:'ATGT'}),1);
  assert.equal(coverage({aligned_reference:'ACGT',aligned_query:'A--T'}),.5);
  assert.equal(coverage({aligned_reference:'AC--GT',aligned_query:'ACTTGT'}),1);
  assert.equal(coverage({identity:.8}),null);
  assert.equal(coveragePercent({reference_coverage:.999999}),'>99.99%');
});
test('coverage heatmap clamps below 50% to red and maps 75% to yellow and 100% to green',()=>{
  const {coverageHue}=require('../app/static/compare-visuals.js');
  assert.equal(coverageHue({reference_coverage:0}),0);
  assert.equal(coverageHue({reference_coverage:.49}),0);
  assert.equal(coverageHue({reference_coverage:.5}),0);
  assert.equal(coverageHue({reference_coverage:.75}),60);
  assert.equal(coverageHue({reference_coverage:1}),120);
  assert.equal(coverageHue({reference_coverage:2}),120);
  assert.equal(coverageHue({}),null);
});
test('filename tick requires every record in that file to have an exact match',()=>{
  const {filePerfect}=require('../app/static/compare-visuals.js');
  const exact={matches:[{exact:true,identity:1}]},near={matches:[{exact:false,identity:.9999}]};
  assert.ok(filePerfect({status:'Done',result:{records:[exact]}}));
  assert.equal(filePerfect({status:'Done',result:{records:[exact,near]}}),false);
  assert.equal(filePerfect({status:'Comparing',result:{records:[exact]}}),false);
});
test('exports include all exact records or only selected files, excluding full DNA',()=>{
  const {exportRecords}=require('../app/static/compare-visuals.js');
  const exact={query_name:'Exact',query_sequence:'ACTG',matches:[{exact:true,identity:1,name:'Reference',sequence:'ACTG',aligned_query:'ACTG'}]},near={query_name:'Near',matches:[{exact:false,identity:.99}]};
  const jobs=[{id:1,path:'multi.gb',status:'Done',result:{records:[exact,near]}},{id:2,path:'near.gb',status:'Done',result:{records:[near]}}];
  const all=exportRecords(jobs,new Set(),'exact');assert.equal(all.length,1);assert.equal(all[0].filename,'multi.gb');assert.equal(all[0].query_sequence,undefined);assert.equal(all[0].matches[0].sequence,undefined);
  const selected=exportRecords(jobs,new Set([2]),'selected');assert.equal(selected.length,1);assert.equal(selected[0].filename,'near.gb');
  assert.equal(exportRecords(jobs,new Set([1]),'selected').length,2);
});

test('identity heatmap uses identity rather than coverage',()=>{
  const {identityHue}=require('../app/static/compare-visuals.js');
  assert.equal(identityHue({identity:.42,reference_coverage:1}),0);
  assert.equal(identityHue({identity:.75}),60);assert.equal(identityHue({identity:1}),120);
  assert.equal(identityHue({reference_coverage:1}),null);
});
