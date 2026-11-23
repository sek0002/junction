const test=require('node:test'),assert=require('node:assert/strict');
const C=require('../app/static/coding-viewer.js');
const D=require('../app/static/difference-viewer.js');
function effect(){return{type:'missense',region_name:'Reporter <unsafe>',amino_acid_position:2,query_amino_acid_position:2,reference_codon:'AAA',query_codon:'GAA',protein_change:'K2E',reference_spans:[[3,4]],query_spans:[[3,4]]};}
function region(basis='annotated_cds'){return{name:'Reporter <unsafe>',basis,source:'reference',reference_frame:1,query_frame:-2,codon_start:1,translation_table:1,reference_aa_length:3,query_aa_length:3,protein_changed:true,reference_protein:'MKG*',query_protein:'MEG*',warnings:[],effects:[effect()]};}
test('translation panel separates predictions from annotated CDS and shows codons, amino acids and frames',()=>{
 const report={regions:[region(),region('predicted_orf')],predicted:true,min_orf_aa:30,frames:{query:[{frame:-2,orf_count:1,longest_aa:40}]}};
 const html=C.panelHtml(report);
 for(const text of ['Annotated CDS','Predicted ORFs','Ref frame +1','Query frame -2','AAA','GAA','K2E','MKG*','MEG*','minimum 30 aa'])assert.ok(html.includes(text),text);
 assert.ok(html.includes('Reporter &lt;unsafe&gt;'));assert.ok(!html.includes('Reporter <unsafe>'));
 assert.ok(C.effectsHtml([effect()]).includes('Missense'));
 assert.ok(C.summaryHtml({predicted:true,summary:{missense:1}}).includes('Predicted'));
});
test('nucleotide difference hover retains the actual coding consequence',()=>{
 const model=D.build({aligned_reference:'ATGAAAGGGTAA',aligned_query:'ATGGAAGGGTAA',circular:false,changes:[{type:'substitution',reference_start:3,reference_end:4,query_start:3,query_end:4,coding_effects:[effect()]}]});
 assert.equal(model.changes[0].coding_effects.length,1);
 const hover=D.hoverHtml(model,'change',0);
 for(const text of ['Missense','K2E','AAA','GAA'])assert.ok(hover.includes(text),text);
});
test('missing analysis and uncertain translations have clear states',()=>{
 assert.ok(C.panelHtml(null).includes('unavailable'));
 assert.ok(C.panelHtml({regions:[{...region(),protein_changed:null,warnings:['Manual review']}]}).includes('Review translation'));
 assert.equal(C.summaryHtml(null),'');
});

test('query-only translation shows uploaded frame without inventing a reference',()=>{
 const html=C.panelHtml({query_only:true,regions:[{...region(),query_only:true,source:'query',reference_frame:null,reference_protein:'',reference_aa_length:null,protein_changed:null,effects:[]}]});
 assert.ok(html.includes('no reference alignment'));assert.ok(html.includes('Query frame -2'));assert.ok(html.includes('Uploaded CDS'));
 assert.ok(!html.includes('Ref frame'));assert.ok(!html.includes('Protein unchanged'));
});
