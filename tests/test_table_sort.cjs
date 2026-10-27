const test=require('node:test'),assert=require('node:assert/strict'),T=require('../app/static/table-sort.js');
const cell=(text,value)=>({textContent:text,dataset:{},querySelector:selector=>selector.startsWith('input')&&value!==undefined?{value}:null});
const row=(id,text,value)=>({id,cells:[cell(text,value)],selected:id===2});
test('table sort parses decimals, percentages, scientific notation and missing cells',()=>{
 for(const[text,value]of [['1,234 bp',1234],['0.05 µL',.05],['99.99%',99.99],['1e-3',.001],['>99.99%',99.99],['—',null],['',null]])assert.equal(T.parse(text),value);
 assert.equal(T.parse('A10'),'A10');assert.equal(T.parse('1–5'),'1–5');
});
test('natural text and numeric sorting are stable, with unknown values last',()=>{
 const rows=[row(1,'A10'),row(2,'A2'),row(3,'—')];
 assert.deepEqual(T.orderRows(rows,0,1).map(r=>r.id),[2,1,3]);assert.deepEqual(T.orderRows(rows,0,-1).map(r=>r.id),[1,2,3]);
 const nums=[row(1,'100'),row(2,'2'),row(3,'—'),row(4,'2')];assert.deepEqual(T.orderRows(nums,0,1).map(r=>r.id),[2,4,1,3]);
 assert.deepEqual(nums.map(r=>r.id),[1,2,3,4]);
});
test('editable table columns sort by current input value and preserve row identity',()=>{
 const rows=[row(1,'100 old stock','3.5'),row(2,'2 old stock','25'),row(3,'missing','')];
 const sorted=T.orderRows(rows,0,-1);assert.deepEqual(sorted.map(r=>r.id),[2,1,3]);assert.equal(sorted[0],rows[1]);assert.equal(sorted[0].selected,true);
 rows[0].cells[0].dataset.sortValue='50';assert.equal(T.cellValue(rows[0].cells[0]),50);
});
