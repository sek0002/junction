'use strict';
const assert=require('node:assert/strict');
const m=require('../app/static/mrna.js');
assert.equal(m.hamming('ATGGAATTT','ATGGAGTTC'),2/9);
assert.equal(m.hamming('aug gaa','ATGGAA'),0);
assert.equal(m.hamming('ATG','ATGG'),null);
assert.equal(m.hamming('',''),null);
assert.deepEqual(m.parse('>A\nauggaa\n>B\nATGGAG').map(r=>r.sequence),['auggaa','ATGGAG']);
assert.equal(m.parse('>Protein\nACGT','input.faa')[0].kind,'protein');
assert.deepEqual(m.parse('name,sequence,group\n"a,b",ATGGAA,"Set 1"\n"b",ATGGAG,"Set 2"').map(r=>r.name),['a,b','b']);
assert.equal(m.parse('tx_id\tcds_sequence\na\tATGGAA','in.tsv')[0].sequence,'ATGGAA');
assert.throws(()=>m.parse('name,length\na,6'),/sequence or cds/);
assert.throws(()=>m.csvRows('a,"unclosed'),/Unclosed/);
assert.equal(m.csvCell('=SUM(A1:A2)'),"\"'=SUM(A1:A2)\"");
assert.equal(m.csvCell(-123.4),'-123.4');
console.log('mRNA input, comparison and export checks passed');

// Independent column scales retain missing values and use population SD.
const stats=m.columnStats([1,2,3,null],x=>x);
assert.equal(stats.n,3);assert.equal(stats.mean,2);
assert.equal(m.zScore(2,stats),0);assert.ok(Math.abs(m.zScore(3,stats)-Math.sqrt(1.5))<1e-10);
assert.equal(m.zScore(null,stats),null);assert.equal(m.zScore(4,m.columnStats([4,4],x=>x)),0);
assert.equal(m.zScore(1,m.columnStats([],x=>x)),null);
assert.equal(m.zColor(-2),'#000004');assert.equal(m.zColor(2),'#fcffa4');assert.equal(m.zColor(0),'#bc3754');
assert.equal(m.stabilityColor(0,0,1),'#fcffa4');assert.equal(m.stabilityColor(1,0,1),'#000004');assert.equal(m.stabilityColor(null,0,1),'#aab7b0');
const row={id:'0-0',input_name:'A',name:'A input',strategy:'input',group:'G',cds:'GCGCAT',fold_sequence:'AAAGCGCATTT',fold_scope:'transcript',regions:{cds:[4,9]},gc_window:4,gc_profile:[[1,1],[2,.75],[3,.5]],pairs:[[1,11],[4,9]]};
assert.deepEqual(m.foldRange(row,1,4),{start:1,end:4,fold_start:4,fold_end:7});
assert.equal(m.gcWindowForBase(row,3),null);assert.equal(m.gcWindowForBase(row,10),null);
assert.equal(m.gcWindowForBase(row,4).fold_start,4);assert.equal(m.gcWindowForBase(row,9).fold_end,9);
const after={...row,id:'0-1',name:'A after',strategy:'MaxCAI',gc_profile:[[1,.5],[2,.5],[3,.5]]};
const unrelated={...row,id:'1-0',input_name:'B',group:'Other'};
assert.equal(m.matchedPairs([unrelated,after,row])[0].before.id,row.id);
assert.equal(m.matchedPairs([unrelated,after]).length,0);
const sameStrategy={...row,id:'2-0',name:'C input',gc_profile:[[1,.5],[2,.25]]};
const grouped=m.gcSeries([row,after,sameStrategy],true);
assert.equal(grouped.length,2);assert.equal(grouped[0].strategy,'input');assert.equal(grouped[0].points[0].gc,.75);assert.equal(grouped[0].points[0].n,2);assert.equal(grouped[0].points.at(-1).n,1);
assert.equal(grouped[1].points[0].gc,.5);
const long={...row,fold_sequence:'A'.repeat(1000),pairs:[[1,1000],[50,140],[400,700]]};
const arc=m.arcGeometry(long,500,150);assert.equal(arc.width,150);assert.ok(arc.start<=500&&arc.end>=500);assert.equal(arc.end-arc.start,149);assert.ok(arc.box[3]<arc.box[2]);
assert.equal(m.arcGeometry(long,1,150).start,1);assert.equal(m.arcGeometry(long,1000,150).end,1000);assert.equal(m.arcGeometry(long,500,'all').width,1000);
console.log('mRNA linked coordinates, heatmap, grouping, paired radar and arc checks passed');

// A selected transcript region clips to the CDS without losing UTR coordinates.
assert.deepEqual(m.sequenceRange(row,8,5),{fold_start:5,fold_end:8,start:2,end:5,gc:.75});
assert.deepEqual(m.sequenceRange(row,1,3),{fold_start:1,fold_end:3,start:null,end:null,gc:null});
assert.deepEqual(m.sequenceRange(row,2,6),{fold_start:2,fold_end:6,start:1,end:3,gc:1});
assert.deepEqual(m.sequenceRange(row,8,11),{fold_start:8,fold_end:11,start:5,end:6,gc:0});
assert.equal(m.sequenceRange(row,-10,100).fold_end,11);
assert.equal(m.sequenceRange({...row,fold_scope:'cds',fold_sequence:row.cds},2,4).gc,1);
assert.equal(m.selectedPositions(null,{}),null);
console.log('mRNA persistent sequence range and transcript/CDS clipping checks passed');

