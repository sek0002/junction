/* Backdrop dismissal requires a complete outside gesture, so dragging from a
   map or form to the backdrop never discards the open editor. */
(function(root){
  function outside(event,rect){return event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom;}
  function bindDialog(dialog){
    let startedOutside=false;
    dialog.addEventListener('pointerdown',event=>{startedOutside=event.button===0&&event.target===dialog&&outside(event,dialog.getBoundingClientRect());});
    dialog.addEventListener('pointercancel',()=>{startedOutside=false;});
    dialog.addEventListener('close',()=>{startedOutside=false;});
    dialog.addEventListener('click',event=>{
      const dismiss=startedOutside&&event.target===dialog&&outside(event,dialog.getBoundingClientRect());startedOutside=false;
      if(!dismiss||!dialog.open)return;
      if(typeof dialog.requestClose==='function')dialog.requestClose();
      else if(dialog.dispatchEvent(new Event('cancel',{cancelable:true})))dialog.close();
    });
  }
  const api={outside,bindDialog};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.PopupControls=api;
})(typeof window==='object'?window:globalThis);
