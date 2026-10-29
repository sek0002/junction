const {test}=require('node:test');
const assert=require('node:assert/strict');
const {blank,paste,payload,tsv}=require('../app/static/custom-upload.js');
const {badge,location}=require('../app/static/fragment-search.js');
test('spreadsheet headers map optional coordinates and preserve open-ended locations',()=>{
 const rows=paste([],'Name\tConcentration\tLocation\tPlate\tWell\tLink\tSequence\nDonor\t15.5\tFreezer / box 4 / tube 7\t\t\tDonor (#12)\t');
 assert.deepEqual(payload(rows),[{name:'Donor',concentration:15.5,location:'Freezer / box 4 / tube 7',plate:'',well:'',link:'Donor (#12)',sequence:'',filename:'',features:[]}]);
 assert.equal(rows[0].location,'Freezer / box 4 / tube 7');
});
test('quoted copy and paste round trip multiline sequence and location',()=>{
 const rows=[{...blank(),name:'A "stock"',location:'Shelf, top\nbox 5',sequence:'>A\nACGT\nACGT',concentration:'20'}];
 assert.deepEqual(paste([],tsv(rows)),rows);
});
test('cell paste fills rows without mutating other rows or replacing imported stocks',()=>{
 const original=[{...blank(),name:'Existing',link:'#1'},{...blank(),name:'New'}];
 const result=paste(original,'25\tBench\tPlate A\tA1\t#3',1,'concentration');assert.equal(result[1].name,'New');assert.equal(result[1].plate,'Plate A');assert.equal(result[1].well,'A1');assert.equal(original[1].plate,'');
 assert.throws(()=>paste([{...original[0],imported:true}],'Replacement',0),/new row/);
 assert.throws(()=>paste([],'Name\tName\nA\tB'),/Repeated/);assert.throws(()=>paste([],'Name\tMade up\nA\tB'),/Unknown/);
});
test('payload rejects invalid concentration, missing DNA and conflicting link',()=>{
 for(const row of [{...blank(),name:'Empty'},{...blank(),sequence:'ACGT',concentration:'NaN'},{...blank(),sequence:'ACGT',concentration:'-1'},{...blank(),sequence:'ACGT',link:'#12'}])assert.throws(()=>payload([row]));
 assert.deepEqual(payload([blank(),{...blank(),sequence:'ACGT',imported:true}]),[]);
 assert.equal(payload([{...blank(),sequence:'ACGT'}])[0].concentration,null);
});
test('linked stocks have a distinct flag and visible free location plus physical coordinates',()=>{
 const stock={custom_metadata:{linked_fragment_id:3,linked_fragment_name:'<Donor>'},location:'Freezer 2',plate_id:'P1',well:'A1'};
 assert.match(badge(stock),/Linked stock/);assert.match(badge(stock),/independent stock and volume/);assert.doesNotMatch(badge(stock),/<Donor>/);assert.equal(location(stock),'Freezer 2 · P1 / A1');assert.equal(location({}),'Location not set');
});
