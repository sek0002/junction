const test=require('node:test');
const assert=require('node:assert/strict');
const D=require('../app/static/difference-viewer.js');
const example=()=>D.build({aligned_reference:'AAC-GTTA',aligned_query:'ATCGG-TA',orientation:'+',rotation:0,features:[{label:'Left',type:'gene',start:0,end:3},{label:'Right',type:'gene',start:3,end:7}]});
test('alignment columns map substitutions, insertions and deletions to real base positions',()=>{
  const m=example();assert.equal(m.referenceLength,7);assert.equal(m.queryLength,7);
  assert.deepEqual(m.changes.map(c=>[c.type,c.startColumn,c.endColumn,c.reference_start,c.reference_end,c.query_start,c.query_end]),[
    ['substitution',1,2,1,2,1,2],['insertion',3,4,3,3,3,4],['deletion',5,6,4,5,5,5]]);
  assert.equal(D.columnForReference(m,3),4);assert.equal(D.columnForReference(m,7),8);
});
test('reference, connector and query tracks share the same columns at every window position',()=>{
  const m=D.build({aligned_reference:'ACGT'.repeat(25)+'---'+'ACGT'.repeat(30),aligned_query:'ACGT'.repeat(25)+'TTT'+'ACGT'.repeat(30)});
  for(const start of [0,1,53,67,110,999]){
    const range=D.windowRange(m,start,120),html=D.windowHtml(m,start,120,null);
    assert.ok(!html.includes('1ch'));
    const blocks=[...html.matchAll(/data-diff-start="(\d+)" data-diff-end="(\d+)" style="--diff-columns:(\d+)"/g)];
    assert.equal(Number(blocks[0][1]),range.start);
    for(const block of blocks)assert.equal(Number(block[3]),Number(block[2])-Number(block[1]));
    const columns=[...html.matchAll(/data-diff-column="(\d+)"/g)].map(m=>Number(m[1]));
    for(let i=range.start;i<range.end;i++)assert.equal(columns.filter(c=>c===i).length,3);
    assert.equal(D.startFor(m,range.sliderValue,120),range.start);
    assert.ok(range.sliderValue>=range.sliderMin&&range.sliderValue<=range.sliderMax);
  }
  const short=D.windowRange(example(),0,120);assert.equal(short.sliderMin,short.sliderMax);
});
test('insertions at annotation boundaries reference both adjacent features',()=>{
  const m=example();assert.deepEqual(D.affected(m,m.changes[1]).map(f=>f.label),['Left','Right']);
  assert.deepEqual(D.affected(m,m.changes[2]).map(f=>f.label),['Right']);
});
test('original query spans and base coordinates account for rotation and reverse complement',()=>{
  const m=D.build({aligned_reference:'AAC-GTTA',aligned_query:'ATCGG-TA',orientation:'-',rotation:2});
  assert.equal(D.queryPosition(m,1),4);
  assert.deepEqual(m.changes[0].original_query_spans,[[3,4]]);
  assert.deepEqual(D.originalSpans(3,6,7,2,'-'),[[0,2],[6,7]]);
  assert.deepEqual(D.originalSpans(7,7,7,0,'+',false),[[7,7]]);
});
test('focused sequence highlights indels and escapes all inserted text',()=>{
  const m=example(),html=D.windowHtml(m,0,8,1);
  assert.ok(html.includes('Reference gap after 3'));assert.ok(html.includes('Original query base 4'));
  assert.ok(html.includes('change-insertion diff-selected-base'));assert.ok(html.includes('change-deletion'));
  const dirty=D.build({aligned_reference:'<tag>',aligned_query:'<tag>',features:[{type:'gene',label:'<script>x</script>',start:0,end:5}]});
  assert.ok(!D.windowHtml(dirty,0,20,null).includes('<tag>'));
  const overview=D.overviewHtml(dirty,null,'all',0,20);assert.ok(overview.includes('&lt;script&gt;'));assert.ok(!overview.includes('<script>'));
});
test('circular-origin annotations correctly identify differences on either side',()=>{
  const m=D.build({aligned_reference:'AACGTTAA',aligned_query:'TACGTTAT',features:[{label:'Origin',type:'gene',start:6,end:10}]});
  assert.equal(D.affected(m,m.changes[0])[0].label,'Origin');assert.equal(D.affected(m,m.changes[1])[0].label,'Origin');
});
test('navigation reaches differences beyond the old 15000-column display limit',()=>{
  const reference='A'.repeat(20000),query=reference.slice(0,19000)+'T'+reference.slice(19001);
  const m=D.build({aligned_reference:reference,aligned_query:query}),start=D.startFor(m,m.changes[0].startColumn,120);
  assert.ok(start>15000);assert.ok(D.windowHtml(m,start,120,0).includes('Reference base 19001'));
  assert.equal(D.startFor(m,0,120),0);assert.equal(D.startFor(m,20000,120),19880);
});
test('exact matches and empty annotation sets remain browsable',()=>{
  const m=D.build({aligned_reference:'ACGT',aligned_query:'ACGT',exact:true});
  assert.deepEqual(m.changes,[]);assert.equal(m.columns,4);
  assert.ok(!D.windowHtml(m,0,120,null).includes('change-'));
  assert.ok(!/NaN|Infinity/.test(D.overviewHtml(m,null,'all',0,120)));
  assert.throws(()=>D.build({aligned_reference:'ACTG',aligned_query:'AC'}),/unavailable/);
});
test('restriction sites use correct cuts on both strands and retain incomplete linear sites',()=>{
  for(const[enzyme,spec]of Object.entries(D.enzymes))for(const[index,motif]of spec.motifs.entries()){
    const seq='C'.repeat(12)+motif+'A'.repeat(15),site=D.restrictionSites(seq).find(s=>s.enzyme===enzyme);
    assert.equal(site.start,12);assert.equal(site.strand,index===0?1:-1);
    const top=enzyme==='HindIII'?13:index===0?18+spec.offset:12-spec.offset-4;
    assert.equal(site.topCut,top);assert.equal(site.bottomCut,top+4);assert.equal(site.overhang,seq.slice(top,top+4));
  }
  const incomplete=D.restrictionSites('GGTCTC')[0];
  assert.equal(incomplete.topCut,null);assert.equal(incomplete.bottomCut,null);assert.equal(incomplete.overhang,'');
  const wrapped=D.restrictionSites('TCTC'+'A'.repeat(6)+'GG',true).find(s=>s.enzyme==='BsaI');
  assert.equal(wrapped.start,10);assert.equal(wrapped.wrapsOrigin,true);assert.equal(wrapped.topCut,5);assert.equal(wrapped.bottomCut,9);
});
test('mutation hovers name affected features and identify a lost colored restriction site',()=>{
  const ref='AAAA'+'GGTCTC'+'AACCGGTT'+'T'.repeat(12),query=ref.slice(0,6)+'A'+ref.slice(7);
  const m=D.build({aligned_reference:ref,aligned_query:query,circular:false,features:[{label:'Promoter <full name>',type:'regulatory',start:0,end:20}]});
  assert.equal(m.refSites.length,1);assert.equal(m.querySites.length,0);assert.equal(m.refSites[0].shared,false);
  const hover=D.hoverHtml(m,'change',0);
  assert.ok(hover.includes('Affected features'));assert.ok(hover.includes('Promoter &lt;full name&gt;'));assert.ok(hover.includes('BsaI'));
  const site=D.hoverHtml(m,'site',0);assert.ok(site.includes('Reference only'));assert.ok(site.includes('Top cut'));assert.ok(site.includes('after base 11'));
  const map=D.overviewHtml(m,0,'all',0,60);assert.ok(!map.includes('Ref RE'));assert.ok(!map.includes('Query RE'));assert.ok(map.includes('--site-bsai'));assert.ok(map.includes('diff-feature-compact'));assert.ok(map.includes('diff-feature-re'));
  const sequence=D.windowHtml(m,0,60,0);assert.ok(sequence.includes('diff-re-base'));assert.ok(sequence.includes('diff-cut-top'));assert.ok(sequence.includes('data-diff-change="0"'));
});
test('joined feature hovers describe the real segments and do not annotate the intervening gap',()=>{
  const m=D.build({aligned_reference:'AACCGGTTAA',aligned_query:'AACCATTTAA',features:[{label:'Joined',type:'CDS',start:0,end:10,segments:[{start:0,end:3},{start:7,end:10}]}]});
  assert.deepEqual(D.affected(m,m.changes[0]),[]);
  const tooltip=D.hoverHtml(m,'feature',0);assert.ok(tooltip.includes('1–3 / 8–10'));assert.ok(tooltip.includes('6 bp'));
});
test('restriction names in fragment titles are not mistaken for restriction annotations',()=>{
  assert.equal(D.enzymeFor({label:'F17 (BsmbI)',type:'misc_feature'}),null);
  assert.equal(D.enzymeFor({label:'BsmBI site',type:'misc_feature'}),'BsmBI');
  assert.equal(D.enzymeFor({label:'Esp3I',type:'restriction_site'}),'BsmBI');
  const ref='C'.repeat(12)+'GGTCTC'+'A'.repeat(5),m=D.build({aligned_reference:ref,aligned_query:ref,circular:false});
  assert.ok(D.windowHtml(m,0,60,null).includes('diff-cut-end-bottom'));
});

