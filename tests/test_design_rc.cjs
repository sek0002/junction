const {test}=require('node:test');
const assert=require('node:assert/strict');
const {exportPayload,fragmentRcTag}=require('../app/static/design.js');
test('Design RC badges follow resolved donor orientation, never saved flags or output preferences',()=>{
 const fragment={kind:'fragment',reverse:true},before=structuredClone(fragment);
 const tag=fragmentRcTag(fragment,{digest:{reverse_complement:true}});
 assert.match(tag,/class="fragment-rc"/);assert.match(tag,/aria-label="Reverse complement"/);assert.match(tag,/<span>RC<\/span>/);
 for(const node of [undefined,{reverse:false},{reverse:true,digest:{reverse_complement:false}}])assert.equal(fragmentRcTag(fragment,node),'');
 assert.equal(fragmentRcTag({kind:'placeholder',reverse:true},{reverse:true,digest:{reverse_complement:true}}),'');
 assert.ok(fragmentRcTag(fragment,{reverse:true}));assert.deepEqual(fragment,before);
});
const fixture=()=>({id:'private',name:'Design',enzyme:'BsaI',reverse_output:false,use_table:true,entries:[{id:'insert',kind:'placeholder',sequence:'AACCGT',sections:[{name:'Cargo',start:1,end:4,mode:'dynamic',variants:[{name:'A',sequence:'TTAACC'}]}]}],table_rows:[{name:'Alpha',dynamic_inputs:{'insert:1:4':'GGTT'}}]});
test('RC output changes only the export preference, preserving design DNA, regions and table inputs',()=>{
 const original=fixture(),before=structuredClone(original),body=exportPayload(original,true);
 assert.equal(body.reverse_output,true);assert.equal(body.id,undefined);
 assert.deepEqual(body.entries,original.entries);assert.deepEqual(body.table_rows,original.table_rows);
 assert.deepEqual(original,before);
});
test('reference export removes batch alternatives without mutating the saved design',()=>{
 const original=fixture(),body=exportPayload(original,true,true);
 assert.equal(body.use_table,false);assert.deepEqual(body.table_rows,[]);assert.deepEqual(body.entries[0].sections[0].variants,[]);
 assert.equal(original.table_rows.length,1);assert.equal(original.entries[0].sections[0].variants.length,1);assert.equal(original.use_table,true);
});
test('forward export overrides a prior saved RC output preference without changing it',()=>{
 const original=fixture();original.reverse_output=true;
 const body=exportPayload(original,false);assert.equal(body.reverse_output,false);assert.equal(original.reverse_output,true);
});
