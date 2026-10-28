const {test}=require('node:test');
const assert=require('node:assert/strict');
const {record,assembly}=require('../app/static/design-preview.js');
test('insert viewer includes every Constant gap and named Dynamic region in displayed coordinates',()=>{
 const entry={name:'Insert',reverse:true,sections:[{name:'Cargo',start:4,end:8,mode:'dynamic'}]};
 const sites=[{enzyme:'BsaI',start:2,end:8,strand:1,motif:'GGTCTC'}];
 const r=record(entry,{kind:'placeholder',sequence:'AAGGTCTCAACC',sites},'BsmBI',{left_overhang:'TTTG',right_overhang:'ACCT'});
 assert.equal(r.name,'Insert · RC');assert.equal(r.length,12);assert.equal(r.circular,false);
 assert.deepEqual(r.features.map(f=>[f.label,f.start,f.end]),[['Constant',0,4],['Cargo',4,8],['Constant',8,12]]);
 assert.deepEqual(r.restriction_sites,sites);assert.match(r.viewSummary,/5′ TTTG \/ 3′ ACCT/);
 assert.equal(r.features[1].qualifiers.note[0],'Dynamic region');
});
test('donor viewer keeps the oriented full sequence, detected sites and exact four-base fusion positions',()=>{
 const node={kind:'fragment',oriented_sequence:'GGTCTCAAACCAAGGTTAACCCGAGACC',digest:{target_start:11,target_end:16,left_site_start:0,right_site_start:21,left_overhang:'AACC',right_overhang:'AACC',all_sites:[{enzyme:'BsaI',start:0,end:6}]}};
 const r=record({name:'F1',reverse:true},node,'BsaI');
 assert.equal(r.sequence,node.oriented_sequence);assert.equal(r.restriction_sites.length,1);
 assert.deepEqual(r.features.map(f=>[f.start,f.end]),[[11,16],[7,11],[16,20]]);
});
test('viewing incomplete or invalid DNA reports a useful error without removing invalid bases',()=>{
 for(const sequence of ['', 'ACGN', 'ACGT;'])assert.throws(()=>record({sections:[]},{kind:'placeholder',sequence},'BsaI'),/A\/C\/G\/T/);
});
test('generated assembly preview preserves topology, oriented features and sites without mutating the result',()=>{
 const result={name:'Designed plasmid',valid:true,assembly:{sequence:'AACCGGTT',circular:true,features:[{label:'RC donor',start:2,end:6,strand:-1,reverse_complement:true}],restriction_sites:[{enzyme:'BsmBI',start:1,end:7}]}};
 const before=structuredClone(result),view=assembly(result);
 assert.equal(view.name,'Designed plasmid');assert.equal(view.viewerTitle,'Example assembly');assert.equal(view.circular,true);assert.equal(view.sequence,result.assembly.sequence);
 assert.deepEqual(view.features,result.assembly.features);assert.deepEqual(view.restriction_sites,result.assembly.restriction_sites);
 view.features[0].start=0;view.restriction_sites[0].start=0;assert.deepEqual(result,before);
});
test('preview names identify the displayed table row and invalid assemblies remain labelled schematic',()=>{
 const result={name:'Batch',table_mode:true,valid:false,assemblies:[{name:'First row'}],assembly:{sequence:'ACGT',circular:false}};
 const view=assembly(result);assert.equal(view.name,'Batch · First row');assert.match(view.viewSummary,/Schematic/);assert.match(view.viewSummary,/Linear/);
 for(const product of [null,{sequence:''},{sequence:'ACGN'}])assert.throws(()=>assembly({assembly:product}),/Generate an assembly/);
});
