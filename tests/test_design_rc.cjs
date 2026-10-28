const {test}=require('node:test');
const assert=require('node:assert/strict');
const {reverseDNA,reverseInsert}=require('../app/static/design.js');
const {columns}=require('../app/static/design-table.js');
function fixture(){return {name:'Design',enzyme:'BsaI',backbone_id:42,slot_id:'cassette',left_overhang:'TTTG',right_overhang:'ACCT',use_table:true,entries:[
  {id:'insert',kind:'placeholder',name:'Cargo insert',sequence:'>Template\nAACCGTATGCCATTGAACGT',sections:[
    {name:'Promoter',start:0,end:4,mode:'constant'},
    {name:'Cargo',start:6,end:12,mode:'dynamic',variants:[{name:'Short',sequence:'TTAAGC'},{name:'Long',sequence:'ACGTTTGGAA'}],variant_text:'>Short\nTTAAGC\n>Long\nACGTTTGGAA'},
    {name:'Tail',start:16,end:20,mode:'constant'}]},
  {id:'other',kind:'placeholder',name:'Unchanged',sequence:'AACC',sections:[]},
  {id:'existing',kind:'fragment',fragment_id:17,reverse:true}
],table_rows:[{name:'Alpha',dynamic_inputs:{'insert:6:12':'ATGAAA','other:1:2':'CC'}},{name:'Beta',dynamic_inputs:{'insert:6:12':'>one\nAACCGGTT','old:1:4':'GGTT'}}]};}

test('RC preserves all bases, normalizes pasted DNA and leaves invalid input visible',()=>{
  assert.equal(reverseDNA('>insert\na cgT\nTAA'),'TTAACGT');
  assert.equal(reverseDNA('ACGN;'),' ;NCGT'.trim());
});

test('insert RC mirrors section coordinates and order, transforms alternatives and retains fixed context',()=>{
  const before=fixture(),snapshot=structuredClone(before),after=reverseInsert(before,'insert');
  const insert=after.entries[0];
  assert.equal(insert.sequence,'ACGTTCAATGGCATACGGTT');assert.equal(insert.reverse,true);
  assert.deepEqual(insert.sections.map(s=>[s.name,s.start,s.end,s.mode]),[['Tail',0,4,'constant'],['Cargo',8,14,'dynamic'],['Promoter',16,20,'constant']]);
  assert.equal(insert.sections[1].variant_text,'>Short\nGCTTAA\n>Long\nTTCCAAACGT');
  assert.deepEqual(insert.sections[1].variants.map(v=>[v.name,v.sequence]),[['Short','GCTTAA'],['Long','TTCCAAACGT']]);
  assert.deepEqual(after.entries.slice(1),before.entries.slice(1));
  for(const field of ['name','enzyme','backbone_id','slot_id','left_overhang','right_overhang'])assert.equal(after[field],before[field]);
  assert.deepEqual(before,snapshot);
});

test('named table inputs retain names and map to the mirrored Dynamic region without touching other inserts',()=>{
  const after=reverseInsert(fixture(),'insert');
  assert.deepEqual(after.table_rows,[{name:'Alpha',dynamic_inputs:{'insert:8:14':'TTTCAT','other:1:2':'CC'}},{name:'Beta',dynamic_inputs:{'insert:8:14':'AACCGGTT','old:1:4':'GGTT'}}]);
  const dynamic=columns(after).filter(c=>c.mode==='dynamic');
  assert.equal(dynamic[0].key,'insert:8:14');
  assert.equal(dynamic[0].value,'TGGCAT');
});

test('two RC toggles restore DNA, section metadata, variants and table inputs',()=>{
  const before=fixture();before.entries[0].sequence='AACCGTATGCCATTGAACGT';before.table_rows[1].dynamic_inputs['insert:6:12']='AACCGGTT';
  const after=reverseInsert(reverseInsert(before,'insert'),'insert');
  assert.equal(after.entries[0].reverse,false);assert.equal(after.entries[0].sequence,before.entries[0].sequence);
  assert.deepEqual(after.entries[0].sections.map(({variants,...rest})=>rest),before.entries[0].sections.map(({variants,...rest})=>rest));
  assert.deepEqual(after.entries[0].sections[1].variants,before.entries[0].sections[1].variants);
  assert.deepEqual(after.table_rows,before.table_rows);
});

test('symmetrically placed Dynamic regions swap keys atomically rather than overwriting each other',()=>{
  const before={entries:[{id:'a',kind:'placeholder',name:'a',sequence:'AACCTTGGAACC',sections:[{name:'Left',start:0,end:4,mode:'dynamic'},{name:'Right',start:8,end:12,mode:'dynamic'}]}],table_rows:[{name:'One',dynamic_inputs:{'a:0:4':'AAAC','a:8:12':'CCGA'}}]};
  assert.deepEqual(reverseInsert(before,'a').table_rows[0].dynamic_inputs,{'a:8:12':'GTTT','a:0:4':'TCGG'});
});

test('invalid FASTA and obsolete-cell collisions fail atomically without losing inputs',()=>{
  const before=fixture();before.entries[0].sections[1].variant_text='ORPHAN\n>First\nACGT';
  const copy=structuredClone(before);assert.throws(()=>reverseInsert(before,'insert'),/FASTA header/);assert.deepEqual(before,copy);
  const stale=fixture();stale.table_rows[0].dynamic_inputs['insert:8:14']='TTAA';
  assert.throws(()=>reverseInsert(stale,'insert'),/deleted regions/);
});
