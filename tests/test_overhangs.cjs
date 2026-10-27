const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const Overhangs=require('../app/static/overhangs.js');
const source=fs.readFileSync(require('node:path').join(__dirname,'../app/static/app.js'),'utf8');

test('all 256 four-base labels identify exactly the 16 reverse-complement palindromes',()=>{
  const palindromes=[];
  for(const a of 'ACGT')for(const b of 'ACGT')for(const c of 'ACGT')for(const d of 'ACGT'){
    const label=a+b+c+d;
    if(Overhangs.isPalindromic(label))palindromes.push(label);
  }
  assert.deepEqual(palindromes,['AATT','ACGT','AGCT','ATAT','CATG','CCGG','CGCG','CTAG','GATC','GCGC','GGCC','GTAC','TATA','TCGA','TGCA','TTAA']);
  for(const label of ['AAAA','CCCC','AGAG','','—','AT','ATATAT','NATN','<ATAT>'])assert.equal(Overhangs.isPalindromic(label),false,label);
  assert.equal(Overhangs.isPalindromic(' tcga '),true);
  assert.deepEqual(Overhangs.labels('TCGA','tcga'),['TCGA']);
});
function ui(){
  const elements={'sequence-start':{value:1},'sequence-view':{innerHTML:''}};
  const context=vm.createContext({PlasmidFeatures:require('../app/static/plasmid-features.js'),Overhangs,$:id=>elements[id],esc:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),state:{result:null,selectedFeature:null},isBackboneLinker:label=>label==='ATAT'});
  vm.runInContext(source.slice(source.indexOf('function overhangHtml('),source.indexOf('function validationGlyph(')),context);
  vm.runInContext(source.slice(source.indexOf('function fragmentLinker('),source.indexOf('let buildSaveTimer')),context);
  vm.runInContext(source.slice(source.indexOf('function nestedLinker('),source.indexOf('function renderNestedEditor(')),context);
  vm.runInContext(source.slice(source.indexOf('function renderSequence('),source.indexOf('\n',source.indexOf('function renderSequence('))),context);
  return {context,elements};
}
test('backbone, mismatched and nested labels flag only the palindromic side',()=>{
  const {context}=ui();
  const link=context.fragmentLinker('ATAT','CAGT');
  assert.match(link,/backbone-linker incompatible/);
  assert.match(link,/linker-sequence backbone-overhang palindromic-overhang/);
  assert.match(link,/class="linker-other">CAGT/);
  const nested=context.nestedLinker('ATAT','CAGT',{left_overhang:'ATAT',right_overhang:'AGGT'});
  assert.match(nested,/nested-boundary palindromic-overhang/);
  assert.match(nested,/class="nested-mismatch">CAGT/);
  const ends=context.fusionEnds('TCGA','ACCT');
  assert.equal((ends.match(/class="end palindromic-overhang"/g)||[]).length,1);
  assert.match(ends,/can self-ligate/);
});
test('message formatting escapes HTML and flags explicit fusion labels',()=>{
  const {context}=ui();
  const html=context.overhangMessage('Incompatible junction <unsafe>: TCGA does not match ACCT.');
  assert.match(html,/&lt;unsafe&gt;/);assert.match(html,/palindromic-overhang/);
  assert.equal(context.overhangMessage('Feature named TCGA'),'Feature named TCGA');
});
test('sequence view flags annotated fusion positions and leaves incidental DNA words unchanged',()=>{
  const {context,elements}=ui();
  context.state.result={sequence:'ATATTCGACAGT',circular:false,features:[{source:'fusion',start:4,end:8}]};
  context.renderSequence();
  assert.equal((elements['sequence-view'].innerHTML.match(/class="palindromic-overhang/g)||[]).length,4);
  assert.match(elements['sequence-view'].innerHTML,/ATAT<mark/);
  context.state.result={sequence:'GACCCCCCTC',circular:true,features:[{label:'TCGA fusion: boundary',start:8,end:12}]};
  context.renderSequence();
  assert.equal((elements['sequence-view'].innerHTML.match(/class="palindromic-overhang/g)||[]).length,4);
});
