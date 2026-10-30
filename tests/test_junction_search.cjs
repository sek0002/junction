const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('app/static/app.js','utf8');
function setup(){
 const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',innerHTML:''});return nodes.get(id);};
 const state={libraryMetrics:{qc_enzyme:'BsaI',junctions:[
 {overhang:'AAGC',reverse_complement:'GCTT',fragments:['Donor A'],backbones:[],enzymes:['BsaI'],problems:[]},
 {overhang:'ACCT',reverse_complement:'AGGT',fragments:[],backbones:['Template'],enzymes:['BsmBI'],problems:[{source:'Template',message:'Check site'}]}
 ]}};
 const context=vm.createContext({state,$,esc:String,overhangHtml:(sequence,classes)=>`<code class="${classes}">${sequence}</code>`});
 vm.runInContext(source.slice(source.indexOf('function renderJunctionList()'),source.indexOf('\nasync function refresh(){')),context);
 return{$,state,render:context.renderJunctionList};
}
test('junction search matches either strand, ignoring case and pasted whitespace',()=>{
 const s=setup();s.$('junction-list-search').value='gc tt';s.render();assert.match(s.$('junction-list').innerHTML,/AAGC/);assert.doesNotMatch(s.$('junction-list').innerHTML,/ACCT/);assert.match(s.$('junction-list-summary').textContent,/1 of 2/);
 s.$('junction-list-search').value='aa';s.render();assert.match(s.$('junction-list').innerHTML,/Donor A/);
});
test('filter preserves backbone colours and problems, and clearing restores the list',()=>{
 const s=setup();s.$('junction-list-search').value='ACCT';s.render();assert.match(s.$('junction-list').innerHTML,/backbone-end/);assert.match(s.$('junction-list').innerHTML,/Check site/);assert.doesNotMatch(s.$('junction-list').innerHTML,/Donor A/);
 s.$('junction-list-search').value='';s.render();assert.match(s.$('junction-list').innerHTML,/Donor A/);assert.match(s.$('junction-list').innerHTML,/Template/);assert.match(s.$('junction-list-summary').textContent,/^2 unique/);
});
test('no-match and empty-library states remain clear without changing inventory',()=>{
 const s=setup();s.$('junction-list-search').value='TTTT';s.render();assert.match(s.$('junction-list').innerHTML,/No matching junctions/);assert.match(s.$('junction-list-summary').textContent,/0 of 2/);assert.equal(s.state.libraryMetrics.junctions.length,2);
 s.state.libraryMetrics.junctions=[];s.$('junction-list-search').value='';s.render();assert.match(s.$('junction-list').innerHTML,/No junctions/);
});
