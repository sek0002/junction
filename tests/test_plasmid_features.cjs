const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const F=require('../app/static/plasmid-features.js');
const wrap={type:'CDS',label:'Wrapped CDS',raw_location:'complement(join(901..1000,1..80))',strand:-1,segments:[{start:900,end:1000,strand:-1},{start:0,end:80,strand:-1}],start:0,end:1000,qualifiers:{gene:['marker'],product:['Test protein'],note:['Retain this annotation'],ApEinfo_revcolor:['#4A90D9']}};
test('joined and origin-spanning features highlight only their real segments',()=>{
  assert.equal(F.size(wrap,1000),180);assert.equal(F.anchor(wrap,1000),950);
  assert.ok(F.contains(wrap,950,1000));assert.ok(F.contains(wrap,50,1000));assert.equal(F.contains(wrap,400,1000),false);
  assert.equal(F.location(wrap,1000),'complement(join(901..1000,1..80))');
  const restriction={start:998,end:1004,wraps_origin:true};assert.ok(F.contains(restriction,1,1000));assert.equal(F.contains(restriction,50,1000),false);
});
test('short annotations, remote locations and overlapping features stay distinct',()=>{
  assert.equal(F.size({start:20,end:21},1000),1);
  assert.equal(F.segments({start:0,end:0,raw_location:'AB123.1:1..40'},1000).length,0);
  const f=[wrap,{start:20,end:26},{start:100,end:400},{start:150,end:160}];const layout=F.lanes(f,1000);
  assert.notEqual(layout.indices[0],layout.indices[1]);assert.equal(layout.indices[0],layout.indices[2]);assert.notEqual(layout.indices[2],layout.indices[3]);
});
test('annotation colours are safe and qualifiers retain full details',()=>{
  assert.equal(F.color(wrap,'fallback'),'#4A90D9');assert.equal(F.color({qualifiers:{color:['url(bad)']}},'fallback'),'fallback');
  assert.deepEqual(F.qualifiers(wrap),[['gene','marker'],['product','Test protein'],['note','Retain this annotation']]);
  assert.equal(F.qualifiers({qualifiers:{translation:['MPEPTIDE']}},true)[0][1],'8 aa');
});
test('viewer draws both joined parts and includes one-base uploaded annotations',()=>{
  const source=fs.readFileSync(path.join(__dirname,'../app/static/app.js'),'utf8');
  const state={result:{sequence:'A'.repeat(1000),name:'Annotations',circular:true,storedReference:true,features:[wrap,{type:'protein_bind',label:'Short site',start:25,end:26,strand:1},{type:'source',start:0,end:1000}]}};
  const context=vm.createContext({state,PlasmidFeatures:F,MapLabelLayout:require('../app/static/map-layout.js'),colors:['red','blue'],esc:v=>String(v).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))});
  vm.runInContext(source.slice(source.indexOf('function mapFeatures(){'),source.indexOf('let mapTooltipFeature=')),context);
  vm.runInContext(source.slice(source.indexOf('function mapFeatureGroup('),source.indexOf('const mapSiteColors=')),context);
  vm.runInContext(source.slice(source.indexOf('function linearMapSvg('),source.indexOf('function renderMap(){')),context);
  const features=context.mapFeatures(),text={fit:v=>({text:String(v),width:String(v).length*6}),measure:v=>String(v).length*6};
  assert.equal(features.length,2);
  const linear=context.linearMapSvg(state.result,features,900,text,[]),circle=context.circularMapSvg(state.result,features,900,text,[]);
  assert.ok(linear.includes('Short site'));assert.ok(circle.includes('Short site'));
  assert.equal((linear.match(/<path d=/g)||[]).length,3);
  assert.equal((circle.match(/stroke="#4A90D9"/g)||[]).length,2);
  assert.ok(!linear.includes('NaN'));assert.ok(!circle.includes('NaN'));
});
