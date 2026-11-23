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

test('A/T-adjusted percentages show true percentages beside them and retain exact-match rules',()=>{
  const V=require('../app/static/compare-visuals.js');
  const match={identity:.9,adjusted_identity:1,reference_coverage:.9,adjusted_reference_coverage:1,exact:false,excluded_at_deletion_bp:20};
  assert.equal(V.percent(match),'100%');assert.equal(V.percent(match,false),'90%');
  assert.equal(V.coveragePercent(match),'100%');assert.equal(V.coveragePercent(match,false),'90%');
  const html=V.identityHtml(match);
  for(const label of ['Adjusted identity','True identity','20 A/T deletion bp excluded','at least 20 bases'])assert.ok(html.includes(label),label);
  assert.equal(V.perfect(match),false);
  const coverage=V.coverageHtml(match);assert.ok(coverage.includes('Adjusted coverage'));assert.ok(coverage.includes('True coverage'));
  const record={matches:[match]};
  assert.equal(V.filePerfect({status:'Done',result:record}),false);
  const exported=V.exportRecords([{id:1,path:'polyA.gb',status:'Done',result:record}],new Set([1]),'selected');
  assert.equal(exported[0].matches[0].identity,.9);assert.equal(exported[0].matches[0].adjusted_identity,1);assert.equal(exported[0].matches[0].excluded_at_deletion_bp,20);
});

test('adjusted 100% gets its own tick and all completed records must qualify for a file tick',()=>{
 const V=require('../app/static/compare-visuals.js');
 const adjusted={exact:false,identity:.9,adjusted_identity:1,excluded_at_deletion_bp:25};
 const exact={exact:true,identity:1,adjusted_identity:1};
 assert.equal(V.matchType(adjusted),'adjusted');assert.equal(V.matchType(exact),'exact');
 assert.equal(V.matchType({...adjusted,adjusted_identity:.999999}),null);
 assert.ok(V.identityHtml(adjusted).includes('aria-label="100% adjusted identity"'));
 const job={status:'Done',result:{records:[{matches:[exact]},{matches:[adjusted]}]}};
 assert.equal(V.fileMatchType(job),'adjusted');
 job.result.records[1].matches=[{...adjusted,adjusted_identity:.999999}];assert.equal(V.fileMatchType(job),null);
 job.result.records[1].matches=[exact];assert.equal(V.fileMatchType(job),'exact');
 job.status='Comparing';assert.equal(V.fileMatchType(job),null);
});

test('100% result exports include true and adjusted records while retaining both percentages',()=>{
 const V=require('../app/static/compare-visuals.js');
 const records=[{query_name:'True',matches:[{exact:true,identity:1}]},
  {query_name:'Adjusted',matches:[{exact:false,identity:.9,adjusted_identity:1,excluded_at_deletion_bp:20}]},
  {query_name:'Rounded',matches:[{exact:false,identity:.9,adjusted_identity:.999999}]},
  {query_name:'Error',error:'Invalid record',matches:[{identity:.9,adjusted_identity:1}]}];
 const exported=V.exportRecords([{id:1,path:'multi.gb',status:'Done',result:{records}}],new Set(),'exact');
 assert.deepEqual(exported.map(r=>r.query_name),['True','Adjusted']);
 assert.equal(exported[1].matches[0].identity,.9);assert.equal(exported[1].matches[0].adjusted_identity,1);
});
