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

const fragment=(id,left,right,name='Fragment '+id)=>({id,name,plate_id:'Plate',well:'A1',digest:{left_overhang:left,right_overhang:right,target:'ACCTGA',valid:true}});
test('an empty side can change while an occupied fragment side stays matched',()=>{
  const current=fragment(1,'CAAA','CCAT'),next=fragment(2,'CCAT','GATT');
  const candidates=[fragment(3,'GTTA','CCAT'),fragment(4,'GTTA','AGTC')];
  assert.deepEqual(F.alternatives([current,next],candidates,0).map(p=>p.id),[3]);
  const previous=fragment(2,'GATT','CAAA');
  assert.deepEqual(F.alternatives([previous,current],[fragment(3,'CAAA','AGTC')],1).map(p=>p.id),[3]);
  assert.equal(F.alternatives([fragment(1,'','')],[fragment(3,'AGTC','CCAT')],0).length,1);
});
test('an unmatched backbone side can change freely and ranks repairs first',()=>{
  const current=fragment(1,'CAAA','CCAT'),next=fragment(2,'CCAT','GATT');
  const variants=[fragment(3,'CAAA','CCAT','A variant'),fragment(4,'GTTA','CCAT','Z repair'),fragment(5,'AGTC','CCAT')];
  const result=F.alternatives([current,next],variants,0,{hasBackbone:true,left:'GTTA',right:'GATT'});
  assert.deepEqual(result.map(p=>p.id),[4,3,5]);
  assert.deepEqual(result[0].swap_backbone_mismatches,[]);
  assert.deepEqual(result[1].swap_backbone_mismatches,['5′ backbone: CAAA / GTTA']);
  assert.equal(current.digest.left_overhang,'CAAA');
});
test('a fragment alone can swap freely until both backbone ends are matched',()=>{
  const current=fragment(1,'CAAA','CCAT');
  const candidates=[fragment(2,'CAAA','CCAT'),fragment(3,'GTTA','AGTC'),fragment(4,'CAAA','AGTC')];
  assert.equal(F.alternatives([current],candidates,0).length,3);
  assert.equal(F.alternatives([current],candidates,0,{hasBackbone:true,left:'GTTA',right:'AGTC'}).length,3);
  assert.deepEqual(F.alternatives([current],candidates,0,{hasBackbone:true,left:'CAAA',right:'CCAT'}).map(p=>p.id),[2]);
});
test('the right backbone boundary and reverse-complement repair are supported',()=>{
  const current=fragment(1,'CAAA','CCAT'),previous=fragment(2,'GATT','CAAA');
  const right=F.alternatives([previous,current],[fragment(3,'CAAA','CCAT'),fragment(4,'CAAA','GTTA')],1,{hasBackbone:true,right:'GTTA'});
  assert.deepEqual(right.map(p=>p.id),[4,3]);
  assert.deepEqual(right[1].swap_backbone_mismatches,['3′ backbone: CCAT / GTTA']);
  const reversed=F.alternatives([current],[fragment(3,'ATGG','TAAC')],0,{hasBackbone:true,left:'GTTA',right:'CCAT'})[0];
  assert.ok(reversed.reverse_complement);
  assert.equal(reversed.digest.left_overhang,'GTTA');
  assert.deepEqual(reversed.swap_backbone_mismatches,[]);
});
test('known fragment neighbours remain required and used or invalid inputs stay excluded',()=>{
  const current=fragment(1,'CAAA','CCAT'),previous=fragment(2,'GATT','CAAA'),next=fragment(3,'CCAT','TCAT');
  const bad=fragment(7,'CAAA','CCAT');bad.digest.valid=false;
  const result=F.alternatives([previous,current,next],[current,previous,next,fragment(4,'CAAA','CCAT'),fragment(5,'CAAA','AGTC'),fragment(6,'GTTA','CCAT'),bad],1,{hasBackbone:true,left:'GTTA',right:'GTTA'});
  assert.deepEqual(result.map(p=>p.id),[4]);
});
