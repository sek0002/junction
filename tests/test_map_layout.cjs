const test=require('node:test');
const assert=require('node:assert/strict');
const {spread,rows}=require('../app/static/map-layout.js');
function withinBoundsAndSeparated(labels,min,max,gap){
  const sorted=[...labels].sort((a,b)=>a.position-b.position);
  for(const [index,label] of sorted.entries()){
    assert.ok(label.position-label.size/2>=min-1e-7,'label starts outside the map');
    assert.ok(label.position+label.size/2<=max+1e-7,'label ends outside the map');
    if(index)assert.ok(label.position-label.size/2-(sorted[index-1].position+sorted[index-1].size/2)>=gap-1e-7,'labels overlap');
  }
}
test('coincident circular labels repel and retain every feature',()=>{
  const input=Array.from({length:24},(_,index)=>({index,position:40,size:14}));
  const original=structuredClone(input);
  const result=spread(input,24,700,8);
  assert.equal(result.length,input.length);
  assert.equal(new Set(result.map(item=>item.index)).size,24);
  assert.deepEqual(input,original);
  withinBoundsAndSeparated(result,24,700,8);
});
test('both boundaries constrain displaced labels',()=>{
  for(const ideal of [-1000,10000]){
    const result=spread(Array.from({length:10},(_,index)=>({index,position:ideal,size:index%2?35:65})),20,650,10);
    withinBoundsAndSeparated(result,20,650,10);
  }
});
test('dense linear labels get additional non-overlapping rows',()=>{
  const input=Array.from({length:30},(_,index)=>({index,position:495,size:110}));
  const result=rows(input,24,596,10);
  assert.ok(result.count>1);
  assert.equal(result.labels.length,input.length);
  for(let row=0;row<result.count;row++)withinBoundsAndSeparated(result.labels.filter(item=>item.row===row),24,596,10);
});
test('varying label widths remain inside each row without collisions',()=>{
  let seed=72;
  const random=()=>{seed=(seed*1664525+1013904223)>>>0;return seed/2**32;};
  for(let run=0;run<100;run++){
    const input=Array.from({length:1+Math.floor(random()*100)},(_,index)=>({index,position:random()*1000-200,size:10+random()*180}));
    const result=rows(input,24,596,10);
    assert.equal(new Set(result.labels.map(item=>item.index)).size,input.length);
    for(let row=0;row<result.count;row++)withinBoundsAndSeparated(result.labels.filter(item=>item.row===row),24,596,10);
  }
});
test('impossible layouts are rejected instead of overlapping silently',()=>{
  assert.throws(()=>spread([{position:5,size:30},{position:5,size:30}],0,50,8),RangeError);
  assert.throws(()=>rows([{position:5,size:70}],0,50,8),RangeError);
});
