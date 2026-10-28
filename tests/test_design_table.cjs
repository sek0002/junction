const {test}=require('node:test');
const assert=require('node:assert/strict');
const {columns,parseDelimited,applyPaste,templateTSV}=require('../app/static/design-table.js');
const schema=columns({entries:[{id:'insert',kind:'placeholder',name:'Insert',sequence:'AACCGGTTCCAATTGG',sections:[{name:'Cargo A',start:4,end:8,mode:'dynamic'},{name:'Cargo B',start:12,end:16,mode:'dynamic'}]}]});
test('table mirrors sequence order with fixed constant columns and stable dynamic keys',()=>{
  assert.deepEqual(schema.map(c=>c.mode),['name','constant','dynamic','constant','dynamic']);
  assert.equal(schema[2].key,'insert:4:8');assert.equal(schema[1].value,'AACC');
  const fixed=columns({entries:[{id:'existing',kind:'fragment',name:'F1'}]},[{id:'existing',digest:{target:'AACCAA'}}]);
  assert.equal(fixed[1].value,'AACCAA');assert.equal(fixed[1].mode,'constant');
});
test('TSV and quoted CSV accept multiline sequence cells and escaped names',()=>{
  assert.deepEqual(parseDelimited('\ufeffName,A,B\r\n"Alpha, \"\"one\"\"","AC\nGT",TTAA'),[['Name','A','B'],['Alpha, "one"','AC\nGT','TTAA']]);
  const rows=applyPaste([], 'Name\tCargo A\tCargo B\nAlpha\tac gt\tCCAA\nBeta\tTTAA\tGGTT',schema);
  assert.deepEqual(rows,[{name:'Alpha',dynamic_inputs:{'insert:4:8':'ACGT','insert:12:16':'CCAA'}},{name:'Beta',dynamic_inputs:{'insert:4:8':'TTAA','insert:12:16':'GGTT'}}]);
  assert.throws(()=>parseDelimited('"open'),/quoted CSV/);
});
test('full table paste verifies constants atomically and exported template round-trips',()=>{
  const template=templateTSV(schema),rows=applyPaste([],template,schema);
  assert.deepEqual(rows,[{name:'Example',dynamic_inputs:{'insert:4:8':'GGTT','insert:12:16':'TTGG'}}]);
  const original=structuredClone(rows);
  assert.throws(()=>applyPaste(rows,'Alpha\tAAAA\tGGTT\tCCAA\tTTGG',schema,0),/Constant sequence differs/);
  assert.deepEqual(rows,original);
  assert.throws(()=>applyPaste(rows,'Name\tNo such column\nBeta\tACGT',schema),/Unknown/);
  assert.throws(()=>applyPaste(rows,'Name\tCargo A\tCargo A\nBeta\tACGT\tACGT',schema),/repeat/);
});
test('native cell paste fills downward and across dynamic inputs without overwriting constants or original data',()=>{
  const initial=[{name:'Keep',dynamic_inputs:{'insert:4:8':'AAAA','insert:12:16':'TTTT'}}];
  const rows=applyPaste(initial,'CCCC\tGGGG\nAACC\tTTGG',schema,0,'insert:4:8');
  assert.equal(rows[0].name,'Keep');assert.equal(rows[1].name,'Variant 2');
  assert.deepEqual(rows[0].dynamic_inputs,{'insert:4:8':'CCCC','insert:12:16':'GGGG'});
  assert.equal(initial[0].dynamic_inputs['insert:4:8'],'AAAA');
  assert.throws(()=>applyPaste(initial,'AA\tCC',schema,0,schema[1].key),/fixed/);
  assert.throws(()=>applyPaste(initial,'X\tAA\tCC\tGG',schema),/Too many/);
  assert.throws(()=>applyPaste([],Array(385).fill('Sample\tACGT\tTTAA').join('\n'),schema),/384/);
});

test('copied template uses unique keys when region titles repeat',()=>{
  const repeated=schema.map(column=>({...column,title:column.mode==='dynamic'?'Repeated / Cargo':column.title}));
  assert.deepEqual(applyPaste([],templateTSV(repeated),repeated),[{name:'Example',dynamic_inputs:{'insert:4:8':'GGTT','insert:12:16':'TTGG'}}]);
});
