const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('app/static/app.js','utf8');
function renderer(){
 const context=vm.createContext({state:{result:null},esc:String,colors:['green','purple'],PlasmidFeatures:require('../app/static/plasmid-features.js'),MapLabelLayout:require('../app/static/map-layout.js'),mapSiteColors:{BsmBI:'purple'}});
 const code=source.slice(source.indexOf('function mapFeatureGroup('),source.indexOf('const mapSiteColors='))+source.slice(source.indexOf('function mapSiteRange('),source.indexOf('function renderMapSiteLegend('))+source.slice(source.indexOf('function linearMapSvg('),source.indexOf('\nfunction renderMap()'));
 vm.runInContext(code,context);return context;
}
const tools={measure:text=>text.length*7,fit:(text,limit,width)=>({text:text.slice(0,Math.min(limit,Math.floor(width/7))),width:Math.min(text.length*7,width)})};
test('both map renderers use their own record length and tooltip rather than the builder result',()=>{
 const context=renderer(),record={name:'Design map',sequence:'A'.repeat(1000),circular:true};
 const features=[{label:'Donor',type:'misc_feature',start:200,end:900,strand:-1}];
 const sites=[{enzyme:'BsmBI',index:0,start:998,end:1004,wraps_origin:true}];
 for(const render of [context.linearMapSvg,context.circularMapSvg]){
   const svg=render(record,features,780,tools,sites,'design-tooltip');
   assert.match(svg,/aria-label="Donor · complement\(201\.\.900\)"/);assert.match(svg,/aria-describedby="design-tooltip"/);
   assert.match(svg,/999–4 · across origin/);assert.doesNotMatch(svg,/aria-describedby="map-tooltip"/);
 }
 assert.equal(context.state.result,null);
});
test('dense circular previews retain every displaced label and leader',()=>{
 const context=renderer(),features=Array.from({length:32},(_,i)=>({label:'Feature '+i,type:'misc_feature',start:300+i,end:320+i,strand:1}));
 const svg=context.circularMapSvg({name:'Dense map',sequence:'A'.repeat(1000),circular:true},features,780,tools,[],'dense-tooltip');
 const labels=[...svg.matchAll(/data-map-label="(\d+)" x="([\d.]+)" y="([\d.]+)"/g)];
 assert.equal(labels.length,features.length);assert.equal((svg.match(/data-map-leader=/g)||[]).length,features.length);
 const sides=new Map();for(const item of labels){if(!sides.has(item[2]))sides.set(item[2],[]);sides.get(item[2]).push(item);}
 for(const group of sides.values()){
   const positions=group.map(item=>Number(item[3])).sort((a,b)=>a-b);
   for(let i=1;i<positions.length;i++)assert.ok(positions[i]-positions[i-1]>=22-1e-7);
 }
});
