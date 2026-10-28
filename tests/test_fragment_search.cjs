const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const FragmentSearch=require('../app/static/fragment-search.js');
const designSource=fs.readFileSync('app/static/design.js','utf8');
const appSource=fs.readFileSync('app/static/app.js','utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
test('search-match labels distinguish query RC from assembly orientation and escape metadata',()=>{
 assert.equal(FragmentSearch.badge({search_match:{kind:'name'}}),'');
 const part={reverse_complement:false,search_match:{kind:'sequence',reverse_complement:true,start:10,end:25,source:'sequence'}};
 const badge=FragmentSearch.badge(part);assert.match(badge,/DNA · RC/);assert.match(badge,/11–25/);assert.match(badge,/Assembly orientation remains automatic/);assert.equal(part.reverse_complement,false);
 assert.match(FragmentSearch.badge({search_match:{kind:'overhang',side:'left',matched_sequence:'ACCT',reverse_complement:false}}),/5′ overhang ACCT/);
 assert.doesNotMatch(FragmentSearch.badge({search_match:{kind:'overhang',matched_sequence:'<script>'}}),/<script>/);
});
function designFixture(){
 const nodes=new Map(),calls=[],design={id:'one',enzyme:'BsaI'};
 const $=id=>{if(!nodes.has(id))nodes.set(id,{value:'',innerHTML:'',classList:{hidden:false,add(){this.hidden=true;},remove(){this.hidden=false;}}});return nodes.get(id);};
 const context=vm.createContext({$,root:{FragmentSearch},esc:String,URLSearchParams,current:()=>design,label:String,refs:{},refsEnzyme:'BsaI',request:url=>new Promise(resolve=>calls.push({url,resolve}))});
 vm.runInContext('let searchRevision=0;'+designSource.slice(designSource.indexOf('  async function renderSearch(){'),designSource.indexOf('  function sequenceHtml(')),context);
 return {context,$,calls,design,run:code=>vm.runInContext(code,context)};
}
const row=id=>({id,name:'Donor '+id,plate_id:'P1',well:'A1',length:60,digest:{valid:true,left_overhang:'ACCT',right_overhang:'TGCT'},search_match:{kind:'sequence',reverse_complement:true,start:0,end:12,source:'sequence'}});
test('Design uses shared DNA search and only the newest response can populate results',async()=>{
 const f=designFixture();f.$('design-fragment-search').value='ACGTAC';const first=f.context.renderSearch();
 f.$('design-fragment-search').value='AGGT';const second=f.context.renderSearch();
 assert.match(f.calls[1].url,/q=AGGT/);assert.match(f.calls[1].url,/enzyme=BsaI/);
 f.calls[1].resolve({json:async()=>[row(2)]});await second;assert.match(f.$('design-search-results').innerHTML,/Donor 2/);assert.match(f.$('design-search-results').innerHTML,/DNA · RC/);
 f.calls[0].resolve({json:async()=>[row(1)]});await first;assert.doesNotMatch(f.$('design-search-results').innerHTML,/Donor 1/);
});
test('Design ignores a late query after it is cleared or after the enzyme changes',async()=>{
 for(const change of [f=>{f.$('design-fragment-search').value='';f.context.renderSearch();},f=>{f.design.enzyme='BsmBI';}]){
   const f=designFixture();f.$('design-fragment-search').value='ACGTAC';const pending=f.context.renderSearch();change(f);
   f.calls[0].resolve({json:async()=>[row(1)]});await pending;assert.doesNotMatch(f.$('design-search-results').innerHTML,/Donor 1/);
 }
});
test('swap searches intersect sequence matches with compatible alternatives and preserve their orientation',async()=>{
 const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,{value:id==='enzyme'?'BsaI':'ACGTAC',innerHTML:'',querySelectorAll:()=>[]});return nodes.get(id);};
 const context=vm.createContext({$,FragmentSearch,URLSearchParams,esc:String,state:{swapIndex:0},fragmentSwapCandidates:[{...row(1),reverse_complement:true,physical_length:60,swap_backbone_mismatches:[]}],api:async()=>[row(1),row(2)],reverseCompFlag:()=>'<span>Assembly RC</span>',plateLabel:String,fmt:String,fusionEnds:()=>'',positionFragmentSwap(){}});
 vm.runInContext('let swapSearchCounter=0;'+appSource.slice(appSource.indexOf('async function renderSwapOptions()'),appSource.indexOf('\nfunction compatibleFragmentAlternatives(')),context);
 await context.renderSwapOptions();assert.match($('swap-options').innerHTML,/Donor 1/);assert.match($('swap-options').innerHTML,/Assembly RC/);assert.match($('swap-options').innerHTML,/DNA · RC/);assert.doesNotMatch($('swap-options').innerHTML,/Donor 2/);
});
