const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('app/static/app.js','utf8');
const FragmentSearch=require('../app/static/fragment-search.js');
function setup(){
 const nodes=new Map(),calls=[],$=id=>{if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',innerHTML:'',open:false,hidden:false,disabled:false,attributes:{},setAttribute(k,v){this.attributes[k]=v;},showModal(){this.open=true;},close(){this.open=false;},querySelector(){return null;},focus(){this.focused=true;},select(){this.selected=true;}});return nodes.get(id);};
 const record={id:1,name:'Tube donor',sequence:'GGTCTCAACCTAACCGGTATGCGAGACC',construct_sequence:'AAAAGGTCTCAACCTAACCGGTATGCGAGACCTTTT',location:'Freezer 2',plate_id:'',well:'',length:26,physical_length:34,custom_metadata:{linked_fragment_name:'Source <DNA>'},fusion_ends:[],sites:[],inventory:{yield_ng:100,resuspension_ul:20,stock_ng_ul:5,input_volume_ul:1}};
 const context=vm.createContext({$,FragmentSearch,esc:v=>String(v??'').replace(/</g,'&lt;').replace(/>/g,'&gt;'),fmt:String,inventoryQuantity:String,inventoryIcon:String,plateSitesHtml:()=>'<div>Sites</div>',plateEndHtml:()=>'',messages:()=>'<p>Saved values</p>',api:async url=>{calls.push(url);return record;},persistInventoryRow:async id=>calls.push(['save',id]),openPlateMap:async(...args)=>calls.push(['plate',...args]),toast:message=>calls.push(message),navigator:{clipboard:{writeText:async text=>calls.push(['copy',text])}}});
 vm.runInContext(source.slice(source.indexOf('let fragmentInfoToken='),source.indexOf('let plateViewToken=')),context);
 return{$,record,calls,context,run:text=>vm.runInContext(text,context)};
}
test('library names open the exact physical well after pending stocks finish saving',async()=>{
 const s=setup();await s.context.openInventoryFragment({id:7,plate_id:'Plate 1',well:'H12'});assert.deepEqual(s.calls,[['save',7],['plate','Plate 1','H12']]);assert.equal(s.$('fragment-info-dialog').open,false);
 // Partial coordinates do not invent a plate or pick an unrelated well.
 await s.context.openInventoryFragment({id:1,plate_id:'Plate only',well:''});assert.equal(s.$('fragment-info-dialog').open,true);assert.match(s.$('fragment-info-body').innerHTML,/Freezer 2/);assert.match(s.$('fragment-info-body').innerHTML,/Linked stock/);assert.doesNotMatch(s.$('fragment-info-body').innerHTML,/<DNA>/);
});
test('plate viewer starts on the clicked well instead of the first occupied well',async()=>{
 const s=setup();s.context.state={plateView:{},plateWell:'A1',plateWellSelection:new Set([2])};s.context.updatePlateArchiveControls=()=>{};s.context.loadPlateView=async id=>{assert.equal(id,'P1');assert.equal(s.context.state.plateWell,'D8');};
 vm.runInContext(source.slice(source.indexOf('async function openPlateMap('),source.indexOf('async function loadPlateView(')),s.context);await s.context.openPlateMap('P1','D8');assert.equal(s.context.state.plateWellSelection.size,0);
});
test('unlocated information offers sequence and keeps invalid inventory edits readable',async()=>{
 const s=setup();s.context.persistInventoryRow=async()=>{throw Error('Invalid stock');};await s.context.openInventoryFragment(s.record);assert.match(s.$('fragment-info-body').innerHTML,/Saved values/);assert.match(s.$('fragment-info-body').innerHTML,/fragment-info-sequence/);await s.$('fragment-info-sequence').onclick();assert.equal(s.$('fragment-sequence-text').value,s.record.sequence);
});
test('sequence popup switches and copies exact fragment or construct DNA',async()=>{
 const s=setup();await s.context.openFragmentSequence(1);assert.equal(s.$('fragment-sequence-kind').hidden,false);assert.equal(s.$('fragment-sequence-text').value,s.record.sequence);await s.context.copyFragmentSequence();assert.deepEqual(s.calls.at(-1),['copy',s.record.sequence]);assert.match(s.$('fragment-sequence-status').textContent,/Copied/);
 s.$('fragment-sequence-kind').value='construct_sequence';s.context.renderFragmentSequence();await s.context.copyFragmentSequence();assert.deepEqual(s.calls.at(-1),['copy',s.record.construct_sequence]);assert.equal(s.$('fragment-sequence-text').attributes['aria-label'],'Construct sequence');
});
test('single-sequence stock hides construct switch and clipboard failure selects DNA',async()=>{
 const s=setup();s.record.construct_sequence='';await s.context.openFragmentSequence(1);assert.equal(s.$('fragment-sequence-kind').hidden,true);s.context.navigator.clipboard.writeText=async()=>{throw Error('Unavailable');};await s.context.copyFragmentSequence();assert.equal(s.$('fragment-sequence-text').selected,true);assert.match(s.$('fragment-sequence-status').textContent,/Ctrl\+C/);
});
test('closed and superseded popups ignore late responses',async()=>{
 const s=setup(),pending=[];s.context.api=()=>new Promise(resolve=>pending.push(resolve));const first=s.context.openFragmentSequence(1);s.$('fragment-sequence-dialog').open=false;pending.shift()(s.record);await first;assert.equal(s.$('fragment-sequence-text').value,'');
 const one=s.context.openFragmentSequence(1),two=s.context.openFragmentSequence(2);pending[1]({...s.record,id:2,name:'Newest',sequence:'ACGT'});await two;pending[0](s.record);await one;assert.equal(s.$('fragment-sequence-title').textContent,'Newest');assert.equal(s.$('fragment-sequence-text').value,'ACGT');
});
test('direct clipboard copy finishes without waiting for a blocked asynchronous clipboard API',async()=>{
 const s=setup();let commands=[];s.context.document={execCommand:command=>{commands.push(command);assert.equal(s.$('fragment-sequence-text').selected,true);return true;}};s.context.navigator.clipboard.writeText=()=>{throw Error('Should not be needed');};await s.context.openFragmentSequence(1);await s.context.copyFragmentSequence();assert.deepEqual(commands,['copy']);assert.match(s.$('fragment-sequence-status').textContent,/Copied/);
});