test('compact feature lane has no persistent labels and includes query-only restriction sites',()=>{
  const ref='C'.repeat(12)+'GGACTC'+'A'.repeat(15),qry=ref.slice(0,14)+'T'+ref.slice(15);
  const m=D.build({aligned_reference:ref,aligned_query:qry,circular:false,features:[{label:'Full feature name',type:'gene',start:0,end:30}]});
  assert.equal(m.refSites.length,0);assert.equal(m.querySites[0].enzyme,'BsaI');
  const index=m.features.findIndex(f=>f._siteSide==='query');assert.ok(index>=0);
  const html=D.overviewHtml(m,0,'all',0,60);
  assert.equal((html.match(/diff-feature-lane/g)||[]).length,1);
  assert.ok(!html.includes('>Full feature name<'));assert.ok(!html.includes('Ref RE'));assert.ok(!html.includes('Query RE'));
  const hover=D.hoverHtml(m,'feature',index);assert.ok(hover.includes('Query only'));assert.ok(hover.includes('Top cut'));
});

test('feature subtracks follow aligned columns, preserve joined gaps and separate overlapping features',()=>{
  const m=D.build({aligned_reference:'AAA---CCCGGGTTT',aligned_query:'AAATTTCCCGGGTTT',circular:false,features:[
    {label:'Joined',type:'CDS',start:0,end:12,segments:[{start:0,end:3},{start:9,end:12}]},
    {label:'Middle',type:'gene',start:2,end:10},{label:'Unsafe <tag>',type:'misc_feature',start:0,end:1,color:'red;background:evil'}]});
  const parts=D.annotationParts(m,0,m.columns).parts;
  assert.deepEqual(parts.filter(p=>p.index===0).map(p=>[p.start,p.end]),[[0,3],[12,15]]);
  for(const a of parts)for(const b of parts)if(a!==b&&a.lane===b.lane)assert.ok(a.end<=b.start||b.end<=a.start);
  const html=D.featureSubtrack(m,4,13);assert.ok(html.includes('diff-local-feature'));assert.ok(!html.includes('background:evil'));assert.ok(!html.includes('>Joined<'));
  assert.ok(html.includes('width:12px')); // only the second joined segment intersects columns 4..13.
  const overview=D.overviewHtml(m,null,'all',0,60);assert.ok(overview.includes('>Sites<'));assert.ok(overview.includes('diff-annotation-feature'));
});
test('connected enzyme overlays place both cuts on exact column boundaries after alignment gaps',()=>{
  const ref='CCCCCCCCCCCC'+'GGTCTC'+'AACCGGTTAAAA';
  const m=D.build({aligned_reference:ref.slice(0,10)+'---'+ref.slice(10),aligned_query:ref.slice(0,10)+'AAA'+ref.slice(10),circular:false});
  const site=m.refSites[0],a=D.siteColumn(m,'reference',site.topCut),b=D.siteColumn(m,'reference',site.bottomCut);
  assert.equal(a,22);assert.equal(b,26);
  const overlay=D.siteOverlay(m,'reference',0,m.columns);
  assert.ok(overlay.includes('data-diff-cut-top="22" d="M264 0V28"'));
  assert.ok(overlay.includes('data-diff-cut-bottom="26" d="M312 15V28"'));
  assert.ok(overlay.includes('data-diff-cut-span="22:26" d="M264 28H312"'));
  assert.equal((overlay.match(/class="diff-site-motif"/g)||[]).length,1);
  assert.ok(overlay.includes('class="diff-site-leader" d="M252 22H264"'));
  const moved=D.siteOverlay(m,'reference',20,m.columns);assert.ok(moved.includes('data-diff-cut-top="22" d="M24 0V28"'));
});
test('enzyme overlays clip cut brackets at row edges and split circular-origin overhangs',()=>{
  const ref='C'.repeat(50)+'GGTCTC'+'A'.repeat(30),m=D.build({aligned_reference:ref,aligned_query:ref,circular:false});
  const left=D.siteOverlay(m,'reference',0,60),right=D.siteOverlay(m,'reference',60,ref.length);
  assert.ok(left.includes('data-diff-cut-span="57:61" d="M684 28H720"'));assert.ok(!left.includes('data-diff-cut-bottom="61"'));
  assert.ok(right.includes('data-diff-cut-span="57:61" d="M0 28H12"'));assert.ok(right.includes('data-diff-cut-bottom="61" d="M12 15V28"'));
  assert.ok(!right.includes('data-diff-cut-top="57"'));
  const seq='A'.repeat(12)+'GGTCTC'+'A'.repeat(3),circle=D.build({aligned_reference:seq,aligned_query:seq,circular:true});
  const site=circle.refSites[0];assert.deepEqual(D.cutSpans(site,seq.length,true),[{start:19,end:21,top:true,bottom:false},{start:0,end:2,top:false,bottom:true}]);
  const svg=D.siteOverlay(circle,'reference',0,seq.length);assert.ok(!/NaN|Infinity/.test(svg));assert.ok(svg.includes('data-diff-cut-bottom="2"'));assert.ok(!svg.includes('data-diff-cut-span="19:2"'));
});

