const {test}=require('node:test');
const assert=require('node:assert/strict');
const {dna,addSection,moveEntry,parseVariants}=require('../app/static/design.js');
test('FASTA input preserves invalid bases for explicit validation',()=>{
  assert.equal(dna('>insert\nac gt\r\nTT'),'ACGTTT');
  assert.equal(dna('ACGT N;'),'ACGTN;');
});
test('highlighted regions preserve coordinates, mode and sequence order',()=>{
  const sequence='ACGT'.repeat(100);
  let sections=addSection([],sequence,100,200,'Cargo','dynamic');
  sections=addSection(sections,sequence,0,100,'Promoter','constant');
  assert.deepEqual(sections.map(s=>[s.name,s.start,s.end,s.mode]),[['Promoter',0,100,'constant'],['Cargo',100,200,'dynamic']]);
  assert.throws(()=>addSection(sections,sequence,99,120,'Overlap'));
  assert.throws(()=>addSection([],sequence,-1,2,'Outside'));
  assert.throws(()=>addSection([],sequence,1,401,'Outside'));
});
test('drag ordering retains placeholder identity and the original inputs',()=>{
  const original=[{id:'constant'},{id:'dynamic'},{id:'tail'}];
  assert.deepEqual(moveEntry(original,1,0).map(e=>e.id),['dynamic','constant','tail']);
  assert.deepEqual(original.map(e=>e.id),['constant','dynamic','tail']);
  assert.deepEqual(moveEntry(original,0,-1),original);
});

test('pasted dynamic alternatives parse FASTA without changing DNA or dropping invalid bases',()=>{
  assert.deepEqual(parseVariants('>Short\nac gt\n>Long\nTTAA\nCC'),[{name:'Short',sequence:'ACGT'},{name:'Long',sequence:'TTAACC'}]);
  assert.deepEqual(parseVariants('ac gt\nTT'),[{name:'Variant 1',sequence:'ACGTTT'}]);
  assert.deepEqual(parseVariants(''),[]);assert.equal(parseVariants('>Bad\nACGN')[0].sequence,'ACGN');
});
