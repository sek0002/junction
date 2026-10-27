const test=require('node:test');
const assert=require('node:assert/strict');
const {bindDialog}=require('../app/static/popup-controls.js');
class Dialog extends EventTarget{
  open=true;
  closes=0;
  getBoundingClientRect(){return {left:100,right:500,top:100,bottom:500};}
  close(){this.open=false;this.closes++;this.dispatchEvent(new Event('close'));}
}
function gesture(dialog,start,end=start){
  for(const [type,point] of [['pointerdown',start],['click',end]]){
    const event=new Event(type);Object.assign(event,{button:0,clientX:point[0],clientY:point[1]});dialog.dispatchEvent(event);
  }
}
test('backdrop click closes an open dialog',()=>{const d=new Dialog();bindDialog(d);gesture(d,[20,20]);assert.equal(d.closes,1);});
test('blank space inside dialog does not dismiss it',()=>{const d=new Dialog();bindDialog(d);gesture(d,[200,200]);assert.equal(d.closes,0);});
test('dragging out of an editor or into it does not dismiss',()=>{const d=new Dialog();bindDialog(d);gesture(d,[200,200],[20,20]);gesture(d,[20,20],[200,200]);assert.equal(d.closes,0);});
test('cancel guard protects an operation in progress',()=>{const d=new Dialog();bindDialog(d);d.addEventListener('cancel',event=>event.preventDefault());gesture(d,[20,20]);assert.equal(d.closes,0);});
test('native requestClose is used when available',()=>{const d=new Dialog();bindDialog(d);let requested=0;d.requestClose=()=>requested++;gesture(d,[20,20]);assert.equal(requested,1);});