test('reverse-complement matches use one reference ruler and one row per sequence',()=>{
  const m=D.build({aligned_reference:'AACCGGTTAACCGGTT',aligned_query:'AACCGGTTAACCGGTT',orientation:'-',rotation:3,circular:true});
  const html=D.windowHtml(m,0,120,null);
  assert.equal((html.match(/class="diff-sequence-block"/g)||[]).length,1);
  assert.equal((html.match(/>Reference<\/div>/g)||[]).length,1);
  assert.equal((html.match(/>Query \(RC\)<\/div>/g)||[]).length,1);
  assert.ok(html.includes('Reference coordinates shared by both sequences'));
  assert.ok(html.includes('data-reference-position="1"'));assert.ok(!html.includes('<small>'));
  assert.ok(D.hoverHtml(m,'base',0,'query').includes('Reference base 1'));
  assert.ok(D.hoverHtml(m,'base',0,'query').includes('original base 13'));
  assert.equal(D.originalQueryLabel(m,0,5),'13→9');
});
test('wide alignment windows remain continuous when moving, without repeating reference rows',()=>{
  const m=D.build({aligned_reference:'ACGT'.repeat(160),aligned_query:'ACGT'.repeat(160),orientation:'-',rotation:70});
  for(const size of [60,120,240,480])for(const start of [0,79,160]){
    const html=D.windowHtml(m,start,size,null),range=D.windowRange(m,start,size);
    assert.equal((html.match(/class="diff-sequence-block"/g)||[]).length,1);
    assert.ok(html.includes(`--diff-columns:${range.end-range.start}`));
    assert.ok(html.includes(`data-reference-position="${range.start+1}"`));
  }
});
test('query hovers retain original reverse coordinates while sharing reference positions across indels',()=>{
  const m=D.build({aligned_reference:'AAC---CGGTT',aligned_query:'AACAAACG-TT',orientation:'-',rotation:2});
  assert.ok(D.hoverHtml(m,'base',3,'query').includes('Reference gap after 3'));
  assert.ok(D.hoverHtml(m,'base',8,'query').includes('Reference base 6'));
  assert.equal(D.originalQueryLabel({queryLength:100,rotation:50,orientation:'-',circular:true},35,80),'15→1 / 100→71');
  const html=D.windowHtml(m,0,60,null);assert.ok(html.includes('Reference base 6 · Query gap'));
});
