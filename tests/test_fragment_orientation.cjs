const {test}=require('node:test'),assert=require('node:assert/strict');
const F=require('../app/static/fragment-orientation.js');
const part={id:1,name:'Insert',digest:{left_overhang:'CAAA',right_overhang:'CCAT',target:'ACCTGA',sequence:'CAAAACCTGACCAT',valid:true}};
test('reverse matching swaps both labels and reverse-complements the full payload',()=>{
  const chosen=F.match(part,'ATGG','TTTG');assert.ok(chosen.reverse_complement);
  assert.equal(chosen.digest.left_overhang,'ATGG');assert.equal(chosen.digest.right_overhang,'TTTG');assert.equal(chosen.digest.target,'TCAGGT');
  assert.equal(F.orient(chosen,false).digest.target,'ACCTGA');assert.equal(part.digest.left_overhang,'CAAA');
});
test('both neighbours must match and forward matches win ties',()=>{
  assert.equal(F.match(part,'ATGG','AAAA'),null);assert.equal(F.match(part,'TTTG'),null);
  assert.ok(!F.match(part,'CAAA','CCAT').reverse_complement);
  assert.ok(!F.match({digest:{left_overhang:'ATAT',right_overhang:'ATAT'}},'ATAT','ATAT').reverse_complement);
});