assert.equal(m.infernoColor(0),'#000004');assert.equal(m.infernoColor(1),'#fcffa4');assert.equal(m.infernoColor(-1),'#000004');
assert.equal(m.contrastColor('#000004'),'#ffffff');assert.equal(m.contrastColor('#fcffa4'),'#000000');
assert.equal(m.radarFraction(.8,{min:0,max:1,direction:'higher'}),.8);
assert.equal(m.radarFraction(-.25,{min:-.5,max:0,direction:'lower'}),.5);
assert.equal(m.radarFraction(60,{min:40,max:70,target:60,direction:'target'}),1);
assert.equal(m.radarFraction(70,{min:40,max:70,target:60,direction:'target'}),0);
assert.equal(m.radarFraction(100,{min:0,max:1,direction:'higher'}),1);
assert.equal(m.radarFraction(null,{min:0,max:1,direction:'higher'}),null);
assert.equal(m.restoreRadarRanges({cai:{min:2,max:1,direction:'higher'}}).cai.max,1);
assert.equal(m.restoreRadarRanges({gc:{min:40,max:70,target:100,direction:'target'}}).gc.target,60);
console.log('mRNA Inferno and fixed-reference radar checks passed');
assert.deepEqual(m.gcDisplayRange(100,{start:20,end:80}),{start:20,end:80});
assert.deepEqual(m.gcDisplayRange(100,{start:-10,end:200}),{start:1,end:100});
assert.deepEqual(m.gcDisplayRange(100,{start:100,end:100}),{start:99,end:100});
assert.deepEqual(m.gcDisplayRange(100,{start:1,end:null}),{start:1,end:100});
console.log('mRNA GC viewport bounds checks passed');

// The radar reads the nearest displayed axis rather than interpolating polygon values.
assert.equal(m.radarAxisIndex(270,82,5),0);
assert.equal(m.radarAxisIndex(408,220,4),1);
assert.equal(m.radarAxisIndex(270,358,4),2);
assert.equal(m.radarAxisIndex(132,220,4),3);
assert.equal(m.radarAxisIndex(269.999,82,5),0);
assert.equal(m.radarAxisIndex(270,220,5),-1);
assert.equal(m.radarAxisIndex(270,-100,5),-1);
assert.equal(m.radarAxisIndex(NaN,220,5),-1);
assert.equal(m.radarAxisIndex(270,82,2),-1);
console.log('mRNA radar hover axis selection checks passed');

// Fit only when explicitly requested; keep signed raw translation values and padding.
assert.deepEqual(m.fitRadarRange([.63,.96]),{min:.58,max:1.01});
assert.deepEqual(m.fitRadarRange([0,0]),{min:-.05,max:.05});
assert.deepEqual(m.fitRadarRange([-4,-2]),{min:-4.3,max:-1.7});
assert.equal(m.fitRadarRange([null,1]),null);
assert.equal(m.fitRadarRange([]),null);
console.log('mRNA optional translation axis fit checks passed');

assert.equal(m.radarDefaults.predicted_half_life.max,2);
assert.deepEqual([m.radarDefaults.translation.min,m.radarDefaults.translation.max],[0,2]);
const migrated=m.restoreRadarRanges({translation:{min:-3,max:3,direction:'higher'},predicted_half_life:{min:0,max:24,direction:'higher'}},1);
assert.equal(migrated.translation.max,2);assert.equal(migrated.predicted_half_life.max,2);
assert.equal(m.restoreRadarRanges({translation:{min:-2,max:7,direction:'higher'}},1).translation.max,7);
assert.equal(m.restoreRadarRanges({translation:{min:-3,max:3,direction:'higher'}},2).translation.max,3);
console.log('mRNA revised model ranges migrate only legacy defaults and preserve custom bounds');

const reference={...after,id:'benchmark:fixture',name:'Reference fixture',strategy:'benchmark',benchmark:{id:'fixture'}};
assert.equal(m.matchedPairs([row,after,reference]).length,1);
assert.equal(m.hamming(reference.cds,reference.cds),0);
assert.equal(m.hamming(reference.cds,row.cds+'ATG'),null);
console.log('mRNA references remain separate from optimisation pairs');

// Previous default migrates once; deliberate custom limits remain unchanged.
assert.equal(m.restoreRadarRanges({translation:{min:0,max:5,direction:'higher'}},2).translation.max,2);
assert.equal(m.restoreRadarRanges({translation:{min:0,max:5,direction:'higher'}},3).translation.max,5);
assert.equal(m.restoreRadarRanges({translation:{min:-1,max:5,direction:'higher'}},2).translation.min,-1);
for(const [key,range] of Object.entries(m.radarDefaults)){
 const lo=m.radarScaleBounds(key,range,'min'),hi=m.radarScaleBounds(key,range,'max');
 assert(lo.min<=range.min&&lo.max<range.max&&lo.step>0);assert(hi.max>=range.max&&hi.min>range.min&&hi.step>0);
 if(range.direction==='target'){const t=m.radarScaleBounds(key,range,'target');assert(t.min<range.target&&t.max>range.target);assert(lo.max<range.target&&hi.min>range.target);}
}
assert.equal(m.radarScaleBounds('translation',{min:-7,max:9,direction:'higher'},'min').min,-7);
assert.equal(m.radarScaleBounds('translation',{min:-7,max:9,direction:'higher'},'max').max,9);
console.log('mRNA translation range migration and parameter slider bounds passed');
